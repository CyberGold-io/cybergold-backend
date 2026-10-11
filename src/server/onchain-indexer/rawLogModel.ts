import {
    decodeEventLog,
    hexToBigInt,
    isAddress,
    toEventSelector,
    type AbiEvent,
    type Address,
    type Hex,
} from "viem";

export type RawRpcLog = Readonly<{
    address?: unknown;
    blockNumber?: unknown;
    blockHash?: unknown;
    transactionHash?: unknown;
    logIndex?: unknown;
    data?: unknown;
    topics?: unknown;
    removed?: unknown;
}>;

export type RawJournalLog = Readonly<{
    contractAddress: Address;
    blockNumber: bigint;
    blockHash: Hex;
    transactionHash: Hex;
    logIndex: number;
    topics: readonly Hex[];
    data: Hex;
    blockTimestampSeconds: bigint;
}>;

export type RawBlockHeader = Readonly<{
    hash: Hex;
    timestamp: bigint;
}>;

type KnownEventDefinition<Name extends string = string> = Readonly<{
    name: Name;
    abi: AbiEvent;
}>;

const HASH_PATTERN = /^0x[a-fA-F0-9]{64}$/;
const QUANTITY_PATTERN = /^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$/;
const DATA_PATTERN = /^0x(?:[a-fA-F0-9]{2})*$/;
const MAX_POSTGRES_BIGINT = 9_223_372_036_854_775_807n;
const MAX_POSTGRES_INTEGER = 2_147_483_647n;
const MAX_JAVASCRIPT_DATE_SECONDS = 8_640_000_000_000n;
const MAX_RAW_LOGS_PER_REQUEST = 50_000;

function isHash(value: unknown): value is Hex {
    return typeof value === "string" && HASH_PATTERN.test(value);
}

function parseRpcLog(
    value: unknown,
    expectedAddress: Address,
    fromBlock: bigint,
    toBlock: bigint
) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
        throw new Error("Address-scoped eth_getLogs returned a non-object entry");
    }
    const log = value as RawRpcLog;
    if (
        typeof log.address !== "string" ||
        !isAddress(log.address) ||
        log.address.toLowerCase() !== expectedAddress.toLowerCase()
    ) {
        throw new Error("Address-scoped eth_getLogs returned an unexpected address");
    }
    if (log.removed === true) {
        throw new Error("Address-scoped eth_getLogs returned a removed log");
    }
    if (!isHash(log.blockHash) || !isHash(log.transactionHash)) {
        throw new Error("Address-scoped eth_getLogs returned an incomplete log identity");
    }
    if (
        typeof log.blockNumber !== "string" ||
        !QUANTITY_PATTERN.test(log.blockNumber) ||
        typeof log.logIndex !== "string" ||
        !QUANTITY_PATTERN.test(log.logIndex)
    ) {
        throw new Error("Address-scoped eth_getLogs returned an invalid numeric identity");
    }
    if (typeof log.data !== "string" || !DATA_PATTERN.test(log.data)) {
        throw new Error("Address-scoped eth_getLogs returned invalid data");
    }
    if (!Array.isArray(log.topics) || !log.topics.every(isHash)) {
        throw new Error("Address-scoped eth_getLogs returned invalid topics");
    }

    const blockNumber = hexToBigInt(log.blockNumber as Hex);
    if (
        blockNumber > MAX_POSTGRES_BIGINT ||
        blockNumber < fromBlock ||
        blockNumber > toBlock
    ) {
        throw new Error("Address-scoped eth_getLogs returned an out-of-range log");
    }
    const logIndexValue = hexToBigInt(log.logIndex as Hex);
    if (logIndexValue > MAX_POSTGRES_INTEGER) {
        throw new Error("Address-scoped eth_getLogs returned an invalid log index");
    }
    const logIndex = Number(logIndexValue);

    return {
        contractAddress: expectedAddress,
        blockNumber,
        blockHash: log.blockHash.toLowerCase() as Hex,
        transactionHash: log.transactionHash.toLowerCase() as Hex,
        logIndex,
        topics: log.topics.map((topic) => topic.toLowerCase() as Hex),
        data: log.data.toLowerCase() as Hex,
    };
}

export async function normalizeAddressScopedRpcLogs(input: {
    value: unknown;
    expectedAddress: Address;
    fromBlock: bigint;
    toBlock: bigint;
    readBlockHeader(blockNumber: bigint): Promise<RawBlockHeader>;
}) {
    if (!Array.isArray(input.value)) {
        throw new Error("Address-scoped eth_getLogs returned a non-array result");
    }
    if (input.value.length > MAX_RAW_LOGS_PER_REQUEST) {
        throw new Error("Address-scoped eth_getLogs exceeded the raw log cardinality limit");
    }

    const parsed = input.value.map((value) =>
        parseRpcLog(value, input.expectedAddress, input.fromBlock, input.toBlock)
    );
    const headers = new Map<bigint, RawBlockHeader>();
    const identities = new Map<string, string>();
    const normalized: RawJournalLog[] = [];

    for (const log of parsed) {
        let header = headers.get(log.blockNumber);
        if (!header) {
            header = await input.readBlockHeader(log.blockNumber);
            if (
                !isHash(header.hash) ||
                typeof header.timestamp !== "bigint" ||
                header.timestamp < 0n ||
                header.timestamp > MAX_JAVASCRIPT_DATE_SECONDS
            ) {
                throw new Error("Address-scoped raw log block header is invalid");
            }
            headers.set(log.blockNumber, header);
        }
        if (header.hash.toLowerCase() !== log.blockHash.toLowerCase()) {
            throw new Error(
                "Address-scoped eth_getLogs block hash does not match its header"
            );
        }

        const identity = `${log.transactionHash}:${log.logIndex}`;
        const fingerprint = JSON.stringify({
            ...log,
            blockNumber: log.blockNumber.toString(),
        });
        const previousFingerprint = identities.get(identity);
        if (previousFingerprint && previousFingerprint !== fingerprint) {
            throw new Error("Address-scoped eth_getLogs returned conflicting duplicates");
        }
        if (previousFingerprint) continue;
        identities.set(identity, fingerprint);

        normalized.push({
            ...log,
            blockTimestampSeconds: header.timestamp,
        });
    }

    return normalized.sort((left, right) => {
        if (left.blockNumber !== right.blockNumber) {
            return left.blockNumber < right.blockNumber ? -1 : 1;
        }
        return left.logIndex - right.logIndex;
    });
}

export function createKnownRawLogDecoder<
    const Definitions extends readonly KnownEventDefinition[],
>(definitions: Definitions) {
    const definitionsByTopic = new Map(
        definitions.map((definition) => [
            toEventSelector(definition.abi).toLowerCase(),
            definition,
        ])
    );

    return (log: RawJournalLog) => {
        const topic = log.topics[0]?.toLowerCase();
        const definition = topic ? definitionsByTopic.get(topic) : undefined;
        if (!definition) return null;

        try {
            const decoded = decodeEventLog({
                abi: [definition.abi],
                data: log.data,
                topics: [...log.topics] as [] | [Hex, ...Hex[]],
                strict: true,
            });
            return {
                eventName: definition.name as Definitions[number]["name"],
                args: decoded.args,
            };
        } catch (error) {
            throw new Error(`Failed to decode known ${definition.name} raw log`, {
                cause: error,
            });
        }
    };
}

export function addressScopedRawLogsEnabled(value: string | undefined) {
    if (value === undefined || value === "" || value === "0" || value === "false") {
        return false;
    }
    if (value === "1" || value === "true") return true;
    throw new Error(
        "ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS must be one of 0, 1, false, or true"
    );
}
