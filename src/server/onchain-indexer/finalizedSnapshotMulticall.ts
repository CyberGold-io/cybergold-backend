import { encodeFunctionData, type Address, type Hex } from "viem";

export const CYBERGOLD_MULTICALL3_ADDRESS =
    "0xca11bde05977b3631167028862be2a173976ca11" as Address;
export const FINALIZED_MULTICALL_MAX_CALLS = 1_024;
export const FINALIZED_MULTICALL_MAX_TOTAL_CALLDATA_BYTES = 1_048_576;
export const FINALIZED_MULTICALL_MAX_CALLS_PER_BATCH = 32;
export const FINALIZED_MULTICALL_MAX_BATCH_CALLDATA_BYTES = 65_536;
export const FINALIZED_MULTICALL_MAX_PROVIDER_REQUESTS = 32;

type BatchingLimits = Readonly<{
    maxCalls: number;
    maxTotalCalldataBytes: number;
    maxCallsPerBatch: number;
    maxBatchCalldataBytes: number;
}>;

type FinalizedMulticallLimits = BatchingLimits &
    Readonly<{ maxProviderRequests: number }>;

export class FinalizedMulticallBudgetExceededError extends Error {
    constructor(message = "Finalized Multicall read budget exceeded") {
        super(message);
        this.name = "FinalizedMulticallBudgetExceededError";
    }
}

export class FinalizedMulticallProviderRequestBudgetExceededError extends
    FinalizedMulticallBudgetExceededError {
    constructor() {
        super("Finalized Multicall provider request budget exceeded");
        this.name = "FinalizedMulticallProviderRequestBudgetExceededError";
    }
}

export function isFinalizedMulticallBudgetExceeded(error: unknown) {
    return error instanceof FinalizedMulticallBudgetExceededError;
}

type ReadRequest = Readonly<{
    address: Address;
    abi: readonly unknown[];
    functionName: string;
    args?: readonly unknown[];
    blockHash?: Hex;
    requireCanonical?: boolean;
    blockNumber?: bigint;
    blockTag?: string;
}>;

type PendingRead = {
    request: ReadRequest;
    calldataBytes: number;
    resolve(value: unknown): void;
    reject(error: unknown): void;
};

type MulticallResult =
    | { status: "success"; result: unknown }
    | { status: "failure"; error: unknown };

type MulticallCapableClient = {
    readContract(request: ReadRequest): Promise<unknown>;
    multicall(request: unknown): Promise<readonly MulticallResult[]>;
};

export function finalizedSnapshotMulticallEnabled(value: string | undefined) {
    if (value === undefined || value === "" || value === "0" || value === "false") {
        return false;
    }
    if (value === "1" || value === "true") return true;
    throw new Error(
        "ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED must be one of 0, 1, false, or true"
    );
}

export function planBoundedMulticallBatches(
    calldataBytes: readonly number[],
    limits: BatchingLimits = {
        maxCalls: FINALIZED_MULTICALL_MAX_CALLS,
        maxTotalCalldataBytes: FINALIZED_MULTICALL_MAX_TOTAL_CALLDATA_BYTES,
        maxCallsPerBatch: FINALIZED_MULTICALL_MAX_CALLS_PER_BATCH,
        maxBatchCalldataBytes: FINALIZED_MULTICALL_MAX_BATCH_CALLDATA_BYTES,
    }
) {
    if (
        calldataBytes.length > limits.maxCalls ||
        calldataBytes.some(
            (size) => !Number.isSafeInteger(size) || size <= 0 || size > limits.maxBatchCalldataBytes
        ) ||
        calldataBytes.reduce((sum, size) => sum + size, 0) >
            limits.maxTotalCalldataBytes
    ) {
        throw new FinalizedMulticallBudgetExceededError();
    }
    const batches: Array<{ from: number; to: number; calldataBytes: number }> = [];
    let from = 0;
    let size = 0;
    for (let index = 0; index < calldataBytes.length; index += 1) {
        const next = calldataBytes[index];
        if (
            index > from &&
            (index - from >= limits.maxCallsPerBatch ||
                size + next > limits.maxBatchCalldataBytes)
        ) {
            batches.push({ from, to: index, calldataBytes: size });
            from = index;
            size = 0;
        }
        size += next;
    }
    if (from < calldataBytes.length) {
        batches.push({ from, to: calldataBytes.length, calldataBytes: size });
    }
    return Object.freeze(batches.map((batch) => Object.freeze(batch)));
}

function calldataSize(request: ReadRequest) {
    const data = encodeFunctionData({
        abi: request.abi,
        functionName: request.functionName,
        args: request.args,
    } as never);
    return (data.length - 2) / 2;
}

export function createBoundedFinalizedMulticallClient<TClient extends object>(input: {
    client: TClient;
    blockHash: Hex;
    limits?: FinalizedMulticallLimits;
}): TClient {
    const client = input.client as TClient & MulticallCapableClient;
    const queue: PendingRead[] = [];
    let flushScheduled = false;
    let totalCalls = 0;
    let totalCalldataBytes = 0;
    let providerRequests = 0;

    const flush = async () => {
        flushScheduled = false;
        const pending = queue.splice(0);
        if (pending.length === 0) return;
        let batches: ReturnType<typeof planBoundedMulticallBatches>;
        try {
            batches = planBoundedMulticallBatches(
                pending.map((entry) => entry.calldataBytes),
                input.limits
            );
        } catch (error) {
            pending.forEach((entry) => entry.reject(error));
            return;
        }
        const maximumProviderRequests =
            input.limits?.maxProviderRequests ??
            FINALIZED_MULTICALL_MAX_PROVIDER_REQUESTS;
        if (
            !Number.isSafeInteger(maximumProviderRequests) ||
            maximumProviderRequests <= 0 ||
            providerRequests + batches.length > maximumProviderRequests
        ) {
            const error =
                new FinalizedMulticallProviderRequestBudgetExceededError();
            pending.forEach((entry) => entry.reject(error));
            return;
        }
        providerRequests += batches.length;
        for (const batch of batches) {
            const entries = pending.slice(batch.from, batch.to);
            try {
                const results = await client.multicall({
                    contracts: entries.map(({ request }) => ({
                        address: request.address,
                        abi: request.abi,
                        functionName: request.functionName,
                        args: request.args,
                    })),
                    allowFailure: true,
                    blockHash: input.blockHash,
                    requireCanonical: true,
                    multicallAddress: CYBERGOLD_MULTICALL3_ADDRESS,
                    // The package-lock-pinned Viem multicall action chunks on
                    // the same sum of encoded inner callData byte lengths used
                    // by planBoundedMulticallBatches. Matching batchSize here
                    // makes each counted wrapper invocation exactly one eth_call.
                    batchSize: FINALIZED_MULTICALL_MAX_BATCH_CALLDATA_BYTES,
                });
                if (results.length !== entries.length) {
                    throw new Error("Finalized Multicall returned the wrong result count");
                }
                results.forEach((result, index) => {
                    const entry = entries[index];
                    if (result.status === "success") entry.resolve(result.result);
                    else entry.reject(result.error);
                });
            } catch (error) {
                entries.forEach((entry) => entry.reject(error));
            }
        }
    };

    const readContract = (request: ReadRequest) => {
        if (
            request.blockHash?.toLowerCase() !== input.blockHash.toLowerCase() ||
            request.requireCanonical !== true ||
            request.blockNumber !== undefined ||
            request.blockTag !== undefined
        ) {
            return Promise.reject(
                new Error("Finalized Multicall read is not bound to its exact canonical anchor")
            );
        }
        let size: number;
        try {
            size = calldataSize(request);
            totalCalls += 1;
            totalCalldataBytes += size;
            planBoundedMulticallBatches(
                Array.from({ length: totalCalls }, (_, index) =>
                    index === totalCalls - 1 ? size : 1
                ),
                {
                    ...(input.limits ?? {
                        maxCalls: FINALIZED_MULTICALL_MAX_CALLS,
                        maxTotalCalldataBytes:
                            FINALIZED_MULTICALL_MAX_TOTAL_CALLDATA_BYTES,
                        maxCallsPerBatch: FINALIZED_MULTICALL_MAX_CALLS_PER_BATCH,
                        maxBatchCalldataBytes:
                            FINALIZED_MULTICALL_MAX_BATCH_CALLDATA_BYTES,
                    }),
                    maxTotalCalldataBytes:
                        input.limits?.maxTotalCalldataBytes ??
                        FINALIZED_MULTICALL_MAX_TOTAL_CALLDATA_BYTES,
                }
            );
            if (
                totalCalldataBytes >
                (input.limits?.maxTotalCalldataBytes ??
                    FINALIZED_MULTICALL_MAX_TOTAL_CALLDATA_BYTES)
            ) {
                throw new FinalizedMulticallBudgetExceededError();
            }
        } catch (error) {
            return Promise.reject(error);
        }
        const result = new Promise<unknown>((resolve, reject) => {
            queue.push({ request, calldataBytes: size, resolve, reject });
        });
        if (!flushScheduled) {
            flushScheduled = true;
            queueMicrotask(() => void flush());
        }
        return result;
    };

    return new Proxy(input.client, {
        get(target, property, receiver) {
            if (property === "readContract") return readContract;
            return Reflect.get(target, property, receiver);
        },
    });
}
