import assert from "node:assert/strict";
import test from "node:test";
import type { Hex } from "viem";
import {
  ARCHIVE_FREE_RECONCILE_INTERVAL_MS,
  LEGACY_RECONCILE_INTERVAL_MS,
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
} from "../server/onchain-indexer/finalizedReconciliation.ts";

const HASH_A = `0x${"11".repeat(32)}` as Hex;
const HASH_B = `0x${"22".repeat(32)}` as Hex;
const anchor = { blockNumber: 1_000n, blockHash: HASH_A } as const;

test("archive-free finalized mode is explicit and defaults to a 60-second cadence", () => {
  assert.equal(archiveFreeFinalizedModeEnabled(undefined), false);
  assert.equal(archiveFreeFinalizedModeEnabled("0"), false);
  assert.equal(archiveFreeFinalizedModeEnabled("false"), false);
  assert.equal(archiveFreeFinalizedModeEnabled("1"), true);
  assert.equal(archiveFreeFinalizedModeEnabled("true"), true);
  assert.throws(() => archiveFreeFinalizedModeEnabled("yes"), /must be one of/);
  assert.equal(LEGACY_RECONCILE_INTERVAL_MS, 30_000);
  assert.equal(ARCHIVE_FREE_RECONCILE_INTERVAL_MS, 60_000);
  assert.equal(defaultReconcileIntervalMs(false), 30_000);
  assert.equal(defaultReconcileIntervalMs(true), 60_000);
});

test("only the isolated Sandbox fork uses its latest block as the reconciliation anchor", () => {
  assert.equal(reconciliationAnchorBlockTag(31338n), "latest");
  assert.equal(reconciliationAnchorBlockTag(1n), "finalized");
  assert.equal(reconciliationAnchorBlockTag(31337n), "finalized");
});

test("one finalized block number and hash form an immutable run anchor", async () => {
  let reads = 0;
  const resolved = await resolveFinalizedRunAnchor(async () => {
    reads += 1;
    return { number: anchor.blockNumber, hash: anchor.blockHash };
  });
  assert.equal(reads, 1);
  assert.deepEqual(resolved, anchor);
  assert.throws(
    () => normalizeFinalizedRunAnchor({ number: 1_000n, hash: "0x12" as Hex }),
    /incomplete or invalid/
  );
  assert.throws(
    () => normalizeFinalizedRunAnchor({ number: null, hash: HASH_A }),
    /incomplete or invalid/
  );
});

test("Ethereum mainnet archive-free mode requires an explicit deployment block", () => {
  assert.throws(
    () =>
      resolveArchiveFreeDeploymentStart({
        chainId: 1n,
        configuredStartBlock: 0n,
        anchorBlock: 1_000n,
      }),
    /configured nonzero block/
  );
  assert.equal(
    resolveArchiveFreeDeploymentStart({
      chainId: 1n,
      configuredStartBlock: 100n,
      anchorBlock: 1_000n,
    }),
    100n
  );
  assert.equal(
    resolveArchiveFreeDeploymentStart({
      chainId: 31337n,
      configuredStartBlock: 0n,
      anchorBlock: 1_000n,
    }),
    0n
  );
});

test("deep catch-up continues without overlap when the finalized cursor hash matches", () => {
  assert.deepEqual(
    planFinalizedProjectionScan({
      deploymentStartBlock: 100n,
      anchor,
      cursor: { blockNumber: 400n, blockHash: HASH_B },
      canonicalCursorHash: HASH_B,
      reorgWindow: 12n,
      forceConfigurationOverlap: false,
    }),
    { fromBlock: 401n, reason: "continue" }
  );
});

test("hash drift and a cursor beyond the captured anchor restart from safe overlap", () => {
  assert.deepEqual(
    planFinalizedProjectionScan({
      deploymentStartBlock: 100n,
      anchor,
      cursor: { blockNumber: 400n, blockHash: HASH_A },
      canonicalCursorHash: HASH_B,
      reorgWindow: 12n,
      forceConfigurationOverlap: false,
    }),
    { fromBlock: 388n, reason: "hash-mismatch-overlap" }
  );
  assert.deepEqual(
    planFinalizedProjectionScan({
      deploymentStartBlock: 100n,
      anchor,
      cursor: { blockNumber: 1_050n, blockHash: HASH_B },
      canonicalCursorHash: null,
      reorgWindow: 12n,
      forceConfigurationOverlap: false,
    }),
    { fromBlock: 988n, reason: "cursor-ahead-overlap" }
  );
});

test("an exact projected cursor yields no log scan unless configuration changed", () => {
  assert.deepEqual(
    planFinalizedProjectionScan({
      deploymentStartBlock: 100n,
      anchor,
      cursor: { blockNumber: anchor.blockNumber, blockHash: HASH_A },
      canonicalCursorHash: HASH_A,
      reorgWindow: 12n,
      forceConfigurationOverlap: false,
    }),
    { fromBlock: null, reason: "already-projected" }
  );
  assert.deepEqual(
    planFinalizedProjectionScan({
      deploymentStartBlock: 100n,
      anchor,
      cursor: { blockNumber: anchor.blockNumber, blockHash: HASH_A },
      canonicalCursorHash: HASH_A,
      reorgWindow: 12n,
      forceConfigurationOverlap: true,
    }),
    { fromBlock: 100n, reason: "configuration-overlap" }
  );
});

test("snapshot no-op identity binds anchor hash, profile, and physical snapshots", () => {
  const profile = finalizedRunProfile({
    addressScopedRawLogs: true,
    coreDeploymentStartBlock: 100n,
    safeLookbackBlocks: 50_000n,
    governanceAddress: "0x00000000000000000000000000000000000000AA",
    safeAddresses: [
      "0x00000000000000000000000000000000000000CC",
      "0x00000000000000000000000000000000000000BB",
    ],
    rawJournalVersion: "1",
    dashboardProjectionVersion: "14",
    safeCursorVersion: "1",
    coreEventSelectors: ["0xAAAA"],
    governanceEventSelectors: ["0xBBBB"],
    safeEventSelectors: ["0xCCCC"],
  });
  assert.equal(
    profile,
    '{"version":1,"addressScopedRawLogs":true,"coreDeploymentStartBlock":"100","safeLookbackBlocks":"50000","governanceAddress":"0x00000000000000000000000000000000000000aa","safeAddresses":["0x00000000000000000000000000000000000000bb","0x00000000000000000000000000000000000000cc"],"rawJournalVersion":"1","dashboardProjectionVersion":"14","safeCursorVersion":"1","coreEventSelectors":["0xaaaa"],"governanceEventSelectors":["0xbbbb"],"safeEventSelectors":["0xcccc"]}'
  );
  assert.equal(
    finalizedSnapshotMatches({
      anchor,
      expectedProfile: profile,
      snapshotBlockNumber: anchor.blockNumber,
      snapshotBlockHash: anchor.blockHash,
      snapshotProfile: profile,
      requiredSnapshotsExist: true,
    }),
    true
  );
  assert.equal(
    finalizedSnapshotMatches({
      anchor,
      expectedProfile: profile,
      snapshotBlockNumber: anchor.blockNumber,
      snapshotBlockHash: HASH_B,
      snapshotProfile: profile,
      requiredSnapshotsExist: true,
    }),
    false
  );
  assert.equal(
    finalizedSnapshotMatches({
      anchor,
      expectedProfile: profile,
      snapshotBlockNumber: anchor.blockNumber,
      snapshotBlockHash: anchor.blockHash,
      snapshotProfile: profile,
      requiredSnapshotsExist: false,
    }),
    false
  );
});

test("history-completeness profile drift forces a full configured backfill", () => {
  const base = {
    addressScopedRawLogs: true,
    coreDeploymentStartBlock: 100n,
    safeLookbackBlocks: 50_000n,
    governanceAddress: null,
    safeAddresses: [] as string[],
    rawJournalVersion: "1",
    dashboardProjectionVersion: "14",
    safeCursorVersion: "1",
    coreEventSelectors: ["0xaaaa"],
    governanceEventSelectors: [] as string[],
    safeEventSelectors: ["0xbbbb"],
  };
  assert.notEqual(
    finalizedRunProfile(base),
    finalizedRunProfile({ ...base, coreDeploymentStartBlock: 50n })
  );
  assert.notEqual(
    finalizedRunProfile(base),
    finalizedRunProfile({ ...base, safeLookbackBlocks: 100_000n })
  );
  assert.notEqual(
    finalizedRunProfile(base),
    finalizedRunProfile({ ...base, coreEventSelectors: ["0xcccc"] })
  );
  assert.deepEqual(
    planFinalizedProjectionScan({
      deploymentStartBlock: 50n,
      anchor,
      cursor: { blockNumber: anchor.blockNumber, blockHash: HASH_A },
      canonicalCursorHash: HASH_A,
      reorgWindow: 12n,
      forceConfigurationOverlap: true,
    }),
    { fromBlock: 50n, reason: "configuration-overlap" }
  );
});

test("a committed projection profile lets the second catch-up pass continue", () => {
  const deploymentStartBlock = 100n;
  const firstPass = planFinalizedProjectionScan({
    deploymentStartBlock,
    anchor,
    cursor: { blockNumber: 900n, blockHash: HASH_B },
    canonicalCursorHash: HASH_B,
    reorgWindow: 12n,
    forceConfigurationOverlap: true,
  });
  assert.deepEqual(firstPass, {
    fromBlock: deploymentStartBlock,
    reason: "configuration-overlap",
  });

  // The first pass transaction stores its new projection profile together with
  // this cursor. The next run therefore plans against force=false even though
  // the separately stored state-snapshot profile is still old or absent.
  const firstPassCursor = 299n;
  const secondPass = planFinalizedProjectionScan({
    deploymentStartBlock,
    anchor,
    cursor: { blockNumber: firstPassCursor, blockHash: HASH_B },
    canonicalCursorHash: HASH_B,
    reorgWindow: 12n,
    forceConfigurationOverlap: false,
  });
  assert.deepEqual(secondPass, { fromBlock: 300n, reason: "continue" });
});

test("lease-bound multi-pass scans resume only from the last successful committed checkpoint", () => {
  const failedWorking = {
    blockNumber: 700n,
    blockHash: HASH_A,
    profile: "profile-v1",
  };
  const firstCommittedPass = {
    blockNumber: 299n,
    blockHash: HASH_B,
    profile: "profile-v1",
  };
  assert.deepEqual(
    selectFinalizedPlanningBoundary({
      leaseBound: true,
      working: failedWorking,
      committed: firstCommittedPass,
    }),
    firstCommittedPass,
    "a failure after Core but before Safe must ignore the provisional Core cursor"
  );
  const secondPass = planFinalizedProjectionScan({
    deploymentStartBlock: 100n,
    anchor,
    cursor: selectFinalizedPlanningBoundary({
      leaseBound: true,
      working: failedWorking,
      committed: firstCommittedPass,
    }),
    canonicalCursorHash: HASH_B,
    reorgWindow: 12n,
    forceConfigurationOverlap: false,
  });
  assert.deepEqual(secondPass, { fromBlock: 300n, reason: "continue" });
  assert.deepEqual(
    selectFinalizedPlanningBoundary({
      leaseBound: true,
      working: failedWorking,
      committed: { blockNumber: null, blockHash: null, profile: null },
    }),
    { blockNumber: null, blockHash: null, profile: null }
  );
});
