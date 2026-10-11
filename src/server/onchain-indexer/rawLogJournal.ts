
import type { Address, Hex } from "viem";
import {
    executeAdaptiveBlockRanges,
    type InclusiveBlockRange,
} from "./adaptiveLogPagination";
import { query, withTransaction, type TransactionQuery } from "./db";
import {
    normalizeAddressScopedRpcLogs,
    type RawBlockHeader,
    type RawJournalLog,
} from "./rawLogModel";
import {
    instrumentEthGetLogsAttempt,
    type IndexerRpcRequestCounter,
    type IndexerRpcRequestSource,
} from "./rpcRequestInstrumentation";
import {
    assertRawJournalReplayCoverage,
    normalizeStoredRawJournalRows,
    parseRawJournalCoverageRows,
    planRawJournalCoverageMerge,
    RAW_JOURNAL_COVERAGE_STATE_KEYS,
    RAW_JOURNAL_CURSOR_VERSION_KEY,
    RAW_JOURNAL_LAST_SCANNED_BLOCK_HASH_KEY,
    RAW_JOURNAL_LAST_SCANNED_BLOCK_KEY,
    RAW_JOURNAL_START_BLOCK_KEY,
    type RawJournalCoverage,
    type RawJournalCoverageRow,
    type StoredRawJournalLogRow,
} from "./rawJournalCoverage";

export {
    assertRawJournalReplayCoverage,
    parseRawJournalCoverageRows,
    planRawJournalCoverageMerge,
    rawJournalProjectionReplayEnabled,
    RAW_JOURNAL_COVERAGE_STATE_KEYS,
    RAW_JOURNAL_CURSOR_VERSION_KEY,
    RAW_JOURNAL_LAST_SCANNED_BLOCK_HASH_KEY,
    RAW_JOURNAL_LAST_SCANNED_BLOCK_KEY,
    RAW_JOURNAL_START_BLOCK_KEY,
    type RawJournalCoverage,
} from "./rawJournalCoverage";

const RAW_LOG_INSERT_BATCH_SIZE = 500;
const RAW_LOG_REPLAY_LIMIT = 50_000;
const HASH_PATTERN = /^0x[a-fA-F0-9]{64}$/;
const MAX_POSTGRES_BIGINT = 9_223_372_036_854_775_807n;
const MAX_JAVASCRIPT_DATE_SECONDS = 8_640_000_000_000n;

async function readRawJournalCoverageWithQuery(input: {
    chainId: bigint;
    address: Address;
    expectedVersion: string;
    execute: TransactionQuery;
    forUpdate?: boolean;
}) {
    const result = await input.execute<RawJournalCoverageRow>(
        `
            SELECT state_key, state_value
            FROM onchain_sync_state
            WHERE chain_id = $1
              AND contract_address = $2
              AND state_key = ANY($3::text[])
            ${input.forUpdate ? "FOR UPDATE" : ""}
        `,
        [
            input.chainId.toString(),
            input.address.toLowerCase(),
            RAW_JOURNAL_COVERAGE_STATE_KEYS,
        ]
    );
    return parseRawJournalCoverageRows({
        address: input.address,
        expectedVersion: input.expectedVersion,
        rows: result.rows,
    });
}

export async function readRawJournalCoverage(input: {
    chainId: bigint;
    address: Address;
    expectedVersion: string;
}) {
    return readRawJournalCoverageWithQuery({ ...input, execute: query });
}

export async function prepareRawJournalReplayCoverage(input: {
    enabled: boolean;
    chainId: bigint;
    address: Address;
    expectedVersion: string;
    requiredStartBlock: bigint;
    maximumBlock: bigint;
    readBlockHeader(blockNumber: bigint): Promise<RawBlockHeader>;
}) {
    if (!input.enabled) return null;
    const coverage = await readRawJournalCoverage(input);
    if (!coverage) return null;
    if (coverage.startBlock > input.requiredStartBlock) {
        throw new Error(
            "Raw journal coverage is non-authoritative until provider backfill reaches the configured recovery start"
        );
    }
    if (coverage.cursorBlock > input.maximumBlock) {
        throw new Error("Raw journal coverage is ahead of the finalized replay anchor");
    }
    const cursorHeader = await input.readBlockHeader(coverage.cursorBlock);
    return assertRawJournalReplayCoverage({
        coverage,
        requiredStartBlock: input.requiredStartBlock,
        maximumBlock: input.maximumBlock,
        canonicalCursorHash: cursorHeader.hash,
    });
}

async function setAddressState(
    transactionQuery: TransactionQuery,
    chainId: bigint,
    address: Address,
    key: string,
    value: string
) {
    await transactionQuery(
        `
            INSERT INTO onchain_sync_state (
                chain_id,
                contract_address,
                state_key,
                state_value
            ) VALUES ($1, $2, $3, $4)
            ON CONFLICT (chain_id, contract_address, state_key)
            DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = NOW()
        `,
        [chainId.toString(), address.toLowerCase(), key, value]
    );
}

async function insertRawLogBatch(
    transactionQuery: TransactionQuery,
    chainId: bigint,
    logs: readonly RawJournalLog[]
) {
    if (logs.length === 0) return;
    const params: unknown[] = [];
    const values = logs.map((log, rowIndex) => {
        const first = rowIndex * 9;
        params.push(
            chainId.toString(),
            log.contractAddress.toLowerCase(),
            log.blockNumber.toString(),
            log.blockHash.toLowerCase(),
            log.transactionHash.toLowerCase(),
            log.logIndex,
            JSON.stringify(log.topics),
            log.data.toLowerCase(),
            log.blockTimestampSeconds.toString()
        );
        return `($${first + 1}, $${first + 2}, $${first + 3}, $${first + 4}, $${first + 5}, $${first + 6}, $${first + 7}::jsonb, $${first + 8}, $${first + 9})`;
    });

    await transactionQuery(
        `
            INSERT INTO onchain_raw_logs (
                chain_id,
                contract_address,
                block_number,
                block_hash,
                tx_hash,
                log_index,
                topics,
                data,
                block_timestamp_seconds
            ) VALUES ${values.join(", ")}
            ON CONFLICT (chain_id, contract_address, tx_hash, log_index)
            DO UPDATE SET
                block_number = EXCLUDED.block_number,
                block_hash = EXCLUDED.block_hash,
                topics = EXCLUDED.topics,
                data = EXCLUDED.data,
                block_timestamp_seconds = EXCLUDED.block_timestamp_seconds,
                updated_at = NOW()
            WHERE onchain_raw_logs.block_number IS DISTINCT FROM EXCLUDED.block_number
               OR onchain_raw_logs.block_hash IS DISTINCT FROM EXCLUDED.block_hash
               OR onchain_raw_logs.topics IS DISTINCT FROM EXCLUDED.topics
               OR onchain_raw_logs.data IS DISTINCT FROM EXCLUDED.data
               OR onchain_raw_logs.block_timestamp_seconds IS DISTINCT FROM EXCLUDED.block_timestamp_seconds
        `,
        params
    );
}

export async function readRawJournalLogs(input: {
    chainId: bigint;
    address: Address;
    fromBlock: bigint;
    toBlock: bigint;
    coverage: RawJournalCoverage;
    execute?: TransactionQuery;
}) {
    if (
        input.coverage.address.toLowerCase() !== input.address.toLowerCase() ||
        input.fromBlock < input.coverage.startBlock ||
        input.toBlock > input.coverage.cursorBlock ||
        input.fromBlock > input.toBlock
    ) {
        throw new Error("Raw journal replay range is outside authoritative coverage");
    }
    const runQuery = input.execute ?? query;
    const result = await runQuery<StoredRawJournalLogRow>(
        `
            SELECT
                contract_address,
                block_number::text,
                block_hash,
                tx_hash,
                log_index,
                topics,
                data,
                block_timestamp_seconds::text
            FROM onchain_raw_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND block_number BETWEEN $3 AND $4
            ORDER BY block_number ASC, log_index ASC, tx_hash ASC
            LIMIT ${RAW_LOG_REPLAY_LIMIT + 1}
        `,
        [
            input.chainId.toString(),
            input.address.toLowerCase(),
            input.fromBlock.toString(),
            input.toBlock.toString(),
        ]
    );
    if (result.rows.length > RAW_LOG_REPLAY_LIMIT) {
        throw new Error("Raw journal replay exceeds its log cardinality limit");
    }

    return normalizeStoredRawJournalRows({
        rows: result.rows,
        address: input.address,
        fromBlock: input.fromBlock,
        toBlock: input.toBlock,
        coverage: input.coverage,
    });
}

export async function replaceRawJournalRange(input: {
    chainId: bigint;
    address: Address;
    authoritativeStartBlock: bigint;
    fromBlock: bigint;
    toBlock: bigint;
    toBlockHash: Hex;
    journalVersion: string;
    logs: readonly RawJournalLog[];
}) {
    if (
        input.authoritativeStartBlock < 0n ||
        input.fromBlock < 0n ||
        input.toBlock > MAX_POSTGRES_BIGINT ||
        input.fromBlock > input.toBlock
    ) {
        throw new Error("Raw journal replacement range is inverted");
    }
    if (!HASH_PATTERN.test(input.toBlockHash)) {
        throw new Error("Raw journal replacement anchor hash is invalid");
    }
    for (const log of input.logs) {
        if (
            log.contractAddress.toLowerCase() !== input.address.toLowerCase() ||
            log.blockNumber < input.fromBlock ||
            log.blockNumber > input.toBlock
        ) {
            throw new Error("Raw journal replacement contains an out-of-scope log");
        }
    }

    await withTransaction(async (transactionQuery) => {
        const current = await readRawJournalCoverageWithQuery({
            chainId: input.chainId,
            address: input.address,
            expectedVersion: input.journalVersion,
            execute: transactionQuery,
            forUpdate: true,
        });
        const mergedCoverage = planRawJournalCoverageMerge({
            current,
            address: input.address,
            journalVersion: input.journalVersion,
            authoritativeStartBlock: input.authoritativeStartBlock,
            fromBlock: input.fromBlock,
            toBlock: input.toBlock,
            toBlockHash: input.toBlockHash,
        });
        if (current === null) {
            await setAddressState(
                transactionQuery,
                input.chainId,
                input.address,
                RAW_JOURNAL_CURSOR_VERSION_KEY,
                input.journalVersion
            );
        }
        await transactionQuery(
            `
                DELETE FROM onchain_raw_logs
                WHERE chain_id = $1
                  AND contract_address = $2
                  AND block_number BETWEEN $3 AND $4
            `,
            [
                input.chainId.toString(),
                input.address.toLowerCase(),
                input.fromBlock.toString(),
                input.toBlock.toString(),
            ]
        );
        for (
            let offset = 0;
            offset < input.logs.length;
            offset += RAW_LOG_INSERT_BATCH_SIZE
        ) {
            await insertRawLogBatch(
                transactionQuery,
                input.chainId,
                input.logs.slice(offset, offset + RAW_LOG_INSERT_BATCH_SIZE)
            );
        }
        await setAddressState(
            transactionQuery,
            input.chainId,
            input.address,
            RAW_JOURNAL_START_BLOCK_KEY,
            mergedCoverage.startBlock.toString()
        );
        await setAddressState(
            transactionQuery,
            input.chainId,
            input.address,
            RAW_JOURNAL_LAST_SCANNED_BLOCK_KEY,
            mergedCoverage.cursorBlock.toString()
        );
        await setAddressState(
            transactionQuery,
            input.chainId,
            input.address,
            RAW_JOURNAL_LAST_SCANNED_BLOCK_HASH_KEY,
            mergedCoverage.cursorBlockHash.toLowerCase()
        );
    });
}

export async function ingestAddressScopedRawLogs(input: {
    chainId: bigint;
    address: Address;
    authoritativeStartBlock: bigint;
    fromBlock: bigint;
    toBlock: bigint;
    journalVersion: string;
    requestCounter: IndexerRpcRequestCounter;
    requestSource: IndexerRpcRequestSource;
    requestLogs(range: InclusiveBlockRange): Promise<unknown>;
    shouldSplitRequestFailure?(error: unknown): boolean;
    readBlockHeader(blockNumber: bigint): Promise<RawBlockHeader>;
    blockHeaderCache?: Map<bigint, RawBlockHeader>;
}) {
    const blockHeaderCache = input.blockHeaderCache ?? new Map();
    const validateBlockHeader = (header: RawBlockHeader) => {
        if (
            !HASH_PATTERN.test(header.hash) ||
            typeof header.timestamp !== "bigint" ||
            header.timestamp < 0n ||
            header.timestamp > MAX_JAVASCRIPT_DATE_SECONDS
        ) {
            throw new Error("Raw journal block header is invalid");
        }
        return header;
    };
    const readBlockHeader = async (blockNumber: bigint) => {
        const cached = blockHeaderCache.get(blockNumber);
        if (cached) return validateBlockHeader(cached);
        const header = validateBlockHeader(await input.readBlockHeader(blockNumber));
        blockHeaderCache.set(blockNumber, header);
        return header;
    };
    input.requestCounter.recordEthGetLogsPlan(input.requestSource);
    const adaptiveResult = await executeAdaptiveBlockRanges<RawJournalLog>({
        baseRange: {
            fromBlock: input.fromBlock,
            toBlock: input.toBlock,
        },
        shouldSplitRequestFailure: input.shouldSplitRequestFailure,
        requestRange: ({ range, adaptive }) =>
            instrumentEthGetLogsAttempt(
                input.requestCounter,
                input.requestSource,
                adaptive,
                () => input.requestLogs(range)
            ),
        validateRange: (value, range) =>
            normalizeAddressScopedRpcLogs({
                value,
                expectedAddress: input.address,
                fromBlock: range.fromBlock,
                toBlock: range.toBlock,
                readBlockHeader,
            }),
    });
    const logIdentities = new Set<string>();
    const logs = [...adaptiveResult.values];
    for (const log of logs) {
        const identity = `${log.transactionHash.toLowerCase()}:${log.logIndex}`;
        if (logIdentities.has(identity)) {
            throw new Error(
                "Adaptive eth_getLogs ranges returned a duplicate raw log identity"
            );
        }
        logIdentities.add(identity);
    }
    logs.sort((left, right) => {
        if (left.blockNumber !== right.blockNumber) {
            return left.blockNumber < right.blockNumber ? -1 : 1;
        }
        return left.logIndex - right.logIndex;
    });
    const anchor = await readBlockHeader(input.toBlock);
    await replaceRawJournalRange({
        chainId: input.chainId,
        address: input.address,
        authoritativeStartBlock: input.authoritativeStartBlock,
        fromBlock: input.fromBlock,
        toBlock: input.toBlock,
        toBlockHash: anchor.hash,
        journalVersion: input.journalVersion,
        logs,
    });
    return logs;
}
