import { publicEnv } from "../../config/publicEnvironment.ts";
import { serverEnv } from "../environment.ts";
import { targetChainId } from "@/config/chain";

import { randomUUID } from "node:crypto";
import { createPublicClient, parseAbiItem, toEventSelector, toHex, zeroAddress, type Address, type Hex } from "viem";
import { CORE_DIAMOND_ABI } from "@/contracts/generated/coreDiamond";
import { reconcileRecoveryPoolLifecycleSnapshot } from "@/utils/recovery";
import {
    configuredSafeHistoryProfileForIndexer,
    reconcileConfiguredSafeExecutionEvents,
    SAFE_COMMITTED_FINALIZED_BLOCK_HASH_STATE_KEY,
    SAFE_COMMITTED_FINALIZED_BLOCK_STATE_KEY,
    SAFE_COMMITTED_FINALIZED_PROFILE_STATE_KEY,
    SAFE_COMMITTED_RECONCILIATION_ID_STATE_KEY,
} from "@/server/safe-events/indexer";
import {
    ensureSchema,
    query,
    withSharedAdvisoryLock,
    withTransaction,
    type TransactionQuery,
} from "./db";
import { planIndexerIdentityTransition } from "./indexerIdentity";
import {
    applySandboxForkGeneration,
    markSandboxForkGenerationReady,
    prepareSandboxForkGeneration,
    readSandboxForkGeneration,
} from "./forkGenerationRecovery";
import type { ForkGenerationAnchor } from "./forkGenerationTransition";
import snapshotIdentity from "./snapshot-identity.json";
import {
    archiveFreeFinalizedModeEnabled,
    defaultReconcileIntervalMs,
    finalizedRunProfile,
    finalizedSnapshotMatches,
    normalizeFinalizedRunAnchor,
    planFinalizedProjectionScan,
    reconciliationAnchorBlockTag,
    resolveArchiveFreeDeploymentStart,
    resolveFinalizedRunAnchor,
    selectFinalizedPlanningBoundary,
    type FinalizedRunAnchor,
} from "./finalizedReconciliation";
import {
    indexerGatewayHealthIsSuppressed,
    type PrivateIndexerGatewayClient,
    type PrivateIndexerGatewayLease,
} from "./gatewayLease";
import { indexerRpcTransport } from "./rpcTransport";
import {
    ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT,
    assertLegacyPerEventDefinitionCount,
    createIndexerRpcRequestCounter,
    instrumentEthGetLogsRequest,
    type IndexerRpcRequestCounter,
    type IndexerRpcRequestCounts,
} from "./rpcRequestInstrumentation";
import {
    persistDashboardSnapshot,
    readCachedDashboardSnapshot,
} from "./dashboardSnapshotRepository";
import {
    readRecoveryFundSnapshot,
    type StateReadTarget,
    type RecoveryFundSnapshot,
} from "./recoveryFundSnapshot";
import {
    parseAddressLike,
    parseBigIntLike,
    readIndexedRecoveryAssets,
    readIndexedReserveAssets,
    readRecoveryShareV2Checkpoint,
    reconcileRecoveryShareBalancesV2,
    recoveryShareV2Enabled,
    RECOVERY_SHARE_V2_VERSION,
    rebuildRecoveryShareBalances,
    type RecoveryQuery,
    type RecoveryTransaction,
} from "./recoverySharePersistence";
import {
    ingestAddressScopedRawLogs,
    prepareRawJournalReplayCoverage,
    rawJournalProjectionReplayEnabled,
    readRawJournalLogs,
    type RawJournalCoverage,
} from "./rawLogJournal";
import {
    createBoundedFinalizedMulticallClient,
    finalizedSnapshotMulticallEnabled,
    isFinalizedMulticallBudgetExceeded,
} from "./finalizedSnapshotMulticall";
import { shouldSplitDirectProviderLogRequest } from "./adaptiveLogPagination";
import {
    addressScopedRawLogsEnabled,
    createKnownRawLogDecoder,
    type RawBlockHeader,
} from "./rawLogModel";
import {
    createReconciliationReceipt,
    parseReconciliationReceipt,
    type OnchainIndexerReconciliationReceipt,
} from "./reconciliationReceipt";
import {
    assertGatewayExpectationNotStale,
    classifyInternalReconcileOutcome,
    createDashboardHistoryProgress,
    planInternalGatewayReconcile,
    type DashboardHistoryProgress,
    type InternalGatewayExpectation,
    type InternalReconcileResult,
} from "./internalReconcileContract";
import { buildRecoveryPortfolioReadModel } from "./recoveryPortfolioModel";
import {
    persistRecoveryPortfolioReadModel,
    pruneRecoveryApiRateLimits,
    readCachedRecoverySharePortfolio,
} from "./recoveryPortfolioRepository";

const INDEXER_STATE_KEY_LAST_SCANNED_BLOCK = "last_scanned_block";
const INDEXER_STATE_KEY_PROJECTION_BLOCK_HASH = "finalized_projection_block_hash";
const INDEXER_STATE_KEY_PROJECTION_PROFILE = "finalized_projection_profile";
const INDEXER_STATE_KEY_DEPLOYMENT_BLOCK = "deployment_block";
const INDEXER_STATE_KEY_INDEXER_VERSION = "indexer_version";
const INDEXER_STATE_KEY_RAW_JOURNAL_VERSION = "raw_journal_version";
const INDEXER_STATE_KEY_DASHBOARD_PROJECTION_VERSION = "dashboard_projection_version";
const INDEXER_STATE_KEY_STATE_SNAPSHOT_VERSION = "state_snapshot_version";
const INDEXER_STATE_KEY_GOVERNANCE_ADDRESS = "governance_address";
const INDEXER_STATE_KEY_DASHBOARD_PROJECTION_GOVERNANCE_ADDRESS =
    "dashboard_projection_governance_address";
const INDEXER_STATE_KEY_HOLDER_COUNT = "holder_count";
const INDEXER_STATE_KEY_HOLDER_CACHE_READY = "holder_cache_ready";
const INDEXER_STATE_KEY_CYGLD_REF_GRAMS_FP18 = "cygld_ref_grams_fp18";
const INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK = "finalized_snapshot_block";
const INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK_HASH =
    "finalized_snapshot_block_hash";
const INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_PROFILE = "finalized_snapshot_profile";
const INDEXER_STATE_KEY_COMMITTED_FINALIZED_BLOCK =
    "committed_finalized_block";
const INDEXER_STATE_KEY_COMMITTED_FINALIZED_BLOCK_HASH =
    "committed_finalized_block_hash";
const INDEXER_STATE_KEY_COMMITTED_FINALIZED_PROFILE =
    "committed_finalized_profile";
const INDEXER_STATE_KEY_COMMITTED_RECONCILIATION_ID =
    "committed_reconciliation_id";
const INDEXER_STATE_KEY_COMMITTED_GATEWAY_CONFIG_REVISION =
    "committed_gateway_config_revision";
const INDEXER_STATE_KEY_RECONCILIATION_RECEIPT =
    "completed_reconciliation_receipt_v2";
const RAW_LOG_CURSOR_VERSION_STATE_KEY = "raw_log_journal_version";
const RAW_LOG_CURSOR_BLOCK_STATE_KEY = "raw_log_last_scanned_block";
const RAW_LOG_CURSOR_BLOCK_HASH_STATE_KEY =
    "raw_log_last_scanned_block_hash";
const SAFE_WORKING_CURSOR_VERSION_STATE_KEY = "safe_execution_cursor_version";
const SAFE_WORKING_CURSOR_BLOCK_STATE_KEY =
    "safe_execution_last_scanned_block";
const SAFE_WORKING_CURSOR_BLOCK_HASH_STATE_KEY =
    "safe_execution_last_scanned_block_hash";
const SAFE_WORKING_PROFILE_STATE_KEY = "safe_finalized_projection_profile";
const HASH_PATTERN = /^0x[a-fA-F0-9]{64}$/;
const LEGACY_INDEXER_VERSION = snapshotIdentity.dashboardIndexerVersion;
const RAW_JOURNAL_VERSION = snapshotIdentity.rawJournalVersion;
const DASHBOARD_PROJECTION_VERSION = snapshotIdentity.dashboardProjectionVersion;
const STATE_SNAPSHOT_VERSION = snapshotIdentity.stateSnapshotVersion;
const DEFAULT_CYGLD_REF_CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const DASHBOARD_MAX_LOG_ROWS = 100_000;
const REQUIRED_FINALIZED_SNAPSHOT_MODEL_KEYS = [
    "onchain-dashboard-v1",
    "recovery-portfolio-v5",
] as const;

const EVENT_DEFINITIONS = [
    {
        name: "DiamondCut",
        category: "logic",
        abi: parseAbiItem(
            "event DiamondCut((address facetAddress, uint8 action, bytes4[] functionSelectors)[] _diamondCut, address _init, bytes _calldata)"
        ),
    },
    {
        name: "IssuanceFeePpmUpdated",
        category: "parameter",
        abi: parseAbiItem("event IssuanceFeePpmUpdated(uint256 previousIssuanceFeePpm, uint256 newIssuanceFeePpm)"),
    },
    {
        name: "RedemptionFeePpmUpdated",
        category: "parameter",
        abi: parseAbiItem("event RedemptionFeePpmUpdated(uint256 previousRedemptionFeePpm, uint256 newRedemptionFeePpm)"),
    },
    {
        name: "TreasuryUpdated",
        category: "parameter",
        abi: parseAbiItem("event TreasuryUpdated(address previousTreasury, address newTreasury)"),
    },
    {
        name: "BasketConfigured",
        category: "parameter",
        abi: parseAbiItem(
            "event BasketConfigured(address[] assets, uint256[] targetsPpm, uint256[] goldRefGramsFp18, uint256 cygldRefGramsFp18, uint256[] cygldPerUnitFp18)"
        ),
    },
    {
        name: "Issued",
        category: "activity",
        abi: parseAbiItem(
            "event Issued(address indexed caller, address indexed reserve, address indexed treasury, uint256 grossCygldOut, uint256 netCygldOut, uint256 protocolFeeCygld, uint256[] amountsIn)"
        ),
    },
    {
        name: "Redeemed",
        category: "activity",
        abi: parseAbiItem(
            "event Redeemed(address indexed caller, address indexed reserve, address indexed treasury, uint256 grossCygldIn, uint256 netCygldIn, uint256 protocolFeeCygld, uint8[] kinds, address[] tokens, uint256[] ids, uint256[] amounts)"
        ),
    },
    {
        name: "Transfer",
        category: "activity",
        abi: parseAbiItem("event Transfer(address indexed from, address indexed to, uint256 value)"),
    },
    {
        name: "ReserveLifecycleChanged",
        category: "lifecycle",
        abi: parseAbiItem("event ReserveLifecycleChanged(address indexed asset, uint8 previousLifecycle, uint8 newLifecycle, uint256 exitEntitlementRaw)"),
    },
    {
        name: "RecoveryActivated",
        category: "recovery",
        abi: parseAbiItem("event RecoveryActivated(address indexed asset, uint256 addedCoreAttachedShares)"),
    },
    {
        name: "RecoveryRehabilitated",
        category: "recovery",
        abi: parseAbiItem("event RecoveryRehabilitated(address indexed asset, uint256 totalPoolRaw, uint256 coreRaw, uint256 externalRaw)"),
    },
    {
        name: "RecoverySharesRedeemed",
        category: "recovery",
        abi: parseAbiItem("event RecoverySharesRedeemed(address indexed asset, address indexed account, address indexed recipient, uint256 shares, uint256 liabilityReleasedRaw, uint256 rawAmountOut)"),
    },
    {
        name: "TransferSingle",
        category: "share",
        abi: parseAbiItem("event TransferSingle(address indexed operator, address indexed from, address indexed to, uint256 id, uint256 value)"),
    },
    {
        name: "TransferBatch",
        category: "share",
        abi: parseAbiItem("event TransferBatch(address indexed operator, address indexed from, address indexed to, uint256[] ids, uint256[] values)"),
    },
] as const;

const RECOVERY_FUND_EVENT_DEFINITIONS = [
    {
        name: "RecoveryFundInitialized",
        abi: parseAbiItem("event RecoveryFundInitialized(address indexed trustedCore)"),
    },
    {
        name: "AssetRecoveryFundActivated",
        abi: parseAbiItem("event AssetRecoveryFundActivated(address indexed impairedAsset, uint64 indexed generation, uint256 coverageShares, uint256 cygldCommitment)"),
    },
    {
        name: "RecoverySharesPurchased",
        abi: parseAbiItem("event RecoverySharesPurchased(address indexed impairedAsset, uint64 indexed generation, address indexed seller, uint256 shares, uint256 cygldAmount)"),
    },
] as const;

assertLegacyPerEventDefinitionCount("core", EVENT_DEFINITIONS.length);
assertLegacyPerEventDefinitionCount(
    "governance",
    RECOVERY_FUND_EVENT_DEFINITIONS.length
);

const decodeCoreRawLog = createKnownRawLogDecoder(EVENT_DEFINITIONS);
const decodeGovernanceRawLog = createKnownRawLogDecoder(
    RECOVERY_FUND_EVENT_DEFINITIONS
);

type EventName =
    | (typeof EVENT_DEFINITIONS)[number]["name"]
    | (typeof RECOVERY_FUND_EVENT_DEFINITIONS)[number]["name"];
type PendingIndexedEventLog = {
    contractAddress: Address;
    eventName: EventName;
    blockNumber: bigint;
    blockHash: Hex | null;
    txHash: Hex;
    logIndex: number;
    payload: unknown;
};
type IndexerWriteQuery = (sql: string, params?: unknown[]) => Promise<unknown>;
type IndexerPublicClient = ReturnType<typeof createPublicClient>;
type DashboardRangeKey = "24H" | "7D" | "1M";

export type IndexerConfig = {
    chainId: bigint;
    coreAddress: Address;
    governanceAddress: Address | null;
    rpcUrl: string;
    startBlock: bigint;
    chunkSize: bigint;
    maxBlocksPerRun: bigint;
    reorgWindow: bigint;
    reconcileIntervalMs: number;
    archiveFreeFinalizedMode: boolean;
    addressScopedRawLogs: boolean;
    rawJournalProjectionReplay: boolean;
    recoveryShareV2: boolean;
    finalizedSnapshotMulticall: boolean;
    privateGatewayClient: PrivateIndexerGatewayClient | null;
    runtimeConfigId: string | null;
};

type IndexerRuntimeState = {
    reconcilePromise: Promise<ReconciliationOutcome | undefined> | null;
    lastReconciledAtMs: number;
    lastRpcRequestCounts: IndexerRpcRequestCounts | null;
    lastReconciliationReceipt: OnchainIndexerReconciliationReceipt | null;
    activeGatewayReconciliationId: string | null;
    gatewayLeaseAmbiguousUntilMs: number;
};

type ReconciliationOutcome = Readonly<{
    finalizedAnchor: FinalizedRunAnchor | null;
    finalizedProfile: string | null;
    completed: boolean;
    dashboardHistoryProgress: DashboardHistoryProgress | null;
}>;

type DashboardRangeConfig = {
    buckets: number;
    stepMs: number;
};

type DashboardRangeBucket = {
    bucketStartMs: number;
    mintCygld: number;
    redeemCygld: number;
    netCygld: number;
    supplyCygld: number;
    transferredCygld: number;
    transferTxCount: number;
};

type BasketSnapshotAsset = {
    address: string;
    symbol: string;
    targetPercent: number;
    actualPercent: number;
    driftPercent: number;
    decimals: number | null;
    reserveBalance: number | null;
    reserveBalanceRaw: string;
    totalSupply: number | null;
    totalSupplyRaw: string | null;
    goldRefGrams: number | null;
    cygldPerUnitFp18: string;
    cygldPerToken: number | null;
};

type BasketSnapshot = {
    reserveAddress: string | null;
    cygldRefGrams: number | null;
    cygldRefGramsFp18: string | null;
    assets: BasketSnapshotAsset[];
    withinBand: boolean | null;
};

type RecoveryPoolSnapshot = {
    asset: string;
    impaired: boolean;
    coreAttachedShares: string;
    externalShares: string;
    totalShares: string;
    redeemableRaw: string;
    cygldPerAssetRawFp18: string;
    cygldSupplyCap: string;
    referenceShares: string;
    referenceValueCygld: string;
    shareDecimals: number;
    lifecycle: ReserveLifecycleSnapshot;
    custody: ReserveCustodySnapshot;
};

type ReserveLifecycleSnapshot = {
    asset: string;
    lifecycle: number;
    exitEntitlementRaw: string;
};

type ReserveCustodySnapshot = {
    lifecycle: number;
    poolImpaired: boolean;
    redeemablePoolRaw: string;
    coreAttachedShares: string;
    externalShares: string;
    exitEntitlementRaw: string;
    liveBalanceAvailable: boolean;
    liveRawCustody: string;
    activeAvailableRaw: string;
    poolRawDeficit: string;
    exitEntitlementDeficitRaw: string;
};

export type RecoverySnapshot = {
    collection: string;
    pools: RecoveryPoolSnapshot[];
    reserveLifecycles: ReserveLifecycleSnapshot[];
    fund: RecoveryFundSnapshot;
};

const TOKEN_DECIMALS_FALLBACK = 18n;
const GATEWAY_HISTORICAL_MAX_BLOCKS_PER_RUN = 500n;
const GATEWAY_HISTORICAL_RPC_INTERVAL_MS = 1_000;
const DASHBOARD_RANGE_CONFIG: Record<DashboardRangeKey, DashboardRangeConfig> = {
    "24H": { buckets: 24, stepMs: 60 * 60 * 1000 },
    "7D": { buckets: 28, stepMs: 6 * 60 * 60 * 1000 },
    "1M": { buckets: 30, stepMs: 24 * 60 * 60 * 1000 },
};

declare global {
    var __cybergoldIndexerState: IndexerRuntimeState | undefined;
}

function getRuntimeState(): IndexerRuntimeState {
    if (!global.__cybergoldIndexerState) {
        global.__cybergoldIndexerState = {
            reconcilePromise: null,
            lastReconciledAtMs: 0,
            lastRpcRequestCounts: null,
            lastReconciliationReceipt: null,
            activeGatewayReconciliationId: null,
            gatewayLeaseAmbiguousUntilMs: 0,
        };
    }
    return global.__cybergoldIndexerState;
}

function createGatewayRequestPacer() {
    let nextRequestAtMs = 0;
    let tail = Promise.resolve();
    return async () => {
        const previous = tail;
        let release: () => void;
        tail = new Promise<void>((resolve) => {
            release = resolve;
        });
        await previous;
        try {
            const waitMs = nextRequestAtMs - Date.now();
            if (waitMs > 0) {
                await new Promise<void>((resolve) => setTimeout(resolve, waitMs));
            }
            nextRequestAtMs = Date.now() + GATEWAY_HISTORICAL_RPC_INTERVAL_MS;
        } finally {
            release!();
        }
    };
}

export function getLastOnchainIndexerRpcRequestCounts() {
    return getRuntimeState().lastRpcRequestCounts ?? null;
}

export async function getLastOnchainIndexerReconciliationReceipt() {
    const config = getIndexerConfig();
    const runtimeState = getRuntimeState();
    const suppressHealth = indexerGatewayHealthIsSuppressed({
        activeReconciliationId: runtimeState.activeGatewayReconciliationId,
        ambiguousUntilMs: runtimeState.gatewayLeaseAmbiguousUntilMs,
        nowMs: Date.now(),
    });
    if (runtimeState.activeGatewayReconciliationId !== null && !suppressHealth) {
        runtimeState.activeGatewayReconciliationId = null;
        runtimeState.gatewayLeaseAmbiguousUntilMs = 0;
    }
    if (!config?.privateGatewayClient || suppressHealth) {
        return null;
    }
    const stored = await getSyncStateString(
        config,
        INDEXER_STATE_KEY_RECONCILIATION_RECEIPT
    );
    if (!stored) return null;
    try {
        const receipt = parseReconciliationReceipt(stored);
        const [
            committedBlock,
            committedHash,
            committedProfile,
            committedReconciliationId,
            committedGatewayRevision,
        ] = await Promise.all([
            getSyncStateBigInt(
                config,
                INDEXER_STATE_KEY_COMMITTED_FINALIZED_BLOCK
            ),
            getSyncStateString(
                config,
                INDEXER_STATE_KEY_COMMITTED_FINALIZED_BLOCK_HASH
            ),
            getSyncStateString(
                config,
                INDEXER_STATE_KEY_COMMITTED_FINALIZED_PROFILE
            ),
            getSyncStateString(
                config,
                INDEXER_STATE_KEY_COMMITTED_RECONCILIATION_ID
            ),
            getSyncStateString(
                config,
                INDEXER_STATE_KEY_COMMITTED_GATEWAY_CONFIG_REVISION
            ),
        ]);
        if (
            committedBlock?.toString() !== receipt.finalizedAnchor.number ||
            committedHash?.toLowerCase() !== receipt.finalizedAnchor.hash ||
            committedProfile !== receipt.dashboardProjection.profile ||
            committedReconciliationId !== receipt.reconciliationId ||
            committedGatewayRevision !== receipt.gatewayConfigRevision ||
            receipt.runtimeConfigId !== config.runtimeConfigId
        ) {
            return null;
        }
        const safeAddresses = receipt.safeCursors.cursors.map(
            (cursor) => cursor.address as Address
        );
        const safeStates = await readAddressStateValues(config, safeAddresses, [
            SAFE_COMMITTED_FINALIZED_BLOCK_STATE_KEY,
            SAFE_COMMITTED_FINALIZED_BLOCK_HASH_STATE_KEY,
            SAFE_COMMITTED_FINALIZED_PROFILE_STATE_KEY,
            SAFE_COMMITTED_RECONCILIATION_ID_STATE_KEY,
        ]);
        for (const cursor of receipt.safeCursors.cursors) {
            const state = safeStates.get(cursor.address);
            if (
                state?.get(SAFE_COMMITTED_FINALIZED_BLOCK_STATE_KEY) !==
                    cursor.blockNumber ||
                state
                    ?.get(SAFE_COMMITTED_FINALIZED_BLOCK_HASH_STATE_KEY)
                    ?.toLowerCase() !== cursor.blockHash ||
                state?.get(SAFE_COMMITTED_FINALIZED_PROFILE_STATE_KEY) !==
                    receipt.dashboardProjection.profile ||
                state?.get(SAFE_COMMITTED_RECONCILIATION_ID_STATE_KEY) !==
                    receipt.reconciliationId
            ) {
                return null;
            }
        }
        const liveCheckpoint = await readGatewaySuccessfulRunCheckpoint(
            config,
            {
                blockNumber: BigInt(receipt.finalizedAnchor.number),
                blockHash: receipt.finalizedAnchor.hash as Hex,
            },
            receipt.dashboardProjection.profile
        );
        const receiptRawAddresses = receipt.rawJournal.cursors.map(
            (cursor) => cursor.address
        );
        const receiptSafeAddresses = receipt.safeCursors.cursors.map(
            (cursor) => cursor.address
        );
        if (
            liveCheckpoint.coreCursor.blockNumber.toString() !==
                receipt.finalizedAnchor.number ||
            liveCheckpoint.coreCursor.blockHash.toLowerCase() !==
                receipt.finalizedAnchor.hash ||
            liveCheckpoint.rawCursors.some(
                (cursor) =>
                    cursor.blockNumber.toString() !==
                        receipt.finalizedAnchor.number ||
                    cursor.blockHash.toLowerCase() !==
                        receipt.finalizedAnchor.hash
            ) ||
            liveCheckpoint.safeCursors.some(
                (cursor) =>
                    cursor.blockNumber.toString() !==
                        receipt.finalizedAnchor.number ||
                    cursor.blockHash.toLowerCase() !==
                        receipt.finalizedAnchor.hash
            ) ||
            liveCheckpoint.rawCursors
                .map((cursor) => cursor.address.toLowerCase())
                .sort()
                .join(",") !== [...receiptRawAddresses].sort().join(",") ||
            liveCheckpoint.safeCursors
                .map((cursor) => cursor.address.toLowerCase())
                .sort()
                .join(",") !== [...receiptSafeAddresses].sort().join(",") ||
            !(await finalizedSnapshotIsComplete(
                config,
                {
                    blockNumber: BigInt(receipt.finalizedAnchor.number),
                    blockHash: receipt.finalizedAnchor.hash as Hex,
                },
                receipt.dashboardProjection.profile
            ))
        ) {
            return null;
        }
        return receipt;
    } catch {
        return null;
    }
}

function parseBigIntEnv(name: keyof typeof serverEnv, fallback: bigint) {
    const value = serverEnv[name];
    return value === undefined ? fallback : BigInt(value);
}

function parseBoundedBigIntEnv(
    name: keyof typeof serverEnv,
    fallback: bigint,
    maximum: bigint
) {
    const value = parseBigIntEnv(name, fallback);
    if (value <= 0n) return fallback;
    return value > maximum ? maximum : value;
}

function parseNumberEnv(name: keyof typeof serverEnv, fallback: number) {
    const value = serverEnv[name];
    return value === undefined || Number(value) === 0 ? fallback : Number(value);
}

function parseRuntimeConfigId(value: string | undefined) {
    if (value === undefined || value === "") return null;
    if (!/^sha256:[0-9a-f]{64}$/.test(value)) {
        throw new Error("CYBERGOLD_RUNTIME_CONFIG_ID is invalid");
    }
    return value;
}

function getIndexerConfig(): IndexerConfig | null {
    const databaseUrl = serverEnv.DATABASE_URL;
    const rpcUrl =
        serverEnv.ONCHAIN_INDEXER_RPC_URL ??
        serverEnv.RPC_URL ??
        publicEnv.NEXT_PUBLIC_RPC_URL;
    const chainId = BigInt(targetChainId);
    const rawCoreAddress = publicEnv.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS;
    if (!databaseUrl || !rawCoreAddress) {
        return null;
    }

    try {
        const archiveFreeFinalizedMode = archiveFreeFinalizedModeEnabled(
            serverEnv.ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE
        );
        const addressScopedRawLogs = addressScopedRawLogsEnabled(
            serverEnv.ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS
        );
        const rawJournalProjectionReplay = rawJournalProjectionReplayEnabled(
            serverEnv.ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED
        );
        const recoveryShareV2 = recoveryShareV2Enabled(
            serverEnv.ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED
        );
        const finalizedSnapshotMulticall = finalizedSnapshotMulticallEnabled(
            serverEnv.ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED
        );
        if (
            rawJournalProjectionReplay &&
            (!archiveFreeFinalizedMode || !addressScopedRawLogs)
        ) {
            throw new Error(
                "Raw journal projection replay requires archive-free finalized address-scoped mode"
            );
        }
        if (recoveryShareV2 && !archiveFreeFinalizedMode) {
            throw new Error(
                "Recovery-share v2 projection requires archive-free finalized mode"
            );
        }
        if (finalizedSnapshotMulticall && !archiveFreeFinalizedMode) {
            throw new Error(
                "Finalized Multicall requires archive-free finalized mode"
            );
        }
        return {
            chainId,
            coreAddress: rawCoreAddress,
            governanceAddress: publicEnv.NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS ?? null,
            rpcUrl,
            startBlock: parseBigIntEnv("ONCHAIN_INDEXER_START_BLOCK", 0n),
            chunkSize: parseBoundedBigIntEnv("ONCHAIN_INDEXER_CHUNK_SIZE", 2_000n, 10_000n),
            maxBlocksPerRun: parseBoundedBigIntEnv(
                "ONCHAIN_INDEXER_MAX_BLOCKS_PER_RUN",
                20_000n,
                50_000n
            ),
            reorgWindow: parseBoundedBigIntEnv("ONCHAIN_INDEXER_REORG_WINDOW", 12n, 256n),
            reconcileIntervalMs: parseNumberEnv(
                "ONCHAIN_INDEXER_RECONCILE_INTERVAL_MS",
                defaultReconcileIntervalMs(archiveFreeFinalizedMode)
            ),
            archiveFreeFinalizedMode,
            addressScopedRawLogs,
            rawJournalProjectionReplay,
            recoveryShareV2,
            finalizedSnapshotMulticall,
            // Endpoint selection is ordinary transport configuration.  New
            // runtimes never opt into an App-side Gateway control path.
            privateGatewayClient: null,
            runtimeConfigId: parseRuntimeConfigId(
                serverEnv.CYBERGOLD_RUNTIME_CONFIG_ID
            ),
        };
    } catch {
        return null;
    }
}

function toJsonSafe(value: unknown): unknown {
    if (typeof value === "bigint") {
        return value.toString();
    }
    if (Array.isArray(value)) {
        return value.map((entry) => toJsonSafe(entry));
    }
    if (value && typeof value === "object") {
        return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, toJsonSafe(entry)]));
    }
    return value;
}

function maxBigInt(a: bigint, b: bigint) {
    return a > b ? a : b;
}

async function getLastScannedBlock(config: IndexerConfig) {
    const result = await query<{ state_value: string }>(
        `
            SELECT state_value
            FROM onchain_sync_state
            WHERE chain_id = $1
              AND contract_address = $2
              AND state_key = $3
            LIMIT 1
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), INDEXER_STATE_KEY_LAST_SCANNED_BLOCK]
    );

    if (result.rowCount === 0) return null;
    try {
        return BigInt(result.rows[0].state_value);
    } catch {
        return null;
    }
}

async function getSyncStateBigInt(config: IndexerConfig, key: string) {
    const result = await query<{ state_value: string }>(
        `
            SELECT state_value
            FROM onchain_sync_state
            WHERE chain_id = $1
              AND contract_address = $2
              AND state_key = $3
            LIMIT 1
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), key]
    );

    if (result.rowCount === 0) return null;
    try {
        return BigInt(result.rows[0].state_value);
    } catch {
        return null;
    }
}

async function getSyncStateString(config: IndexerConfig, key: string) {
    const result = await query<{ state_value: string }>(
        `
            SELECT state_value
            FROM onchain_sync_state
            WHERE chain_id = $1
              AND contract_address = $2
              AND state_key = $3
            LIMIT 1
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), key]
    );

    return (result.rowCount ?? 0) > 0 ? result.rows[0].state_value : null;
}

async function getCommittedFinalizedBoundary(config: IndexerConfig) {
    const [
        blockNumber,
        blockHash,
        profile,
        reconciliationId,
        gatewayConfigRevision,
    ] = await Promise.all([
        getSyncStateBigInt(config, INDEXER_STATE_KEY_COMMITTED_FINALIZED_BLOCK),
        getSyncStateString(
            config,
            INDEXER_STATE_KEY_COMMITTED_FINALIZED_BLOCK_HASH
        ),
        getSyncStateString(config, INDEXER_STATE_KEY_COMMITTED_FINALIZED_PROFILE),
        getSyncStateString(
            config,
            INDEXER_STATE_KEY_COMMITTED_RECONCILIATION_ID
        ),
        getSyncStateString(
            config,
            INDEXER_STATE_KEY_COMMITTED_GATEWAY_CONFIG_REVISION
        ),
    ]);
    const complete = Boolean(
        blockNumber !== null &&
            blockHash &&
            HASH_PATTERN.test(blockHash) &&
            profile &&
            reconciliationId &&
            gatewayConfigRevision &&
            /^[0-9a-f]{64}$/.test(gatewayConfigRevision)
    );
    return {
        blockNumber: complete ? blockNumber : null,
        blockHash: complete ? (blockHash as Hex) : null,
        profile: complete ? profile : null,
        reconciliationId: complete ? reconciliationId : null,
    };
}

async function getSyncStateEntry(config: IndexerConfig, key: string) {
    const result = await query<{ state_value: string; updated_at: Date | string }>(
        `
            SELECT state_value, updated_at
            FROM onchain_sync_state
            WHERE chain_id = $1
              AND contract_address = $2
              AND state_key = $3
            LIMIT 1
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), key]
    );

    if ((result.rowCount ?? 0) === 0) return null;

    const row = result.rows[0];
    const updatedAtMs = row.updated_at instanceof Date ? row.updated_at.getTime() : new Date(row.updated_at).getTime();

    return {
        stateValue: row.state_value,
        updatedAtMs: Number.isFinite(updatedAtMs) ? updatedAtMs : 0,
    };
}

async function setSyncState(
    config: IndexerConfig,
    key: string,
    value: string,
    execute: IndexerWriteQuery = query
) {
    await execute(
        `
            INSERT INTO onchain_sync_state (chain_id, contract_address, state_key, state_value)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (chain_id, contract_address, state_key)
            DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = NOW()
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), key, value]
    );
}

async function deleteSyncState(
    config: IndexerConfig,
    key: string,
    execute: TransactionQuery = query
) {
    await execute(
        `
            DELETE FROM onchain_sync_state
            WHERE chain_id = $1
              AND contract_address = $2
              AND state_key = $3
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), key]
    );
}

async function setLastScannedBlock(config: IndexerConfig, blockNumber: bigint) {
    await setSyncState(config, INDEXER_STATE_KEY_LAST_SCANNED_BLOCK, blockNumber.toString());
}

async function setFinalizedProjectionCursor(
    config: IndexerConfig,
    anchor: FinalizedRunAnchor,
    profile: string
) {
    await withTransaction(async (transactionQuery) => {
        await setSyncState(
            config,
            INDEXER_STATE_KEY_LAST_SCANNED_BLOCK,
            anchor.blockNumber.toString(),
            transactionQuery
        );
        await setSyncState(
            config,
            INDEXER_STATE_KEY_PROJECTION_BLOCK_HASH,
            anchor.blockHash.toLowerCase(),
            transactionQuery
        );
        await setSyncState(
            config,
            INDEXER_STATE_KEY_PROJECTION_PROFILE,
            profile,
            transactionQuery
        );
    });
}

async function requiredFinalizedSnapshotsExist(
    config: IndexerConfig,
    blockNumber: bigint
) {
    const result = await query<{ model_count: string }>(
        `
            SELECT COUNT(*)::text AS model_count
            FROM (
                SELECT model_key
                FROM onchain_read_model_snapshots
                WHERE chain_id = $1
                  AND contract_address = $2
                  AND model_key = ANY($4::text[])
                GROUP BY model_key
                HAVING MAX(block_number) = $3
            ) AS completed_models
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            blockNumber.toString(),
            REQUIRED_FINALIZED_SNAPSHOT_MODEL_KEYS,
        ]
    );
    return Number(result.rows[0]?.model_count ?? 0) ===
        REQUIRED_FINALIZED_SNAPSHOT_MODEL_KEYS.length;
}

async function finalizedSnapshotIsComplete(
    config: IndexerConfig,
    anchor: FinalizedRunAnchor,
    expectedProfile: string
) {
    const [
        snapshotBlockNumber,
        snapshotBlockHash,
        snapshotProfile,
        snapshotsExist,
        recoveryShareV2Checkpoint,
    ] =
        await Promise.all([
            getSyncStateBigInt(config, INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK),
            getSyncStateString(
                config,
                INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK_HASH
            ),
            getSyncStateString(config, INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_PROFILE),
            requiredFinalizedSnapshotsExist(config, anchor.blockNumber),
            config.recoveryShareV2
                ? readRecoveryShareV2Checkpoint(config, recoveryQuery)
                : Promise.resolve(null),
        ]);
    return finalizedSnapshotMatches({
        anchor,
        expectedProfile,
        snapshotBlockNumber,
        snapshotBlockHash,
        snapshotProfile,
        requiredSnapshotsExist: snapshotsExist,
    }) &&
        (!config.recoveryShareV2 ||
            (recoveryShareV2Checkpoint?.version ===
                RECOVERY_SHARE_V2_VERSION &&
                recoveryShareV2Checkpoint.blockNumber === anchor.blockNumber &&
                recoveryShareV2Checkpoint.blockHash.toLowerCase() ===
                    anchor.blockHash.toLowerCase() &&
                recoveryShareV2Checkpoint.profile === expectedProfile));
}

async function readCygldRefGramsFp18(
    config: IndexerConfig,
    client: IndexerPublicClient,
    stateReadTarget: StateReadTarget,
    options?: {
        forcePinnedRead?: boolean;
        isTerminalReadFailure?(error: unknown): boolean;
    }
) {
    const cached = await getSyncStateEntry(config, INDEXER_STATE_KEY_CYGLD_REF_GRAMS_FP18);
    const cachedValue = cached?.stateValue ? parseBigIntValue(cached.stateValue) : 0n;
    const cacheTtlMs = parseNumberEnv("ONCHAIN_CYGLD_REF_CACHE_TTL_MS", DEFAULT_CYGLD_REF_CACHE_TTL_MS);
    const cacheFresh =
        cachedValue > 0n && cached !== null && cached.updatedAtMs > 0 && Date.now() - cached.updatedAtMs < cacheTtlMs;

    if (cacheFresh && !options?.forcePinnedRead) {
        return cachedValue;
    }

    try {
        const onchainValue = await client.readContract({
            address: config.coreAddress,
            abi: [parseAbiItem("function cygldRefGramsFp18() view returns (uint256)")],
            functionName: "cygldRefGramsFp18",
            ...stateReadTarget,
        });
        if (!options?.forcePinnedRead) {
            await setSyncState(
                config,
                INDEXER_STATE_KEY_CYGLD_REF_GRAMS_FP18,
                onchainValue.toString()
            );
        }
        return onchainValue;
    } catch (error) {
        if (options?.isTerminalReadFailure?.(error)) throw error;
        if (options?.forcePinnedRead) return null;
        return cachedValue > 0n ? cachedValue : null;
    }
}

function isZeroAddress(address: string) {
    return address.toLowerCase() === zeroAddress;
}

function extractTransferArgs(payload: unknown): { from: string; to: string; value: bigint } | null {
    if (!payload || typeof payload !== "object") return null;
    const args = (payload as { args?: unknown }).args;
    if (!args || typeof args !== "object") return null;

    const from = parseAddressLike((args as { from?: unknown }).from);
    const to = parseAddressLike((args as { to?: unknown }).to);
    const value = parseBigIntLike((args as { value?: unknown }).value);

    if (!from || !to || value === null) return null;
    return { from, to, value };
}

const recoveryQuery: RecoveryQuery = async (sql, params = []) => query(sql, params);
const recoveryTransaction: RecoveryTransaction = async (action) =>
    withTransaction((transactionQuery) =>
        action(async (sql, params = []) => transactionQuery(sql, params))
    );

async function clearHolderCache(
    config: IndexerConfig,
    execute: TransactionQuery = query
) {
    await execute(
        `
            DELETE FROM onchain_token_balances
            WHERE chain_id = $1
              AND contract_address = $2
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase()]
    );
    await execute(
        `
            DELETE FROM onchain_holder_balance_deltas
            WHERE chain_id = $1
              AND contract_address = $2
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase()]
    );
    await execute(
        `
            DELETE FROM onchain_recovery_share_balances
            WHERE chain_id = $1
              AND contract_address = $2
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase()]
    );
    await clearReadModelSnapshots(config, execute);
    await setSyncState(config, INDEXER_STATE_KEY_HOLDER_COUNT, "0", execute);
    await setSyncState(config, INDEXER_STATE_KEY_HOLDER_CACHE_READY, "0", execute);
}

async function clearReadModelSnapshots(
    config: IndexerConfig,
    execute: TransactionQuery = query
) {
    await execute(
        `
            DELETE FROM onchain_read_model_snapshots
            WHERE chain_id = $1
              AND contract_address = $2
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase()]
    );
}

async function getHolderCacheReady(config: IndexerConfig) {
    return (await getSyncStateString(config, INDEXER_STATE_KEY_HOLDER_CACHE_READY)) === "1";
}

async function setHolderCacheReady(config: IndexerConfig, ready: boolean) {
    await setSyncState(config, INDEXER_STATE_KEY_HOLDER_CACHE_READY, ready ? "1" : "0");
}

async function getHolderCountBigInt(config: IndexerConfig) {
    const raw = await getSyncStateString(config, INDEXER_STATE_KEY_HOLDER_COUNT);
    if (raw === null) return null;
    try {
        return BigInt(raw);
    } catch {
        return null;
    }
}

async function setHolderCountBigInt(config: IndexerConfig, value: bigint) {
    await setSyncState(config, INDEXER_STATE_KEY_HOLDER_COUNT, value.toString());
}

async function getHolderBalanceRaw(config: IndexerConfig, holderAddress: string) {
    const result = await query<{ balance_raw: string }>(
        `
            SELECT balance_raw
            FROM onchain_token_balances
            WHERE chain_id = $1
              AND contract_address = $2
              AND holder_address = $3
            LIMIT 1
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), holderAddress.toLowerCase()]
    );
    if (result.rowCount === 0) return 0n;
    try {
        return BigInt(result.rows[0].balance_raw);
    } catch {
        return 0n;
    }
}

async function setHolderBalanceRaw(config: IndexerConfig, holderAddress: string, balanceRaw: bigint) {
    const address = holderAddress.toLowerCase();
    if (balanceRaw === 0n) {
        await query(
            `
                DELETE FROM onchain_token_balances
                WHERE chain_id = $1
                  AND contract_address = $2
                  AND holder_address = $3
            `,
            [config.chainId.toString(), config.coreAddress.toLowerCase(), address]
        );
        return;
    }

    await query(
        `
            INSERT INTO onchain_token_balances (chain_id, contract_address, holder_address, balance_raw)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (chain_id, contract_address, holder_address)
            DO UPDATE SET balance_raw = EXCLUDED.balance_raw, updated_at = NOW()
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), address, balanceRaw.toString()]
    );
}

async function recordHolderDelta(
    config: IndexerConfig,
    blockNumber: bigint,
    txHash: Hex,
    logIndex: number,
    holderAddress: string,
    deltaRaw: bigint
) {
    if (deltaRaw === 0n) return;
    await query(
        `
            INSERT INTO onchain_holder_balance_deltas (
                chain_id,
                contract_address,
                block_number,
                tx_hash,
                log_index,
                holder_address,
                delta_raw
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (chain_id, tx_hash, log_index, holder_address) DO NOTHING
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            blockNumber.toString(),
            txHash.toLowerCase(),
            logIndex,
            holderAddress.toLowerCase(),
            deltaRaw.toString(),
        ]
    );
}

async function applyHolderBalanceDelta(
    config: IndexerConfig,
    holderAddress: string,
    deltaRaw: bigint,
    options?: {
        recordDelta?: {
            blockNumber: bigint;
            txHash: Hex;
            logIndex: number;
        };
    }
) {
    if (deltaRaw === 0n || isZeroAddress(holderAddress)) return;

    const currentBalance = await getHolderBalanceRaw(config, holderAddress);
    let nextBalance = currentBalance + deltaRaw;
    if (nextBalance < 0n) {
        nextBalance = 0n;
    }

    const currentCount = (await getHolderCountBigInt(config)) ?? 0n;
    let nextCount = currentCount;
    if (currentBalance === 0n && nextBalance > 0n) nextCount += 1n;
    if (currentBalance > 0n && nextBalance === 0n) nextCount -= 1n;
    if (nextCount < 0n) nextCount = 0n;

    await setHolderBalanceRaw(config, holderAddress, nextBalance);
    await setHolderCountBigInt(config, nextCount);

    if (options?.recordDelta) {
        await recordHolderDelta(
            config,
            options.recordDelta.blockNumber,
            options.recordDelta.txHash,
            options.recordDelta.logIndex,
            holderAddress,
            deltaRaw
        );
    }
}

async function applyTransferToHolderCache(
    config: IndexerConfig,
    transfer: { from: string; to: string; value: bigint },
    meta: { blockNumber: bigint; txHash: Hex; logIndex: number }
) {
    if (transfer.value === 0n) return;
    if (transfer.from === transfer.to) return;

    if (!isZeroAddress(transfer.from)) {
        await applyHolderBalanceDelta(config, transfer.from, -transfer.value, { recordDelta: meta });
    }
    if (!isZeroAddress(transfer.to)) {
        await applyHolderBalanceDelta(config, transfer.to, transfer.value, { recordDelta: meta });
    }
}

type HolderDeltaRow = {
    holder_address: string;
    delta_raw: string;
    block_number: string;
    tx_hash: string;
    log_index: number;
};

async function rollbackHolderCacheFromBlock(config: IndexerConfig, fromBlock: bigint) {
    if (!(await getHolderCacheReady(config))) {
        return false;
    }

    const transferLogCountResult = await query<{ count: string }>(
        `
            SELECT COUNT(*)::text AS count
            FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND event_name = 'Transfer'
              AND block_number >= $3
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), fromBlock.toString()]
    );
    const rewoundTransferLogCount = BigInt(transferLogCountResult.rows[0]?.count ?? "0");

    const deltaRows = await query<HolderDeltaRow>(
        `
            SELECT holder_address, delta_raw, block_number::text, tx_hash, log_index
            FROM onchain_holder_balance_deltas
            WHERE chain_id = $1
              AND contract_address = $2
              AND block_number >= $3
            ORDER BY block_number DESC, log_index DESC
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), fromBlock.toString()]
    );

    if (rewoundTransferLogCount > 0n && (deltaRows.rowCount ?? 0) === 0) {
        return false;
    }

    for (const row of deltaRows.rows) {
        const deltaRaw = parseBigIntLike(row.delta_raw);
        if (deltaRaw === null || deltaRaw === 0n) continue;
        await applyHolderBalanceDelta(config, row.holder_address, -deltaRaw);
    }

    await query(
        `
            DELETE FROM onchain_holder_balance_deltas
            WHERE chain_id = $1
              AND contract_address = $2
              AND block_number >= $3
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), fromBlock.toString()]
    );

    return true;
}

type TransferReplayRow = {
    block_number: string;
    tx_hash: string;
    log_index: number;
    payload: unknown;
};

async function rebuildHolderCacheFromIndexedLogs(config: IndexerConfig, deltaRetentionFromBlock?: bigint) {
    await clearHolderCache(config);
    await setHolderCountBigInt(config, 0n);

    const transferRows = await query<TransferReplayRow>(
        `
            SELECT block_number::text, tx_hash, log_index, payload
            FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND event_name = 'Transfer'
            ORDER BY block_number ASC, log_index ASC
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase()]
    );

    for (const row of transferRows.rows) {
        const transfer = extractTransferArgs(row.payload);
        if (!transfer) continue;

        const blockNumber = BigInt(row.block_number);
        const shouldRecordDelta = deltaRetentionFromBlock === undefined || blockNumber >= deltaRetentionFromBlock;
        const meta = {
            blockNumber,
            txHash: row.tx_hash as Hex,
            logIndex: row.log_index,
        };

        if (transfer.value === 0n || transfer.from === transfer.to) {
            continue;
        }

        if (!isZeroAddress(transfer.from)) {
            await applyHolderBalanceDelta(config, transfer.from, -transfer.value, shouldRecordDelta ? { recordDelta: meta } : undefined);
        }
        if (!isZeroAddress(transfer.to)) {
            await applyHolderBalanceDelta(config, transfer.to, transfer.value, shouldRecordDelta ? { recordDelta: meta } : undefined);
        }
    }

    await setHolderCacheReady(config, true);
}

async function pruneOldHolderDeltas(config: IndexerConfig, keepFromBlock: bigint) {
    await query(
        `
            DELETE FROM onchain_holder_balance_deltas
            WHERE chain_id = $1
              AND contract_address = $2
              AND block_number < $3
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), keepFromBlock.toString()]
    );
}

async function deleteLogsFromBlock(
    config: IndexerConfig,
    fromBlock: bigint,
    additionalAddresses: string[] = []
) {
    const contractAddresses = [
        config.coreAddress.toLowerCase(),
        ...(config.governanceAddress ? [config.governanceAddress.toLowerCase()] : []),
        ...additionalAddresses.map((address) => address.toLowerCase()),
    ];
    await query(
        `
            DELETE FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = ANY($2::text[])
              AND block_number >= $3
        `,
        [config.chainId.toString(), contractAddresses, fromBlock.toString()]
    );
}

async function deleteProjectedLogsForAddress(
    config: IndexerConfig,
    contractAddress: string,
    execute: TransactionQuery = query
) {
    await execute(
        `
            DELETE FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
        `,
        [config.chainId.toString(), contractAddress.toLowerCase()]
    );
}

async function deleteReadModelSnapshotsFromBlock(
    config: IndexerConfig,
    fromBlock: bigint
) {
    await query(
        `
            WITH latest_completed AS (
                SELECT model_key, MAX(block_number) AS block_number
                FROM onchain_read_model_snapshots
                WHERE chain_id = $1
                  AND contract_address = $2
                GROUP BY model_key
            )
            DELETE FROM onchain_read_model_snapshots AS snapshot
            WHERE snapshot.chain_id = $1
              AND snapshot.contract_address = $2
              AND snapshot.block_number >= $3
              AND NOT EXISTS (
                  SELECT 1
                  FROM latest_completed
                  WHERE latest_completed.model_key = snapshot.model_key
                    AND latest_completed.block_number = snapshot.block_number
              )
        `,
        [
            config.chainId.toString(),
            config.coreAddress.toLowerCase(),
            fromBlock.toString(),
        ]
    );
}

async function ensureIndexerVersion(config: IndexerConfig) {
    const expectedGovernanceAddress = config.governanceAddress?.toLowerCase() ?? "none";
    return withTransaction(async (transactionQuery) => {
        const identityKeys = [
            INDEXER_STATE_KEY_RAW_JOURNAL_VERSION,
            INDEXER_STATE_KEY_DASHBOARD_PROJECTION_VERSION,
            INDEXER_STATE_KEY_STATE_SNAPSHOT_VERSION,
            INDEXER_STATE_KEY_INDEXER_VERSION,
            INDEXER_STATE_KEY_GOVERNANCE_ADDRESS,
            INDEXER_STATE_KEY_DASHBOARD_PROJECTION_GOVERNANCE_ADDRESS,
        ];
        const result = await transactionQuery<{
            state_key: string;
            state_value: string;
        }>(
            `
                SELECT state_key, state_value
                FROM onchain_sync_state
                WHERE chain_id = $1
                  AND contract_address = $2
                  AND state_key = ANY($3::text[])
            `,
            [
                config.chainId.toString(),
                config.coreAddress.toLowerCase(),
                identityKeys,
            ]
        );
        const storedValues = new Map(
            result.rows.map((row) => [row.state_key, row.state_value])
        );
        const storedProjectionGovernanceAddress =
            storedValues.get(
                INDEXER_STATE_KEY_DASHBOARD_PROJECTION_GOVERNANCE_ADDRESS
            ) ?? storedValues.get(INDEXER_STATE_KEY_GOVERNANCE_ADDRESS) ?? null;
        const transition = planIndexerIdentityTransition(
            {
                rawJournalVersion:
                    storedValues.get(INDEXER_STATE_KEY_RAW_JOURNAL_VERSION) ?? null,
                dashboardProjectionVersion:
                    storedValues.get(INDEXER_STATE_KEY_DASHBOARD_PROJECTION_VERSION) ??
                    null,
                stateSnapshotVersion:
                    storedValues.get(INDEXER_STATE_KEY_STATE_SNAPSHOT_VERSION) ?? null,
                legacyIndexerVersion:
                    storedValues.get(INDEXER_STATE_KEY_INDEXER_VERSION) ?? null,
                dashboardProjectionGovernanceAddress:
                    storedValues.get(
                        INDEXER_STATE_KEY_DASHBOARD_PROJECTION_GOVERNANCE_ADDRESS
                    ) ?? null,
                legacyGovernanceAddress:
                    storedValues.get(INDEXER_STATE_KEY_GOVERNANCE_ADDRESS) ?? null,
            },
            {
                rawJournalVersion: RAW_JOURNAL_VERSION,
                dashboardProjectionVersion: DASHBOARD_PROJECTION_VERSION,
                stateSnapshotVersion: STATE_SNAPSHOT_VERSION,
                governanceAddress: expectedGovernanceAddress,
            }
        );

        if (transition.resetProjection) {
            await clearHolderCache(config, transactionQuery);
        } else if (transition.resetStateSnapshots) {
            await clearReadModelSnapshots(config, transactionQuery);
        }
        if (transition.restartScanFromDeployment) {
            if (
                storedProjectionGovernanceAddress !== null &&
                storedProjectionGovernanceAddress !== "none"
            ) {
                await deleteProjectedLogsForAddress(
                    config,
                    storedProjectionGovernanceAddress,
                    transactionQuery
                );
            }
            await deleteSyncState(
                config,
                INDEXER_STATE_KEY_LAST_SCANNED_BLOCK,
                transactionQuery
            );
        }
        if (transition.initializeRawJournalIdentity) {
            await setSyncState(
                config,
                INDEXER_STATE_KEY_RAW_JOURNAL_VERSION,
                RAW_JOURNAL_VERSION,
                transactionQuery
            );
        }
        if (
            transition.initializeStateSnapshotIdentity ||
            transition.resetStateSnapshots
        ) {
            await setSyncState(
                config,
                INDEXER_STATE_KEY_STATE_SNAPSHOT_VERSION,
                STATE_SNAPSHOT_VERSION,
                transactionQuery
            );
        }
        if (
            storedValues.get(INDEXER_STATE_KEY_DASHBOARD_PROJECTION_VERSION) !==
            DASHBOARD_PROJECTION_VERSION
        ) {
            await setSyncState(
                config,
                INDEXER_STATE_KEY_DASHBOARD_PROJECTION_VERSION,
                DASHBOARD_PROJECTION_VERSION,
                transactionQuery
            );
        }
        // Retain the exact legacy value so the previous App slot cannot enter its
        // destructive version-drift reset while both slots share this database.
        if (
            storedValues.get(INDEXER_STATE_KEY_INDEXER_VERSION) !==
            LEGACY_INDEXER_VERSION
        ) {
            await setSyncState(
                config,
                INDEXER_STATE_KEY_INDEXER_VERSION,
                LEGACY_INDEXER_VERSION,
                transactionQuery
            );
        }
        if (
            storedValues.get(
                INDEXER_STATE_KEY_DASHBOARD_PROJECTION_GOVERNANCE_ADDRESS
            ) !== expectedGovernanceAddress
        ) {
            await setSyncState(
                config,
                INDEXER_STATE_KEY_DASHBOARD_PROJECTION_GOVERNANCE_ADDRESS,
                expectedGovernanceAddress,
                transactionQuery
            );
        }
        // Like the legacy indexer version, an existing legacy Governance address
        // belongs to the retained previous slot and must not be rewritten.
        if (!storedValues.has(INDEXER_STATE_KEY_GOVERNANCE_ADDRESS)) {
            await setSyncState(
                config,
                INDEXER_STATE_KEY_GOVERNANCE_ADDRESS,
                expectedGovernanceAddress,
                transactionQuery
            );
        }

        return transition.resetProjection;
    });
}

async function persistLogs(
    config: IndexerConfig,
    logs: Array<{
        contractAddress: Address;
        eventName: EventName;
        blockNumber: bigint;
        blockHash: Hex | null;
        txHash: Hex;
        logIndex: number;
        blockTimestampMs: number;
        payload: unknown;
    }>,
    options?: {
        updateHolderCache?: boolean;
    }
) {
    for (const entry of logs) {
        const insertResult = await query(
            `
                INSERT INTO onchain_event_logs (
                    chain_id,
                    contract_address,
                    event_name,
                    block_number,
                    block_hash,
                    tx_hash,
                    log_index,
                    block_timestamp,
                    payload
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                ON CONFLICT (chain_id, tx_hash, log_index) DO NOTHING
            `,
            [
                config.chainId.toString(),
                entry.contractAddress.toLowerCase(),
                entry.eventName,
                entry.blockNumber.toString(),
                entry.blockHash,
                entry.txHash.toLowerCase(),
                entry.logIndex,
                new Date(entry.blockTimestampMs),
                JSON.stringify(toJsonSafe(entry.payload)),
            ]
        );

        if (
            options?.updateHolderCache &&
            (insertResult.rowCount ?? 0) > 0 &&
            entry.eventName === "Transfer"
        ) {
            const transfer = extractTransferArgs(entry.payload);
            if (transfer) {
                await applyTransferToHolderCache(config, transfer, {
                    blockNumber: entry.blockNumber,
                    txHash: entry.txHash,
                    logIndex: entry.logIndex,
                });
            }
        }
    }
}

async function hasCodeAtBlock(
    client: ReturnType<typeof createPublicClient>,
    address: Address,
    blockNumber: bigint
) {
    const code = await client.getCode({ address, blockNumber });
    return !!code && code !== "0x";
}

async function detectDeploymentBlock(
    client: ReturnType<typeof createPublicClient>,
    address: Address,
    chainHeadBlock: bigint
) {
    const existsAtHead = await hasCodeAtBlock(client, address, chainHeadBlock);
    if (!existsAtHead) {
        return null;
    }

    let low = 0n;
    let high = chainHeadBlock;
    let firstWithCode = chainHeadBlock;

    while (low <= high) {
        const mid = (low + high) / 2n;
        const existsAtMid = await hasCodeAtBlock(client, address, mid);

        if (existsAtMid) {
            firstWithCode = mid;
            if (mid === 0n) break;
            high = mid - 1n;
        } else {
            low = mid + 1n;
        }
    }

    return firstWithCode;
}

async function resolveStartBlock(
    config: IndexerConfig,
    client: ReturnType<typeof createPublicClient>,
    chainHeadBlock: bigint
) {
    if (config.archiveFreeFinalizedMode) {
        return resolveArchiveFreeDeploymentStart({
            chainId: config.chainId,
            configuredStartBlock: config.startBlock,
            anchorBlock: chainHeadBlock,
        });
    }
    if (config.startBlock > 0n) {
        return config.startBlock > chainHeadBlock ? chainHeadBlock : config.startBlock;
    }

    const cachedDeploymentBlock = await getSyncStateBigInt(config, INDEXER_STATE_KEY_DEPLOYMENT_BLOCK);
    if (cachedDeploymentBlock !== null) {
        return cachedDeploymentBlock > chainHeadBlock ? chainHeadBlock : cachedDeploymentBlock;
    }

    try {
        const detectedDeploymentBlock = await detectDeploymentBlock(client, config.coreAddress, chainHeadBlock);
        if (detectedDeploymentBlock !== null) {
            await setSyncState(config, INDEXER_STATE_KEY_DEPLOYMENT_BLOCK, detectedDeploymentBlock.toString());
            return detectedDeploymentBlock;
        }
    } catch {
        // If detection fails (RPC limitations), fall back to default full scan behavior.
    }

    return 0n;
}

export type OnchainIndexerDiagnosticStage =
    | "configuration"
    | "database-schema"
    | "advisory-lock"
    | "reconciliation"
    | "indexer-version"
    | "finalized-anchor"
    | "projection-plan"
    | "raw-log-journal"
    | "dashboard-projection"
    | "safe-history"
    | "state-snapshot"
    | "request-parsing";

async function reconcileInternal(
    config: IndexerConfig,
    rpcRequestCounter: IndexerRpcRequestCounter,
    suppliedFinalizedAnchor?: FinalizedRunAnchor,
    gatewayLease?: PrivateIndexerGatewayLease,
    onDiagnosticStage?: (stage: OnchainIndexerDiagnosticStage) => void
) {
    onDiagnosticStage?.("indexer-version");
    await ensureSchema();
    const projectionReset = await ensureIndexerVersion(config);
    const useAddressScopedRawLogs = config.addressScopedRawLogs;
    const paceGatewayRequest = gatewayLease
        ? createGatewayRequestPacer()
        : undefined;
    const client = createPublicClient({
        transport: gatewayLease
            ? gatewayLease.createRpcTransport(
                  rpcRequestCounter,
                  paceGatewayRequest
              )
            : indexerRpcTransport(config.rpcUrl),
    });
    const rawLogClient = useAddressScopedRawLogs
        ? gatewayLease
            ? client
            : createPublicClient({
                  transport: indexerRpcTransport(config.rpcUrl, {
                      retryCount: ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT,
                  }),
              })
        : client;
    if (suppliedFinalizedAnchor && !config.archiveFreeFinalizedMode) {
        throw new Error(
            "A supplied finalized anchor requires archive-free finalized mode"
        );
    }
    onDiagnosticStage?.("finalized-anchor");
    const finalizedAnchor = config.archiveFreeFinalizedMode
        ? (suppliedFinalizedAnchor
              ? normalizeFinalizedRunAnchor({
                    number: suppliedFinalizedAnchor.blockNumber,
                    hash: suppliedFinalizedAnchor.blockHash,
                })
              : undefined) ??
          (await resolveFinalizedRunAnchor(async () => {
              const block = await client.getBlock({
                  blockTag: reconciliationAnchorBlockTag(config.chainId),
              });
              return { number: block.number, hash: block.hash };
          }))
        : null;
    if (
        gatewayLease &&
        (!finalizedAnchor ||
            finalizedAnchor.blockNumber !==
                gatewayLease.finalizedAnchor.blockNumber ||
            finalizedAnchor.blockHash.toLowerCase() !==
                gatewayLease.finalizedAnchor.blockHash.toLowerCase())
    ) {
        throw new Error("Indexer gateway lease anchor was not used exactly");
    }
    const latestChainHeadBlock = finalizedAnchor
        ? finalizedAnchor.blockNumber
        : await client.getBlockNumber();
    const effectiveStartBlock = await resolveStartBlock(config, client, latestChainHeadBlock);

    const lastScannedBlock = await getLastScannedBlock(config);
    const safeHistoryProfile = finalizedAnchor
        ? configuredSafeHistoryProfileForIndexer()
        : null;
    const finalizedProfile = finalizedAnchor
        ? finalizedRunProfile({
              addressScopedRawLogs: useAddressScopedRawLogs,
              coreDeploymentStartBlock: effectiveStartBlock,
              safeLookbackBlocks: safeHistoryProfile?.lookbackBlocks ?? 0n,
              governanceAddress: config.governanceAddress,
              safeAddresses: safeHistoryProfile?.safeAddresses ?? [],
              rawJournalVersion: RAW_JOURNAL_VERSION,
              dashboardProjectionVersion: DASHBOARD_PROJECTION_VERSION,
              safeCursorVersion: snapshotIdentity.safeCursorVersion,
              coreEventSelectors: EVENT_DEFINITIONS.map((definition) =>
                  toEventSelector(definition.abi)
              ),
              governanceEventSelectors: RECOVERY_FUND_EVENT_DEFINITIONS.map(
                  (definition) => toEventSelector(definition.abi)
              ),
              safeEventSelectors: safeHistoryProfile?.eventSelectors ?? [],
          })
        : null;
    onDiagnosticStage?.("projection-plan");
    let fromBlock: bigint;
    let shouldScanLogs = true;
    let committedBoundaryAlreadyComplete = false;
    let committedReconciliationId: string | null = null;
    if (finalizedAnchor) {
        const storedProjectionHash = await getSyncStateString(
            config,
            INDEXER_STATE_KEY_PROJECTION_BLOCK_HASH
        );
        const storedFinalizedProjectionProfile = await getSyncStateString(
            config,
            INDEXER_STATE_KEY_PROJECTION_PROFILE
        );
        const committed = gatewayLease
            ? projectionReset
                ? {
                      blockNumber: null,
                      blockHash: null,
                      profile: null,
                      reconciliationId: null,
                  }
                : await getCommittedFinalizedBoundary(config)
            : {
                  blockNumber: null,
                  blockHash: null,
                  profile: null,
                  reconciliationId: null,
              };
        const planningBoundary = selectFinalizedPlanningBoundary({
            leaseBound: Boolean(gatewayLease),
            working: {
                blockNumber: lastScannedBlock,
                blockHash: storedProjectionHash as Hex | null,
                profile: storedFinalizedProjectionProfile,
            },
            committed,
        });
        committedReconciliationId = gatewayLease
            ? committed.reconciliationId
            : null;
        committedBoundaryAlreadyComplete = Boolean(
            gatewayLease &&
                planningBoundary.blockNumber === finalizedAnchor.blockNumber &&
                planningBoundary.blockHash?.toLowerCase() ===
                    finalizedAnchor.blockHash.toLowerCase() &&
                planningBoundary.profile === finalizedProfile
        );
        let canonicalCursorHash: Hex | null = null;
        if (
            planningBoundary.blockNumber !== null &&
            planningBoundary.blockNumber <= finalizedAnchor.blockNumber
        ) {
            if (planningBoundary.blockNumber === finalizedAnchor.blockNumber) {
                canonicalCursorHash = finalizedAnchor.blockHash;
            } else {
                const cursorBlock = await client.getBlock({
                    blockNumber: planningBoundary.blockNumber,
                });
                const normalizedCursorBlock = normalizeFinalizedRunAnchor({
                    number: cursorBlock.number,
                    hash: cursorBlock.hash,
                });
                if (
                    normalizedCursorBlock.blockNumber !==
                    planningBoundary.blockNumber
                ) {
                    throw new Error(
                        "Finalized projection cursor header returned the wrong block"
                    );
                }
                canonicalCursorHash = normalizedCursorBlock.blockHash;
            }
        }
        const scanPlan = planFinalizedProjectionScan({
            deploymentStartBlock: effectiveStartBlock,
            anchor: finalizedAnchor,
            cursor: {
                blockNumber: planningBoundary.blockNumber,
                blockHash: planningBoundary.blockHash,
            },
            canonicalCursorHash,
            reorgWindow: config.reorgWindow,
            forceConfigurationOverlap:
                planningBoundary.profile !== finalizedProfile,
        });
        shouldScanLogs = scanPlan.fromBlock !== null;
        fromBlock = scanPlan.fromBlock ?? finalizedAnchor.blockNumber + 1n;
    } else {
        fromBlock =
            lastScannedBlock === null
                ? effectiveStartBlock
                : maxBigInt(
                      effectiveStartBlock,
                      maxBigInt(0n, lastScannedBlock - config.reorgWindow)
                  );
    }
    const maximumBlocksPerRun = gatewayLease
        ? config.maxBlocksPerRun < GATEWAY_HISTORICAL_MAX_BLOCKS_PER_RUN
            ? config.maxBlocksPerRun
            : GATEWAY_HISTORICAL_MAX_BLOCKS_PER_RUN
        : config.maxBlocksPerRun;
    const chainHeadBlock = shouldScanLogs
        ? fromBlock + maximumBlocksPerRun - 1n < latestChainHeadBlock
            ? fromBlock + maximumBlocksPerRun - 1n
            : latestChainHeadBlock
        : latestChainHeadBlock;

    const blockTimestampCache = new Map<bigint, bigint>();
    const rawBlockHeaderCache = new Map<bigint, RawBlockHeader>();
    const readRawBlockHeader = async (blockNumber: bigint) => {
        const cached = rawBlockHeaderCache.get(blockNumber);
        if (cached) return cached;
        const block = await client.getBlock({ blockNumber });
        const normalizedBlock = normalizeFinalizedRunAnchor({
            number: block.number,
            hash: block.hash,
        });
        if (normalizedBlock.blockNumber !== blockNumber) {
            throw new Error("Raw log header returned the wrong block number");
        }
        const header = {
            hash: normalizedBlock.blockHash,
            timestamp: block.timestamp,
        };
        rawBlockHeaderCache.set(blockNumber, header);
        return header;
    };
    const prepareReplayCoverage = async (address: Address) => {
        if (!finalizedAnchor) return null;
        return prepareRawJournalReplayCoverage({
            enabled: config.rawJournalProjectionReplay,
            chainId: config.chainId,
            address,
            expectedVersion: RAW_JOURNAL_VERSION,
            requiredStartBlock: effectiveStartBlock,
            maximumBlock: finalizedAnchor.blockNumber,
            readBlockHeader: readRawBlockHeader,
        });
    };
    onDiagnosticStage?.("raw-log-journal");
    const coreRawReplayCoverage = await prepareReplayCoverage(config.coreAddress);
    const governanceRawReplayCoverage = config.governanceAddress
        ? await prepareReplayCoverage(config.governanceAddress)
        : null;
    const collectRawJournalChunk = async (input: {
        address: Address;
        coverage: RawJournalCoverage | null;
        cursor: bigint;
        chunkEnd: bigint;
        requestSource: "core-address" | "governance-address";
    }) => {
        if (input.coverage && input.chunkEnd <= input.coverage.cursorBlock) {
            return readRawJournalLogs({
                chainId: config.chainId,
                address: input.address,
                fromBlock: input.cursor,
                toBlock: input.chunkEnd,
                coverage: input.coverage,
            });
        }
        return ingestAddressScopedRawLogs({
            chainId: config.chainId,
            address: input.address,
            authoritativeStartBlock: effectiveStartBlock,
            fromBlock: input.cursor,
            toBlock: input.chunkEnd,
            journalVersion: RAW_JOURNAL_VERSION,
            requestCounter: rpcRequestCounter,
            requestSource: input.requestSource,
            shouldSplitRequestFailure: gatewayLease
                ? (error) => gatewayLease.isRangeReductionRequiredError(error)
                : shouldSplitDirectProviderLogRequest,
            requestLogs: (range) =>
                rawLogClient.request({
                    method: "eth_getLogs",
                    params: [
                        {
                            address: input.address,
                            fromBlock: toHex(range.fromBlock),
                            toBlock: toHex(range.toBlock),
                        },
                    ],
                }),
            readBlockHeader: readRawBlockHeader,
            blockHeaderCache: rawBlockHeaderCache,
        });
    };
    const collectAddressScopedRawChunk = async (
        cursor: bigint,
        chunkEnd: bigint
    ) => {
        const eventLogs: PendingIndexedEventLog[] = [];
        const coreRawLogs = await collectRawJournalChunk({
            address: config.coreAddress,
            coverage: coreRawReplayCoverage,
            cursor,
            chunkEnd,
            requestSource: "core-address",
        });
        for (const log of coreRawLogs) {
            blockTimestampCache.set(log.blockNumber, log.blockTimestampSeconds);
            const decoded = decodeCoreRawLog(log);
            if (!decoded) continue;
            eventLogs.push({
                contractAddress: config.coreAddress,
                eventName: decoded.eventName,
                blockNumber: log.blockNumber,
                blockHash: log.blockHash,
                txHash: log.transactionHash,
                logIndex: log.logIndex,
                payload: {
                    args: decoded.args ?? {},
                    topics: log.topics,
                    data: log.data,
                },
            });
        }

        const governanceAddress = config.governanceAddress;
        if (governanceAddress) {
            const governanceRawLogs = await collectRawJournalChunk({
                address: governanceAddress,
                coverage: governanceRawReplayCoverage,
                cursor,
                chunkEnd,
                requestSource: "governance-address",
            });
            for (const log of governanceRawLogs) {
                blockTimestampCache.set(
                    log.blockNumber,
                    log.blockTimestampSeconds
                );
                const decoded = decodeGovernanceRawLog(log);
                if (!decoded) continue;
                eventLogs.push({
                    contractAddress: governanceAddress,
                    eventName: decoded.eventName,
                    blockNumber: log.blockNumber,
                    blockHash: log.blockHash,
                    txHash: log.transactionHash,
                    logIndex: log.logIndex,
                    payload: {
                        args: decoded.args ?? {},
                        topics: log.topics,
                        data: log.data,
                    },
                });
            }
        }
        return eventLogs;
    };
    const preparedAddressScopedChunks = new Map<
        bigint,
        { chunkEnd: bigint; eventLogs: PendingIndexedEventLog[] }
    >();
    if (useAddressScopedRawLogs && fromBlock <= chainHeadBlock) {
        let rawCursor = fromBlock;
        let preparedEventCount = 0;
        while (rawCursor <= chainHeadBlock) {
            const chunkEnd =
                rawCursor + config.chunkSize - 1n > chainHeadBlock
                    ? chainHeadBlock
                    : rawCursor + config.chunkSize - 1n;
            const eventLogs = await collectAddressScopedRawChunk(
                rawCursor,
                chunkEnd
            );
            preparedEventCount += eventLogs.length;
            if (preparedEventCount > 50_000) {
                throw new Error(
                    "On-chain indexer event cardinality exceeds 50,000 entries per run"
                );
            }
            preparedAddressScopedChunks.set(rawCursor, { chunkEnd, eventLogs });
            rawCursor = chunkEnd + 1n;
        }
    }

    let canIncrementallyMaintainHolderCache = !projectionReset;
    const holderCacheReady = await getHolderCacheReady(config);
    if (!holderCacheReady) {
        // Existing indexed logs may predate holder cache support; rebuild after this reconcile completes.
        canIncrementallyMaintainHolderCache =
            canIncrementallyMaintainHolderCache && lastScannedBlock === null;
        if (canIncrementallyMaintainHolderCache) {
            await clearHolderCache(config);
            await setHolderCountBigInt(config, 0n);
            await setHolderCacheReady(config, true);
        }
    }

    if (shouldScanLogs && lastScannedBlock !== null) {
        if (holderCacheReady) {
            const rolledBack = await rollbackHolderCacheFromBlock(config, fromBlock);
            if (!rolledBack) {
                canIncrementallyMaintainHolderCache = false;
            }
        }
        await deleteLogsFromBlock(config, fromBlock);
        await deleteReadModelSnapshotsFromBlock(config, fromBlock);
    }

    onDiagnosticStage?.("dashboard-projection");
    let cursor = fromBlock;
    let indexedEventCount = 0;

    while (cursor <= chainHeadBlock) {
        const chunkEnd = cursor + config.chunkSize - 1n > chainHeadBlock ? chainHeadBlock : cursor + config.chunkSize - 1n;
        const allEventLogs: PendingIndexedEventLog[] = [];

        const appendKnownEvent = (entry: (typeof allEventLogs)[number]) => {
            allEventLogs.push(entry);
            indexedEventCount += 1;
            if (indexedEventCount > 50_000) {
                throw new Error(
                    "On-chain indexer event cardinality exceeds 50,000 entries per run"
                );
            }
        };

        if (useAddressScopedRawLogs) {
            const prepared = preparedAddressScopedChunks.get(cursor);
            if (!prepared || prepared.chunkEnd !== chunkEnd) {
                throw new Error("Address-scoped raw log preparation is incomplete");
            }
            allEventLogs.push(...prepared.eventLogs);
            indexedEventCount += prepared.eventLogs.length;
        } else {
            for (const definition of EVENT_DEFINITIONS) {
                const logs = await instrumentEthGetLogsRequest(
                    rpcRequestCounter,
                    "core-event",
                    () =>
                        client.getLogs({
                            address: config.coreAddress,
                            event: definition.abi,
                            fromBlock: cursor,
                            toBlock: chunkEnd,
                        })
                );

                for (const log of logs) {
                    if (log.blockNumber === null || log.transactionHash === null) {
                        continue;
                    }
                    appendKnownEvent({
                        contractAddress: config.coreAddress,
                        eventName: definition.name,
                        blockNumber: log.blockNumber,
                        blockHash: log.blockHash ?? null,
                        txHash: log.transactionHash,
                        logIndex: log.logIndex ?? 0,
                        payload: {
                            args: log.args ?? {},
                            topics: log.topics,
                            data: log.data,
                        },
                    });
                }
            }

            if (config.governanceAddress) {
                for (const definition of RECOVERY_FUND_EVENT_DEFINITIONS) {
                    const logs = await instrumentEthGetLogsRequest(
                        rpcRequestCounter,
                        "governance-event",
                        () =>
                            client.getLogs({
                                address: config.governanceAddress!,
                                event: definition.abi,
                                fromBlock: cursor,
                                toBlock: chunkEnd,
                            })
                    );

                    for (const log of logs) {
                        if (
                            log.blockNumber === null ||
                            log.transactionHash === null
                        ) {
                            continue;
                        }
                        appendKnownEvent({
                            contractAddress: config.governanceAddress,
                            eventName: definition.name,
                            blockNumber: log.blockNumber,
                            blockHash: log.blockHash ?? null,
                            txHash: log.transactionHash,
                            logIndex: log.logIndex ?? 0,
                            payload: {
                                args: log.args ?? {},
                                topics: log.topics,
                                data: log.data,
                            },
                        });
                    }
                }
            }
        }

        const uniqueBlockNumbers = Array.from(new Set(allEventLogs.map((entry) => entry.blockNumber))).filter(
            (blockNumber) => !blockTimestampCache.has(blockNumber)
        );

        for (const blockNumber of uniqueBlockNumbers) {
            if (finalizedAnchor) {
                const block = await readRawBlockHeader(blockNumber);
                blockTimestampCache.set(blockNumber, block.timestamp);
            } else {
                const block = await client.getBlock({ blockNumber });
                blockTimestampCache.set(blockNumber, block.timestamp);
            }
        }
        if (finalizedAnchor) {
            for (const entry of allEventLogs) {
                const header = await readRawBlockHeader(entry.blockNumber);
                if (
                    !entry.blockHash ||
                    entry.blockHash.toLowerCase() !== header.hash.toLowerCase()
                ) {
                    throw new Error(
                        "Finalized event log block hash changed during the captured run"
                    );
                }
            }
        }

        const chunkHeader = finalizedAnchor
            ? await readRawBlockHeader(chunkEnd)
            : null;
        if (
            finalizedAnchor &&
            chunkEnd === finalizedAnchor.blockNumber &&
            chunkHeader?.hash.toLowerCase() !==
                finalizedAnchor.blockHash.toLowerCase()
        ) {
            throw new Error("Projection reached a different finalized anchor hash");
        }

        await persistLogs(
            config,
            allEventLogs.map((entry) => ({
                ...entry,
                blockTimestampMs: Number(blockTimestampCache.get(entry.blockNumber) ?? 0n) * 1000,
            })),
            { updateHolderCache: canIncrementallyMaintainHolderCache }
        );
        if (finalizedAnchor && chunkHeader) {
            if (finalizedProfile === null) {
                throw new Error("Finalized projection profile is unavailable");
            }
            await setFinalizedProjectionCursor(config, {
                blockNumber: chunkEnd,
                blockHash: chunkHeader.hash,
            }, finalizedProfile);
        } else {
            await setLastScannedBlock(config, chunkEnd);
        }
        cursor = chunkEnd + 1n;
    }

    if ((!canIncrementallyMaintainHolderCache && shouldScanLogs) || projectionReset) {
        const deltaRetentionFromBlock = chainHeadBlock > config.reorgWindow ? chainHeadBlock - config.reorgWindow : 0n;
        await rebuildHolderCacheFromIndexedLogs(config, deltaRetentionFromBlock);
    }

    if (shouldScanLogs || projectionReset) {
        const keepDeltaFromBlock = chainHeadBlock > config.reorgWindow ? chainHeadBlock - config.reorgWindow : 0n;
        await pruneOldHolderDeltas(config, keepDeltaFromBlock);
    }

    if (!finalizedAnchor) {
        if (fromBlock > chainHeadBlock) {
            await setLastScannedBlock(config, chainHeadBlock);
        }
        onDiagnosticStage?.("state-snapshot");
        await refreshRecoveryPortfolioReadModel(config, {
            blockNumber: chainHeadBlock,
            blockHash: null,
            profile: null,
        }, client);
        onDiagnosticStage?.("safe-history");
        await reconcileConfiguredSafeExecutionEvents(rpcRequestCounter);
        return {
            finalizedAnchor: null,
            finalizedProfile: null,
            completed: true,
            dashboardHistoryProgress: null,
        } as const;
    }

    onDiagnosticStage?.("safe-history");
    const coreReachedAnchor = chainHeadBlock === finalizedAnchor.blockNumber;
    const safesReachedAnchor = await reconcileConfiguredSafeExecutionEvents(
        rpcRequestCounter,
        {
            finalizedAnchor,
            finalizedProfile: finalizedProfile ?? undefined,
            gatewayLease,
            committedReconciliationId,
            maximumBlocksPerRun,
            beforeGatewayRequest: paceGatewayRequest,
        }
    );
    const indexedHeader = await readRawBlockHeader(chainHeadBlock);
    const finalizedHeader = await readRawBlockHeader(latestChainHeadBlock);
    const dashboardHistoryProgress = createDashboardHistoryProgress({
        startBlock: effectiveStartBlock,
        indexedThroughBlock: chainHeadBlock,
        indexedThroughTimestampSeconds: indexedHeader.timestamp,
        networkFinalizedBlock: latestChainHeadBlock,
        networkFinalizedTimestampSeconds: finalizedHeader.timestamp,
    });
    if (!coreReachedAnchor || !safesReachedAnchor || finalizedProfile === null) {
        return {
            finalizedAnchor,
            finalizedProfile,
            completed: false,
            dashboardHistoryProgress,
        } as const;
    }
    if (
        (!gatewayLease || committedBoundaryAlreadyComplete) &&
        (await finalizedSnapshotIsComplete(
            config,
            finalizedAnchor,
            finalizedProfile
        ))
    ) {
        return {
            finalizedAnchor,
            finalizedProfile,
            completed: true,
            dashboardHistoryProgress,
        } as const;
    }
    onDiagnosticStage?.("state-snapshot");
    await refreshRecoveryPortfolioReadModel(config, {
        blockNumber: finalizedAnchor.blockNumber,
        blockHash: finalizedAnchor.blockHash,
        profile: finalizedProfile,
    }, client, gatewayLease);
    return {
        finalizedAnchor,
        finalizedProfile,
        completed: true,
        dashboardHistoryProgress,
    } as const;
}

function getLogicAndParameterEventNames() {
    return {
        logic: EVENT_DEFINITIONS.filter((entry) => entry.category === "logic").map((entry) => entry.name),
        parameter: EVENT_DEFINITIONS.filter((entry) => entry.category === "parameter").map((entry) => entry.name),
    };
}

async function reconcileLogs(
    config: IndexerConfig,
    rpcRequestCounter: IndexerRpcRequestCounter,
    force = false,
    suppliedFinalizedAnchor?: FinalizedRunAnchor,
    gatewayLease?: PrivateIndexerGatewayLease,
    onDiagnosticStage?: (stage: OnchainIndexerDiagnosticStage) => void
) {
    const state = getRuntimeState();

    if (state.reconcilePromise) {
        return state.reconcilePromise;
    }

    if (!force && Date.now() - state.lastReconciledAtMs < config.reconcileIntervalMs) {
        return undefined;
    }

    state.reconcilePromise = (async () => {
        const outcome = await reconcileInternal(
            config,
            rpcRequestCounter,
            suppliedFinalizedAnchor,
            gatewayLease,
            onDiagnosticStage
        );
        state.lastReconciledAtMs = Date.now();
        return outcome;
    })().finally(() => {
        state.reconcilePromise = null;
    });

    return state.reconcilePromise;
}

export type OnchainIndexerWorkerRunOptions = Readonly<{
    force?: boolean;
    finalizedAnchor?: FinalizedRunAnchor;
    gatewayExpectation?: InternalGatewayExpectation;
    onDiagnosticStage?: (stage: OnchainIndexerDiagnosticStage) => void;
}>;

type GatewaySuccessfulRunCheckpoint = Readonly<{
    coreCursor: Readonly<{
        address: Address;
        blockNumber: bigint;
        blockHash: Hex;
    }>;
    safeCursors: readonly Readonly<{
        address: Address;
        blockNumber: bigint;
        blockHash: Hex;
    }>[];
    rawCursors: readonly Readonly<{
        address: Address;
        blockNumber: bigint;
        blockHash: Hex;
    }>[];
    profile: string;
}>;

async function readAddressStateValues(
    config: IndexerConfig,
    addresses: readonly Address[],
    keys: readonly string[]
) {
    if (addresses.length === 0) {
        return new Map<string, Map<string, string>>();
    }
    const result = await query<{
        contract_address: string;
        state_key: string;
        state_value: string;
    }>(
        `
            SELECT contract_address, state_key, state_value
            FROM onchain_sync_state
            WHERE chain_id = $1
              AND contract_address = ANY($2::text[])
              AND state_key = ANY($3::text[])
        `,
        [
            config.chainId.toString(),
            addresses.map((address) => address.toLowerCase()),
            keys,
        ]
    );
    const values = new Map<string, Map<string, string>>();
    for (const row of result.rows) {
        const address = row.contract_address.toLowerCase();
        const state = values.get(address) ?? new Map<string, string>();
        state.set(row.state_key, row.state_value);
        values.set(address, state);
    }
    return values;
}

function checkpointCursor(input: {
    address: Address;
    state: Map<string, string> | undefined;
    blockKey: string;
    hashKey: string;
    versionKey?: string;
    expectedVersion?: string;
    profileKey?: string;
    expectedProfile?: string;
    maximumBlock: bigint;
}) {
    if (
        (input.versionKey &&
            input.state?.get(input.versionKey) !== input.expectedVersion) ||
        (input.profileKey &&
            input.state?.get(input.profileKey) !== input.expectedProfile)
    ) {
        throw new Error("Gateway checkpoint identity is incomplete");
    }
    const blockValue = input.state?.get(input.blockKey);
    const blockHash = input.state?.get(input.hashKey);
    if (!blockValue || !blockHash || !HASH_PATTERN.test(blockHash)) {
        throw new Error("Gateway checkpoint cursor is incomplete");
    }
    let blockNumber: bigint;
    try {
        blockNumber = BigInt(blockValue);
    } catch {
        throw new Error("Gateway checkpoint cursor is invalid");
    }
    if (blockNumber < 0n || blockNumber > input.maximumBlock) {
        throw new Error("Gateway checkpoint cursor is outside the lease anchor");
    }
    return Object.freeze({
        address: input.address,
        blockNumber,
        blockHash: blockHash.toLowerCase() as Hex,
    });
}

async function readGatewaySuccessfulRunCheckpoint(
    config: IndexerConfig,
    anchor: FinalizedRunAnchor,
    profile: string
): Promise<GatewaySuccessfulRunCheckpoint> {
    const safeAddresses = configuredSafeHistoryProfileForIndexer().safeAddresses;
    const rawAddresses = Array.from(
        new Map(
            [
                config.coreAddress,
                ...(config.governanceAddress ? [config.governanceAddress] : []),
                ...safeAddresses,
            ].map((address) => [address.toLowerCase(), address])
        ).values()
    );
    const states = await readAddressStateValues(config, rawAddresses, [
        INDEXER_STATE_KEY_LAST_SCANNED_BLOCK,
        INDEXER_STATE_KEY_PROJECTION_BLOCK_HASH,
        INDEXER_STATE_KEY_PROJECTION_PROFILE,
        RAW_LOG_CURSOR_VERSION_STATE_KEY,
        RAW_LOG_CURSOR_BLOCK_STATE_KEY,
        RAW_LOG_CURSOR_BLOCK_HASH_STATE_KEY,
        SAFE_WORKING_CURSOR_VERSION_STATE_KEY,
        SAFE_WORKING_CURSOR_BLOCK_STATE_KEY,
        SAFE_WORKING_CURSOR_BLOCK_HASH_STATE_KEY,
        SAFE_WORKING_PROFILE_STATE_KEY,
    ]);
    const coreCursor = checkpointCursor({
        address: config.coreAddress,
        state: states.get(config.coreAddress.toLowerCase()),
        blockKey: INDEXER_STATE_KEY_LAST_SCANNED_BLOCK,
        hashKey: INDEXER_STATE_KEY_PROJECTION_BLOCK_HASH,
        profileKey: INDEXER_STATE_KEY_PROJECTION_PROFILE,
        expectedProfile: profile,
        maximumBlock: anchor.blockNumber,
    });
    const safeCursors = safeAddresses.map((address) =>
        checkpointCursor({
            address,
            state: states.get(address.toLowerCase()),
            blockKey: SAFE_WORKING_CURSOR_BLOCK_STATE_KEY,
            hashKey: SAFE_WORKING_CURSOR_BLOCK_HASH_STATE_KEY,
            versionKey: SAFE_WORKING_CURSOR_VERSION_STATE_KEY,
            expectedVersion: snapshotIdentity.safeCursorVersion,
            profileKey: SAFE_WORKING_PROFILE_STATE_KEY,
            expectedProfile: profile,
            maximumBlock: anchor.blockNumber,
        })
    );
    const safeCursorByAddress = new Map(
        safeCursors.map((cursor) => [cursor.address.toLowerCase(), cursor])
    );
    const rawCursors = rawAddresses.map((address) => {
        const expectedCursor =
            safeCursorByAddress.get(address.toLowerCase()) ?? coreCursor;
        const cursor = checkpointCursor({
            address,
            state: states.get(address.toLowerCase()),
            blockKey: RAW_LOG_CURSOR_BLOCK_STATE_KEY,
            hashKey: RAW_LOG_CURSOR_BLOCK_HASH_STATE_KEY,
            versionKey: RAW_LOG_CURSOR_VERSION_STATE_KEY,
            expectedVersion: RAW_JOURNAL_VERSION,
            maximumBlock: anchor.blockNumber,
        });
        if (
            cursor.blockNumber !== expectedCursor.blockNumber ||
            cursor.blockHash.toLowerCase() !==
                expectedCursor.blockHash.toLowerCase()
        ) {
            throw new Error(
                "Raw journal and projection checkpoint cursors do not match"
            );
        }
        return cursor;
    });
    return Object.freeze({
        coreCursor,
        safeCursors: Object.freeze(safeCursors),
        rawCursors: Object.freeze(rawCursors),
        profile,
    });
}

async function countRows(
    sql: string,
    params: unknown[]
): Promise<string> {
    const result = await query<{ row_count: string }>(sql, params);
    const count = result.rows[0]?.row_count;
    if (!count || !/^(?:0|[1-9][0-9]*)$/.test(count)) {
        throw new Error("Reconciliation receipt count query failed");
    }
    return count;
}

async function buildCompletedGatewayReceipt(input: {
    config: IndexerConfig;
    lease: PrivateIndexerGatewayLease;
    checkpoint: GatewaySuccessfulRunCheckpoint;
    rpcRequests: IndexerRpcRequestCounts;
    startedAtMs: number;
    completedAtMs: number;
}) {
    const { config, lease, checkpoint } = input;
    if (
        checkpoint.coreCursor.blockNumber !==
            lease.finalizedAnchor.blockNumber ||
        checkpoint.coreCursor.blockHash.toLowerCase() !==
            lease.finalizedAnchor.blockHash.toLowerCase() ||
        checkpoint.safeCursors.some(
            (cursor) =>
                cursor.blockNumber !== lease.finalizedAnchor.blockNumber ||
                cursor.blockHash.toLowerCase() !==
                    lease.finalizedAnchor.blockHash.toLowerCase()
        ) ||
        checkpoint.rawCursors.some(
            (cursor) =>
                cursor.blockNumber !== lease.finalizedAnchor.blockNumber ||
                cursor.blockHash.toLowerCase() !==
                    lease.finalizedAnchor.blockHash.toLowerCase()
        )
    ) {
        throw new Error("Completed gateway receipt checkpoint is partial");
    }
    const dashboardAddresses = [
        config.coreAddress.toLowerCase(),
        ...(config.governanceAddress
            ? [config.governanceAddress.toLowerCase()]
            : []),
    ];
    const safeAddresses = checkpoint.safeCursors.map((cursor) =>
        cursor.address.toLowerCase()
    );
    const rawAddresses = checkpoint.rawCursors.map((cursor) =>
        cursor.address.toLowerCase()
    );
    const [
        rawLogCount,
        dashboardEventLogCount,
        safeEventLogCount,
        snapshotModelCount,
        snapshotBlock,
        snapshotBlockHash,
        snapshotProfile,
    ] = await Promise.all([
        countRows(
            `SELECT COUNT(*)::text AS row_count FROM onchain_raw_logs
             WHERE chain_id = $1 AND contract_address = ANY($2::text[])`,
            [config.chainId.toString(), rawAddresses]
        ),
        countRows(
            `SELECT COUNT(*)::text AS row_count FROM onchain_event_logs
             WHERE chain_id = $1 AND contract_address = ANY($2::text[])`,
            [config.chainId.toString(), dashboardAddresses]
        ),
        safeAddresses.length === 0
            ? Promise.resolve("0")
            : countRows(
                  `SELECT COUNT(*)::text AS row_count FROM onchain_event_logs
                   WHERE chain_id = $1
                     AND contract_address = ANY($2::text[])
                     AND event_name = ANY($3::text[])`,
                  [
                      config.chainId.toString(),
                      safeAddresses,
                      ["ExecutionSuccess", "ExecutionFailure"],
                  ]
              ),
        countRows(
            `SELECT COUNT(DISTINCT model_key)::text AS row_count
             FROM onchain_read_model_snapshots
             WHERE chain_id = $1 AND contract_address = $2
               AND block_number = $3 AND model_key = ANY($4::text[])`,
            [
                config.chainId.toString(),
                config.coreAddress.toLowerCase(),
                lease.finalizedAnchor.blockNumber.toString(),
                REQUIRED_FINALIZED_SNAPSHOT_MODEL_KEYS,
            ]
        ),
        getSyncStateBigInt(config, INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK),
        getSyncStateString(
            config,
            INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK_HASH
        ),
        getSyncStateString(config, INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_PROFILE),
    ]);
    if (snapshotBlock === null || snapshotBlockHash === null) {
        throw new Error("Completed gateway state snapshot cursor is missing");
    }
    if (
        snapshotModelCount !==
        REQUIRED_FINALIZED_SNAPSHOT_MODEL_KEYS.length.toString()
    ) {
        throw new Error("Completed gateway state snapshot models are incomplete");
    }
    return createReconciliationReceipt({
        reconciliationId: lease.reconciliationId,
        gatewayConfigRevision: lease.configRevision,
        runtimeConfigId: config.runtimeConfigId,
        finalizedAnchor: lease.finalizedAnchor,
        identities: {
            databaseSchemaVersion: snapshotIdentity.databaseSchemaVersion,
            rawJournalVersion: RAW_JOURNAL_VERSION,
            dashboardProjectionVersion: DASHBOARD_PROJECTION_VERSION,
            stateSnapshotVersion: STATE_SNAPSHOT_VERSION,
            safeCursorVersion: snapshotIdentity.safeCursorVersion,
        },
        rawJournal: {
            trackedAddressCount: checkpoint.rawCursors.length,
            logCount: rawLogCount,
            cursors: checkpoint.rawCursors,
        },
        dashboardProjection: {
            eventLogCount: dashboardEventLogCount,
            blockNumber: checkpoint.coreCursor.blockNumber,
            blockHash: checkpoint.coreCursor.blockHash,
            profile: checkpoint.profile,
        },
        stateSnapshot: {
            modelCount: snapshotModelCount,
            blockNumber: snapshotBlock,
            blockHash: snapshotBlockHash as Hex,
            profile: snapshotProfile ?? "",
        },
        safeCursors: {
            configuredSafeCount: checkpoint.safeCursors.length,
            eventLogCount: safeEventLogCount,
            cursors: checkpoint.safeCursors,
        },
        rpcRequests: input.rpcRequests,
        completedAtMs: input.completedAtMs,
        durationMs: input.completedAtMs - input.startedAtMs,
    });
}

async function setAddressSyncState(
    transactionQuery: TransactionQuery,
    chainId: bigint,
    address: Address,
    key: string,
    value: string
) {
    await transactionQuery(
        `
            INSERT INTO onchain_sync_state (
                chain_id, contract_address, state_key, state_value
            ) VALUES ($1, $2, $3, $4)
            ON CONFLICT (chain_id, contract_address, state_key)
            DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = NOW()
        `,
        [chainId.toString(), address.toLowerCase(), key, value]
    );
}

async function commitGatewaySuccessfulRun(input: {
    config: IndexerConfig;
    lease: PrivateIndexerGatewayLease;
    checkpoint: GatewaySuccessfulRunCheckpoint;
    receipt: OnchainIndexerReconciliationReceipt | null;
}) {
    await withTransaction(async (transactionQuery) => {
        const setCoreState = (key: string, value: string) =>
            setSyncState(input.config, key, value, transactionQuery);
        await setCoreState(
            INDEXER_STATE_KEY_COMMITTED_FINALIZED_BLOCK,
            input.checkpoint.coreCursor.blockNumber.toString()
        );
        await setCoreState(
            INDEXER_STATE_KEY_COMMITTED_FINALIZED_BLOCK_HASH,
            input.checkpoint.coreCursor.blockHash.toLowerCase()
        );
        await setCoreState(
            INDEXER_STATE_KEY_COMMITTED_FINALIZED_PROFILE,
            input.checkpoint.profile
        );
        await setCoreState(
            INDEXER_STATE_KEY_COMMITTED_RECONCILIATION_ID,
            input.lease.reconciliationId
        );
        await setCoreState(
            INDEXER_STATE_KEY_COMMITTED_GATEWAY_CONFIG_REVISION,
            input.lease.configRevision
        );
        for (const cursor of input.checkpoint.safeCursors) {
            await setAddressSyncState(
                transactionQuery,
                input.config.chainId,
                cursor.address,
                SAFE_COMMITTED_FINALIZED_BLOCK_STATE_KEY,
                cursor.blockNumber.toString()
            );
            await setAddressSyncState(
                transactionQuery,
                input.config.chainId,
                cursor.address,
                SAFE_COMMITTED_FINALIZED_BLOCK_HASH_STATE_KEY,
                cursor.blockHash.toLowerCase()
            );
            await setAddressSyncState(
                transactionQuery,
                input.config.chainId,
                cursor.address,
                SAFE_COMMITTED_FINALIZED_PROFILE_STATE_KEY,
                input.checkpoint.profile
            );
            await setAddressSyncState(
                transactionQuery,
                input.config.chainId,
                cursor.address,
                SAFE_COMMITTED_RECONCILIATION_ID_STATE_KEY,
                input.lease.reconciliationId
            );
        }
        if (input.receipt) {
            await setCoreState(
                INDEXER_STATE_KEY_RECONCILIATION_RECEIPT,
                JSON.stringify(input.receipt)
            );
        } else {
            await deleteSyncState(
                input.config,
                INDEXER_STATE_KEY_RECONCILIATION_RECEIPT,
                transactionQuery
            );
        }
    });
}

export async function runOnchainIndexerWorkerOnce(
    options?: OnchainIndexerWorkerRunOptions
): Promise<InternalReconcileResult> {
    options?.onDiagnosticStage?.("configuration");
    const config = getIndexerConfig();
    if (!config) {
        throw new Error("On-chain indexer worker configuration is incomplete");
    }
    options?.onDiagnosticStage?.("database-schema");
    await ensureSchema();
    options?.onDiagnosticStage?.("advisory-lock");
    const lock = await withSharedAdvisoryLock(
        `onchain-indexer:${config.chainId}:${config.coreAddress.toLowerCase()}`,
        async () => {
            const rpcRequestCounter = createIndexerRpcRequestCounter();
            const startedAtMs = Date.now();
            let lease: PrivateIndexerGatewayLease | null = null;
            let outcome: ReconciliationOutcome | undefined;
            const forceWorkerRun = config.privateGatewayClient
                ? true
                : options?.force ?? true;
            try {
                if (config.privateGatewayClient) {
                    if (options?.finalizedAnchor || !options?.gatewayExpectation) {
                        throw new Error(
                            "An exact controller expectation is required with an indexer gateway lease"
                        );
                    }
                    const runtimeState = getRuntimeState();
                    const ambiguous = indexerGatewayHealthIsSuppressed({
                        activeReconciliationId:
                            runtimeState.activeGatewayReconciliationId,
                        ambiguousUntilMs:
                            runtimeState.gatewayLeaseAmbiguousUntilMs,
                        nowMs: Date.now(),
                    });
                    if (ambiguous) {
                        throw new Error(
                            "A previous indexer gateway lease remains ambiguous"
                        );
                    }
                    if (runtimeState.activeGatewayReconciliationId !== null) {
                        runtimeState.activeGatewayReconciliationId = null;
                        runtimeState.gatewayLeaseAmbiguousUntilMs = 0;
                    }
                    const committedBoundary =
                        await getCommittedFinalizedBoundary(config);
                    assertGatewayExpectationNotStale({
                        expectedAnchor:
                            options.gatewayExpectation.finalizedAnchor,
                        committedBlockNumber: committedBoundary.blockNumber,
                        committedBlockHash: committedBoundary.blockHash,
                    });
                    if (!(options.force ?? false)) {
                        const existingReceipt =
                            await getLastOnchainIndexerReconciliationReceipt();
                        const expectation = options.gatewayExpectation;
                        const expectedNumber =
                            expectation.finalizedAnchor.blockNumber.toString();
                        const expectedHash =
                            expectation.finalizedAnchor.blockHash.toLowerCase();
                        const compatibleReceipt = Boolean(
                            existingReceipt &&
                                existingReceipt.gatewayConfigRevision ===
                                    expectation.runtimeRevision &&
                                existingReceipt.runtimeConfigId ===
                                    config.runtimeConfigId &&
                                BigInt(existingReceipt.finalizedAnchor.number) <=
                                    expectation.finalizedAnchor.blockNumber &&
                                (existingReceipt.finalizedAnchor.number !==
                                    expectedNumber ||
                                    existingReceipt.finalizedAnchor.hash ===
                                        expectedHash)
                        );
                        const disposition = planInternalGatewayReconcile({
                            mode: "allow-exact-receipt-noop",
                            exactReceiptAvailable: Boolean(
                                compatibleReceipt &&
                                    existingReceipt?.finalizedAnchor.number ===
                                        expectedNumber &&
                                    existingReceipt.finalizedAnchor.hash ===
                                        expectedHash
                            ),
                            compatibleReceiptCompletedAtMs:
                                compatibleReceipt && existingReceipt
                                    ? Date.parse(existingReceipt.completedAt)
                                    : null,
                            nowMs: Date.now(),
                            reconcileIntervalMs: config.reconcileIntervalMs,
                            leaseAmbiguous: false,
                        });
                        if (
                            disposition === "exact-receipt-noop" ||
                            disposition === "deferred-cadence"
                        ) {
                            runtimeState.lastRpcRequestCounts =
                                rpcRequestCounter.snapshot();
                            runtimeState.lastReconciliationReceipt =
                                existingReceipt;
                            return Object.freeze({
                                status:
                                    disposition === "deferred-cadence"
                                        ? "deferred-cadence"
                                        : "reconciled",
                                dashboardHistoryProgress: null,
                            });
                        }
                    }
                    lease = await config.privateGatewayClient.acquire(
                        {
                            reconciliationId: `app-${randomUUID()}`,
                            expectedRuntimeRevision:
                                options.gatewayExpectation.runtimeRevision,
                            expectedFinalizedAnchor:
                                options.gatewayExpectation.finalizedAnchor,
                        }
                    );
                    runtimeState.activeGatewayReconciliationId =
                        lease.reconciliationId;
                    runtimeState.gatewayLeaseAmbiguousUntilMs =
                        lease.expiresAtMs;
                } else if (options?.gatewayExpectation) {
                    throw new Error(
                        "A gateway expectation is forbidden when gateway mode is disabled"
                    );
                }
                options?.onDiagnosticStage?.("reconciliation");
                outcome = await reconcileLogs(
                    config,
                    rpcRequestCounter,
                    forceWorkerRun,
                    lease?.finalizedAnchor ?? options?.finalizedAnchor,
                    lease ?? undefined,
                    options?.onDiagnosticStage
                );
                if (!outcome && forceWorkerRun) {
                    throw new Error(
                        "Forced on-chain indexer reconciliation did not run"
                    );
                }
            } finally {
                getRuntimeState().lastRpcRequestCounts = rpcRequestCounter.snapshot();
                if (lease) {
                    await lease.release();
                    const runtimeState = getRuntimeState();
                    runtimeState.activeGatewayReconciliationId = null;
                    runtimeState.gatewayLeaseAmbiguousUntilMs = 0;
                }
            }
            if (lease && outcome) {
                if (!outcome.finalizedAnchor || !outcome.finalizedProfile) {
                    throw new Error(
                        "Gateway reconciliation did not produce a finalized profile"
                    );
                }
                const checkpoint = await readGatewaySuccessfulRunCheckpoint(
                    config,
                    outcome.finalizedAnchor,
                    outcome.finalizedProfile
                );
                const completedAtMs = Date.now();
                const receipt = outcome.completed
                    ? await buildCompletedGatewayReceipt({
                          config,
                          lease,
                          checkpoint,
                          rpcRequests: rpcRequestCounter.snapshot(),
                          startedAtMs,
                          completedAtMs,
                      })
                    : null;
                await commitGatewaySuccessfulRun({
                    config,
                    lease,
                    checkpoint,
                    receipt,
                });
                getRuntimeState().lastReconciliationReceipt = receipt;
            }
            if (outcome?.completed && config.chainId === 31338n) {
                await withTransaction((execute) =>
                    markSandboxForkGenerationReady({
                        execute,
                        coreAddress: config.coreAddress,
                        reachedBlock: outcome.finalizedAnchor?.blockNumber ?? 0n,
                    })
                );
            }
            return Object.freeze({
                status: classifyInternalReconcileOutcome(outcome),
                dashboardHistoryProgress:
                    outcome?.dashboardHistoryProgress ?? null,
            });
        }
    );
    return lock.acquired
        ? lock.result
        : Object.freeze({ status: "busy" as const, dashboardHistoryProgress: null });
}

/** Called only by the authenticated internal fork-refresh route. */
export async function transitionSandboxForkGeneration(input:
    | { action: "prepare"; current: ForkGenerationAnchor }
    | {
          action: "apply";
          previous: ForkGenerationAnchor;
          current: ForkGenerationAnchor;
      }
) {
    const config = getIndexerConfig();
    if (!config || config.chainId !== 31338n) {
        throw new Error("Sandbox fork recovery requires the chain-31338 indexer");
    }
    await ensureSchema();
    const lock = await withSharedAdvisoryLock(
        `onchain-indexer:${config.chainId}:${config.coreAddress.toLowerCase()}`,
        async () => {
            const client = createPublicClient({
                transport: indexerRpcTransport(config.rpcUrl),
            });
            if (await client.getChainId() !== 31338) {
                throw new Error("Sandbox indexer RPC chain ID differs");
            }
            const currentBlock = await client.getBlock({
                blockNumber: input.current.forkBlock,
            });
            if (
                currentBlock.number !== input.current.forkBlock ||
                currentBlock.hash.toLowerCase() !== input.current.forkBlockHash.toLowerCase()
            ) {
                throw new Error("current Sandbox fork-point header differs");
            }
            if (input.action === "prepare") {
                return withTransaction((execute) =>
                    prepareSandboxForkGeneration({
                        execute,
                        coreAddress: config.coreAddress,
                        current: input.current,
                    })
                );
            }
            let commonHash: string | null = null;
            if (input.previous.forkBlock <= input.current.forkBlock) {
                const commonBlock = await client.getBlock({
                    blockNumber: input.previous.forkBlock,
                });
                if (commonBlock.number !== input.previous.forkBlock) {
                    throw new Error("previous Sandbox fork-point header number differs");
                }
                commonHash = commonBlock.hash;
            }
            const result = await withTransaction((execute) =>
                applySandboxForkGeneration({
                    execute,
                    coreAddress: config.coreAddress,
                    previous: input.previous,
                    current: input.current,
                    deploymentStartBlock: config.startBlock,
                    currentHashAtPreviousForkBlock: commonHash,
                })
            );
            getRuntimeState().lastReconciledAtMs = 0;
            getRuntimeState().lastReconciliationReceipt = null;
            return result;
        }
    );
    return lock.acquired ? lock.result : { status: "busy" as const };
}

/** Readiness is recorded by the worker after both Dashboard and Safe scanning finish. */
export async function getSandboxForkGenerationStatus() {
    const config = getIndexerConfig();
    if (!config || config.chainId !== 31338n) {
        throw new Error("Sandbox fork recovery requires the chain-31338 indexer");
    }
    await ensureSchema();
    const stored = await readSandboxForkGeneration(query, config.coreAddress.toLowerCase());
    if (!stored) return null;
    return {
        generation: stored.anchor.generation,
        forkBlock: stored.anchor.forkBlock.toString(),
        forkBlockHash: stored.anchor.forkBlockHash,
        status: stored.status,
    };
}

type LatestUpdateRecord = {
    timestampMs: number;
    txHash: string | null;
};

type AmountLogRow = {
    block_timestamp: Date;
    tx_hash: string;
    amount_raw: string | null;
};

async function getLatestEventRecord(config: IndexerConfig, eventNames: EventName[]): Promise<LatestUpdateRecord | null> {
    const result = await query<{ block_timestamp: Date; tx_hash: string }>(
        `
            SELECT block_timestamp, tx_hash
            FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND event_name = ANY($3::text[])
            ORDER BY block_number DESC, log_index DESC
            LIMIT 1
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), eventNames]
    );

    if (result.rowCount === 0) return null;

    return {
        timestampMs: result.rows[0].block_timestamp.getTime(),
        txHash: result.rows[0].tx_hash,
    };
}

async function readCoreAndTokenMetrics(
    config: IndexerConfig,
    client: IndexerPublicClient,
    stateReadTarget: StateReadTarget
) {
    const [totalSupplyRaw, tokenDecimalsRaw, issuanceFeePpmRaw, redemptionFeePpmRaw, pausedRaw] = await Promise.all([
        client.readContract({
            address: config.coreAddress,
            abi: [parseAbiItem("function totalSupply() view returns (uint256)")],
            functionName: "totalSupply",
            ...stateReadTarget,
        }),
        client.readContract({
            address: config.coreAddress,
            abi: [parseAbiItem("function decimals() view returns (uint8)")],
            functionName: "decimals",
            ...stateReadTarget,
        }),
        client.readContract({
            address: config.coreAddress,
            abi: [parseAbiItem("function issuanceFeePpm() view returns (uint256)")],
            functionName: "issuanceFeePpm",
            ...stateReadTarget,
        }),
        client.readContract({
            address: config.coreAddress,
            abi: [parseAbiItem("function redemptionFeePpm() view returns (uint256)")],
            functionName: "redemptionFeePpm",
            ...stateReadTarget,
        }),
        client.readContract({
            address: config.coreAddress,
            abi: [parseAbiItem("function paused() view returns (bool)")],
            functionName: "paused",
            ...stateReadTarget,
        }),
    ]);

    return {
        totalSupplyRaw: totalSupplyRaw as bigint,
        tokenDecimals: BigInt(tokenDecimalsRaw as number),
        issuanceFeePpm: issuanceFeePpmRaw as bigint,
        redemptionFeePpm: redemptionFeePpmRaw as bigint,
        paused: pausedRaw as boolean,
    };
}

async function readBasketSnapshot(
    config: IndexerConfig,
    client: IndexerPublicClient,
    stateReadTarget: StateReadTarget,
    options?: {
        forcePinnedStateReads?: boolean;
        isTerminalReadFailure?(error: unknown): boolean;
    }
): Promise<BasketSnapshot | null> {
    const readSafe = async <T>(action: () => Promise<T>): Promise<T | null> => {
        try {
            return await action();
        } catch (error) {
            if (options?.isTerminalReadFailure?.(error)) throw error;
            return null;
        }
    };

    const [
        assetsRaw,
        targetsPpmRaw,
        goldRefGramsRaw,
        cygldPerUnitRaw,
        cygldRefGramsRaw,
    ] = await Promise.all([
        readSafe(() =>
            client.readContract({
                address: config.coreAddress,
                abi: CORE_DIAMOND_ABI,
                functionName: "basketAssets",
                ...stateReadTarget,
            })
        ),
        readSafe(() =>
            client.readContract({
                address: config.coreAddress,
                abi: CORE_DIAMOND_ABI,
                functionName: "basketTargetsPpm",
                ...stateReadTarget,
            })
        ),
        readSafe(() =>
            client.readContract({
                address: config.coreAddress,
                abi: CORE_DIAMOND_ABI,
                functionName: "basketGoldRefGramsFp18",
                ...stateReadTarget,
            })
        ),
        readSafe(() =>
            client.readContract({
                address: config.coreAddress,
                abi: CORE_DIAMOND_ABI,
                functionName: "basketCygldPerUnitFp18",
                ...stateReadTarget,
            })
        ),
        readCygldRefGramsFp18(config, client, stateReadTarget, {
            forcePinnedRead: options?.forcePinnedStateReads,
            isTerminalReadFailure: options?.isTerminalReadFailure,
        }),
    ]);

    if (!assetsRaw || !targetsPpmRaw || !goldRefGramsRaw || !cygldPerUnitRaw) {
        return null;
    }

    const assets = assetsRaw as Address[];
    const targets = targetsPpmRaw as bigint[];
    const goldReferences = goldRefGramsRaw as bigint[];
    const cygldPerUnits = cygldPerUnitRaw as bigint[];
    const reserveAddress = config.coreAddress;

    if (
        assets.length === 0 ||
        assets.length !== targets.length ||
        assets.length !== goldReferences.length ||
        assets.length !== cygldPerUnits.length
    ) {
        return {
            reserveAddress: reserveAddress?.toLowerCase() ?? null,
            cygldRefGrams: cygldRefGramsRaw === null ? null : bigIntToTokenNumber(cygldRefGramsRaw as bigint, 18n),
            cygldRefGramsFp18: cygldRefGramsRaw === null ? null : (cygldRefGramsRaw as bigint).toString(),
            assets: [],
            withinBand: null,
        };
    }

    const reserveDetails = await Promise.all(
        assets.map(async (asset) => {
            const [balanceRaw, totalSupplyRaw, decimalsRaw, symbolRaw] = await Promise.all([
                readSafe(() =>
                    client.readContract({
                        address: asset,
                        abi: [parseAbiItem("function balanceOf(address) view returns (uint256)")],
                        functionName: "balanceOf",
                        args: [reserveAddress],
                        ...stateReadTarget,
                    })
                ),
                readSafe(() =>
                    client.readContract({
                        address: asset,
                        abi: [parseAbiItem("function totalSupply() view returns (uint256)")],
                        functionName: "totalSupply",
                        ...stateReadTarget,
                    })
                ),
                readSafe(() =>
                    client.readContract({
                        address: asset,
                        abi: [parseAbiItem("function decimals() view returns (uint8)")],
                        functionName: "decimals",
                        ...stateReadTarget,
                    })
                ),
                readSafe(() =>
                    client.readContract({
                        address: asset,
                        abi: [parseAbiItem("function symbol() view returns (string)")],
                        functionName: "symbol",
                        ...stateReadTarget,
                    })
                ),
            ]);
            return {
                balanceRaw: (balanceRaw as bigint | null) ?? 0n,
                totalSupplyRaw: (totalSupplyRaw as bigint | null) ?? null,
                decimals: Number((decimalsRaw as number | null) ?? 18),
                symbol: (symbolRaw as string | null) ?? `${asset.slice(0, 6)}...${asset.slice(-4)}`,
            };
        })
    );

    const actualValueRaw = reserveDetails.map(
        (detail, index) => (detail.balanceRaw * cygldPerUnits[index]) / 1_000_000_000_000_000_000n
    );
    const totalActualValueRaw = actualValueRaw.reduce((sum, value) => sum + value, 0n);

    const assetsSnapshot: BasketSnapshotAsset[] = assets.map((asset, index) => {
        const targetPpm = targets[index];
        const actualPpm = totalActualValueRaw > 0n ? (actualValueRaw[index] * 1_000_000n) / totalActualValueRaw : 0n;
        const driftPpm = actualPpm - targetPpm;
        const decimals = reserveDetails[index].decimals;
        const decimalsBigInt = BigInt(decimals);
        const cygldPerTokenFp18 = (cygldPerUnits[index] * 10n ** decimalsBigInt) / 1_000_000_000_000_000_000n;
        const reserveBalanceRaw = reserveDetails[index].balanceRaw;
        const totalSupplyRaw = reserveDetails[index].totalSupplyRaw;
        return {
            address: asset.toLowerCase(),
            symbol: reserveDetails[index].symbol,
            targetPercent: Number(targetPpm) / 10_000,
            actualPercent: Number(actualPpm) / 10_000,
            driftPercent: Number(driftPpm) / 10_000,
            decimals,
            reserveBalance: bigIntToTokenNumber(reserveBalanceRaw, decimalsBigInt),
            reserveBalanceRaw: reserveBalanceRaw.toString(),
            totalSupply: totalSupplyRaw === null ? null : bigIntToTokenNumber(totalSupplyRaw, decimalsBigInt),
            totalSupplyRaw: totalSupplyRaw === null ? null : totalSupplyRaw.toString(),
            goldRefGrams: bigIntToTokenNumber(goldReferences[index], 18n),
            cygldPerUnitFp18: cygldPerUnits[index].toString(),
            cygldPerToken: bigIntToTokenNumber(cygldPerTokenFp18, 18n),
        };
    });

    const withinBand = assetsSnapshot.every((asset) => Math.abs(asset.driftPercent) <= 5);

    return {
        reserveAddress: reserveAddress.toLowerCase(),
        cygldRefGrams: cygldRefGramsRaw === null ? null : bigIntToTokenNumber(cygldRefGramsRaw as bigint, 18n),
        cygldRefGramsFp18: cygldRefGramsRaw === null ? null : (cygldRefGramsRaw as bigint).toString(),
        assets: assetsSnapshot,
        withinBand,
    };
}

type RecoveryPoolRead = {
    impaired: boolean;
    coreAttachedShares: bigint;
    externalShares: bigint;
    redeemableRaw: bigint;
    cygldPerAssetRawFp18: bigint;
    cygldSupplyCap: bigint;
    referenceShares: bigint;
    referenceValueCygld: bigint;
    shareDecimals: number;
};

type ReserveLifecycleRead = {
    lifecycle: number;
    exitEntitlementRaw: bigint;
};

type ReserveCustodyRead = {
    lifecycle: number;
    poolImpaired: boolean;
    redeemablePoolRaw: bigint;
    coreAttachedShares: bigint;
    externalShares: bigint;
    exitEntitlementRaw: bigint;
    liveBalanceAvailable: boolean;
    liveRawCustody: bigint;
    activeAvailableRaw: bigint;
    poolRawDeficit: bigint;
    exitEntitlementDeficitRaw: bigint;
};

function uniqueOrderedAssets(groups: readonly (readonly Address[])[]) {
    const assets = new Map<string, Address>();
    for (const group of groups) {
        for (const asset of group) assets.set(asset.toLowerCase(), asset);
    }
    return [...assets.values()].sort((left, right) =>
        BigInt(left) < BigInt(right) ? -1 : 1
    );
}

async function readRecoverySnapshot(
    config: IndexerConfig,
    blockNumber: bigint,
    client: IndexerPublicClient,
    stateReadTarget: StateReadTarget,
    isTerminalReadFailure?: (error: unknown) => boolean
): Promise<RecoverySnapshot | null> {
    try {
        const [
            coreAttachedRecoveryAssets,
            indexedRecoveryAssets,
            indexedReserveAssets,
            basketAssets,
        ] = await Promise.all([
            client.readContract({
                address: config.coreAddress,
                abi: CORE_DIAMOND_ABI,
                functionName: "coreAttachedRecoveryAssets",
                ...stateReadTarget,
            }),
            readIndexedRecoveryAssets(config, blockNumber, recoveryQuery),
            readIndexedReserveAssets(config, blockNumber, recoveryQuery),
            client.readContract({
                address: config.coreAddress,
                abi: CORE_DIAMOND_ABI,
                functionName: "basketAssets",
                ...stateReadTarget,
            }),
        ]);

        const poolAssets = uniqueOrderedAssets([
            coreAttachedRecoveryAssets,
            indexedRecoveryAssets,
        ]);
        const reserveAssets = uniqueOrderedAssets([
            indexedReserveAssets,
            poolAssets,
            basketAssets,
        ]);
        if (poolAssets.length > 256 || reserveAssets.length > 512) {
            throw new Error("Recovery asset cardinality exceeds the App read-model policy");
        }

        const reserveLifecycles = await Promise.all(
            reserveAssets.map(async (asset): Promise<ReserveLifecycleSnapshot> => {
                const lifecycle = (await client.readContract({
                    address: config.coreAddress,
                    abi: CORE_DIAMOND_ABI,
                    functionName: "reserveLifecycle",
                    args: [asset],
                    ...stateReadTarget,
                })) as ReserveLifecycleRead;
                return {
                    asset: asset.toLowerCase(),
                    lifecycle: Number(lifecycle.lifecycle),
                    exitEntitlementRaw: lifecycle.exitEntitlementRaw.toString(),
                };
            })
        );
        const lifecycleByAsset = new Map(
            reserveLifecycles.map((lifecycle) => [lifecycle.asset, lifecycle])
        );

        const poolRows = await Promise.all(
            poolAssets.map(async (asset): Promise<RecoveryPoolSnapshot> => {
                const [poolRaw, custodyRaw] = await Promise.all([
                    client.readContract({
                        address: config.coreAddress,
                        abi: CORE_DIAMOND_ABI,
                        functionName: "recoveryPool",
                        args: [asset],
                        ...stateReadTarget,
                    }),
                    client.readContract({
                        address: config.coreAddress,
                        abi: CORE_DIAMOND_ABI,
                        functionName: "reserveCustodyStatus",
                        args: [asset],
                        ...stateReadTarget,
                    }),
                ]);
                const pool = poolRaw as RecoveryPoolRead;
                const custody = custodyRaw as ReserveCustodyRead;
                const lifecycle = lifecycleByAsset.get(asset.toLowerCase());
                if (!lifecycle) {
                    throw new Error("Recovery pool, lifecycle, and custody views are inconsistent");
                }
                const currentPool = {
                    asset: asset.toLowerCase(),
                    impaired: pool.impaired,
                    coreAttachedShares: pool.coreAttachedShares.toString(),
                    externalShares: pool.externalShares.toString(),
                    totalShares: (
                        pool.coreAttachedShares + pool.externalShares
                    ).toString(),
                    redeemableRaw: pool.redeemableRaw.toString(),
                    cygldPerAssetRawFp18:
                        pool.cygldPerAssetRawFp18.toString(),
                    cygldSupplyCap: pool.cygldSupplyCap.toString(),
                    referenceShares: pool.referenceShares.toString(),
                    referenceValueCygld: pool.referenceValueCygld.toString(),
                    shareDecimals: pool.shareDecimals,
                };
                const currentCustody = {
                    lifecycle: Number(custody.lifecycle),
                    poolImpaired: custody.poolImpaired,
                    redeemablePoolRaw: custody.redeemablePoolRaw.toString(),
                    coreAttachedShares: custody.coreAttachedShares.toString(),
                    externalShares: custody.externalShares.toString(),
                    exitEntitlementRaw: custody.exitEntitlementRaw.toString(),
                    liveBalanceAvailable: custody.liveBalanceAvailable,
                    liveRawCustody: custody.liveRawCustody.toString(),
                    activeAvailableRaw: custody.activeAvailableRaw.toString(),
                    poolRawDeficit: custody.poolRawDeficit.toString(),
                    exitEntitlementDeficitRaw:
                        custody.exitEntitlementDeficitRaw.toString(),
                };
                return reconcileRecoveryPoolLifecycleSnapshot(
                    currentPool,
                    lifecycle,
                    currentCustody
                ) as RecoveryPoolSnapshot;
            })
        );

        const pools = poolRows.filter(
            (pool) =>
                pool.impaired ||
                pool.coreAttachedShares !== "0" ||
                pool.externalShares !== "0" ||
                pool.redeemableRaw !== "0"
        );

        const fund = await readRecoveryFundSnapshot({
            coreAddress: config.coreAddress,
            governanceAddress: config.governanceAddress,
            stateReadTarget,
            client,
            pools,
            isTerminalReadFailure,
        });

        return {
            collection: config.coreAddress.toLowerCase(),
            pools,
            reserveLifecycles,
            fund,
        };
    } catch (error) {
        if (isTerminalReadFailure?.(error)) throw error;
        // Incomplete local deployments must not synthesize recovery state. The
        // UI treats null as unavailable and fails closed.
        return null;
    }
}

async function refreshRecoveryPortfolioReadModel(
    config: IndexerConfig,
    snapshotTarget: {
        blockNumber: bigint;
        blockHash: Hex | null;
        profile: string | null;
    },
    client: IndexerPublicClient,
    gatewayLease?: PrivateIndexerGatewayLease
) {
    const stateReadTarget: StateReadTarget = snapshotTarget.blockHash
        ? {
              blockHash: snapshotTarget.blockHash,
              requireCanonical: true,
          }
        : { blockNumber: snapshotTarget.blockNumber };
    const stateReadClient =
        config.finalizedSnapshotMulticall && snapshotTarget.blockHash
            ? createBoundedFinalizedMulticallClient({
                  client,
                  blockHash: snapshotTarget.blockHash,
              })
            : client;
    const isTerminalReadFailure = (error: unknown) =>
        isFinalizedMulticallBudgetExceeded(error) ||
        Boolean(
            gatewayLease?.isRestartRequiredError(error) ||
                gatewayLease?.isRpcAccountingFailure(error)
        );
    const assertSnapshotAnchor = async () => {
        if (!snapshotTarget.blockHash) return;
        const block = await client.getBlock({ blockHash: snapshotTarget.blockHash });
        const normalized = normalizeFinalizedRunAnchor({
            number: block.number,
            hash: block.hash,
        });
        if (
            normalized.blockNumber !== snapshotTarget.blockNumber ||
            normalized.blockHash.toLowerCase() !==
                snapshotTarget.blockHash.toLowerCase()
        ) {
            throw new Error("Finalized state snapshot anchor changed during the run");
        }
    };

    await assertSnapshotAnchor();
    const recovery = await readRecoverySnapshot(
        config,
        snapshotTarget.blockNumber,
        stateReadClient,
        stateReadTarget,
        isTerminalReadFailure
    );
    const model = buildRecoveryPortfolioReadModel(
        config.chainId,
        snapshotTarget.blockNumber,
        config.coreAddress,
        recovery
    );
    const dashboard = await buildOnchainDashboardSummary(
        config,
        snapshotTarget.blockNumber,
        recovery,
        stateReadClient,
        stateReadTarget,
        {
            expectedBlockHash: snapshotTarget.blockHash,
            forcePinnedStateReads: snapshotTarget.blockHash !== null,
            isTerminalReadFailure,
        }
    );
    const recoveryShareV2Checkpoint = config.recoveryShareV2
        ? await readRecoveryShareV2Checkpoint(config, recoveryQuery)
        : null;
    let canonicalRecoveryShareV2CheckpointHash: Hex | null = null;
    if (
        recoveryShareV2Checkpoint &&
        recoveryShareV2Checkpoint.blockNumber < snapshotTarget.blockNumber
    ) {
        const checkpointBlock = await client.getBlock({
            blockNumber: recoveryShareV2Checkpoint.blockNumber,
        });
        const normalizedCheckpointBlock = normalizeFinalizedRunAnchor({
            number: checkpointBlock.number,
            hash: checkpointBlock.hash,
        });
        if (
            normalizedCheckpointBlock.blockNumber !==
            recoveryShareV2Checkpoint.blockNumber
        ) {
            throw new Error(
                "Recovery-share v2 checkpoint header returned the wrong block"
            );
        }
        canonicalRecoveryShareV2CheckpointHash =
            normalizedCheckpointBlock.blockHash;
    }
    await assertSnapshotAnchor();
    // The retained rollback image still reads the legacy table, so its bounded
    // lifetime replay remains deliberate during coexistence. The additive v2
    // projection is incremental, but cannot retire this cost/100k ceiling until
    // rollback compatibility is formally closed.
    await rebuildRecoveryShareBalances(
        config,
        recoveryQuery,
        recoveryTransaction,
        async (transactionQuery) => {
            if (config.recoveryShareV2) {
                if (!snapshotTarget.blockHash || !snapshotTarget.profile) {
                    throw new Error(
                        "Recovery-share v2 projection requires an exact finalized snapshot"
                    );
                }
                await reconcileRecoveryShareBalancesV2({
                    config,
                    snapshotBlock: snapshotTarget.blockNumber,
                    snapshotBlockHash: snapshotTarget.blockHash,
                    profile: snapshotTarget.profile,
                    canonicalPreviousCheckpointHash:
                        canonicalRecoveryShareV2CheckpointHash,
                    transactionQuery,
                });
            }
            await persistRecoveryPortfolioReadModel(config, model, transactionQuery);
            await persistDashboardSnapshot(
                config,
                snapshotTarget.blockNumber,
                dashboard,
                transactionQuery
            );
            if (snapshotTarget.blockHash && snapshotTarget.profile) {
                await setSyncState(
                    config,
                    INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK,
                    snapshotTarget.blockNumber.toString(),
                    transactionQuery
                );
                await setSyncState(
                    config,
                    INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK_HASH,
                    snapshotTarget.blockHash.toLowerCase(),
                    transactionQuery
                );
                await setSyncState(
                    config,
                    INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_PROFILE,
                    snapshotTarget.profile,
                    transactionQuery
                );
            }
        }
    );
    await pruneRecoveryApiRateLimits();
}

function parseBigIntValue(value: string | null | undefined) {
    if (!value) return 0n;
    try {
        return BigInt(value);
    } catch {
        return 0n;
    }
}

function bigIntToTokenNumber(raw: bigint, decimals: bigint) {
    const sign = raw < 0n ? -1 : 1;
    const abs = raw < 0n ? -raw : raw;
    const base = 10n ** decimals;
    const whole = abs / base;
    const fraction = abs % base;
    const wholeNumber = Number(whole);
    const fractionNumber = Number(fraction) / 10 ** Number(decimals);
    return sign * (wholeNumber + fractionNumber);
}

async function loadAmountLogs(
    config: IndexerConfig,
    eventName: EventName,
    contractAddress: Address,
    argKey: "grossCygldOut" | "netCygldIn" | "value",
    fromDate: Date,
    toDate: Date
) {
    const result = await query<AmountLogRow>(
        `
            SELECT block_timestamp, tx_hash, payload->'args'->>'${argKey}' AS amount_raw
            FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND event_name = $3
              AND block_timestamp >= $4
              AND block_timestamp <= $5
            ORDER BY block_timestamp ASC, log_index ASC
            LIMIT ${DASHBOARD_MAX_LOG_ROWS + 1}
        `,
        [config.chainId.toString(), contractAddress.toLowerCase(), eventName, fromDate, toDate]
    );
    if (result.rows.length > DASHBOARD_MAX_LOG_ROWS) {
        throw new Error("Dashboard amount-log cardinality exceeds the App read-model policy");
    }
    return result.rows;
}

async function loadTransferAmountLogs(config: IndexerConfig, fromDate: Date, toDate: Date) {
    const result = await query<AmountLogRow>(
        `
            SELECT block_timestamp, tx_hash, payload->'args'->>'value' AS amount_raw
            FROM onchain_event_logs
            WHERE chain_id = $1
              AND contract_address = $2
              AND event_name = 'Transfer'
              AND block_timestamp >= $3
              AND block_timestamp <= $4
            ORDER BY block_timestamp ASC, log_index ASC
            LIMIT ${DASHBOARD_MAX_LOG_ROWS + 1}
        `,
        [config.chainId.toString(), config.coreAddress.toLowerCase(), fromDate, toDate]
    );
    if (result.rows.length > DASHBOARD_MAX_LOG_ROWS) {
        throw new Error("Dashboard transfer-log cardinality exceeds the App read-model policy");
    }
    return result.rows;
}

function buildEmptyBuckets(range: DashboardRangeKey, endMs: number) {
    const config = DASHBOARD_RANGE_CONFIG[range];
    const windowMs = config.buckets * config.stepMs;
    const windowStartMs = endMs - windowMs;
    const buckets = Array.from({ length: config.buckets }, (_, index) => ({
        bucketStartMs: windowStartMs + index * config.stepMs,
        mintRaw: 0n,
        redeemRaw: 0n,
        transferRaw: 0n,
        transferCount: 0,
        supplyRaw: 0n,
    }));

    return {
        range,
        stepMs: config.stepMs,
        windowStartMs,
        buckets,
    };
}

function applyAmountRowsToBuckets(
    rangeBuckets: ReturnType<typeof buildEmptyBuckets>,
    rows: AmountLogRow[],
    field: "mintRaw" | "redeemRaw" | "transferRaw",
    endMs: number
) {
    for (const row of rows) {
        const timestampMs = row.block_timestamp.getTime();
        if (timestampMs < rangeBuckets.windowStartMs || timestampMs > endMs) continue;

        let index = Math.floor((timestampMs - rangeBuckets.windowStartMs) / rangeBuckets.stepMs);
        // Include events exactly at window end in the final bucket.
        if (index === rangeBuckets.buckets.length && timestampMs === endMs) {
            index = rangeBuckets.buckets.length - 1;
        }
        if (index < 0 || index >= rangeBuckets.buckets.length) continue;

        const amountRaw = parseBigIntValue(row.amount_raw);
        rangeBuckets.buckets[index][field] += amountRaw;
        if (field === "transferRaw") rangeBuckets.buckets[index].transferCount += 1;
    }
}

function materializeRangeBuckets(
    rangeBuckets: ReturnType<typeof buildEmptyBuckets>,
    currentTotalSupplyRaw: bigint,
    tokenDecimals: bigint
) {
    const totalNetRaw = rangeBuckets.buckets.reduce((sum, bucket) => sum + (bucket.mintRaw - bucket.redeemRaw), 0n);
    let runningSupplyRaw = currentTotalSupplyRaw - totalNetRaw;

    const buckets: DashboardRangeBucket[] = rangeBuckets.buckets.map((bucket) => {
        const netRaw = bucket.mintRaw - bucket.redeemRaw;
        runningSupplyRaw += netRaw;
        bucket.supplyRaw = runningSupplyRaw;

        return {
            bucketStartMs: bucket.bucketStartMs,
            mintCygld: bigIntToTokenNumber(bucket.mintRaw, tokenDecimals),
            redeemCygld: bigIntToTokenNumber(bucket.redeemRaw, tokenDecimals),
            netCygld: bigIntToTokenNumber(netRaw, tokenDecimals),
            supplyCygld: bigIntToTokenNumber(bucket.supplyRaw, tokenDecimals),
            transferredCygld: bigIntToTokenNumber(bucket.transferRaw, tokenDecimals),
            transferTxCount: bucket.transferCount,
        };
    });

    return {
        buckets,
        netIssuanceRaw: totalNetRaw,
    };
}

async function buildOnchainDashboardSummary(
    config: IndexerConfig,
    snapshotBlockNumber: bigint,
    recoverySnapshot: RecoverySnapshot | null,
    client: IndexerPublicClient,
    stateReadTarget: StateReadTarget,
    options?: {
        expectedBlockHash?: Hex | null;
        forcePinnedStateReads?: boolean;
        isTerminalReadFailure?(error: unknown): boolean;
    }
) {
    const snapshotBlock = options?.expectedBlockHash
        ? await client.getBlock({ blockHash: options.expectedBlockHash })
        : await client.getBlock({ blockNumber: snapshotBlockNumber });
    if (
        options?.expectedBlockHash &&
        snapshotBlock.hash?.toLowerCase() !== options.expectedBlockHash.toLowerCase()
    ) {
        throw new Error("Dashboard snapshot resolved a different finalized block hash");
    }
    const eventGroups = getLogicAndParameterEventNames();
    const nowMs = Number(snapshotBlock.timestamp) * 1000;
    const maxWindowMs = DASHBOARD_RANGE_CONFIG["1M"].buckets * DASHBOARD_RANGE_CONFIG["1M"].stepMs;
    const fromDate = new Date(nowMs - maxWindowMs);
    const toDate = new Date(nowMs);

    const [
        coreMetrics,
        basketSnapshot,
        issuedRows,
        redeemedRows,
        transferRows,
        protocolLogicUpdate,
        protocolParameterUpdate,
        holderCountRaw,
    ] =
        await Promise.all([
            readCoreAndTokenMetrics(config, client, stateReadTarget),
            readBasketSnapshot(config, client, stateReadTarget, {
                forcePinnedStateReads: options?.forcePinnedStateReads,
                isTerminalReadFailure: options?.isTerminalReadFailure,
            }),
            loadAmountLogs(config, "Issued", config.coreAddress, "grossCygldOut", fromDate, toDate),
            loadAmountLogs(config, "Redeemed", config.coreAddress, "netCygldIn", fromDate, toDate),
            loadTransferAmountLogs(config, fromDate, toDate),
            getLatestEventRecord(config, eventGroups.logic),
            getLatestEventRecord(config, eventGroups.parameter),
            getHolderCountBigInt(config),
        ]);

    const ranges = (Object.keys(DASHBOARD_RANGE_CONFIG) as DashboardRangeKey[]).reduce(
        (acc, range) => {
            const emptyBuckets = buildEmptyBuckets(range, nowMs);
            applyAmountRowsToBuckets(emptyBuckets, issuedRows, "mintRaw", nowMs);
            applyAmountRowsToBuckets(emptyBuckets, redeemedRows, "redeemRaw", nowMs);
            applyAmountRowsToBuckets(emptyBuckets, transferRows, "transferRaw", nowMs);

            acc[range] = materializeRangeBuckets(
                emptyBuckets,
                coreMetrics.totalSupplyRaw,
                coreMetrics.tokenDecimals || TOKEN_DECIMALS_FALLBACK
            ).buckets;
            return acc;
        },
        {} as Record<DashboardRangeKey, DashboardRangeBucket[]>
    );

    const netIssuance24hCygld = ranges["24H"].reduce((sum, bucket) => sum + bucket.netCygld, 0);
    const issuanceFeePercent =
        coreMetrics.issuanceFeePpm !== null ? Number(coreMetrics.issuanceFeePpm) / 10_000 : null;
    const redemptionFeePercent =
        coreMetrics.redemptionFeePpm !== null ? Number(coreMetrics.redemptionFeePpm) / 10_000 : null;
    const holderCount =
        holderCountRaw === null || holderCountRaw > BigInt(Number.MAX_SAFE_INTEGER) ? null : Number(holderCountRaw);

    return {
        enabled: true,
        protocolLogicUpdate,
        protocolParameterUpdate,
        chainHeadBlock: snapshotBlockNumber.toString(),
        snapshotBlock: snapshotBlockNumber.toString(),
        chainHeadTimestampMs: nowMs,
        lastScannedBlock: snapshotBlockNumber.toString(),
        metrics: {
            currentTotalSupplyCygld: bigIntToTokenNumber(
                coreMetrics.totalSupplyRaw,
                coreMetrics.tokenDecimals || TOKEN_DECIMALS_FALLBACK
            ),
            netIssuance24hCygld,
            holderCount,
            issuanceFeePercent,
            redemptionFeePercent,
            paused: coreMetrics.paused,
        },
        basket: basketSnapshot,
        recovery: recoverySnapshot,
        series: ranges,
    };
}

/** Wire shape written to the completed dashboard projection. */
export type OnchainDashboardSnapshot = Awaited<ReturnType<typeof buildOnchainDashboardSummary>>;

export async function getOnchainDashboardSummary() {
    const config = getIndexerConfig();
    if (!config) {
        return {
            enabled: false,
            protocolLogicUpdate: null,
            protocolParameterUpdate: null,
            lastScannedBlock: null,
        };
    }
    return readCachedDashboardSnapshot(config);
}

export async function getRecoverySharePortfolio(holder: Address) {
    const config = getIndexerConfig();
    if (!config) {
        return { enabled: false, collection: null, balances: [], pools: [] };
    }
    return readCachedRecoverySharePortfolio(config, holder);
}
