import type { Address, Hex } from "viem";

import type { FinalizedRunAnchor } from "./finalizedReconciliation";
import {
    INDEXER_GATEWAY_RPC_METHODS,
    type IndexerRpcRequestCounts,
} from "./rpcRequestInstrumentation.ts";

export const RECONCILIATION_RECEIPT_KIND =
    "cybergold-onchain-indexer-reconciliation-receipt";
export const RECONCILIATION_RECEIPT_FORMAT_VERSION = 2;

const ADDRESS_PATTERN = /^0x[a-fA-F0-9]{40}$/;
const HASH_PATTERN = /^0x[a-fA-F0-9]{64}$/;
const REVISION_PATTERN = /^[0-9a-f]{64}$/;
const RECONCILIATION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const DECIMAL_PATTERN = /^(?:0|[1-9][0-9]*)$/;
const RUNTIME_CONFIG_ID_PATTERN = /^sha256:[0-9a-f]{64}$/;
const RPC_SOURCE_KEYS = [
    "core-event",
    "governance-event",
    "safe-event",
    "core-address",
    "governance-address",
    "safe-address",
] as const;

type CursorInput = Readonly<{
    address: Address;
    blockNumber: bigint;
    blockHash: Hex;
}>;

type ReceiptCursor = Readonly<{
    address: string;
    blockNumber: string;
    blockHash: string;
}>;

export type OnchainIndexerReconciliationReceipt = Readonly<{
    kind: typeof RECONCILIATION_RECEIPT_KIND;
    formatVersion: typeof RECONCILIATION_RECEIPT_FORMAT_VERSION;
    partial: false;
    reconciliationId: string;
    gatewayConfigRevision: string;
    runtimeConfigId: string | null;
    finalizedAnchor: Readonly<{ number: string; hash: string }>;
    identities: Readonly<{
        databaseSchemaVersion: string;
        rawJournalVersion: string;
        dashboardProjectionVersion: string;
        stateSnapshotVersion: string;
        safeCursorVersion: string;
    }>;
    rawJournal: Readonly<{
        trackedAddressCount: number;
        cursorCount: number;
        logCount: string;
        cursors: readonly ReceiptCursor[];
    }>;
    dashboardProjection: Readonly<{
        cursorCount: 1;
        eventLogCount: string;
        blockNumber: string;
        blockHash: string;
        profile: string;
    }>;
    stateSnapshot: Readonly<{
        cursorCount: 1;
        modelCount: string;
        blockNumber: string;
        blockHash: string;
        profile: string;
    }>;
    safeCursors: Readonly<{
        configuredSafeCount: number;
        cursorCount: number;
        eventLogCount: string;
        cursors: readonly ReceiptCursor[];
    }>;
    rpcRequests: IndexerRpcRequestCounts;
    completedAt: string;
    durationMs: number;
}>;

function assertVersion(value: string, label: string) {
    if (!value || value.length > 128 || !/^[A-Za-z0-9._:-]+$/.test(value)) {
        throw new Error(`${label} is invalid`);
    }
}

function assertCount(value: string, label: string) {
    if (!DECIMAL_PATTERN.test(value)) throw new Error(`${label} is invalid`);
}

function normalizeCursors(
    cursors: readonly CursorInput[],
    anchor: FinalizedRunAnchor,
    label: string
) {
    const addresses = new Set<string>();
    return Object.freeze(
        [...cursors]
            .map((cursor) => {
                const address = cursor.address.toLowerCase();
                if (
                    !ADDRESS_PATTERN.test(address) ||
                    addresses.has(address) ||
                    cursor.blockNumber !== anchor.blockNumber ||
                    cursor.blockHash.toLowerCase() !== anchor.blockHash.toLowerCase()
                ) {
                    throw new Error(`${label} is not completely bound to the anchor`);
                }
                addresses.add(address);
                return Object.freeze({
                    address,
                    blockNumber: cursor.blockNumber.toString(),
                    blockHash: cursor.blockHash.toLowerCase(),
                });
            })
            .sort((left, right) => left.address.localeCompare(right.address))
    );
}

function assertRpcCounts(counts: IndexerRpcRequestCounts) {
    const ethGetLogs = counts.ethGetLogs;
    const scalarCounts = [
        counts.totalAttempts,
        counts.failedAttempts,
        counts.adaptiveRetryAttempts,
        ...Object.values(counts.byMethod),
        ethGetLogs.attempts,
        ethGetLogs.plannedAttempts,
        ethGetLogs.adaptiveAttempts,
        ethGetLogs.failedAttempts,
        ethGetLogs.addressScopedViemTransportRetries,
        ...Object.values(ethGetLogs.bySource),
        ...Object.values(ethGetLogs.plannedBySource),
    ];
    if (
        !exactObjectKeys(counts.byMethod, INDEXER_GATEWAY_RPC_METHODS) ||
        !exactObjectKeys(ethGetLogs.bySource, RPC_SOURCE_KEYS) ||
        !exactObjectKeys(ethGetLogs.plannedBySource, RPC_SOURCE_KEYS) ||
        scalarCounts.some(
            (value) => !Number.isSafeInteger(value) || value < 0
        ) ||
        ethGetLogs.legacyViemTransportRetriesObserved !== null ||
        Object.values(counts.byMethod).reduce(
            (total, value) => total + value,
            0
        ) !== counts.totalAttempts ||
        counts.failedAttempts > counts.totalAttempts ||
        counts.adaptiveRetryAttempts > counts.totalAttempts ||
        counts.byMethod.eth_getLogs !== ethGetLogs.attempts ||
        counts.adaptiveRetryAttempts !== ethGetLogs.adaptiveAttempts ||
        Object.values(ethGetLogs.bySource).reduce(
            (total, value) => total + value,
            0
        ) !== ethGetLogs.attempts ||
        Object.values(ethGetLogs.plannedBySource).reduce(
            (total, value) => total + value,
            0
        ) !== ethGetLogs.plannedAttempts ||
        ethGetLogs.plannedAttempts > ethGetLogs.attempts ||
        ethGetLogs.adaptiveAttempts > ethGetLogs.attempts ||
        ethGetLogs.failedAttempts > ethGetLogs.attempts ||
        ethGetLogs.failedAttempts > counts.failedAttempts
    ) {
        throw new Error("Reconciliation RPC request counts are invalid");
    }
}

export function createReconciliationReceipt(input: {
    reconciliationId: string;
    gatewayConfigRevision: string;
    runtimeConfigId: string | null;
    finalizedAnchor: FinalizedRunAnchor;
    identities: OnchainIndexerReconciliationReceipt["identities"];
    rawJournal: {
        trackedAddressCount: number;
        logCount: string;
        cursors: readonly CursorInput[];
    };
    dashboardProjection: {
        eventLogCount: string;
        blockNumber: bigint;
        blockHash: Hex;
        profile: string;
    };
    stateSnapshot: {
        modelCount: string;
        blockNumber: bigint;
        blockHash: Hex;
        profile: string;
    };
    safeCursors: {
        configuredSafeCount: number;
        eventLogCount: string;
        cursors: readonly CursorInput[];
    };
    rpcRequests: IndexerRpcRequestCounts;
    completedAtMs: number;
    durationMs: number;
}): OnchainIndexerReconciliationReceipt {
    if (
        !RECONCILIATION_ID_PATTERN.test(input.reconciliationId) ||
        !REVISION_PATTERN.test(input.gatewayConfigRevision) ||
        (input.runtimeConfigId !== null &&
            !RUNTIME_CONFIG_ID_PATTERN.test(input.runtimeConfigId)) ||
        !Number.isSafeInteger(input.completedAtMs) ||
        input.completedAtMs < 0 ||
        !Number.isSafeInteger(input.durationMs) ||
        input.durationMs < 0
    ) {
        throw new Error("Reconciliation receipt identity or completion time is invalid");
    }
    for (const [label, version] of Object.entries(input.identities)) {
        assertVersion(version, label);
    }
    assertCount(input.rawJournal.logCount, "Raw journal log count");
    assertCount(
        input.dashboardProjection.eventLogCount,
        "Dashboard projection event count"
    );
    assertCount(input.stateSnapshot.modelCount, "State snapshot model count");
    assertCount(input.safeCursors.eventLogCount, "Safe event count");
    assertRpcCounts(input.rpcRequests);

    const rawCursors = normalizeCursors(
        input.rawJournal.cursors,
        input.finalizedAnchor,
        "Raw journal cursor"
    );
    const safeCursors = normalizeCursors(
        input.safeCursors.cursors,
        input.finalizedAnchor,
        "Safe cursor"
    );
    if (
        !Number.isSafeInteger(input.rawJournal.trackedAddressCount) ||
        input.rawJournal.trackedAddressCount < 1 ||
        rawCursors.length !== input.rawJournal.trackedAddressCount ||
        !Number.isSafeInteger(input.safeCursors.configuredSafeCount) ||
        input.safeCursors.configuredSafeCount < 0 ||
        safeCursors.length !== input.safeCursors.configuredSafeCount ||
        input.dashboardProjection.blockNumber !==
            input.finalizedAnchor.blockNumber ||
        input.dashboardProjection.blockHash.toLowerCase() !==
            input.finalizedAnchor.blockHash.toLowerCase() ||
        input.stateSnapshot.blockNumber !== input.finalizedAnchor.blockNumber ||
        input.stateSnapshot.blockHash.toLowerCase() !==
            input.finalizedAnchor.blockHash.toLowerCase() ||
        input.dashboardProjection.profile !== input.stateSnapshot.profile ||
        !input.dashboardProjection.profile
    ) {
        throw new Error("Reconciliation receipt is partial or anchor-inconsistent");
    }

    return Object.freeze({
        kind: RECONCILIATION_RECEIPT_KIND,
        formatVersion: RECONCILIATION_RECEIPT_FORMAT_VERSION,
        partial: false,
        reconciliationId: input.reconciliationId,
        gatewayConfigRevision: input.gatewayConfigRevision,
        runtimeConfigId: input.runtimeConfigId,
        finalizedAnchor: Object.freeze({
            number: input.finalizedAnchor.blockNumber.toString(),
            hash: input.finalizedAnchor.blockHash.toLowerCase(),
        }),
        identities: Object.freeze({ ...input.identities }),
        rawJournal: Object.freeze({
            trackedAddressCount: input.rawJournal.trackedAddressCount,
            cursorCount: rawCursors.length,
            logCount: input.rawJournal.logCount,
            cursors: rawCursors,
        }),
        dashboardProjection: Object.freeze({
            cursorCount: 1,
            eventLogCount: input.dashboardProjection.eventLogCount,
            blockNumber: input.dashboardProjection.blockNumber.toString(),
            blockHash: input.dashboardProjection.blockHash.toLowerCase(),
            profile: input.dashboardProjection.profile,
        }),
        stateSnapshot: Object.freeze({
            cursorCount: 1,
            modelCount: input.stateSnapshot.modelCount,
            blockNumber: input.stateSnapshot.blockNumber.toString(),
            blockHash: input.stateSnapshot.blockHash.toLowerCase(),
            profile: input.stateSnapshot.profile,
        }),
        safeCursors: Object.freeze({
            configuredSafeCount: input.safeCursors.configuredSafeCount,
            cursorCount: safeCursors.length,
            eventLogCount: input.safeCursors.eventLogCount,
            cursors: safeCursors,
        }),
        rpcRequests: Object.freeze({
            totalAttempts: input.rpcRequests.totalAttempts,
            failedAttempts: input.rpcRequests.failedAttempts,
            adaptiveRetryAttempts: input.rpcRequests.adaptiveRetryAttempts,
            byMethod: Object.freeze({ ...input.rpcRequests.byMethod }),
            ethGetLogs: Object.freeze({
                ...input.rpcRequests.ethGetLogs,
                bySource: Object.freeze({
                    ...input.rpcRequests.ethGetLogs.bySource,
                }),
                plannedBySource: Object.freeze({
                    ...input.rpcRequests.ethGetLogs.plannedBySource,
                }),
            }),
        }),
        completedAt: new Date(input.completedAtMs).toISOString(),
        durationMs: input.durationMs,
    });
}

export function parseReconciliationReceipt(
    rawValue: string
): OnchainIndexerReconciliationReceipt {
    let value: unknown;
    try {
        value = JSON.parse(rawValue);
    } catch {
        throw new Error("Stored reconciliation receipt is invalid");
    }
    try {
        return validateStoredReceipt(value);
    } catch {
        throw new Error("Stored reconciliation receipt is invalid");
    }
}

function record(value: unknown, keys: readonly string[]) {
    if (
        !value ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        !exactObjectKeys(value, keys)
    ) {
        throw new Error("Receipt object is invalid");
    }
    return value as Record<string, unknown>;
}

function exactObjectKeys(value: object, expected: readonly string[]) {
    const actual = Object.keys(value).sort();
    const sortedExpected = [...expected].sort();
    return (
        actual.length === sortedExpected.length &&
        actual.every((key, index) => key === sortedExpected[index])
    );
}

function safeCount(value: unknown) {
    if (!Number.isSafeInteger(value) || (value as number) < 0) {
        throw new Error("Receipt count is invalid");
    }
    return value as number;
}

function decimal(value: unknown) {
    if (typeof value !== "string" || !DECIMAL_PATTERN.test(value)) {
        throw new Error("Receipt decimal is invalid");
    }
    return value;
}

function text(value: unknown) {
    if (typeof value !== "string") throw new Error("Receipt text is invalid");
    return value;
}

function receiptCursors(value: unknown) {
    if (!Array.isArray(value)) throw new Error("Receipt cursors are invalid");
    return value.map((entry) => {
        const cursor = record(entry, ["address", "blockHash", "blockNumber"]);
        const address = text(cursor.address);
        const blockHash = text(cursor.blockHash);
        if (!ADDRESS_PATTERN.test(address) || !HASH_PATTERN.test(blockHash)) {
            throw new Error("Receipt cursor identity is invalid");
        }
        return {
            address: address as Address,
            blockNumber: BigInt(decimal(cursor.blockNumber)),
            blockHash: blockHash as Hex,
        };
    });
}

function rpcCounts(value: unknown): IndexerRpcRequestCounts {
    const rpc = record(value, [
        "adaptiveRetryAttempts",
        "byMethod",
        "ethGetLogs",
        "failedAttempts",
        "totalAttempts",
    ]);
    const byMethod = record(rpc.byMethod, INDEXER_GATEWAY_RPC_METHODS);
    const ethGetLogs = record(rpc.ethGetLogs, [
        "adaptiveAttempts",
        "addressScopedViemTransportRetries",
        "attempts",
        "bySource",
        "failedAttempts",
        "legacyViemTransportRetriesObserved",
        "plannedAttempts",
        "plannedBySource",
    ]);
    const bySource = record(ethGetLogs.bySource, RPC_SOURCE_KEYS);
    const plannedBySource = record(ethGetLogs.plannedBySource, RPC_SOURCE_KEYS);
    const normalizedByMethod = Object.fromEntries(
        INDEXER_GATEWAY_RPC_METHODS.map((key) => [
            key,
            safeCount(byMethod[key]),
        ])
    ) as unknown as IndexerRpcRequestCounts["byMethod"];
    const normalizedBySource = Object.fromEntries(
        RPC_SOURCE_KEYS.map((key) => [key, safeCount(bySource[key])])
    ) as unknown as IndexerRpcRequestCounts["ethGetLogs"]["bySource"];
    const normalizedPlannedBySource = Object.fromEntries(
        RPC_SOURCE_KEYS.map((key) => [key, safeCount(plannedBySource[key])])
    ) as unknown as IndexerRpcRequestCounts["ethGetLogs"]["plannedBySource"];
    if (
        ethGetLogs.addressScopedViemTransportRetries !== 0 ||
        ethGetLogs.legacyViemTransportRetriesObserved !== null
    ) {
        throw new Error("Receipt RPC retry identity is invalid");
    }
    return {
        totalAttempts: safeCount(rpc.totalAttempts),
        failedAttempts: safeCount(rpc.failedAttempts),
        adaptiveRetryAttempts: safeCount(rpc.adaptiveRetryAttempts),
        byMethod: normalizedByMethod,
        ethGetLogs: {
            attempts: safeCount(ethGetLogs.attempts),
            plannedAttempts: safeCount(ethGetLogs.plannedAttempts),
            adaptiveAttempts: safeCount(ethGetLogs.adaptiveAttempts),
            failedAttempts: safeCount(ethGetLogs.failedAttempts),
            addressScopedViemTransportRetries: 0,
            legacyViemTransportRetriesObserved: null,
            bySource: normalizedBySource,
            plannedBySource: normalizedPlannedBySource,
        },
    };
}

function validateStoredReceipt(
    value: unknown
): OnchainIndexerReconciliationReceipt {
    const receipt = record(value, [
        "completedAt",
        "dashboardProjection",
        "durationMs",
        "finalizedAnchor",
        "formatVersion",
        "gatewayConfigRevision",
        "identities",
        "kind",
        "partial",
        "rawJournal",
        "reconciliationId",
        "rpcRequests",
        "runtimeConfigId",
        "safeCursors",
        "stateSnapshot",
    ]);
    if (
        receipt.kind !== RECONCILIATION_RECEIPT_KIND ||
        receipt.formatVersion !== RECONCILIATION_RECEIPT_FORMAT_VERSION ||
        receipt.partial !== false
    ) {
        throw new Error("Receipt header is invalid");
    }
    const finalizedAnchor = record(receipt.finalizedAnchor, ["hash", "number"]);
    const anchorHash = text(finalizedAnchor.hash);
    if (!HASH_PATTERN.test(anchorHash)) throw new Error("Receipt anchor is invalid");
    const identities = record(receipt.identities, [
        "dashboardProjectionVersion",
        "databaseSchemaVersion",
        "rawJournalVersion",
        "safeCursorVersion",
        "stateSnapshotVersion",
    ]);
    const rawJournal = record(receipt.rawJournal, [
        "cursorCount",
        "cursors",
        "logCount",
        "trackedAddressCount",
    ]);
    const rawCursors = receiptCursors(rawJournal.cursors);
    const dashboardProjection = record(receipt.dashboardProjection, [
        "blockHash",
        "blockNumber",
        "cursorCount",
        "eventLogCount",
        "profile",
    ]);
    const stateSnapshot = record(receipt.stateSnapshot, [
        "blockHash",
        "blockNumber",
        "cursorCount",
        "modelCount",
        "profile",
    ]);
    const safeCursors = record(receipt.safeCursors, [
        "configuredSafeCount",
        "cursorCount",
        "cursors",
        "eventLogCount",
    ]);
    const normalizedSafeCursors = receiptCursors(safeCursors.cursors);
    if (
        safeCount(rawJournal.cursorCount) !== rawCursors.length ||
        safeCount(rawJournal.trackedAddressCount) !== rawCursors.length ||
        dashboardProjection.cursorCount !== 1 ||
        stateSnapshot.cursorCount !== 1 ||
        safeCount(safeCursors.cursorCount) !== normalizedSafeCursors.length ||
        safeCount(safeCursors.configuredSafeCount) !==
            normalizedSafeCursors.length
    ) {
        throw new Error("Receipt cursor counts are invalid");
    }
    const completedAt = text(receipt.completedAt);
    const completedAtMs = Date.parse(completedAt);
    if (
        !Number.isSafeInteger(completedAtMs) ||
        new Date(completedAtMs).toISOString() !== completedAt
    ) {
        throw new Error("Receipt completion timestamp is invalid");
    }
    const runtimeConfigId =
        receipt.runtimeConfigId === null
            ? null
            : text(receipt.runtimeConfigId);
    return createReconciliationReceipt({
        reconciliationId: text(receipt.reconciliationId),
        gatewayConfigRevision: text(receipt.gatewayConfigRevision),
        runtimeConfigId,
        finalizedAnchor: {
            blockNumber: BigInt(decimal(finalizedAnchor.number)),
            blockHash: anchorHash as Hex,
        },
        identities: {
            databaseSchemaVersion: text(identities.databaseSchemaVersion),
            rawJournalVersion: text(identities.rawJournalVersion),
            dashboardProjectionVersion: text(
                identities.dashboardProjectionVersion
            ),
            stateSnapshotVersion: text(identities.stateSnapshotVersion),
            safeCursorVersion: text(identities.safeCursorVersion),
        },
        rawJournal: {
            trackedAddressCount: rawCursors.length,
            logCount: decimal(rawJournal.logCount),
            cursors: rawCursors,
        },
        dashboardProjection: {
            eventLogCount: decimal(dashboardProjection.eventLogCount),
            blockNumber: BigInt(decimal(dashboardProjection.blockNumber)),
            blockHash: text(dashboardProjection.blockHash) as Hex,
            profile: text(dashboardProjection.profile),
        },
        stateSnapshot: {
            modelCount: decimal(stateSnapshot.modelCount),
            blockNumber: BigInt(decimal(stateSnapshot.blockNumber)),
            blockHash: text(stateSnapshot.blockHash) as Hex,
            profile: text(stateSnapshot.profile),
        },
        safeCursors: {
            configuredSafeCount: normalizedSafeCursors.length,
            eventLogCount: decimal(safeCursors.eventLogCount),
            cursors: normalizedSafeCursors,
        },
        rpcRequests: rpcCounts(receipt.rpcRequests),
        completedAtMs,
        durationMs: safeCount(receipt.durationMs),
    });
}
