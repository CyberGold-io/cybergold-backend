import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath: string) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

test("the outer worker captures one finalized anchor and passes it through Core and Safe", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const safeIndexer = read("../server/safe-events/indexer.ts");
  const reconcile = indexer.slice(
    indexer.indexOf("async function reconcileInternal"),
    indexer.indexOf("function getLogicAndParameterEventNames")
  );

  assert.equal(
    reconcile.match(/blockTag: reconciliationAnchorBlockTag\(config\.chainId\)/g)?.length,
    1
  );
  assert.match(
    reconcile,
    /const finalizedAnchor = config\.archiveFreeFinalizedMode[\s\S]*suppliedFinalizedAnchor[\s\S]*normalizeFinalizedRunAnchor[\s\S]*resolveFinalizedRunAnchor/
  );
  assert.match(
    reconcile,
    /reconcileConfiguredSafeExecutionEvents\([\s\S]*finalizedAnchor,[\s\S]*finalizedProfile/
  );
  assert.equal(
    indexer.match(/await reconcileConfiguredSafeExecutionEvents\(/g)?.length,
    2,
    "one mutually exclusive legacy call and one finalized call are expected"
  );
  assert.match(
    safeIndexer,
    /const latestBlock = options\?\.finalizedAnchor[\s\S]*\? options\.finalizedAnchor\.blockNumber[\s\S]*: await client\.getBlockNumber\(\)/
  );
});

test("run profiles bind Core start, Safe lookback, and all decoder event sets", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const safeIndexer = read("../server/safe-events/indexer.ts");

  assert.match(indexer, /coreDeploymentStartBlock: effectiveStartBlock/);
  assert.match(indexer, /safeLookbackBlocks: safeHistoryProfile\?\.lookbackBlocks/);
  assert.match(indexer, /coreEventSelectors: EVENT_DEFINITIONS\.map/);
  assert.match(
    indexer,
    /governanceEventSelectors: RECOVERY_FUND_EVENT_DEFINITIONS\.map/
  );
  assert.match(indexer, /safeEventSelectors: safeHistoryProfile\?\.eventSelectors/);
  assert.match(indexer, /INDEXER_STATE_KEY_PROJECTION_PROFILE/);
  assert.match(safeIndexer, /SAFE_FINALIZED_PROFILE_STATE_KEY/);
  assert.match(
    safeIndexer,
    /planningBoundary\.profile !== options\.finalizedProfile/
  );
});

test("archive-free mainnet start resolution cannot enter historical getCode detection", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const resolver = indexer.slice(
    indexer.indexOf("async function resolveStartBlock"),
    indexer.indexOf("async function reconcileInternal")
  );
  const archiveGuard = resolver.indexOf("if (config.archiveFreeFinalizedMode)");
  const archiveReturn = resolver.indexOf("return resolveArchiveFreeDeploymentStart", archiveGuard);
  const detection = resolver.indexOf("detectDeploymentBlock");

  assert.ok(archiveGuard >= 0);
  assert.ok(archiveReturn > archiveGuard);
  assert.ok(detection > archiveReturn);
  assert.match(
    read("../server/onchain-indexer/finalizedReconciliation.ts"),
    /chainId === 1n[\s\S]*configuredStartBlock === 0n[\s\S]*configured nonzero block/
  );
});

test("deep catch-up advances hashed cursors before any finalized state snapshot", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const reconcile = indexer.slice(
    indexer.indexOf("async function reconcileInternal"),
    indexer.indexOf("function getLogicAndParameterEventNames")
  );
  const projectionCursor = reconcile.indexOf("await setFinalizedProjectionCursor");
  const safeProjection = reconcile.indexOf(
    "const safesReachedAnchor = await reconcileConfiguredSafeExecutionEvents"
  );
  const completenessGuard = reconcile.indexOf(
    "if (!coreReachedAnchor || !safesReachedAnchor"
  );
  const snapshotNoop = reconcile.indexOf("await finalizedSnapshotIsComplete");
  const snapshot = reconcile.lastIndexOf("await refreshRecoveryPortfolioReadModel");

  assert.ok(projectionCursor >= 0);
  assert.ok(safeProjection > projectionCursor);
  assert.ok(completenessGuard > safeProjection);
  assert.ok(snapshotNoop > completenessGuard);
  assert.ok(snapshot > snapshotNoop);
  assert.match(
    reconcile,
    /chunkEnd === finalizedAnchor\.blockNumber[\s\S]*Projection reached a different finalized anchor hash/
  );
});

test("finalized snapshots are hash-guarded, pinned, and atomically marked", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const refresh = indexer.slice(
    indexer.indexOf("async function refreshRecoveryPortfolioReadModel"),
    indexer.indexOf("function parseBigIntValue")
  );

  assert.equal(refresh.match(/await assertSnapshotAnchor\(\)/g)?.length, 2);
  assert.match(
    refresh,
    /readRecoverySnapshot\([\s\S]*config,[\s\S]*snapshotTarget\.blockNumber,[\s\S]*stateReadTarget/
  );
  assert.match(refresh, /blockHash: snapshotTarget\.blockHash/);
  assert.match(refresh, /requireCanonical: true/);
  assert.match(
    refresh,
    /forcePinnedStateReads: snapshotTarget\.blockHash !== null/
  );
  assert.match(
    refresh,
    /persistDashboardSnapshot[\s\S]*INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK[\s\S]*INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_BLOCK_HASH[\s\S]*INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_PROFILE/
  );
});

test("scheduled calls honor cadence while explicit manual reconciliation can force a run", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const route = read("../api/internal/onchain-indexer/reconcile/route.ts");
  const worker = indexer.slice(
    indexer.indexOf("export async function runOnchainIndexerWorkerOnce"),
    indexer.indexOf("type LatestUpdateRecord")
  );

  assert.match(indexer, /Date\.now\(\) - state\.lastReconciledAtMs < config\.reconcileIntervalMs/);
  assert.match(
    worker,
    /const forceWorkerRun = config\.privateGatewayClient\s*\?\s*true\s*:\s*options\?\.force \?\? true;/
  );
  assert.match(worker, /reconcileLogs\([\s\S]*forceWorkerRun/);
  assert.match(worker, /if \(!outcome && forceWorkerRun\)/);
  assert.match(worker, /options\?\.finalizedAnchor/);
  assert.match(route, /searchParams\.get\("force"\) === "1"/);
  assert.match(route, /mode === "require-worker-run"/);
  assert.match(route, /runOnchainIndexerWorkerOnce\(\{[\s\S]*force,/);
  assert.doesNotMatch(route, /gatewayExpectation: parsed\.gatewayExpectation/);
  assert.doesNotMatch(worker, /reconcileConfiguredSafeExecutionEvents/);
});
