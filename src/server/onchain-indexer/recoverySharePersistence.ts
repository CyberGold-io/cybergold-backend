import { getAddress, type Address } from "viem";

import {
    applyIndexedRecoveryShareTransfer,
    recoveryShareBalanceKey,
    replayIndexedRecoveryShareTransfers,
    type IndexedRecoveryShareTransfer,
} from "../../utils/recovery.ts";

export type RecoveryPersistenceConfig = {
    chainId: bigint;
    coreAddress: Address;
};

export type RecoveryQueryResult = {
    rows: unknown[];
    rowCount?: number | null;
};

export type RecoveryQuery = (
    sql: string,
    params?: unknown[]
) => Promise<RecoveryQueryResult>;

export type RecoveryTransaction = <T>(
    action: (transactionQuery: RecoveryQuery) => Promise<T>
) => Promise<T>;

type IndexedRecoveryShareLogRow = {
    event_name: string;
    payload: unknown;
};

type IndexedRecoveryAssetRow = {
    payload: unknown;
};

export type RecoveryShareBalanceRow = {
    share_id: string;
    balance_raw: string;
};

const RECOVERY_SHARE_REPLAY_MAX_LOGS = 100_000;
const RECOVERY_SHARE_V2_MAX_BALANCES = 100_000;
export const RECOVERY_SHARE_V2_VERSION = "1";
export const RECOVERY_SHARE_V2_STATE_KEYS = Object.freeze({
    version: "recovery_share_v2_version",
    block: "recovery_share_v2_block",
    blockHash: "recovery_share_v2_block_hash",
    profile: "recovery_share_v2_profile",
});
const HASH_PATTERN = /^0x[a-fA-F0-9]{64}$/;
const DECIMAL_PATTERN = /^(?:0|[1-9][0-9]*)$/;

export function recoveryShareV2Enabled(value: string | undefined) {
    if (value === undefined || value === "" || value === "0" || value === "false") {
        return false;
    }
    if (value === "1" || value === "true") return true;
    throw new Error(
        "ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED must be one of 0, 1, false, or true"
    );
}

export function parseBigIntLike(value: unknown): bigint | null {
    if (typeof value === "bigint") return value;
    if (typeof value === "number" && Number.isFinite(value) && Number.isInteger(value)) {
        return BigInt(value);
    }
    if (typeof value === "string") {
        try {
            return BigInt(value);
        } catch {
            return null;
        }
    }
    return null;
}

export function parseAddressLike(value: unknown): string | null {
    if (typeof value !== "string") return null;
    try {
        return getAddress(value as `0x${string}`).toLowerCase();
    } catch {
        return null;
    }
}

function parseBigIntArrayLike(value: unknown): bigint[] | null {
    if (!Array.isArray(value)) return null;
    const result: bigint[] = [];
    for (const item of value) {
        const parsed = parseBigIntLike(item);
        if (parsed === null) return null;
        result.push(parsed);
    }
    return result;
}

export function extractRecoveryShareTransferArgs(
    eventName: string,
    payload: unknown
): IndexedRecoveryShareTransfer | null {
    if (!payload || typeof payload !== "object") return null;
    const args = (payload as { args?: unknown }).args;
    if (!args || typeof args !== "object") return null;

    const values = args as Record<string, unknown>;
    const operator = parseAddressLike(values.operator);
    const from = parseAddressLike(values.from);
    const to = parseAddressLike(values.to);
    if (!operator || !from || !to) return null;

    if (eventName === "TransferSingle") {
        const id = parseBigIntLike(values.id);
        const value = parseBigIntLike(values.value);
        if (id === null || value === null) return null;
        return {
            operator: operator as Address,
            from: from as Address,
            to: to as Address,
            ids: [id],
            amounts: [value],
        };
    }

    if (eventName === "TransferBatch") {
        const ids = parseBigIntArrayLike(values.ids);
        const amounts = parseBigIntArrayLike(values.values);
        if (!ids || !amounts) return null;
        return {
            operator: operator as Address,
            from: from as Address,
            to: to as Address,
            ids,
            amounts,
        };
    }

    return null;
}

export type RecoveryShareV2Checkpoint = Readonly<{
    version: string;
    blockNumber: bigint;
    blockHash: `0x${string}`;
    profile: string;
}>;

type RecoveryShareV2StateRow = { state_key: string; state_value: string };

export async function readRecoveryShareV2Checkpoint(
    config: RecoveryPersistenceConfig,
    runQuery: RecoveryQuery,
    forUpdate = false
): Promise<RecoveryShareV2Checkpoint | null> {
    const result = await runQuery(
        `
            SELECT state_key, state_value
            FROM onchain_sync_state
            WHERE chain_id = $1
              AND contract_address = $2
              AND state_key = ANY($3::text[])
            ${forUpdate ? "FOR UPDATE" : ""}
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            Object.values(RECOVERY_SHARE_V2_STATE_KEYS),
        ]
    );
    if (result.rows.length === 0) return null;
    if (result.rows.length !== 4) {
        throw new Error("Recovery-share v2 checkpoint is incomplete");
    }
    const values = new Map<string, string>();
    for (const row of result.rows as RecoveryShareV2StateRow[]) {
        if (
            !Object.values(RECOVERY_SHARE_V2_STATE_KEYS).includes(
                row.state_key as (typeof RECOVERY_SHARE_V2_STATE_KEYS)[keyof typeof RECOVERY_SHARE_V2_STATE_KEYS]
            ) ||
            typeof row.state_value !== "string" ||
            values.has(row.state_key)
        ) {
            throw new Error("Recovery-share v2 checkpoint is ambiguous");
        }
        values.set(row.state_key, row.state_value);
    }
    const version = values.get(RECOVERY_SHARE_V2_STATE_KEYS.version);
    const block = values.get(RECOVERY_SHARE_V2_STATE_KEYS.block);
    const blockHash = values.get(RECOVERY_SHARE_V2_STATE_KEYS.blockHash);
    const profile = values.get(RECOVERY_SHARE_V2_STATE_KEYS.profile);
    if (
        !version ||
        !block ||
        !DECIMAL_PATTERN.test(block) ||
        !blockHash ||
        !HASH_PATTERN.test(blockHash) ||
        !profile
    ) {
        throw new Error("Recovery-share v2 checkpoint is invalid");
    }
    return Object.freeze({
        version,
        blockNumber: BigInt(block),
        blockHash: blockHash.toLowerCase() as `0x${string}`,
        profile,
    });
}

export async function reconcileRecoveryShareBalancesV2(input: {
    config: RecoveryPersistenceConfig;
    snapshotBlock: bigint;
    snapshotBlockHash: `0x${string}`;
    profile: string;
    canonicalPreviousCheckpointHash: `0x${string}` | null;
    transactionQuery: RecoveryQuery;
}) {
    const checkpoint = await readRecoveryShareV2Checkpoint(
        input.config,
        input.transactionQuery,
        true
    );
    if (checkpoint && checkpoint.blockNumber > input.snapshotBlock) {
        throw new Error("Recovery-share v2 checkpoint is ahead of the snapshot");
    }
    if (
        checkpoint &&
        checkpoint.blockNumber === input.snapshotBlock &&
        checkpoint.blockHash.toLowerCase() !== input.snapshotBlockHash.toLowerCase()
    ) {
        throw new Error("Recovery-share v2 snapshot hash changed");
    }
    if (
        checkpoint &&
        checkpoint.version === RECOVERY_SHARE_V2_VERSION &&
        checkpoint.profile === input.profile &&
        checkpoint.blockNumber === input.snapshotBlock
    ) {
        return { rebuilt: false, appliedLogCount: 0 } as const;
    }

    const incremental = Boolean(
        checkpoint &&
            checkpoint.version === RECOVERY_SHARE_V2_VERSION &&
            checkpoint.profile === input.profile &&
            checkpoint.blockNumber < input.snapshotBlock &&
            input.canonicalPreviousCheckpointHash &&
            checkpoint.blockHash.toLowerCase() ===
                input.canonicalPreviousCheckpointHash.toLowerCase()
    );
    const lowerBound = incremental && checkpoint ? checkpoint.blockNumber : null;
    const logResult = await input.transactionQuery(
        `
            SELECT event_name, payload
            FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND event_name IN ('TransferSingle', 'TransferBatch')
              AND block_number <= $3
              ${lowerBound === null ? "" : "AND block_number > $4"}
            ORDER BY block_number ASC, log_index ASC, tx_hash ASC
            LIMIT ${RECOVERY_SHARE_REPLAY_MAX_LOGS + 1}
        `,
        lowerBound === null
            ? [
                  input.config.chainId.toString(),
                  input.config.coreAddress.toLowerCase(),
                  input.snapshotBlock.toString(),
              ]
            : [
                  input.config.chainId.toString(),
                  input.config.coreAddress.toLowerCase(),
                  input.snapshotBlock.toString(),
                  lowerBound.toString(),
              ]
    );
    if (logResult.rows.length > RECOVERY_SHARE_REPLAY_MAX_LOGS) {
        throw new Error(
            `Recovery-share v2 replay exceeds ${RECOVERY_SHARE_REPLAY_MAX_LOGS} indexed transfer logs`
        );
    }

    const balances = new Map<string, bigint>();
    if (incremental) {
        const balanceResult = await input.transactionQuery(
            `
                SELECT share_id, holder_address, balance_raw
                FROM onchain_recovery_share_balances_v2
                WHERE chain_id = $1 AND contract_address = $2
                ORDER BY share_id::numeric ASC, holder_address ASC
                LIMIT ${RECOVERY_SHARE_V2_MAX_BALANCES + 1}
            `,
            [
                input.config.chainId.toString(),
                input.config.coreAddress.toLowerCase(),
            ]
        );
        if (balanceResult.rows.length > RECOVERY_SHARE_V2_MAX_BALANCES) {
            throw new Error("Recovery-share v2 balance cardinality limit exceeded");
        }
        for (const row of balanceResult.rows as Array<{
            share_id: string;
            holder_address: string;
            balance_raw: string;
        }>) {
            const holder = parseAddressLike(row.holder_address);
            const shareId = parseBigIntLike(row.share_id);
            const balance = parseBigIntLike(row.balance_raw);
            if (!holder || shareId === null || balance === null || balance <= 0n) {
                throw new Error("Stored recovery-share v2 balance is invalid");
            }
            balances.set(
                recoveryShareBalanceKey(holder as Address, shareId),
                balance
            );
        }
    }
    for (const row of logResult.rows as IndexedRecoveryShareLogRow[]) {
        const transfer = extractRecoveryShareTransferArgs(row.event_name, row.payload);
        if (!transfer) {
            throw new Error(`Malformed indexed ERC-1155 ${row.event_name} payload`);
        }
        applyIndexedRecoveryShareTransfer(balances, transfer);
        if (balances.size > RECOVERY_SHARE_V2_MAX_BALANCES) {
            throw new Error("Recovery-share v2 balance cardinality limit exceeded");
        }
    }

    await input.transactionQuery(
        `DELETE FROM onchain_recovery_share_balances_v2
         WHERE chain_id = $1 AND contract_address = $2`,
        [input.config.chainId.toString(), input.config.coreAddress.toLowerCase()]
    );
    for (const [key, balance] of [...balances.entries()].sort()) {
        const separator = key.lastIndexOf(":");
        await input.transactionQuery(
            `
                INSERT INTO onchain_recovery_share_balances_v2 (
                    chain_id, contract_address, share_id, holder_address, balance_raw
                ) VALUES ($1, $2, $3, $4, $5)
            `,
            [
                input.config.chainId.toString(),
                input.config.coreAddress.toLowerCase(),
                key.slice(separator + 1),
                key.slice(0, separator),
                balance.toString(),
            ]
        );
    }
    for (const [stateKey, stateValue] of [
        [RECOVERY_SHARE_V2_STATE_KEYS.version, RECOVERY_SHARE_V2_VERSION],
        [RECOVERY_SHARE_V2_STATE_KEYS.block, input.snapshotBlock.toString()],
        [RECOVERY_SHARE_V2_STATE_KEYS.blockHash, input.snapshotBlockHash.toLowerCase()],
        [RECOVERY_SHARE_V2_STATE_KEYS.profile, input.profile],
    ] as const) {
        await input.transactionQuery(
            `
                INSERT INTO onchain_sync_state (
                    chain_id, contract_address, state_key, state_value
                ) VALUES ($1, $2, $3, $4)
                ON CONFLICT (chain_id, contract_address, state_key)
                DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = NOW()
            `,
            [
                input.config.chainId.toString(),
                input.config.coreAddress.toLowerCase(),
                stateKey,
                stateValue,
            ]
        );
    }
    return { rebuilt: !incremental, appliedLogCount: logResult.rows.length } as const;
}

export async function readIndexedRecoveryAssets(
    config: RecoveryPersistenceConfig,
    snapshotBlock: bigint,
    runQuery: RecoveryQuery
) {
    const result = await runQuery(
        `
            SELECT payload
            FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND event_name = 'RecoveryActivated'
              AND block_number <= $3
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            snapshotBlock.toString(),
        ]
    );

    const assets = new Map<string, Address>();
    for (const row of result.rows as IndexedRecoveryAssetRow[]) {
        if (!row.payload || typeof row.payload !== "object") continue;
        const args = (row.payload as { args?: unknown }).args;
        if (!args || typeof args !== "object") continue;
        const asset = parseAddressLike((args as { asset?: unknown }).asset);
        if (asset) assets.set(asset, asset as Address);
    }
    return [...assets.values()].sort((left, right) =>
        BigInt(left) < BigInt(right) ? -1 : 1
    );
}

export async function readIndexedReserveAssets(
    config: RecoveryPersistenceConfig,
    snapshotBlock: bigint,
    runQuery: RecoveryQuery
) {
    const result = await runQuery(
        `
            SELECT payload
            FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND event_name = 'ReserveLifecycleChanged'
              AND block_number <= $3
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            snapshotBlock.toString(),
        ]
    );
    const assets = new Map<string, Address>();
    for (const row of result.rows as IndexedRecoveryAssetRow[]) {
        if (!row.payload || typeof row.payload !== "object") continue;
        const args = (row.payload as { args?: unknown }).args;
        if (!args || typeof args !== "object") continue;
        const asset = parseAddressLike((args as { asset?: unknown }).asset);
        if (asset) assets.set(asset, asset as Address);
    }
    return [...assets.values()].sort((left, right) =>
        BigInt(left) < BigInt(right) ? -1 : 1
    );
}

export async function rebuildRecoveryShareBalances(
    config: RecoveryPersistenceConfig,
    runQuery: RecoveryQuery,
    runTransaction: RecoveryTransaction,
    finalize?: (transactionQuery: RecoveryQuery) => Promise<void>
) {
    const result = await runQuery(
        `
            SELECT event_name, payload
            FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND event_name IN ('TransferSingle', 'TransferBatch')
            ORDER BY block_number ASC, log_index ASC, tx_hash ASC
            LIMIT ${RECOVERY_SHARE_REPLAY_MAX_LOGS + 1}
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase()]
    );
    if (result.rows.length > RECOVERY_SHARE_REPLAY_MAX_LOGS) {
        throw new Error(
            `Recovery-share replay exceeds ${RECOVERY_SHARE_REPLAY_MAX_LOGS} indexed transfer logs`
        );
    }

    const transfers = (result.rows as IndexedRecoveryShareLogRow[]).map((row) => {
        const transfer = extractRecoveryShareTransferArgs(row.event_name, row.payload);
        if (!transfer) {
            throw new Error(`Malformed indexed ERC-1155 ${row.event_name} payload`);
        }
        return transfer;
    });
    const balances = replayIndexedRecoveryShareTransfers(transfers);

    await runTransaction(async (transactionQuery) => {
        await transactionQuery(
            `
                DELETE FROM onchain_recovery_share_balances
                WHERE chain_id = $1
                  AND contract_address = $2
            `,
            [config.chainId.toString(), config.coreAddress.toLowerCase()]
        );

        for (const balance of balances) {
            await transactionQuery(
                `
                    INSERT INTO onchain_recovery_share_balances (
                        chain_id,
                        contract_address,
                        share_id,
                        holder_address,
                        balance_raw
                    ) VALUES ($1, $2, $3, $4, $5)
                `,
                [
                    config.chainId.toString(),
                    config.coreAddress.toLowerCase(),
                    balance.shareId.toString(),
                    balance.holder.toLowerCase(),
                    balance.balance.toString(),
                ]
            );
        }
        await finalize?.(transactionQuery);
    });
}

export function buildRecoverySharePortfolio<
    TPool extends { asset: string },
    TRecovery extends { pools: TPool[] },
>(params: {
    config: RecoveryPersistenceConfig;
    snapshotBlock: bigint;
    balanceRows: RecoveryShareBalanceRow[];
    recovery: TRecovery | null;
    fundStatus?: unknown;
    fundOffersByShareId?: ReadonlyMap<string, unknown>;
}) {
    const {
        config,
        snapshotBlock,
        balanceRows,
        recovery,
        fundStatus = null,
        fundOffersByShareId,
    } = params;
    if (!recovery) {
        throw new Error("Core recovery snapshot is unavailable");
    }

    const poolByShareId = new Map(
        recovery.pools.map((pool) => [BigInt(pool.asset).toString(), pool])
    );
    return {
        enabled: true,
        collection: config.coreAddress.toLowerCase(),
        snapshotBlock: snapshotBlock.toString(),
        fund: fundStatus,
        balances: balanceRows.map((row) => ({
            shareId: row.share_id,
            balanceRaw: row.balance_raw,
            pool: poolByShareId.get(row.share_id) ?? null,
            fundOffer: fundOffersByShareId?.get(row.share_id) ?? null,
        })),
        pools: recovery.pools,
    };
}
