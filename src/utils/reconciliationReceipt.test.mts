import assert from "node:assert/strict";
import test from "node:test";
import type { Address, Hex } from "viem";

import {
  createReconciliationReceipt,
  parseReconciliationReceipt,
} from "../server/onchain-indexer/reconciliationReceipt.ts";
import { createIndexerRpcRequestCounter } from "../server/onchain-indexer/rpcRequestInstrumentation.ts";

const HASH = `0x${"34".repeat(32)}` as Hex;
const CORE = "0x0000000000000000000000000000000000000011" as Address;
const SAFE = "0x0000000000000000000000000000000000000022" as Address;

function validReceipt() {
  const counter = createIndexerRpcRequestCounter();
  counter.recordEthGetLogsPlan("core-address");
  counter.recordEthGetLogsAttempt("core-address", false);
  counter.recordGatewayRpcAttempt("eth_getLogs");
  counter.recordEthGetLogsPlan("safe-address");
  counter.recordEthGetLogsAttempt("safe-address", false);
  counter.recordGatewayRpcAttempt("eth_getLogs");
  return createReconciliationReceipt({
    reconciliationId: "app-reconcile-1",
    gatewayConfigRevision: "a".repeat(64),
    runtimeConfigId: `sha256:${"b".repeat(64)}`,
    finalizedAnchor: { blockNumber: 100n, blockHash: HASH },
    identities: {
      databaseSchemaVersion: "12",
      rawJournalVersion: "1",
      dashboardProjectionVersion: "14",
      stateSnapshotVersion: "1",
      safeCursorVersion: "1",
    },
    rawJournal: {
      trackedAddressCount: 2,
      logCount: "20",
      cursors: [
        { address: CORE, blockNumber: 100n, blockHash: HASH },
        { address: SAFE, blockNumber: 100n, blockHash: HASH },
      ],
    },
    dashboardProjection: {
      eventLogCount: "10",
      blockNumber: 100n,
      blockHash: HASH,
      profile: "profile-v1",
    },
    stateSnapshot: {
      modelCount: "2",
      blockNumber: 100n,
      blockHash: HASH,
      profile: "profile-v1",
    },
    safeCursors: {
      configuredSafeCount: 1,
      eventLogCount: "3",
      cursors: [{ address: SAFE, blockNumber: 100n, blockHash: HASH }],
    },
    rpcRequests: counter.snapshot(),
    completedAtMs: Date.parse("2026-08-14T12:00:00.000Z"),
    durationMs: 321,
  });
}

test("receipt binds every completed cursor, identity, count, request budget, and runtime config", () => {
  const receipt = validReceipt();
  assert.equal(receipt.formatVersion, 2);
  assert.equal(receipt.partial, false);
  assert.equal(receipt.finalizedAnchor.number, "100");
  assert.equal(receipt.runtimeConfigId, `sha256:${"b".repeat(64)}`);
  assert.equal(receipt.rawJournal.cursorCount, 2);
  assert.equal(receipt.safeCursors.cursorCount, 1);
  assert.equal(receipt.rpcRequests.totalAttempts, 2);
  assert.equal(receipt.rpcRequests.byMethod.eth_getLogs, 2);
  assert.equal(receipt.rpcRequests.ethGetLogs.plannedAttempts, 2);
  assert.deepEqual(parseReconciliationReceipt(JSON.stringify(receipt)), receipt);
});

test("receipt construction rejects partial, mismatched, or malformed completion state", () => {
  const receipt = validReceipt();
  const input = JSON.parse(JSON.stringify(receipt));
  input.rawJournal.cursors[0].blockNumber = "99";
  assert.throws(
    () => parseReconciliationReceipt(JSON.stringify(input)),
    /Stored reconciliation receipt is invalid/
  );
  const extra = JSON.parse(JSON.stringify(receipt));
  extra.safeCursors.cursors[0].secretProvider = "must-not-pass";
  assert.throws(
    () => parseReconciliationReceipt(JSON.stringify(extra)),
    /Stored reconciliation receipt is invalid/
  );
  const badCounts = JSON.parse(JSON.stringify(receipt));
  badCounts.rpcRequests.ethGetLogs.bySource["core-address"] = -1;
  assert.throws(
    () => parseReconciliationReceipt(JSON.stringify(badCounts)),
    /Stored reconciliation receipt is invalid/
  );
  const mismatchedTransportTotal = JSON.parse(JSON.stringify(receipt));
  mismatchedTransportTotal.rpcRequests.totalAttempts = 3;
  assert.throws(
    () =>
      parseReconciliationReceipt(JSON.stringify(mismatchedTransportTotal)),
    /Stored reconciliation receipt is invalid/
  );
  const staleV1 = JSON.parse(JSON.stringify(receipt));
  staleV1.formatVersion = 1;
  assert.throws(
    () => parseReconciliationReceipt(JSON.stringify(staleV1)),
    /Stored reconciliation receipt is invalid/
  );
  const badRuntime = JSON.parse(JSON.stringify(receipt));
  badRuntime.runtimeConfigId = "sha256:NOT-A-DIGEST";
  assert.throws(
    () => parseReconciliationReceipt(JSON.stringify(badRuntime)),
    /Stored reconciliation receipt is invalid/
  );
});

test("pre-v3 compatibility may record a null runtimeConfigId but no arbitrary value", () => {
  const receipt = JSON.parse(JSON.stringify(validReceipt()));
  receipt.runtimeConfigId = null;
  assert.equal(
    parseReconciliationReceipt(JSON.stringify(receipt)).runtimeConfigId,
    null
  );
});
