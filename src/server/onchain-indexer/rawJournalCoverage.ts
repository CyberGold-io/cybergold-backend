import type { Address, Hex } from "viem";

import type { RawJournalLog } from "./rawLogModel.ts";

export const RAW_JOURNAL_CURSOR_VERSION_KEY = "raw_log_journal_version";
export const RAW_JOURNAL_START_BLOCK_KEY = "raw_log_start_block";
export const RAW_JOURNAL_LAST_SCANNED_BLOCK_KEY = "raw_log_last_scanned_block";
export const RAW_JOURNAL_LAST_SCANNED_BLOCK_HASH_KEY =
    "raw_log_last_scanned_block_hash";
export const RAW_JOURNAL_COVERAGE_STATE_KEYS = Object.freeze([
    RAW_JOURNAL_CURSOR_VERSION_KEY,
    RAW_JOURNAL_START_BLOCK_KEY,
    RAW_JOURNAL_LAST_SCANNED_BLOCK_KEY,
    RAW_JOURNAL_LAST_SCANNED_BLOCK_HASH_KEY,
] as const);

const HASH_PATTERN = /^0x[a-fA-F0-9]{64}$/;
const DATA_PATTERN = /^0x(?:[a-fA-F0-9]{2})*$/;
const CANONICAL_INTEGER_PATTERN = /^(?:0|[1-9][0-9]*)$/;
const MAX_POSTGRES_BIGINT = 9_223_372_036_854_775_807n;
const MAX_POSTGRES_INTEGER = 2_147_483_647n;
const MAX_JAVASCRIPT_DATE_SECONDS = 8_640_000_000_000n;

export type RawJournalCoverage = Readonly<{
    address: Address;
    journalVersion: string;
    startBlock: bigint;
    cursorBlock: bigint;
    cursorBlockHash: Hex;
}>;

export type RawJournalCoverageRow = Readonly<{
    state_key: string;
    state_value: string;
}>;

export type StoredRawJournalLogRow = Readonly<{
    contract_address: string;
    block_number: string;
    block_hash: string;
    tx_hash: string;
    log_index: number | string;
    topics: unknown;
    data: string;
    block_timestamp_seconds: string;
}>;

export function rawJournalProjectionReplayEnabled(value: string | undefined) {
    if (value === undefined || value === "" || value === "0" || value === "false") {
        return false;
    }
    if (value === "1" || value === "true") return true;
    throw new Error(
        "ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED must be one of 0, 1, false, or true"
    );
}

function canonicalNonnegativeBigInt(
    value: unknown,
    label: string,
    maximum = MAX_POSTGRES_BIGINT
) {
    if (typeof value !== "string" || !CANONICAL_INTEGER_PATTERN.test(value)) {
        throw new Error(`${label} is not a canonical integer`);
    }
    const parsed = BigInt(value);
    if (parsed > maximum) {
        throw new Error(`${label} exceeds its supported range`);
    }
    return parsed;
}

export function parseRawJournalCoverageRows(input: {
    address: Address;
    expectedVersion: string;
    rows: readonly RawJournalCoverageRow[];
}): RawJournalCoverage | null {
    if (input.rows.length === 0) return null;
    if (input.rows.length !== RAW_JOURNAL_COVERAGE_STATE_KEYS.length) {
        throw new Error("Raw journal coverage state is incomplete");
    }
    const values = new Map<string, string>();
    for (const row of input.rows) {
        if (
            !RAW_JOURNAL_COVERAGE_STATE_KEYS.includes(
                row.state_key as (typeof RAW_JOURNAL_COVERAGE_STATE_KEYS)[number]
            ) ||
            typeof row.state_value !== "string" ||
            values.has(row.state_key)
        ) {
            throw new Error("Raw journal coverage state is ambiguous");
        }
        values.set(row.state_key, row.state_value);
    }
    const journalVersion = values.get(RAW_JOURNAL_CURSOR_VERSION_KEY);
    if (journalVersion !== input.expectedVersion) {
        throw new Error("Raw journal coverage version does not match the replay profile");
    }
    const startBlock = canonicalNonnegativeBigInt(
        values.get(RAW_JOURNAL_START_BLOCK_KEY),
        "Raw journal coverage start"
    );
    const cursorBlock = canonicalNonnegativeBigInt(
        values.get(RAW_JOURNAL_LAST_SCANNED_BLOCK_KEY),
        "Raw journal coverage cursor"
    );
    const cursorBlockHash = values.get(
        RAW_JOURNAL_LAST_SCANNED_BLOCK_HASH_KEY
    );
    if (!cursorBlockHash || !HASH_PATTERN.test(cursorBlockHash)) {
        throw new Error("Raw journal coverage cursor hash is invalid");
    }
    if (startBlock > cursorBlock) {
        throw new Error("Raw journal coverage interval is inverted");
    }
    return Object.freeze({
        address: input.address,
        journalVersion,
        startBlock,
        cursorBlock,
        cursorBlockHash: cursorBlockHash.toLowerCase() as Hex,
    });
}

export function assertRawJournalReplayCoverage(input: {
    coverage: RawJournalCoverage;
    requiredStartBlock: bigint;
    maximumBlock: bigint;
    canonicalCursorHash: Hex;
}) {
    if (
        input.requiredStartBlock < 0n ||
        input.maximumBlock < input.requiredStartBlock ||
        input.coverage.startBlock > input.requiredStartBlock ||
        input.coverage.cursorBlock > input.maximumBlock
    ) {
        throw new Error("Raw journal coverage does not match the replay profile");
    }
    if (
        input.coverage.cursorBlockHash.toLowerCase() !==
        input.canonicalCursorHash.toLowerCase()
    ) {
        throw new Error("Raw journal coverage cursor hash is not canonical");
    }
    return input.coverage;
}

export function planRawJournalCoverageMerge(input: {
    current: RawJournalCoverage | null;
    address: Address;
    journalVersion: string;
    authoritativeStartBlock: bigint;
    fromBlock: bigint;
    toBlock: bigint;
    toBlockHash: Hex;
}): RawJournalCoverage {
    if (!input.current) {
        if (input.fromBlock !== input.authoritativeStartBlock) {
            throw new Error(
                "First raw journal interval must begin at its configured recovery start"
            );
        }
        return Object.freeze({
            address: input.address,
            journalVersion: input.journalVersion,
            startBlock: input.fromBlock,
            cursorBlock: input.toBlock,
            cursorBlockHash: input.toBlockHash.toLowerCase() as Hex,
        });
    }
    const current = input.current;
    if (
        current.address.toLowerCase() !== input.address.toLowerCase() ||
        current.journalVersion !== input.journalVersion
    ) {
        throw new Error("Raw journal coverage identity changed");
    }
    const isAuthoritativePrefixBackfill =
        current.startBlock > input.authoritativeStartBlock &&
        input.fromBlock === input.authoritativeStartBlock &&
        input.toBlock + 1n === current.startBlock;
    if (
        current.startBlock > input.authoritativeStartBlock &&
        !isAuthoritativePrefixBackfill
    ) {
        throw new Error(
            "Raw journal coverage is non-authoritative; reset its coverage metadata before provider backfill"
        );
    }
    if (
        input.fromBlock > current.cursorBlock + 1n ||
        input.toBlock + 1n < current.startBlock
    ) {
        throw new Error("Raw journal ingestion would create a coverage gap");
    }
    return Object.freeze({
        address: input.address,
        journalVersion: input.journalVersion,
        startBlock:
            input.fromBlock < current.startBlock
                ? input.fromBlock
                : current.startBlock,
        cursorBlock:
            input.toBlock > current.cursorBlock
                ? input.toBlock
                : current.cursorBlock,
        cursorBlockHash:
            input.toBlock >= current.cursorBlock
                ? (input.toBlockHash.toLowerCase() as Hex)
                : current.cursorBlockHash,
    });
}

export function normalizeStoredRawJournalRows(input: {
    rows: readonly StoredRawJournalLogRow[];
    address: Address;
    fromBlock: bigint;
    toBlock: bigint;
    coverage: RawJournalCoverage;
}) {
    const logs: RawJournalLog[] = [];
    let previousIdentity: readonly [bigint, bigint, string] | null = null;
    for (const row of input.rows) {
        if (
            row.contract_address !== input.address.toLowerCase() ||
            !HASH_PATTERN.test(row.block_hash) ||
            !HASH_PATTERN.test(row.tx_hash) ||
            !DATA_PATTERN.test(row.data) ||
            !Array.isArray(row.topics) ||
            row.topics.length > 4 ||
            !row.topics.every(
                (topic) => typeof topic === "string" && HASH_PATTERN.test(topic)
            )
        ) {
            throw new Error("Stored raw journal log identity is invalid");
        }
        const blockNumber = canonicalNonnegativeBigInt(
            row.block_number,
            "Stored raw journal block"
        );
        const logIndex = canonicalNonnegativeBigInt(
            typeof row.log_index === "number"
                ? row.log_index.toString()
                : row.log_index,
            "Stored raw journal log index",
            MAX_POSTGRES_INTEGER
        );
        const blockTimestampSeconds = canonicalNonnegativeBigInt(
            row.block_timestamp_seconds,
            "Stored raw journal block timestamp",
            MAX_JAVASCRIPT_DATE_SECONDS
        );
        if (blockNumber < input.fromBlock || blockNumber > input.toBlock) {
            throw new Error("Stored raw journal log is outside the replay range");
        }
        if (
            blockNumber === input.coverage.cursorBlock &&
            row.block_hash.toLowerCase() !==
                input.coverage.cursorBlockHash.toLowerCase()
        ) {
            throw new Error("Stored raw journal log contradicts its cursor hash");
        }
        const identity = [
            blockNumber,
            logIndex,
            row.tx_hash.toLowerCase(),
        ] as const;
        if (
            previousIdentity &&
            (identity[0] < previousIdentity[0] ||
                (identity[0] === previousIdentity[0] &&
                    (identity[1] < previousIdentity[1] ||
                        (identity[1] === previousIdentity[1] &&
                            identity[2] <= previousIdentity[2]))))
        ) {
            throw new Error("Stored raw journal logs are not uniquely ordered");
        }
        previousIdentity = identity;
        logs.push({
            contractAddress: input.address,
            blockNumber,
            blockHash: row.block_hash.toLowerCase() as Hex,
            transactionHash: row.tx_hash.toLowerCase() as Hex,
            logIndex: Number(logIndex),
            topics: row.topics.map((topic) => topic.toLowerCase() as Hex),
            data: row.data.toLowerCase() as Hex,
            blockTimestampSeconds,
        });
    }
    return Object.freeze(logs);
}
