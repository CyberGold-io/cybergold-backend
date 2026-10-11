import type { Hex } from "viem";

import type { FinalizedRunAnchor } from "./finalizedReconciliation.ts";

export const INTERNAL_RECONCILE_REQUEST_KIND =
    "cybergold-b2b-reconcile-request";
export const INTERNAL_RECONCILE_REQUEST_FORMAT_VERSION = 1;
export const INTERNAL_RECONCILE_RESPONSE_KIND =
    "cybergold-b2b-reconcile-response";
export const INTERNAL_RECONCILE_RESPONSE_FORMAT_VERSION = 2;
export const INTERNAL_RECONCILE_RESPONSE_STATUSES = Object.freeze([
    "reconciled",
    "incomplete",
    "deferred-cadence",
    "busy",
] as const);
export const INTERNAL_RECONCILE_MODES = Object.freeze([
    "allow-exact-receipt-noop",
    "require-worker-run",
] as const);
const MAX_REQUEST_BYTES = 4_096;

export type InternalReconcileMode =
    (typeof INTERNAL_RECONCILE_MODES)[number];
export type InternalReconcileStatus =
    (typeof INTERNAL_RECONCILE_RESPONSE_STATUSES)[number];
export type DashboardHistoryProgress = Readonly<{
    formatVersion: 1;
    startBlock: string;
    indexedThroughBlock: string;
    indexedThroughDate: string;
    networkFinalizedBlock: string;
    networkFinalizedDate: string;
    percent: number;
}>;
export type InternalReconcileResult = Readonly<{
    status: InternalReconcileStatus;
    dashboardHistoryProgress: DashboardHistoryProgress | null;
}>;
/** @deprecated New App configurations use the endpoint as their only RPC mode. */
export type InternalGatewayExpectation = Readonly<{
    runtimeRevision: string;
    finalizedAnchor: FinalizedRunAnchor;
}>;
export type ParsedInternalReconcileRequest = Readonly<{
    legacy: boolean;
    mode: InternalReconcileMode;
}>;

const MAX_JAVASCRIPT_DATE_SECONDS = 8_640_000_000_000n;

export function createDashboardHistoryProgress(input: {
    startBlock: bigint;
    indexedThroughBlock: bigint;
    indexedThroughTimestampSeconds: bigint;
    networkFinalizedBlock: bigint;
    networkFinalizedTimestampSeconds: bigint;
}): DashboardHistoryProgress {
    if (
        input.startBlock < 0n ||
        input.indexedThroughBlock < 0n ||
        input.networkFinalizedBlock < 0n ||
        input.indexedThroughTimestampSeconds < 0n ||
        input.indexedThroughTimestampSeconds > MAX_JAVASCRIPT_DATE_SECONDS ||
        input.networkFinalizedTimestampSeconds < 0n ||
        input.networkFinalizedTimestampSeconds > MAX_JAVASCRIPT_DATE_SECONDS ||
        input.indexedThroughBlock < input.startBlock ||
        input.indexedThroughBlock > input.networkFinalizedBlock ||
        input.startBlock > input.networkFinalizedBlock
    ) {
        throw new Error("Dashboard history progress is invalid");
    }
    const totalBlocks = input.networkFinalizedBlock - input.startBlock;
    const completedBlocks = input.indexedThroughBlock - input.startBlock;
    const percent =
        totalBlocks === 0n
            ? 100
            : Number((completedBlocks * 10_000n) / totalBlocks) / 100;
    return Object.freeze({
        formatVersion: 1,
        startBlock: input.startBlock.toString(),
        indexedThroughBlock: input.indexedThroughBlock.toString(),
        indexedThroughDate: new Date(
            Number(input.indexedThroughTimestampSeconds) * 1_000
        ).toISOString(),
        networkFinalizedBlock: input.networkFinalizedBlock.toString(),
        networkFinalizedDate: new Date(
            Number(input.networkFinalizedTimestampSeconds) * 1_000
        ).toISOString(),
        percent,
    });
}

export function classifyInternalReconcileOutcome(
    outcome: Readonly<{ completed: boolean }> | undefined
): Exclude<InternalReconcileStatus, "busy"> {
    if (!outcome) return "deferred-cadence";
    return outcome.completed ? "reconciled" : "incomplete";
}

export function internalReconcileHttpStatus(
    status: InternalReconcileStatus
): 200 | 202 | 409 {
    switch (status) {
        case "reconciled":
        case "deferred-cadence":
            return 200;
        case "incomplete":
            return 202;
        case "busy":
            return 409;
    }
}

export function buildInternalReconcileResponse(
    result: InternalReconcileResult,
    legacy: boolean
) {
    return Object.freeze({
        body: legacy
            ? Object.freeze({ status: result.status })
            : Object.freeze({
                  kind: INTERNAL_RECONCILE_RESPONSE_KIND,
                  formatVersion: INTERNAL_RECONCILE_RESPONSE_FORMAT_VERSION,
                  status: result.status,
                  dashboardHistoryProgress: result.dashboardHistoryProgress,
              }),
        httpStatus: internalReconcileHttpStatus(result.status),
        retryAfter: result.status === "busy" ? ("1" as const) : null,
    });
}

/** @deprecated Retained only for source compatibility with legacy receipt readers. */
export function planInternalGatewayReconcile(input: {
    mode: InternalReconcileMode;
    exactReceiptAvailable: boolean;
    compatibleReceiptCompletedAtMs: number | null;
    nowMs: number;
    reconcileIntervalMs: number;
    leaseAmbiguous: boolean;
}) {
    if (input.leaseAmbiguous) return "reject-ambiguous" as const;
    if (
        input.mode === "allow-exact-receipt-noop" &&
        input.exactReceiptAvailable &&
        input.compatibleReceiptCompletedAtMs !== null &&
        input.nowMs - input.compatibleReceiptCompletedAtMs >= 0
    ) {
        return "exact-receipt-noop" as const;
    }
    if (
        input.mode === "allow-exact-receipt-noop" &&
        input.compatibleReceiptCompletedAtMs !== null
    ) {
        const ageMs = input.nowMs - input.compatibleReceiptCompletedAtMs;
        if (ageMs >= 0 && ageMs < input.reconcileIntervalMs) {
            return "deferred-cadence" as const;
        }
    }
    return "acquire-lease" as const;
}

/** @deprecated New App configurations never send a Gateway expectation. */
export function assertGatewayExpectationNotStale(input: {
    expectedAnchor: FinalizedRunAnchor;
    committedBlockNumber: bigint | null;
    committedBlockHash: Hex | null;
}) {
    if (
        input.committedBlockNumber !== null &&
        input.committedBlockNumber > input.expectedAnchor.blockNumber
    ) {
        throw new Error("Controller finalized anchor is older than the committed boundary");
    }
    if (
        input.committedBlockNumber === input.expectedAnchor.blockNumber &&
        input.committedBlockHash?.toLowerCase() !==
            input.expectedAnchor.blockHash.toLowerCase()
    ) {
        throw new Error("Controller finalized anchor contradicts the committed boundary");
    }
}

function exactKeys(value: object, keys: readonly string[]) {
    const actual = Object.keys(value).sort();
    const expected = [...keys].sort();
    return (
        actual.length === expected.length &&
        actual.every((key, index) => key === expected[index])
    );
}

function rejectDuplicateJsonKeys(source: string) {
    const stack: Array<{ kind: "object"; keys: Set<string> } | { kind: "array" }> = [];
    let inString = false;
    let escaped = false;
    let stringStart = -1;
    for (let index = 0; index < source.length; index += 1) {
        const character = source[index];
        if (inString) {
            if (escaped) escaped = false;
            else if (character === "\\") escaped = true;
            else if (character === '"') {
                inString = false;
                let next = index + 1;
                while (/\s/.test(source[next] ?? "")) next += 1;
                const frame = stack.at(-1);
                if (source[next] === ":" && frame?.kind === "object") {
                    let key: unknown;
                    try {
                        key = JSON.parse(source.slice(stringStart, index + 1));
                    } catch {
                        throw new Error("Internal reconcile JSON is invalid");
                    }
                    if (typeof key !== "string" || frame.keys.has(key)) {
                        throw new Error("Internal reconcile JSON has duplicate keys");
                    }
                    frame.keys.add(key);
                }
            }
            continue;
        }
        if (character === '"') {
            inString = true;
            stringStart = index;
        } else if (character === "{") {
            stack.push({ kind: "object", keys: new Set() });
        } else if (character === "[") {
            stack.push({ kind: "array" });
        } else if (character === "}" || character === "]") {
            stack.pop();
        }
    }
}

async function boundedBody(request: Request) {
    const declared = request.headers.get("content-length");
    if (
        declared !== null &&
        (!/^\d+$/.test(declared) || Number(declared) > MAX_REQUEST_BYTES)
    ) {
        throw new Error("Internal reconcile request is too large");
    }
    const reader = request.body?.getReader();
    if (!reader) return new Uint8Array();
    const chunks: Uint8Array[] = [];
    let length = 0;
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > MAX_REQUEST_BYTES) {
            await reader.cancel();
            throw new Error("Internal reconcile request is too large");
        }
        chunks.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
    }
    return bytes;
}

export async function parseInternalReconcileRequest(input: {
    request: Request;
}): Promise<ParsedInternalReconcileRequest> {
    const bytes = await boundedBody(input.request);
    if (bytes.length === 0) {
        return Object.freeze({
            legacy: true,
            mode: "require-worker-run",
        });
    }
    if (
        input.request.headers
            .get("content-type")
            ?.split(";", 1)[0]
            ?.trim()
            .toLowerCase() !== "application/json"
    ) {
        throw new Error("Internal reconcile request must use application/json");
    }
    let source: string;
    let value: unknown;
    try {
        source = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        rejectDuplicateJsonKeys(source);
        value = JSON.parse(source);
    } catch {
        throw new Error("Internal reconcile JSON is invalid");
    }
    if (
        !value ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        !exactKeys(value, ["formatVersion", "kind", "mode"])
    ) {
        throw new Error("Internal reconcile request shape is invalid");
    }
    const root = value as Record<string, unknown>;
    if (
        root.kind !== INTERNAL_RECONCILE_REQUEST_KIND ||
        root.formatVersion !== INTERNAL_RECONCILE_REQUEST_FORMAT_VERSION ||
        !INTERNAL_RECONCILE_MODES.includes(root.mode as InternalReconcileMode)
    ) {
        throw new Error("Internal reconcile request identity is invalid");
    }
    return Object.freeze({
        legacy: false,
        mode: root.mode as InternalReconcileMode,
    });
}
