import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  ADDRESS_SCOPED_LOG_REQUEST_BUDGET,
  LEGACY_PER_EVENT_LOG_REQUEST_BASELINE,
  assertLegacyPerEventDefinitionCount,
  calculateAddressScopedLogRequests,
  calculateLegacyPerEventLogRequests,
  calculateRequestReductionPercent,
  calculateScheduledDailyEthGetLogs,
  createIndexerRpcRequestCounter,
  instrumentEthGetLogsAttempt,
  instrumentEthGetLogsRequest,
} from "../server/onchain-indexer/rpcRequestInstrumentation.ts";

test("a gateway worker counter records more than the former App-side attempt cap", () => {
  const counter = createIndexerRpcRequestCounter();
  for (let attempt = 0; attempt < 73; attempt += 1) {
    counter.recordGatewayRpcAttempt("eth_getBlockByNumber");
  }
  assert.equal(counter.snapshot().totalAttempts, 73);
});

test("the current one-chunk Core and Safe baseline is exactly 16 log requests", () => {
  assert.deepEqual(LEGACY_PER_EVENT_LOG_REQUEST_BASELINE, {
    coreRequestsPerChunk: 14,
    governanceRequestsPerChunk: 3,
    safeRequestsPerAddressChunk: 2,
  });
  assert.equal(
    calculateLegacyPerEventLogRequests({
      coreChunks: 1,
      safeAddressChunks: [1],
    }),
    16
  );
  assert.equal(
    calculateLegacyPerEventLogRequests({
      coreChunks: 1,
      governanceChunks: 1,
      safeAddressChunks: [1],
    }),
    19
  );
  assert.equal(
    calculateLegacyPerEventLogRequests({
      coreChunks: 2,
      governanceChunks: 3,
      safeAddressChunks: [2, 1],
    }),
    43
  );
});

test("the request counter records every attempted eth_getLogs at its source", async () => {
  const counter = createIndexerRpcRequestCounter();
  let executedRequests = 0;
  const request = async () => {
    counter.recordGatewayRpcAttempt("eth_getLogs");
    executedRequests += 1;
    return [];
  };

  for (let index = 0; index < 14; index += 1) {
    await instrumentEthGetLogsRequest(counter, "core-event", request);
  }
  for (let index = 0; index < 2; index += 1) {
    await instrumentEthGetLogsRequest(counter, "safe-event", request);
  }

  assert.equal(executedRequests, 16);
  assert.deepEqual(counter.snapshot(), {
    totalAttempts: 16,
    failedAttempts: 0,
    adaptiveRetryAttempts: 0,
    byMethod: {
      eth_call: 0,
      eth_chainId: 0,
      eth_getBlockByHash: 0,
      eth_getBlockByNumber: 0,
      eth_getCode: 0,
      eth_getLogs: 16,
    },
    ethGetLogs: {
      attempts: 16,
      plannedAttempts: 16,
      adaptiveAttempts: 0,
      failedAttempts: 0,
      addressScopedViemTransportRetries: 0,
      legacyViemTransportRetriesObserved: null,
      bySource: {
        "core-event": 14,
        "governance-event": 0,
        "safe-event": 2,
        "core-address": 0,
        "governance-address": 0,
        "safe-address": 0,
      },
      plannedBySource: {
        "core-event": 14,
        "governance-event": 0,
        "safe-event": 2,
        "core-address": 0,
        "governance-address": 0,
        "safe-address": 0,
      },
    },
  });
});

test("a rejected eth_getLogs attempt is still counted", async () => {
  const counter = createIndexerRpcRequestCounter();
  await assert.rejects(
    instrumentEthGetLogsRequest(counter, "governance-event", async () => {
      counter.recordGatewayRpcAttempt("eth_getLogs");
      counter.recordGatewayRpcFailure();
      throw new Error("provider capacity");
    }),
    /provider capacity/
  );
  assert.deepEqual(counter.snapshot(), {
    totalAttempts: 1,
    failedAttempts: 1,
    adaptiveRetryAttempts: 0,
    byMethod: {
      eth_call: 0,
      eth_chainId: 0,
      eth_getBlockByHash: 0,
      eth_getBlockByNumber: 0,
      eth_getCode: 0,
      eth_getLogs: 1,
    },
    ethGetLogs: {
      attempts: 1,
      plannedAttempts: 1,
      adaptiveAttempts: 0,
      failedAttempts: 1,
      addressScopedViemTransportRetries: 0,
      legacyViemTransportRetriesObserved: null,
      bySource: {
        "core-event": 0,
        "governance-event": 1,
        "safe-event": 0,
        "core-address": 0,
        "governance-address": 0,
        "safe-address": 0,
      },
      plannedBySource: {
        "core-event": 0,
        "governance-event": 1,
        "safe-event": 0,
        "core-address": 0,
        "governance-address": 0,
        "safe-address": 0,
      },
    },
  });
});

test("address-scoped ingestion reduces one Core and one Safe chunk from 16 requests to 2", async () => {
  assert.deepEqual(ADDRESS_SCOPED_LOG_REQUEST_BUDGET, {
    coreRequestsPerChunk: 1,
    governanceRequestsPerChunk: 1,
    safeRequestsPerAddressChunk: 1,
  });
  assert.equal(
    calculateAddressScopedLogRequests({
      coreChunks: 1,
      safeAddressChunks: [1],
    }),
    2
  );
  assert.equal(
    calculateAddressScopedLogRequests({
      coreChunks: 1,
      governanceChunks: 1,
      safeAddressChunks: [1],
    }),
    3
  );

  const counter = createIndexerRpcRequestCounter();
  const request = async () => {
    counter.recordGatewayRpcAttempt("eth_getLogs");
    return [];
  };
  await instrumentEthGetLogsRequest(counter, "core-address", request);
  await instrumentEthGetLogsRequest(counter, "safe-address", request);
  assert.deepEqual(counter.snapshot(), {
    totalAttempts: 2,
    failedAttempts: 0,
    adaptiveRetryAttempts: 0,
    byMethod: {
      eth_call: 0,
      eth_chainId: 0,
      eth_getBlockByHash: 0,
      eth_getBlockByNumber: 0,
      eth_getCode: 0,
      eth_getLogs: 2,
    },
    ethGetLogs: {
      attempts: 2,
      plannedAttempts: 2,
      adaptiveAttempts: 0,
      failedAttempts: 0,
      addressScopedViemTransportRetries: 0,
      legacyViemTransportRetriesObserved: null,
      bySource: {
        "core-event": 0,
        "governance-event": 0,
        "safe-event": 0,
        "core-address": 1,
        "governance-address": 0,
        "safe-address": 1,
      },
      plannedBySource: {
        "core-event": 0,
        "governance-event": 0,
        "safe-event": 0,
        "core-address": 1,
        "governance-address": 0,
        "safe-address": 1,
      },
    },
  });
});

test("adaptive retries are reported separately from the planned base call", async () => {
  const counter = createIndexerRpcRequestCounter();
  counter.recordEthGetLogsPlan("core-address");
  await assert.rejects(
    instrumentEthGetLogsAttempt(counter, "core-address", false, async () => {
      counter.recordGatewayRpcAttempt("eth_getLogs");
      counter.recordGatewayRpcFailure();
      throw new Error("capacity");
    }),
    /capacity/
  );
  await instrumentEthGetLogsAttempt(
    counter,
    "core-address",
    true,
    async () => {
      counter.recordGatewayRpcAttempt("eth_getLogs");
      return [];
    }
  );
  await instrumentEthGetLogsAttempt(
    counter,
    "core-address",
    true,
    async () => {
      counter.recordGatewayRpcAttempt("eth_getLogs");
      return [];
    }
  );

  assert.deepEqual(counter.snapshot(), {
    totalAttempts: 3,
    failedAttempts: 1,
    adaptiveRetryAttempts: 2,
    byMethod: {
      eth_call: 0,
      eth_chainId: 0,
      eth_getBlockByHash: 0,
      eth_getBlockByNumber: 0,
      eth_getCode: 0,
      eth_getLogs: 3,
    },
    ethGetLogs: {
      attempts: 3,
      plannedAttempts: 1,
      adaptiveAttempts: 2,
      failedAttempts: 1,
      addressScopedViemTransportRetries: 0,
      legacyViemTransportRetriesObserved: null,
      bySource: {
        "core-event": 0,
        "governance-event": 0,
        "safe-event": 0,
        "core-address": 3,
        "governance-address": 0,
        "safe-address": 0,
      },
      plannedBySource: {
        "core-event": 0,
        "governance-event": 0,
        "safe-event": 0,
        "core-address": 1,
        "governance-address": 0,
        "safe-address": 0,
      },
    },
  });
});

test("legacy definition-count guards fail when the per-event baseline drifts", () => {
  assert.doesNotThrow(() => assertLegacyPerEventDefinitionCount("core", 14));
  assert.doesNotThrow(() =>
    assertLegacyPerEventDefinitionCount("governance", 3)
  );
  assert.doesNotThrow(() => assertLegacyPerEventDefinitionCount("safe", 2));
  assert.throws(
    () => assertLegacyPerEventDefinitionCount("core", 13),
    /expected 14, received 13/
  );
  assert.throws(
    () =>
      calculateLegacyPerEventLogRequests({
        coreChunks: -1,
        safeAddressChunks: [],
      }),
    /non-negative safe integers/
  );
});

test("the live Core, Governance, and Safe request sites are instrumented", () => {
  const coreIndexer = readFileSync(
    new URL("../server/onchain-indexer/indexer.ts", import.meta.url),
    "utf8"
  );
  const safeIndexer = readFileSync(
    new URL("../server/safe-events/indexer.ts", import.meta.url),
    "utf8"
  );

  assert.match(
    coreIndexer,
    /assertLegacyPerEventDefinitionCount\("core", EVENT_DEFINITIONS\.length\)/
  );
  assert.match(
    coreIndexer,
    /assertLegacyPerEventDefinitionCount\([\s\S]*"governance",[\s\S]*RECOVERY_FUND_EVENT_DEFINITIONS\.length/
  );
  assert.match(
    coreIndexer,
    /instrumentEthGetLogsRequest\([\s\S]*"core-event",[\s\S]*client\.getLogs/
  );
  assert.match(
    coreIndexer,
    /instrumentEthGetLogsRequest\([\s\S]*"governance-event",[\s\S]*client\.getLogs/
  );
  assert.match(
    safeIndexer,
    /assertLegacyPerEventDefinitionCount\("safe", SAFE_EXECUTION_EVENTS\.length\)/
  );
  assert.match(
    safeIndexer,
    /instrumentEthGetLogsRequest\([\s\S]*"safe-event",[\s\S]*method: "eth_getLogs"/
  );
  assert.match(
    coreIndexer,
    /addressScopedRawLogsEnabled\([\s\S]*ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS/
  );
  assert.match(coreIndexer, /requestSource: "core-address"/);
  assert.match(coreIndexer, /requestSource: "governance-address"/);
  assert.match(safeIndexer, /requestSource: "safe-address"/);
});

test("the durable ten-minute gateway cadence cuts daily Core and Safe logs by at least 90 percent", () => {
  const legacyPerRun = calculateLegacyPerEventLogRequests({
    coreChunks: 1,
    safeAddressChunks: [1],
  });
  const addressScopedPerRun = calculateAddressScopedLogRequests({
    coreChunks: 1,
    safeAddressChunks: [1],
  });
  const baselineDaily = calculateScheduledDailyEthGetLogs({
    intervalMs: 30_000,
    ethGetLogsPerRun: legacyPerRun,
  });
  const deployedTimerBaselineDaily = calculateScheduledDailyEthGetLogs({
    intervalMs: 120_000,
    ethGetLogsPerRun: legacyPerRun,
  });
  const candidateDaily = calculateScheduledDailyEthGetLogs({
    intervalMs: 600_000,
    ethGetLogsPerRun: addressScopedPerRun,
  });

  assert.equal(legacyPerRun, 16);
  assert.equal(addressScopedPerRun, 2);
  assert.equal(baselineDaily, 46_080);
  assert.equal(deployedTimerBaselineDaily, 11_520);
  assert.equal(candidateDaily, 288);
  assert.ok(addressScopedPerRun <= 2);
  assert.equal(
    calculateRequestReductionPercent({
      baselineRequests: baselineDaily,
      candidateRequests: candidateDaily,
    }),
    99.375
  );

  const withGovernanceDaily = calculateScheduledDailyEthGetLogs({
    intervalMs: 600_000,
    ethGetLogsPerRun: calculateAddressScopedLogRequests({
      coreChunks: 1,
      governanceChunks: 1,
      safeAddressChunks: [1],
    }),
  });
  assert.equal(withGovernanceDaily, 432);
  assert.equal(
    calculateRequestReductionPercent({
      baselineRequests: deployedTimerBaselineDaily,
      candidateRequests: withGovernanceDaily,
    }),
    96.25
  );
  assert.ok(
    calculateRequestReductionPercent({
      baselineRequests: baselineDaily,
      candidateRequests: withGovernanceDaily,
    }) >= 90
  );
});
