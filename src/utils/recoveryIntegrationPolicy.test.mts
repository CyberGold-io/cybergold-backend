import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

function url(relativePath: string) {
  return new URL(relativePath, import.meta.url);
}

function read(relativePath: string) {
  return readFileSync(url(relativePath), "utf8");
}

test("indexer declares only the clean-launch lifecycle and recovery outcomes", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  for (const eventName of [
    "ReserveLifecycleChanged",
    "RecoveryActivated",
    "RecoveryRehabilitated",
    "RecoverySharesRedeemed",
    "TransferSingle",
    "TransferBatch",
  ]) {
    assert.match(indexer, new RegExp(`name: \\"${eventName}\\"`));
  }
  for (const removedEvent of [
    "ReserveCheckpointed",
    "RecoveryRedemptionSettled",
    "ReserveAdmitted",
    "ReserveExitBegun",
    "ReserveInactivated",
    "RecoveryPoolResolved",
    "ZeroEntitlementRecoveryFinalized",
  ]) {
    assert.doesNotMatch(indexer, new RegExp(`name: \\"${removedEvent}\\"`));
  }
  assert.match(
    indexer,
    /loadAmountLogs\(config, "Issued", config\.coreAddress, "grossCygldOut"/
  );
  assert.match(
    indexer,
    /loadAmountLogs\(config, "Redeemed", config\.coreAddress, "netCygldIn"/
  );
  assert.doesNotMatch(indexer, /"cygldAmount" \| "userCygld"/);
});

test("recovery discovery includes zero-share assets and refetches pinned current state", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const persistence = read("../server/onchain-indexer/recoverySharePersistence.ts");
  const model = read("../server/onchain-indexer/recoveryPortfolioModel.ts");
  const repository = read("../server/onchain-indexer/recoveryPortfolioRepository.ts");
  const dashboardRepository = read(
    "../server/onchain-indexer/dashboardSnapshotRepository.ts"
  );

  assert.match(indexer, /readIndexedRecoveryAssets\(config, blockNumber/);
  assert.match(indexer, /readIndexedReserveAssets\(config, blockNumber/);
  assert.match(indexer, /coreAttachedRecoveryAssets/);
  assert.match(indexer, /functionName: "recoveryPool"[\s\S]*blockNumber/);
  assert.match(indexer, /functionName: "reserveLifecycle"[\s\S]*blockNumber/);
  assert.match(indexer, /functionName: "reserveCustodyStatus"[\s\S]*blockNumber/);
  const snapshotRollback = indexer.slice(
    indexer.indexOf("async function deleteReadModelSnapshotsFromBlock"),
    indexer.indexOf("async function ensureIndexerVersion")
  );
  assert.match(snapshotRollback, /DELETE FROM onchain_read_model_snapshots/);
  assert.match(snapshotRollback, /block_number >= \$3/);
  assert.match(snapshotRollback, /GROUP BY model_key/);
  assert.match(snapshotRollback, /MAX\(block_number\)/);
  assert.match(snapshotRollback, /NOT EXISTS/);
  for (const snapshotRepository of [repository, dashboardRepository]) {
    assert.match(snapshotRepository, /block_number > \$4/);
  }
  assert.match(indexer, /deleteReadModelSnapshotsFromBlock\(config, fromBlock\)/);
  const snapshotIdentity = JSON.parse(
    read("../server/onchain-indexer/snapshot-identity.json")
  ) as {
    dashboardIndexerVersion?: unknown;
    rawJournalVersion?: unknown;
    dashboardProjectionVersion?: unknown;
    stateSnapshotVersion?: unknown;
  };
  assert.match(String(snapshotIdentity.dashboardIndexerVersion), /^\d+$/);
  assert.match(String(snapshotIdentity.rawJournalVersion), /^\d+$/);
  assert.match(String(snapshotIdentity.dashboardProjectionVersion), /^\d+$/);
  assert.match(String(snapshotIdentity.stateSnapshotVersion), /^\d+$/);
  assert.match(
    indexer,
    /const LEGACY_INDEXER_VERSION = snapshotIdentity\.dashboardIndexerVersion;/
  );
  const versionReset = indexer.slice(
    indexer.indexOf("async function ensureIndexerVersion"),
    indexer.indexOf("async function persistLogs")
  );
  assert.doesNotMatch(versionReset, /deleteLogsFromBlock/);
  assert.match(versionReset, /planIndexerIdentityTransition/);
  assert.match(versionReset, /clearHolderCache\(config, transactionQuery\)/);
  assert.match(versionReset, /INDEXER_STATE_KEY_RAW_JOURNAL_VERSION/);
  assert.match(versionReset, /INDEXER_STATE_KEY_DASHBOARD_PROJECTION_VERSION/);
  assert.match(
    versionReset,
    /transition\.restartScanFromDeployment[\s\S]*deleteSyncState\([\s\S]*INDEXER_STATE_KEY_LAST_SCANNED_BLOCK/
  );
  assert.match(persistence, /event_name = 'RecoveryActivated'/);
  assert.match(persistence, /event_name = 'ReserveLifecycleChanged'/);
  assert.match(model, /schemaVersion: "5\.0"/);
  assert.match(repository, /recovery-portfolio-v5/);
  assert.doesNotMatch(indexer, /activeRecoveryEventIds|recoveryEvent\b/);
  assert.equal(
    existsSync(url("../server/onchain-indexer/recoveryFundPersistence.ts")),
    false
  );
});

test("Governance Fund snapshots reconcile current asset-plus-generation state", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const snapshot = read("../server/onchain-indexer/recoveryFundSnapshot.ts");
  for (const eventName of [
    "RecoveryFundInitialized",
    "AssetRecoveryFundActivated",
    "RecoverySharesPurchased",
  ]) {
    assert.ok(indexer.includes(`name: "${eventName}"`));
  }
  assert.match(snapshot, /trustedRecoveryFundCore/);
  assert.match(snapshot, /functionName: "paused"/);
  assert.match(snapshot, /governancePaused/);
  assert.match(snapshot, /assetRecoveryFund/);
  assert.match(snapshot, /recoveryFundTreasuryStatus/);
  assert.match(snapshot, /allowanceExposure/);
  assert.match(snapshot, /initialCygldCommitment/);
  assert.match(snapshot, /acquiredRecoveryShares/);
  assert.equal(
    snapshot.match(/functionName: "acquiredRecoveryShares"/g)?.length,
    1,
    "the snapshot must make one live acquired-inventory read"
  );
  assert.match(snapshot, /const governanceBalance = acquiredShares/);
  assert.match(snapshot, /governanceBalance: governanceBalance\.toString\(\)/);
  assert.match(snapshot, /acquiredShares: acquiredShares\.toString\(\)/);
  assert.match(snapshot, /fund\.generation/);
  assert.match(snapshot, /unavailable-or-inconsistent/);
  assert.doesNotMatch(snapshot, /CORE_DIAMOND_ABI|functionName: "balanceOf"/);
  assert.doesNotMatch(snapshot, /facilityId|termsHash|corePoolViewHash|replayIndexed/);
  assert.doesNotMatch(
    snapshot,
    /previewRedeemRecoveryShares|currentPreviewRawOut|redemptionAvailable|surrenderAvailable|recoveryFundPurchasesPaused|purchasesPaused/
  );
  assert.doesNotMatch(indexer, /AcquiredRecoverySharesRedeemed/);
  assert.doesNotMatch(indexer, /RecoveryFundPurchasesPaused|RecoveryFundPurchasesUnpaused/);
  assert.match(indexer, /INDEXER_STATE_KEY_GOVERNANCE_ADDRESS/);
  assert.match(
    indexer,
    /governanceAddress: expectedGovernanceAddress[\s\S]*transition\.restartScanFromDeployment/
  );
});

test("retained indexer APIs stay cached; recovery portfolio is independent and worker remains authenticated", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const safeIndexer = read("../server/safe-events/indexer.ts");
  const recoveryRepository = read(
    "../server/onchain-indexer/recoveryPortfolioRepository.ts"
  );
  const workerRoute = read("../api/internal/onchain-indexer/reconcile/route.ts");
  const recoveryStart = indexer.indexOf(
    "export async function getRecoverySharePortfolio"
  );
  const recoveryBody = indexer.slice(recoveryStart);
  const safeStart = safeIndexer.indexOf(
    "export async function getSafeExecutionStatuses"
  );
  const safeBody = safeIndexer.slice(safeStart);

  assert.match(
    safeIndexer,
    /serverEnv\.ONCHAIN_INDEXER_RPC_URL\s*\?\?\s*serverEnv\.RPC_URL\s*\?\?\s*publicEnv\.NEXT_PUBLIC_RPC_URL/
  );
  assert.match(recoveryBody, /readCachedRecoverySharePortfolio/);
  const route = read("../api/recovery/shares/route.ts");
  assert.match(route, /server\/recovery\/rpcPortfolio/);
  assert.doesNotMatch(route, /onchain-indexer/);
  assert.doesNotMatch(recoveryBody, /reconcileLogs|readRecoverySnapshot|createPublicClient/);
  assert.doesNotMatch(
    safeBody,
    /reconcileSafeExecutionEvents|deleteIndexedSafeExecutionLogs|createPublicClient/
  );
  assert.match(recoveryRepository, /onchain_read_model_snapshots/);
  assert.match(recoveryRepository, /onchain_api_rate_limits/);
  assert.match(recoveryRepository, /pg_try_advisory_xact_lock/);
  assert.match(recoveryRepository, /statement_timeout/);
  assert.match(workerRoute, /authorizeIndexerWorker/);
  assert.match(workerRoute, /runOnchainIndexerWorkerOnce/);
});
