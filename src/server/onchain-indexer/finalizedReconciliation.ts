import type { Hex } from "viem";

export type FinalizedRunAnchor = Readonly<{
    blockNumber: bigint;
    blockHash: Hex;
}>;

export type FinalizedProjectionCursor = Readonly<{
    blockNumber: bigint | null;
    blockHash: Hex | null;
}>;

export type FinalizedCommittedBoundary = FinalizedProjectionCursor &
    Readonly<{ profile: string | null }>;

export type FinalizedScanPlan = Readonly<{
    fromBlock: bigint | null;
    reason:
        | "initial"
        | "continue"
        | "already-projected"
        | "configuration-overlap"
        | "hash-mismatch-overlap"
        | "cursor-ahead-overlap";
}>;

const HASH_PATTERN = /^0x[a-fA-F0-9]{64}$/;
const MAX_POSTGRES_BIGINT = 9_223_372_036_854_775_807n;

export const LEGACY_RECONCILE_INTERVAL_MS = 30_000;
export const ARCHIVE_FREE_RECONCILE_INTERVAL_MS = 60_000;

export function archiveFreeFinalizedModeEnabled(value: string | undefined) {
    if (value === undefined || value === "" || value === "0" || value === "false") {
        return false;
    }
    if (value === "1" || value === "true") return true;
    throw new Error(
        "ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE must be one of 0, 1, false, or true"
    );
}

export function defaultReconcileIntervalMs(archiveFreeFinalizedMode: boolean) {
    return archiveFreeFinalizedMode
        ? ARCHIVE_FREE_RECONCILE_INTERVAL_MS
        : LEGACY_RECONCILE_INTERVAL_MS;
}

/** Anvil's finalized tag trails its head by 64 blocks, including after a fresh fork. */
export function reconciliationAnchorBlockTag(chainId: bigint): "latest" | "finalized" {
    return chainId === 31338n ? "latest" : "finalized";
}

export function normalizeFinalizedRunAnchor(value: {
    number?: bigint | null;
    hash?: Hex | null;
}): FinalizedRunAnchor {
    if (
        typeof value.number !== "bigint" ||
        value.number < 0n ||
        value.number > MAX_POSTGRES_BIGINT ||
        typeof value.hash !== "string" ||
        !HASH_PATTERN.test(value.hash)
    ) {
        throw new Error("Finalized RPC anchor is incomplete or invalid");
    }
    return Object.freeze({
        blockNumber: value.number,
        blockHash: value.hash.toLowerCase() as Hex,
    });
}

export async function resolveFinalizedRunAnchor(
    readFinalizedBlock: () => Promise<{
        number?: bigint | null;
        hash?: Hex | null;
    }>
) {
    return normalizeFinalizedRunAnchor(await readFinalizedBlock());
}

export function resolveArchiveFreeDeploymentStart(input: {
    chainId: bigint;
    configuredStartBlock: bigint;
    anchorBlock: bigint;
}) {
    if (input.configuredStartBlock < 0n) {
        throw new Error("Archive-free deployment start block cannot be negative");
    }
    if (input.chainId === 1n && input.configuredStartBlock === 0n) {
        throw new Error(
            "ONCHAIN_INDEXER_START_BLOCK must be a configured nonzero block on Ethereum mainnet in archive-free mode"
        );
    }
    if (input.configuredStartBlock > input.anchorBlock) {
        throw new Error("Archive-free deployment start block is above the finalized anchor");
    }
    return input.configuredStartBlock;
}

function overlapStart(
    deploymentStartBlock: bigint,
    cursorBlock: bigint,
    reorgWindow: bigint
) {
    const candidate = cursorBlock > reorgWindow ? cursorBlock - reorgWindow : 0n;
    return candidate > deploymentStartBlock ? candidate : deploymentStartBlock;
}

export function planFinalizedProjectionScan(input: {
    deploymentStartBlock: bigint;
    anchor: FinalizedRunAnchor;
    cursor: FinalizedProjectionCursor;
    canonicalCursorHash: Hex | null;
    reorgWindow: bigint;
    forceConfigurationOverlap: boolean;
}): FinalizedScanPlan {
    if (input.reorgWindow <= 0n) {
        throw new Error("Finalized projection reorg window must be positive");
    }
    if (input.cursor.blockNumber === null) {
        return Object.freeze({
            fromBlock: input.deploymentStartBlock,
            reason: "initial" as const,
        });
    }

    const cursorBlock = input.cursor.blockNumber;
    if (cursorBlock < input.deploymentStartBlock) {
        return Object.freeze({
            fromBlock: input.deploymentStartBlock,
            reason: "initial" as const,
        });
    }
    if (input.forceConfigurationOverlap) {
        return Object.freeze({
            fromBlock: input.deploymentStartBlock,
            reason: "configuration-overlap" as const,
        });
    }
    if (cursorBlock > input.anchor.blockNumber) {
        return Object.freeze({
            fromBlock: overlapStart(
                input.deploymentStartBlock,
                input.anchor.blockNumber,
                input.reorgWindow
            ),
            reason: "cursor-ahead-overlap" as const,
        });
    }

    const storedHash = input.cursor.blockHash?.toLowerCase() ?? null;
    const canonicalHash = input.canonicalCursorHash?.toLowerCase() ?? null;
    const hashMatches =
        storedHash !== null && canonicalHash !== null && storedHash === canonicalHash;
    if (!hashMatches) {
        return Object.freeze({
            fromBlock: overlapStart(
                input.deploymentStartBlock,
                cursorBlock,
                input.reorgWindow
            ),
            reason: "hash-mismatch-overlap" as const,
        });
    }
    if (cursorBlock === input.anchor.blockNumber) {
        return Object.freeze({
            fromBlock: null,
            reason: "already-projected" as const,
        });
    }
    return Object.freeze({
        fromBlock: cursorBlock + 1n,
        reason: "continue" as const,
    });
}

export function selectFinalizedPlanningBoundary(input: {
    leaseBound: boolean;
    working: FinalizedCommittedBoundary;
    committed: FinalizedCommittedBoundary;
}) {
    return input.leaseBound ? input.committed : input.working;
}

export function finalizedRunProfile(input: {
    addressScopedRawLogs: boolean;
    coreDeploymentStartBlock: bigint;
    safeLookbackBlocks: bigint;
    governanceAddress: string | null;
    safeAddresses: readonly string[];
    rawJournalVersion: string;
    dashboardProjectionVersion: string;
    safeCursorVersion: string;
    coreEventSelectors: readonly string[];
    governanceEventSelectors: readonly string[];
    safeEventSelectors: readonly string[];
}) {
    return JSON.stringify({
        version: 1,
        addressScopedRawLogs: input.addressScopedRawLogs,
        coreDeploymentStartBlock: input.coreDeploymentStartBlock.toString(),
        safeLookbackBlocks: input.safeLookbackBlocks.toString(),
        governanceAddress: input.governanceAddress?.toLowerCase() ?? null,
        safeAddresses: [...input.safeAddresses]
            .map((address) => address.toLowerCase())
            .sort(),
        rawJournalVersion: input.rawJournalVersion,
        dashboardProjectionVersion: input.dashboardProjectionVersion,
        safeCursorVersion: input.safeCursorVersion,
        coreEventSelectors: input.coreEventSelectors.map((selector) =>
            selector.toLowerCase()
        ),
        governanceEventSelectors: input.governanceEventSelectors.map((selector) =>
            selector.toLowerCase()
        ),
        safeEventSelectors: input.safeEventSelectors.map((selector) =>
            selector.toLowerCase()
        ),
    });
}

export function finalizedSnapshotMatches(input: {
    anchor: FinalizedRunAnchor;
    expectedProfile: string;
    snapshotBlockNumber: bigint | null;
    snapshotBlockHash: string | null;
    snapshotProfile: string | null;
    requiredSnapshotsExist: boolean;
}) {
    return (
        input.requiredSnapshotsExist &&
        input.snapshotBlockNumber === input.anchor.blockNumber &&
        input.snapshotBlockHash?.toLowerCase() ===
            input.anchor.blockHash.toLowerCase() &&
        input.snapshotProfile === input.expectedProfile
    );
}
