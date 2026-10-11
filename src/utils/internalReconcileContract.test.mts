import assert from "node:assert/strict";
import test from "node:test";

import {
  buildInternalReconcileResponse,
  classifyInternalReconcileOutcome,
  createDashboardHistoryProgress,
  INTERNAL_RECONCILE_RESPONSE_STATUSES,
  internalReconcileHttpStatus,
  parseInternalReconcileRequest,
  planInternalGatewayReconcile,
  assertGatewayExpectationNotStale,
} from "../server/onchain-indexer/internalReconcileContract.ts";

const HASH = `0x${"12".repeat(32)}`;

function request(value: string | object, contentType = "application/json") {
  return new Request("http://app.internal/api/internal/onchain-indexer/reconcile", {
    method: "POST",
    headers: { "Content-Type": contentType },
    body: typeof value === "string" ? value : JSON.stringify(value),
  });
}

function body(mode: "allow-exact-receipt-noop" | "require-worker-run") {
  return {
    kind: "cybergold-b2b-reconcile-request",
    formatVersion: 1,
    mode,
  };
}

test("bounded reconciliation passes map truthfully onto the fixed response contract", () => {
  assert.equal(Object.isFrozen(INTERNAL_RECONCILE_RESPONSE_STATUSES), true);
  assert.deepEqual([...INTERNAL_RECONCILE_RESPONSE_STATUSES], [
    "reconciled",
    "incomplete",
    "deferred-cadence",
    "busy",
  ]);

  const firstPass = classifyInternalReconcileOutcome({ completed: false });
  const laterPass = classifyInternalReconcileOutcome({ completed: true });
  assert.equal(firstPass, "incomplete");
  assert.equal(laterPass, "reconciled");
  assert.equal(classifyInternalReconcileOutcome(undefined), "deferred-cadence");

  assert.equal(internalReconcileHttpStatus("reconciled"), 200);
  assert.equal(internalReconcileHttpStatus("incomplete"), 202);
  assert.equal(internalReconcileHttpStatus("deferred-cadence"), 200);
  assert.equal(internalReconcileHttpStatus("busy"), 409);
});

test("legacy and versioned responses preserve exact bodies and transport policy", () => {
  const cases = [
    ["reconciled", 200, null],
    ["incomplete", 202, null],
    ["deferred-cadence", 200, null],
    ["busy", 409, "1"],
  ] as const;
  const dashboardHistoryProgress = createDashboardHistoryProgress({
    startBlock: 100n,
    indexedThroughBlock: 150n,
    indexedThroughTimestampSeconds: 1_700_000_000n,
    networkFinalizedBlock: 200n,
    networkFinalizedTimestampSeconds: 1_700_001_200n,
  });
  assert.deepEqual(dashboardHistoryProgress, {
    formatVersion: 1,
    startBlock: "100",
    indexedThroughBlock: "150",
    indexedThroughDate: "2023-11-14T22:13:20.000Z",
    networkFinalizedBlock: "200",
    networkFinalizedDate: "2023-11-14T22:33:20.000Z",
    percent: 50,
  });

  for (const [status, httpStatus, retryAfter] of cases) {
    const result = {
      status,
      dashboardHistoryProgress:
        status === "incomplete" ? dashboardHistoryProgress : null,
    } as const;
    assert.deepEqual(buildInternalReconcileResponse(result, true), {
      body: { status },
      httpStatus,
      retryAfter,
    });
    assert.deepEqual(buildInternalReconcileResponse(result, false), {
      body: {
        kind: "cybergold-b2b-reconcile-response",
        formatVersion: 2,
        status,
        dashboardHistoryProgress:
          status === "incomplete" ? dashboardHistoryProgress : null,
      },
      httpStatus,
      retryAfter,
    });
  }
});

test("dashboard progress requires a coherent finalized range", () => {
  assert.throws(
    () =>
      createDashboardHistoryProgress({
        startBlock: 100n,
        indexedThroughBlock: 99n,
        indexedThroughTimestampSeconds: 1_700_000_000n,
        networkFinalizedBlock: 200n,
        networkFinalizedTimestampSeconds: 1_700_001_200n,
      }),
    /progress is invalid/
  );
});

test("versioned reconciliation request binds only the execution mode", async () => {
  const parsed = await parseInternalReconcileRequest({
    request: request(body("require-worker-run")),
  });
  assert.deepEqual(parsed, {
    legacy: false,
    mode: "require-worker-run",
  });
  const active = await parseInternalReconcileRequest({
    request: request(body("allow-exact-receipt-noop")),
  });
  assert.equal(active.mode, "allow-exact-receipt-noop");
});

test("reconciliation requests reject extra, duplicate, or malformed bodies", async () => {
  await assert.rejects(
    parseInternalReconcileRequest({
      request: request({ ...body("require-worker-run"), extra: true }),
    }),
    /shape is invalid/
  );
  await assert.rejects(
    parseInternalReconcileRequest({
      request: request(
        `{"kind":"cybergold-b2b-reconcile-request","kind":"shadow","formatVersion":1,"mode":"require-worker-run"}`
      ),
    }),
    /JSON is invalid/
  );
  await assert.rejects(
    parseInternalReconcileRequest({
      request: request(body("require-worker-run"), "text/plain"),
    }),
    /application\/json/
  );
  await assert.rejects(
    parseInternalReconcileRequest({
      request: request({
        ...body("require-worker-run"),
        legacyGatewayExpectation: "forbidden",
      }),
    }),
    /shape is invalid/
  );
});

test("empty legacy requests remain accepted", async () => {
  assert.deepEqual(
    await parseInternalReconcileRequest({
      request: new Request("http://app.internal", { method: "POST" }),
    }),
    {
      legacy: true,
      mode: "require-worker-run",
    }
  );
});

test("candidate mode always runs a worker while active mode may refresh an exact receipt", () => {
  const common = {
    compatibleReceiptCompletedAtMs: 999_999,
    nowMs: 1_000_000,
    reconcileIntervalMs: 600_000,
    leaseAmbiguous: false,
  };
  assert.equal(
    planInternalGatewayReconcile({
      ...common,
      mode: "require-worker-run",
      exactReceiptAvailable: true,
    }),
    "acquire-lease"
  );
  assert.equal(
    planInternalGatewayReconcile({
      ...common,
      mode: "allow-exact-receipt-noop",
      exactReceiptAvailable: true,
    }),
    "exact-receipt-noop"
  );
  assert.equal(
    planInternalGatewayReconcile({
      ...common,
      mode: "allow-exact-receipt-noop",
      exactReceiptAvailable: true,
      leaseAmbiguous: true,
    }),
    "reject-ambiguous"
  );
});

test("periodic cadence defers before lease without allowing a future timestamp to postpone work", () => {
  const input = {
    mode: "allow-exact-receipt-noop" as const,
    exactReceiptAvailable: false,
    nowMs: 1_000_000,
    reconcileIntervalMs: 600_000,
    leaseAmbiguous: false,
  };
  assert.equal(
    planInternalGatewayReconcile({
      ...input,
      compatibleReceiptCompletedAtMs: 400_001,
    }),
    "deferred-cadence"
  );
  for (const completedAtMs of [400_000, 400_000 - 1, 1_000_001, null]) {
    assert.equal(
      planInternalGatewayReconcile({
        ...input,
        compatibleReceiptCompletedAtMs: completedAtMs,
      }),
      "acquire-lease"
    );
  }
  assert.equal(
    planInternalGatewayReconcile({
      ...input,
      mode: "require-worker-run",
      compatibleReceiptCompletedAtMs: 999_999,
    }),
    "acquire-lease"
  );
  assert.equal(
    planInternalGatewayReconcile({
      ...input,
      exactReceiptAvailable: true,
      compatibleReceiptCompletedAtMs: 1_000_001,
    }),
    "acquire-lease"
  );
});

test("stale or hash-contradicting controller anchors fail before lease acquisition", () => {
  assert.throws(
    () =>
      assertGatewayExpectationNotStale({
        expectedAnchor: { blockNumber: 99n, blockHash: HASH as `0x${string}` },
        committedBlockNumber: 100n,
        committedBlockHash: HASH as `0x${string}`,
      }),
    /older than/
  );
  assert.throws(
    () =>
      assertGatewayExpectationNotStale({
        expectedAnchor: { blockNumber: 100n, blockHash: HASH as `0x${string}` },
        committedBlockNumber: 100n,
        committedBlockHash: `0x${"34".repeat(32)}`,
      }),
    /contradicts/
  );
  assert.doesNotThrow(() =>
    assertGatewayExpectationNotStale({
      expectedAnchor: { blockNumber: 101n, blockHash: HASH as `0x${string}` },
      committedBlockNumber: 100n,
      committedBlockHash: HASH as `0x${string}`,
    })
  );
});
