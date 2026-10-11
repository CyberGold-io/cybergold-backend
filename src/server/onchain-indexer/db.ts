import { serverEnv } from "../environment.ts";

import { Pool, type QueryResult, type QueryResultRow } from "pg";
import snapshotIdentity from "./snapshot-identity.json";

declare global {
    var __cybergoldDashboardPgPool: Pool | undefined;
    var __cybergoldDashboardSchemaPromise: Promise<void> | undefined;
    var __cybergoldDashboardSchemaVersion: string | undefined;
}

const SCHEMA_VERSION = snapshotIdentity.databaseSchemaVersion;

function getDatabaseUrl() {
    const value = serverEnv.DATABASE_URL;
    if (!value) {
        throw new Error("DATABASE_URL is required for the on-chain dashboard indexer");
    }
    return value;
}

function getPool() {
    if (!global.__cybergoldDashboardPgPool) {
        global.__cybergoldDashboardPgPool = new Pool({
            connectionString: getDatabaseUrl(),
            max: 8,
        });
    }
    return global.__cybergoldDashboardPgPool;
}

export async function query<T extends QueryResultRow = QueryResultRow>(
    sql: string,
    params: unknown[] = []
): Promise<QueryResult<T>> {
    return getPool().query<T>(sql, params);
}

export type TransactionQuery = <T extends QueryResultRow = QueryResultRow>(
    sql: string,
    params?: unknown[]
) => Promise<QueryResult<T>>;

export async function withTransaction<T>(
    action: (transactionQuery: TransactionQuery) => Promise<T>
): Promise<T> {
    const client = await getPool().connect();
    try {
        await client.query("BEGIN");
        const transactionQuery: TransactionQuery = (sql, params = []) =>
            client.query(sql, params);
        const result = await action(transactionQuery);
        await client.query("COMMIT");
        return result;
    } catch (error) {
        await client.query("ROLLBACK");
        throw error;
    } finally {
        client.release();
    }
}

export async function withSharedAdvisoryLock<T>(
    lockKey: string,
    action: () => Promise<T>
): Promise<{ acquired: false } | { acquired: true; result: T }> {
    const client = await getPool().connect();
    let acquired = false;
    try {
        const lock = await client.query<{ acquired: boolean }>(
            "SELECT pg_try_advisory_lock(hashtext($1), 0) AS acquired",
            [lockKey]
        );
        acquired = lock.rows[0]?.acquired === true;
        if (!acquired) return { acquired: false };
        return { acquired: true, result: await action() };
    } finally {
        if (acquired) {
            try {
                await client.query("SELECT pg_advisory_unlock(hashtext($1), 0)", [lockKey]);
            } catch {
                // Releasing the dedicated connection also releases the session lock.
            }
        }
        client.release();
    }
}

async function resetDatabaseState() {
    global.__cybergoldDashboardSchemaPromise = undefined;
    global.__cybergoldDashboardSchemaVersion = undefined;

    const pool = global.__cybergoldDashboardPgPool;
    global.__cybergoldDashboardPgPool = undefined;

    if (pool) {
        try {
            await pool.end();
        } catch {
            // Ignore pool shutdown errors while resetting failed startup state.
        }
    }
}

async function initializeSchema() {
    await query(`
        CREATE TABLE IF NOT EXISTS onchain_event_logs (
            chain_id BIGINT NOT NULL,
            contract_address TEXT NOT NULL,
            event_name TEXT NOT NULL,
            block_number BIGINT NOT NULL,
            block_hash TEXT,
            tx_hash TEXT NOT NULL,
            log_index INTEGER NOT NULL,
            block_timestamp TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chain_id, tx_hash, log_index)
        );
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_onchain_event_logs_contract_event_time
            ON onchain_event_logs (contract_address, event_name, block_timestamp DESC);
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_onchain_event_logs_contract_block
            ON onchain_event_logs (contract_address, block_number DESC);
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS onchain_raw_logs (
            chain_id BIGINT NOT NULL,
            contract_address TEXT NOT NULL,
            block_number BIGINT NOT NULL,
            block_hash TEXT NOT NULL,
            tx_hash TEXT NOT NULL,
            log_index INTEGER NOT NULL,
            topics JSONB NOT NULL,
            data TEXT NOT NULL,
            block_timestamp_seconds BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chain_id, contract_address, tx_hash, log_index),
            CHECK (jsonb_typeof(topics) = 'array')
        );
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_onchain_raw_logs_contract_block
            ON onchain_raw_logs (
                chain_id,
                contract_address,
                block_number DESC,
                log_index DESC
            );
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS onchain_sync_state (
            chain_id BIGINT NOT NULL,
            contract_address TEXT NOT NULL,
            state_key TEXT NOT NULL,
            state_value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chain_id, contract_address, state_key)
        );
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS onchain_token_balances (
            chain_id BIGINT NOT NULL,
            contract_address TEXT NOT NULL,
            holder_address TEXT NOT NULL,
            balance_raw TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chain_id, contract_address, holder_address)
        );
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_onchain_token_balances_contract
            ON onchain_token_balances (contract_address);
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS onchain_holder_balance_deltas (
            chain_id BIGINT NOT NULL,
            contract_address TEXT NOT NULL,
            block_number BIGINT NOT NULL,
            tx_hash TEXT NOT NULL,
            log_index INTEGER NOT NULL,
            holder_address TEXT NOT NULL,
            delta_raw TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chain_id, tx_hash, log_index, holder_address)
        );
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_onchain_holder_balance_deltas_contract_block
            ON onchain_holder_balance_deltas (contract_address, block_number DESC, log_index DESC);
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS onchain_recovery_share_balances (
            chain_id BIGINT NOT NULL,
            contract_address TEXT NOT NULL,
            share_id TEXT NOT NULL,
            holder_address TEXT NOT NULL,
            balance_raw TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chain_id, contract_address, share_id, holder_address)
        );
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_onchain_recovery_share_balances_holder
            ON onchain_recovery_share_balances (
                chain_id,
                contract_address,
                holder_address,
                share_id
            );
    `);

    // Additive v2 state is intentionally isolated from the rollback image,
    // which continues to own only onchain_recovery_share_balances.
    await query(`
        CREATE TABLE IF NOT EXISTS onchain_recovery_share_balances_v2 (
            chain_id BIGINT NOT NULL,
            contract_address TEXT NOT NULL,
            share_id TEXT NOT NULL,
            holder_address TEXT NOT NULL,
            balance_raw TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chain_id, contract_address, share_id, holder_address)
        );
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_onchain_recovery_share_balances_v2_holder
            ON onchain_recovery_share_balances_v2 (
                chain_id,
                contract_address,
                holder_address,
                share_id
            );
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS onchain_read_model_snapshots (
            chain_id BIGINT NOT NULL,
            contract_address TEXT NOT NULL,
            model_key TEXT NOT NULL,
            block_number BIGINT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chain_id, contract_address, model_key, block_number)
        );
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_onchain_read_model_snapshots_latest
            ON onchain_read_model_snapshots (
                chain_id,
                contract_address,
                model_key,
                block_number DESC
            );
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS onchain_api_rate_limits (
            scope TEXT NOT NULL,
            window_id BIGINT NOT NULL,
            request_count INTEGER NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (scope, window_id)
        );
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_onchain_api_rate_limits_updated
            ON onchain_api_rate_limits (updated_at);
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS quote_pool_cache (
            chain_id BIGINT NOT NULL,
            dex TEXT NOT NULL,
            token0 TEXT NOT NULL,
            token1 TEXT NOT NULL,
            fee INTEGER NOT NULL,
            pool_address TEXT,
            exists BOOLEAN NOT NULL,
            success_count INTEGER NOT NULL DEFAULT 0,
            last_checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_success_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chain_id, dex, token0, token1, fee)
        );
    `);

    await query(`
        ALTER TABLE quote_pool_cache
            ADD COLUMN IF NOT EXISTS active_liquidity_raw TEXT,
            ADD COLUMN IF NOT EXISTS sqrt_price_x96_raw TEXT,
            ADD COLUMN IF NOT EXISTS tick INTEGER,
            ADD COLUMN IF NOT EXISTS token0_balance_raw TEXT,
            ADD COLUMN IF NOT EXISTS token1_balance_raw TEXT,
            ADD COLUMN IF NOT EXISTS liquidity_checked_at TIMESTAMPTZ;
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_quote_pool_cache_pair
            ON quote_pool_cache (
                chain_id,
                dex,
                token0,
                token1,
                exists DESC,
                success_count DESC,
                fee ASC
            );
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS governance_owner_aliases (
            editor_address TEXT NOT NULL,
            owner_address TEXT NOT NULL,
            alias TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (editor_address, owner_address)
        );
    `);

    await query(`
        CREATE INDEX IF NOT EXISTS idx_governance_owner_aliases_owner
            ON governance_owner_aliases (owner_address);
    `);

    await query(`
        CREATE TABLE IF NOT EXISTS governance_owner_alias_auth_nonces (
            editor_address TEXT NOT NULL,
            nonce TEXT NOT NULL,
            used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (editor_address, nonce)
        );
    `);
}

export async function ensureSchema() {
    for (let attempt = 0; attempt < 2; attempt += 1) {
        if (
            !global.__cybergoldDashboardSchemaPromise ||
            global.__cybergoldDashboardSchemaVersion !== SCHEMA_VERSION
        ) {
            global.__cybergoldDashboardSchemaVersion = SCHEMA_VERSION;
            global.__cybergoldDashboardSchemaPromise = initializeSchema();
        }

        try {
            await global.__cybergoldDashboardSchemaPromise;
            return;
        } catch (error) {
            await resetDatabaseState();
            if (attempt === 1) {
                throw error;
            }
        }
    }
}
