export type InclusiveBlockRange = Readonly<{
    fromBlock: bigint;
    toBlock: bigint;
}>;

export type AdaptiveRangeAttempt = Readonly<{
    range: InclusiveBlockRange;
    adaptive: boolean;
}>;

export type AdaptiveRangeResult<T> = Readonly<{
    values: readonly T[];
    successfulRanges: readonly InclusiveBlockRange[];
    attemptCount: number;
    adaptiveAttemptCount: number;
}>;

export const DEFAULT_ADAPTIVE_LOG_MAX_ATTEMPTS = 128;
export const DEFAULT_ADAPTIVE_LOG_MAX_RANGES = 128;
export const DEFAULT_ADAPTIVE_LOG_MAX_CARDINALITY = 50_000;
const DIRECT_PROVIDER_RANGE_RPC_CODES = new Set([-32_005, -32_016]);

export class AdaptiveLogRequestTerminalError extends Error {
    constructor() {
        super("Address-scoped log request failed without an approved range-reduction signal");
        this.name = "AdaptiveLogRequestTerminalError";
    }
}

function assertRange(range: InclusiveBlockRange) {
    if (range.fromBlock < 0n || range.fromBlock > range.toBlock) {
        throw new Error("Adaptive log range is invalid");
    }
}

export function splitInclusiveBlockRange(
    range: InclusiveBlockRange
): readonly [InclusiveBlockRange, InclusiveBlockRange] {
    assertRange(range);
    if (range.fromBlock === range.toBlock) {
        throw new Error("A one-block log range cannot be split");
    }
    const midpoint = (range.fromBlock + range.toBlock) / 2n;
    return Object.freeze([
        Object.freeze({ fromBlock: range.fromBlock, toBlock: midpoint }),
        Object.freeze({ fromBlock: midpoint + 1n, toBlock: range.toBlock }),
    ]);
}

export function assertExactRangeCoverage(
    baseRange: InclusiveBlockRange,
    successfulRanges: readonly InclusiveBlockRange[]
) {
    assertRange(baseRange);
    let expectedFromBlock = baseRange.fromBlock;
    for (const range of successfulRanges) {
        assertRange(range);
        if (
            range.fromBlock !== expectedFromBlock ||
            range.toBlock > baseRange.toBlock
        ) {
            throw new Error("Adaptive log ranges do not exactly cover the base range");
        }
        expectedFromBlock = range.toBlock + 1n;
    }
    if (expectedFromBlock !== baseRange.toBlock + 1n) {
        throw new Error("Adaptive log ranges do not exactly cover the base range");
    }
}

export function shouldSplitDirectProviderLogRequest(error: unknown) {
    const seen = new Set<unknown>();
    let current = error;
    for (let depth = 0; depth < 16 && current && !seen.has(current); depth += 1) {
        seen.add(current);
        if (typeof current !== "object") return false;
        const candidate = current as {
            name?: unknown;
            status?: unknown;
            code?: unknown;
            cause?: unknown;
        };
        if (
            candidate.name === "HttpRequestError" &&
            candidate.status === 413
        ) {
            return true;
        }
        if (
            candidate.name === "RpcRequestError" &&
            typeof candidate.code === "number" &&
            DIRECT_PROVIDER_RANGE_RPC_CODES.has(candidate.code)
        ) {
            return true;
        }
        current = candidate.cause;
    }
    return false;
}

export async function executeAdaptiveBlockRanges<T>(input: {
    baseRange: InclusiveBlockRange;
    maxAttempts?: number;
    maxRanges?: number;
    maxCardinality?: number;
    shouldSplitRequestFailure?(error: unknown): boolean;
    requestRange(attempt: AdaptiveRangeAttempt): Promise<unknown>;
    validateRange(
        value: unknown,
        range: InclusiveBlockRange
    ): Promise<readonly T[]> | readonly T[];
}): Promise<AdaptiveRangeResult<T>> {
    assertRange(input.baseRange);
    const maxAttempts = input.maxAttempts ?? DEFAULT_ADAPTIVE_LOG_MAX_ATTEMPTS;
    const maxRanges = input.maxRanges ?? DEFAULT_ADAPTIVE_LOG_MAX_RANGES;
    const maxCardinality =
        input.maxCardinality ?? DEFAULT_ADAPTIVE_LOG_MAX_CARDINALITY;
    for (const [name, value] of [
        ["attempt", maxAttempts],
        ["range", maxRanges],
        ["cardinality", maxCardinality],
    ] as const) {
        if (!Number.isSafeInteger(value) || value <= 0) {
            throw new Error(`Adaptive log ${name} cap must be a positive safe integer`);
        }
    }

    const pendingRanges: InclusiveBlockRange[] = [input.baseRange];
    const successfulRanges: InclusiveBlockRange[] = [];
    const values: T[] = [];
    let attemptCount = 0;
    let adaptiveAttemptCount = 0;
    let createdRangeCount = 1;

    while (pendingRanges.length > 0) {
        if (attemptCount >= maxAttempts) {
            throw new Error("Adaptive log request attempt cap was exceeded");
        }
        const range = pendingRanges.pop();
        if (!range) {
            throw new Error("Adaptive log range planner lost pending work");
        }
        const adaptive =
            range.fromBlock !== input.baseRange.fromBlock ||
            range.toBlock !== input.baseRange.toBlock;
        attemptCount += 1;
        if (adaptive) adaptiveAttemptCount += 1;

        let response: unknown;
        try {
            response = await input.requestRange({ range, adaptive });
        } catch (error) {
            if (!input.shouldSplitRequestFailure?.(error)) {
                throw new AdaptiveLogRequestTerminalError();
            }
            if (range.fromBlock === range.toBlock) {
                throw new Error("Address-scoped log request failed for one block");
            }
            if (createdRangeCount + 2 > maxRanges) {
                throw new Error("Adaptive log request range cap was exceeded");
            }
            const [left, right] = splitInclusiveBlockRange(range);
            createdRangeCount += 2;
            // Stack order is right then left so execution and recomposition are
            // deterministic and strictly ascending by block range.
            pendingRanges.push(right, left);
            continue;
        }

        const rangeValues = await input.validateRange(response, range);
        if (values.length + rangeValues.length > maxCardinality) {
            throw new Error("Adaptive log response cardinality cap was exceeded");
        }
        successfulRanges.push(range);
        values.push(...rangeValues);
    }

    assertExactRangeCoverage(input.baseRange, successfulRanges);
    return Object.freeze({
        values: Object.freeze(values),
        successfulRanges: Object.freeze(successfulRanges),
        attemptCount,
        adaptiveAttemptCount,
    });
}
