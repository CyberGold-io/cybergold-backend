export const LEGACY_PER_EVENT_LOG_REQUEST_BASELINE = Object.freeze({
    coreRequestsPerChunk: 14,
    governanceRequestsPerChunk: 3,
    safeRequestsPerAddressChunk: 2,
});

export const ADDRESS_SCOPED_LOG_REQUEST_BUDGET = Object.freeze({
    coreRequestsPerChunk: 1,
    governanceRequestsPerChunk: 1,
    safeRequestsPerAddressChunk: 1,
});

// Address-scoped clients disable Viem transport retries so every raw-log wire
// attempt is owned and counted by the App pagination loop. Legacy clients retain
// their existing transport behavior, whose internal retries are not observable.
export const ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT = 0;

const MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000;

export const INDEXER_GATEWAY_RPC_METHODS = [
    "eth_call",
    "eth_chainId",
    "eth_getBlockByHash",
    "eth_getBlockByNumber",
    "eth_getCode",
    "eth_getLogs",
] as const;

export type IndexerGatewayRpcMethod =
    (typeof INDEXER_GATEWAY_RPC_METHODS)[number];

export type IndexerRpcRequestSource =
    | "core-event"
    | "governance-event"
    | "safe-event"
    | "core-address"
    | "governance-address"
    | "safe-address";

export type IndexerRpcRequestCounts = Readonly<{
    totalAttempts: number;
    failedAttempts: number;
    adaptiveRetryAttempts: number;
    byMethod: Readonly<Record<IndexerGatewayRpcMethod, number>>;
    ethGetLogs: Readonly<{
        attempts: number;
        plannedAttempts: number;
        adaptiveAttempts: number;
        failedAttempts: number;
        addressScopedViemTransportRetries: 0;
        legacyViemTransportRetriesObserved: null;
        bySource: Readonly<Record<IndexerRpcRequestSource, number>>;
        plannedBySource: Readonly<Record<IndexerRpcRequestSource, number>>;
    }>;
}>;

export type IndexerRpcRequestCounter = {
    recordEthGetLogsPlan(source: IndexerRpcRequestSource): void;
    recordEthGetLogsAttempt(
        source: IndexerRpcRequestSource,
        adaptive: boolean
    ): void;
    recordEthGetLogsFailure(): void;
    recordGatewayRpcAttempt(method: string): void;
    recordGatewayRpcFailure(): void;
    snapshot(): IndexerRpcRequestCounts;
};

export class IndexerGatewayRpcMethodRejectedError extends Error {
    constructor() {
        super("Indexer gateway RPC method is outside the frozen App allowlist");
        this.name = "IndexerGatewayRpcMethodRejectedError";
    }
}

function isIndexerGatewayRpcMethod(
    method: string
): method is IndexerGatewayRpcMethod {
    return (INDEXER_GATEWAY_RPC_METHODS as readonly string[]).includes(method);
}

export function createIndexerRpcRequestCounter(): IndexerRpcRequestCounter {
    let totalAttempts = 0;
    let failedAttempts = 0;
    let ethGetLogsAttempts = 0;
    let plannedEthGetLogs = 0;
    let adaptiveEthGetLogsAttempts = 0;
    let failedEthGetLogsAttempts = 0;
    const byMethod: Record<IndexerGatewayRpcMethod, number> = {
        eth_call: 0,
        eth_chainId: 0,
        eth_getBlockByHash: 0,
        eth_getBlockByNumber: 0,
        eth_getCode: 0,
        eth_getLogs: 0,
    };
    const bySource: Record<IndexerRpcRequestSource, number> = {
        "core-event": 0,
        "governance-event": 0,
        "safe-event": 0,
        "core-address": 0,
        "governance-address": 0,
        "safe-address": 0,
    };
    const plannedBySource: Record<IndexerRpcRequestSource, number> = {
        "core-event": 0,
        "governance-event": 0,
        "safe-event": 0,
        "core-address": 0,
        "governance-address": 0,
        "safe-address": 0,
    };

    return {
        recordEthGetLogsPlan(source) {
            plannedEthGetLogs += 1;
            plannedBySource[source] += 1;
        },
        recordEthGetLogsAttempt(source, adaptive) {
            ethGetLogsAttempts += 1;
            bySource[source] += 1;
            if (adaptive) adaptiveEthGetLogsAttempts += 1;
        },
        recordEthGetLogsFailure() {
            failedEthGetLogsAttempts += 1;
        },
        recordGatewayRpcAttempt(method) {
            if (!isIndexerGatewayRpcMethod(method)) {
                throw new IndexerGatewayRpcMethodRejectedError();
            }
            totalAttempts += 1;
            byMethod[method] += 1;
        },
        recordGatewayRpcFailure() {
            failedAttempts += 1;
        },
        snapshot() {
            return Object.freeze({
                totalAttempts,
                failedAttempts,
                adaptiveRetryAttempts: adaptiveEthGetLogsAttempts,
                byMethod: Object.freeze({ ...byMethod }),
                ethGetLogs: Object.freeze({
                    attempts: ethGetLogsAttempts,
                    plannedAttempts: plannedEthGetLogs,
                    adaptiveAttempts: adaptiveEthGetLogsAttempts,
                    failedAttempts: failedEthGetLogsAttempts,
                    addressScopedViemTransportRetries:
                        ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT,
                    legacyViemTransportRetriesObserved: null,
                    bySource: Object.freeze({ ...bySource }),
                    plannedBySource: Object.freeze({ ...plannedBySource }),
                }),
            });
        },
    };
}

export async function instrumentEthGetLogsRequest<T>(
    counter: IndexerRpcRequestCounter,
    source: IndexerRpcRequestSource,
    request: () => Promise<T>
): Promise<T> {
    counter.recordEthGetLogsPlan(source);
    return instrumentEthGetLogsAttempt(counter, source, false, request);
}

export async function instrumentEthGetLogsAttempt<T>(
    counter: IndexerRpcRequestCounter,
    source: IndexerRpcRequestSource,
    adaptive: boolean,
    request: () => Promise<T>
): Promise<T> {
    counter.recordEthGetLogsAttempt(source, adaptive);
    try {
        return await request();
    } catch (error) {
        counter.recordEthGetLogsFailure();
        throw error;
    }
}

export function assertLegacyPerEventDefinitionCount(
    source: "core" | "governance" | "safe",
    actual: number
) {
    const expected =
        source === "core"
            ? LEGACY_PER_EVENT_LOG_REQUEST_BASELINE.coreRequestsPerChunk
            : source === "governance"
              ? LEGACY_PER_EVENT_LOG_REQUEST_BASELINE.governanceRequestsPerChunk
              : LEGACY_PER_EVENT_LOG_REQUEST_BASELINE.safeRequestsPerAddressChunk;
    if (actual !== expected) {
        throw new Error(
            `Legacy ${source} per-event RPC baseline changed: expected ${expected}, received ${actual}`
        );
    }
}

export function calculateLegacyPerEventLogRequests(input: {
    coreChunks: number;
    governanceChunks?: number;
    safeAddressChunks: readonly number[];
}) {
    const values = [
        input.coreChunks,
        input.governanceChunks ?? 0,
        ...input.safeAddressChunks,
    ];
    if (values.some((value) => !Number.isSafeInteger(value) || value < 0)) {
        throw new Error("Legacy RPC baseline inputs must be non-negative safe integers");
    }

    return (
        input.coreChunks * LEGACY_PER_EVENT_LOG_REQUEST_BASELINE.coreRequestsPerChunk +
        (input.governanceChunks ?? 0) *
            LEGACY_PER_EVENT_LOG_REQUEST_BASELINE.governanceRequestsPerChunk +
        input.safeAddressChunks.reduce(
            (total, chunks) =>
                total +
                chunks * LEGACY_PER_EVENT_LOG_REQUEST_BASELINE.safeRequestsPerAddressChunk,
            0
        )
    );
}

export function calculateAddressScopedLogRequests(input: {
    coreChunks: number;
    governanceChunks?: number;
    safeAddressChunks: readonly number[];
}) {
    const values = [
        input.coreChunks,
        input.governanceChunks ?? 0,
        ...input.safeAddressChunks,
    ];
    if (values.some((value) => !Number.isSafeInteger(value) || value < 0)) {
        throw new Error("Address-scoped RPC budget inputs must be non-negative safe integers");
    }

    return (
        input.coreChunks * ADDRESS_SCOPED_LOG_REQUEST_BUDGET.coreRequestsPerChunk +
        (input.governanceChunks ?? 0) *
            ADDRESS_SCOPED_LOG_REQUEST_BUDGET.governanceRequestsPerChunk +
        input.safeAddressChunks.reduce(
            (total, chunks) =>
                total +
                chunks * ADDRESS_SCOPED_LOG_REQUEST_BUDGET.safeRequestsPerAddressChunk,
            0
        )
    );
}

export function calculateScheduledDailyEthGetLogs(input: {
    intervalMs: number;
    ethGetLogsPerRun: number;
}) {
    if (
        !Number.isSafeInteger(input.intervalMs) ||
        input.intervalMs <= 0 ||
        !Number.isSafeInteger(input.ethGetLogsPerRun) ||
        input.ethGetLogsPerRun < 0
    ) {
        throw new Error(
            "Scheduled RPC budget inputs must be non-negative safe integers with a positive interval"
        );
    }
    return (
        Math.ceil(MILLISECONDS_PER_DAY / input.intervalMs) * input.ethGetLogsPerRun
    );
}

export function calculateRequestReductionPercent(input: {
    baselineRequests: number;
    candidateRequests: number;
}) {
    if (
        !Number.isSafeInteger(input.baselineRequests) ||
        input.baselineRequests <= 0 ||
        !Number.isSafeInteger(input.candidateRequests) ||
        input.candidateRequests < 0
    ) {
        throw new Error("RPC reduction inputs must be safe non-negative request counts");
    }
    return ((input.baselineRequests - input.candidateRequests) * 100) /
        input.baselineRequests;
}
