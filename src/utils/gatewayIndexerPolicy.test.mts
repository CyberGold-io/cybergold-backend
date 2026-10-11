import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath: string) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

test("one outer lease owns the exact anchor and is released before any checkpoint or receipt", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const worker = indexer.slice(
    indexer.indexOf("export async function runOnchainIndexerWorkerOnce"),
    indexer.indexOf("type LatestUpdateRecord")
  );
  assert.equal(worker.match(/privateGatewayClient\.acquire\(/g)?.length, 1);
  assert.equal(worker.match(/await lease\.release\(\)/g)?.length, 1);
  assert.match(
    worker,
    /lease\?\.finalizedAnchor[\s\S]*lease \?\? undefined/
  );
  assert.ok(
    worker.indexOf("await lease.release()") <
      worker.indexOf("readGatewaySuccessfulRunCheckpoint")
  );
  assert.ok(
    worker.indexOf("readGatewaySuccessfulRunCheckpoint") <
      worker.indexOf("buildCompletedGatewayReceipt")
  );
  assert.ok(
    worker.indexOf("buildCompletedGatewayReceipt") <
      worker.indexOf("commitGatewaySuccessfulRun")
  );
});

test("successful partial leases atomically checkpoint Core and every Safe without a complete receipt", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const commit = indexer.slice(
    indexer.indexOf("async function commitGatewaySuccessfulRun"),
    indexer.indexOf("export async function runOnchainIndexerWorkerOnce")
  );
  assert.match(commit, /await withTransaction/);
  assert.match(commit, /INDEXER_STATE_KEY_COMMITTED_FINALIZED_BLOCK/);
  assert.match(commit, /SAFE_COMMITTED_FINALIZED_BLOCK_STATE_KEY/);
  assert.match(commit, /SAFE_COMMITTED_RECONCILIATION_ID_STATE_KEY/);
  assert.match(commit, /INDEXER_STATE_KEY_COMMITTED_GATEWAY_CONFIG_REVISION/);
  assert.match(
    commit,
    /if \(input\.receipt\)[\s\S]*JSON\.stringify\(input\.receipt\)[\s\S]*else[\s\S]*deleteSyncState/
  );
});

test("failed provisional Core or Safe work cannot become the next lease planning boundary", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const safeIndexer = read("../server/safe-events/indexer.ts");
  assert.match(
    indexer,
    /selectFinalizedPlanningBoundary\([\s\S]*leaseBound: Boolean\(gatewayLease\)[\s\S]*committed/
  );
  assert.match(
    safeIndexer,
    /selectFinalizedPlanningBoundary\([\s\S]*leaseBound: Boolean\(options\.gatewayLease\)[\s\S]*committed/
  );
  assert.match(indexer, /planningBoundary\.blockNumber/);
  assert.match(safeIndexer, /planningBoundary\.blockNumber/);
});

test("all gateway state reads use one client and exact canonical block-hash parameters", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const refresh = indexer.slice(
    indexer.indexOf("async function refreshRecoveryPortfolioReadModel"),
    indexer.indexOf("function parseBigIntValue")
  );
  assert.match(refresh, /blockHash: snapshotTarget\.blockHash/);
  assert.match(refresh, /requireCanonical: true/);
  assert.match(refresh, /readRecoverySnapshot\([\s\S]*stateReadClient,[\s\S]*stateReadTarget/);
  assert.match(
    refresh,
    /buildOnchainDashboardSummary\([\s\S]*stateReadClient,[\s\S]*stateReadTarget/
  );
  assert.match(
    refresh,
    /isFinalizedMulticallBudgetExceeded\(error\)[\s\S]*gatewayLease\?\.isRestartRequiredError\(error\)[\s\S]*gatewayLease\?\.isRpcAccountingFailure\(error\)/
  );
  assert.doesNotMatch(refresh, /createPublicClient/);
  assert.match(
    indexer,
    /reconcileConfiguredSafeExecutionEvents\([\s\S]*gatewayLease/
  );
});

test("v2 receipts count an unbatched zero-retry transport and retain the v1 rollback row", () => {
  const lease = read("../server/onchain-indexer/gatewayLease.ts");
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const receipt = read("../server/onchain-indexer/reconciliationReceipt.ts");
  assert.match(
    lease,
    /batch: false,[\s\S]*retryCount: 0,[\s\S]*recordGatewayRpcAttempt/
  );
  assert.match(indexer, /completed_reconciliation_receipt_v2/);
  assert.doesNotMatch(indexer, /completed_reconciliation_receipt_v1/);
  assert.match(receipt, /RECONCILIATION_RECEIPT_FORMAT_VERSION = 2/);
});

test("active exact receipts and durable cadence defer before a lease while candidate mode always acquires", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const route = read("../api/internal/onchain-indexer/reconcile/route.ts");
  const contract = read("../server/onchain-indexer/internalReconcileContract.ts");
  const worker = indexer.slice(
    indexer.indexOf("export async function runOnchainIndexerWorkerOnce"),
    indexer.indexOf("type LatestUpdateRecord")
  );
  assert.ok(
    worker.indexOf("getLastOnchainIndexerReconciliationReceipt") <
      worker.indexOf("privateGatewayClient.acquire")
  );
  assert.ok(worker.indexOf("planInternalGatewayReconcile") < worker.indexOf("privateGatewayClient.acquire"));
  assert.match(worker, /disposition === "deferred-cadence"/);
  assert.doesNotMatch(worker, /refreshReconciliationReceiptCompletion/);
  assert.match(worker, /rpcRequestCounter\.snapshot\(\)/);
  assert.match(contract, /"allow-exact-receipt-noop"/);
  assert.match(contract, /"require-worker-run"/);
  assert.match(route, /parsed\.mode === "require-worker-run"/);
});

test("bounded catch-up status stays truthful through the worker and HTTP response", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const route = read("../api/internal/onchain-indexer/reconcile/route.ts");
  const worker = indexer.slice(
    indexer.indexOf("export async function runOnchainIndexerWorkerOnce"),
    indexer.indexOf("type LatestUpdateRecord")
  );

  assert.match(worker, /status: classifyInternalReconcileOutcome\(outcome\)/);
  assert.match(worker, /dashboardHistoryProgress/);
  assert.match(worker, /if \(!outcome && forceWorkerRun\)/);
  assert.match(route, /buildInternalReconcileResponse\(outcome, parsed\.legacy\)/);
  assert.match(route, /"Retry-After": response\.retryAfter/);
  assert.doesNotMatch(route, /\{ status: "reconciled" \}/);
});

test("gateway history is deliberately bounded, paced, and reported against the finalized head", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const contract = read("../server/onchain-indexer/internalReconcileContract.ts");
  assert.match(indexer, /GATEWAY_HISTORICAL_MAX_BLOCKS_PER_RUN = 500n/);
  assert.match(indexer, /GATEWAY_HISTORICAL_RPC_INTERVAL_MS = 1_000/);
  assert.match(indexer, /createGatewayRequestPacer/);
  assert.match(indexer, /networkFinalizedBlock: latestChainHeadBlock/);
  assert.match(contract, /INTERNAL_RECONCILE_RESPONSE_FORMAT_VERSION = 2/);
  assert.match(contract, /dashboardHistoryProgress/);
});

test("authenticated health bounds ambiguous leases by expiry and never handles tokens", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const route = read("../api/internal/onchain-indexer/reconcile/route.ts");
  assert.match(indexer, /indexerGatewayHealthIsSuppressed/);
  assert.match(indexer, /gatewayLeaseAmbiguousUntilMs/);
  assert.match(indexer, /lease\.expiresAtMs/);
  const worker = indexer.slice(
    indexer.indexOf("export async function runOnchainIndexerWorkerOnce"),
    indexer.indexOf("type LatestUpdateRecord")
  );
  assert.ok(
    worker.indexOf("await lease.release()") <
      worker.lastIndexOf("runtimeState.activeGatewayReconciliationId = null")
  );
  assert.match(route, /export async function GET/);
  assert.match(route, /authorizationFailure\(request\)/);
  assert.match(route, /Completed on-chain indexer reconciliation is unavailable/);
  assert.doesNotMatch(indexer, /console\.(?:log|error|warn|info)/);
  assert.doesNotMatch(route, /RPC_GATEWAY_TOKEN|leaseToken/);
});
