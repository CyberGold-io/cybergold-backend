import { serverEnv } from "../environment.ts";

import type { Address } from "viem";

import { RecoverySharesApiError } from "@/utils/recoverySharesApi";
import { query, withTransaction } from "./db";
import {
    readRecoveryShareV2Checkpoint,
    recoveryShareV2Enabled,
    RECOVERY_SHARE_V2_VERSION,
} from "./recoverySharePersistence";
import {
    materializeRecoverySharePortfolio,
    parseRecoveryPortfolioReadModel,
    RECOVERY_PORTFOLIO_MAX_BALANCES_PER_HOLDER,
    type RecoveryPortfolioReadModel,
} from "./recoveryPortfolioModel";

export const RECOVERY_PORTFOLIO_MODEL_KEY = "recovery-portfolio-v5";
const RATE_WINDOW_MS = 60_000;
const GLOBAL_REQUESTS_PER_WINDOW = 300;
const HOLDER_REQUESTS_PER_WINDOW = 30;
const MAX_SHARED_CONCURRENCY = 8;
const READ_TIMEOUT_MS = 2_000;

type RepositoryConfig = {
    chainId: bigint;
    coreAddress: Address;
};

type SnapshotRow = {
    block_number: string;
    payload: RecoveryPortfolioReadModel | string;
};

type WriteQuery = (sql: string, params?: unknown[]) => Promise<unknown>;

function scope(config: RepositoryConfig, suffix: string) {
    return `recovery:${config.chainId}:${config.coreAddress.toLowerCase()}:${suffix}`;
}

async function consumeRateLimit(limitScope: string, maximum: number, windowId: number) {
    const result = await query<{ request_count: number }>(
        `
            INSERT INTO onchain_api_rate_limits (scope, window_id, request_count)
            VALUES ($1, $2, 1)
            ON CONFLICT (scope, window_id) DO UPDATE SET
                request_count = onchain_api_rate_limits.request_count + 1,
                updated_at = NOW()
            WHERE onchain_api_rate_limits.request_count < $3
            RETURNING request_count
        `,
        [limitScope, windowId, maximum]
    );
    if ((result.rowCount ?? 0) === 0) {
        throw new RecoverySharesApiError(
            "Recovery-share request rate limit exceeded",
            429,
            Math.max(1, Math.ceil((RATE_WINDOW_MS - (Date.now() % RATE_WINDOW_MS)) / 1000))
        );
    }
}

export async function persistRecoveryPortfolioReadModel(
    config: RepositoryConfig,
    model: RecoveryPortfolioReadModel,
    transactionQuery: WriteQuery
) {
    await transactionQuery(
        `
            INSERT INTO onchain_read_model_snapshots (
                chain_id,
                contract_address,
                model_key,
                block_number,
                payload
            ) VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (chain_id, contract_address, model_key, block_number)
            DO UPDATE SET payload = EXCLUDED.payload, created_at = NOW()
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            RECOVERY_PORTFOLIO_MODEL_KEY,
            model.snapshotBlock,
            JSON.stringify(model),
        ]
    );
    await transactionQuery(
        `
            DELETE FROM onchain_read_model_snapshots
            WHERE chain_id = $1
              AND contract_address = $2
              AND model_key = $3
              AND block_number > $4
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            RECOVERY_PORTFOLIO_MODEL_KEY,
            model.snapshotBlock,
        ]
    );
    await transactionQuery(
        `
            DELETE FROM onchain_read_model_snapshots
            WHERE chain_id = $1
              AND contract_address = $2
              AND model_key = $3
              AND block_number NOT IN (
                  SELECT block_number
                  FROM onchain_read_model_snapshots
                  WHERE chain_id = $1
                    AND contract_address = $2
                    AND model_key = $3
                  ORDER BY block_number DESC
                  LIMIT 4
              )
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            RECOVERY_PORTFOLIO_MODEL_KEY,
        ]
    );
}

export async function pruneRecoveryApiRateLimits() {
    await query(
        `
            DELETE FROM onchain_api_rate_limits
            WHERE updated_at < NOW() - INTERVAL '5 minutes'
        `
    );
}

export async function readCachedRecoverySharePortfolio(
    config: RepositoryConfig,
    holder: Address
) {
    const useRecoveryShareV2 = recoveryShareV2Enabled(
        serverEnv.ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED
    );
    const balanceTable = useRecoveryShareV2
        ? "onchain_recovery_share_balances_v2"
        : "onchain_recovery_share_balances";
    const windowId = Math.floor(Date.now() / RATE_WINDOW_MS);
    await consumeRateLimit(scope(config, "global"), GLOBAL_REQUESTS_PER_WINDOW, windowId);
    await consumeRateLimit(
        scope(config, `holder:${holder.toLowerCase()}`),
        HOLDER_REQUESTS_PER_WINDOW,
        windowId
    );

    return withTransaction(async (transactionQuery) => {
        await transactionQuery("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ");
        await transactionQuery(`SET LOCAL statement_timeout = '${READ_TIMEOUT_MS}ms'`);
        await transactionQuery("SET LOCAL lock_timeout = '250ms'");
        const lockResult = await transactionQuery<{ slot: number }>(
            `
                SELECT candidate.slot
                FROM generate_series(0, $2::integer - 1) AS candidate(slot)
                WHERE pg_try_advisory_xact_lock(hashtext($1), candidate.slot)
                LIMIT 1
            `,
            [scope(config, "concurrency"), MAX_SHARED_CONCURRENCY]
        );
        if ((lockResult.rowCount ?? 0) === 0) {
            throw new RecoverySharesApiError(
                "Recovery-share indexer is busy; retry shortly",
                429,
                1
            );
        }

        const snapshotResult = await transactionQuery<SnapshotRow>(
            `
                SELECT block_number::text, payload
                FROM onchain_read_model_snapshots
                WHERE chain_id = $1
                  AND contract_address = $2
                  AND model_key = $3
                ORDER BY block_number DESC
                LIMIT 1
            `,
            [
                config.chainId.toString(),
                config.coreAddress.toLowerCase(),
                RECOVERY_PORTFOLIO_MODEL_KEY,
            ]
        );
        if ((snapshotResult.rowCount ?? 0) !== 1) {
            throw new RecoverySharesApiError(
                "Recovery-share indexer has no completed cached snapshot",
                503
            );
        }
        const row = snapshotResult.rows[0];
        const model = parseRecoveryPortfolioReadModel(row.payload);
        if (
            model.snapshotBlock !== row.block_number ||
            model.chainId !== config.chainId.toString() ||
            model.collection.toLowerCase() !== config.coreAddress.toLowerCase()
        ) {
            throw new Error("Cached recovery portfolio identity is inconsistent");
        }
        if (useRecoveryShareV2) {
            const checkpoint = await readRecoveryShareV2Checkpoint(
                config,
                (sql, params = []) => transactionQuery(sql, params)
            );
            const finalizedState = await transactionQuery<{
                state_key: string;
                state_value: string;
            }>(
                `
                    SELECT state_key, state_value
                    FROM onchain_sync_state
                    WHERE chain_id = $1
                      AND contract_address = $2
                      AND state_key = ANY($3::text[])
                `,
                [
                    config.chainId.toString(),
                    config.coreAddress.toLowerCase(),
                    [
                        "finalized_snapshot_block",
                        "finalized_snapshot_block_hash",
                        "finalized_snapshot_profile",
                    ],
                ]
            );
            const state = new Map(
                finalizedState.rows.map((entry) => [
                    entry.state_key,
                    entry.state_value,
                ])
            );
            if (
                !checkpoint ||
                checkpoint.version !== RECOVERY_SHARE_V2_VERSION ||
                finalizedState.rows.length !== 3 ||
                checkpoint.blockNumber.toString() !== model.snapshotBlock ||
                state.get("finalized_snapshot_block") !== model.snapshotBlock ||
                checkpoint.blockHash.toLowerCase() !==
                    state.get("finalized_snapshot_block_hash")?.toLowerCase() ||
                checkpoint.profile !== state.get("finalized_snapshot_profile")
            ) {
                throw new RecoverySharesApiError(
                    "Recovery-share v2 checkpoint is not complete for the cached snapshot",
                    503
                );
            }
        }

        const balanceResult = await transactionQuery<{
            share_id: string;
            balance_raw: string;
        }>(
            `
                SELECT share_id, balance_raw
                FROM ${balanceTable}
                WHERE chain_id = $1
                  AND contract_address = $2
                  AND holder_address = $3
                  AND balance_raw <> '0'
                ORDER BY share_id::numeric ASC
                LIMIT $4
            `,
            [
                config.chainId.toString(),
                config.coreAddress.toLowerCase(),
                holder.toLowerCase(),
                RECOVERY_PORTFOLIO_MAX_BALANCES_PER_HOLDER + 1,
            ]
        );
        if (balanceResult.rows.length > RECOVERY_PORTFOLIO_MAX_BALANCES_PER_HOLDER) {
            throw new RecoverySharesApiError(
                "Recovery-share holder cardinality exceeds the public API policy",
                503
            );
        }
        return materializeRecoverySharePortfolio(model, balanceResult.rows);
    });
}
