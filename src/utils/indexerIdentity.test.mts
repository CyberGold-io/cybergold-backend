import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { planIndexerIdentityTransition } from "../server/onchain-indexer/indexerIdentity.ts";

const expectedIdentity = {
  rawJournalVersion: "1",
  dashboardProjectionVersion: "14",
  stateSnapshotVersion: "1",
  governanceAddress: "0x0000000000000000000000000000000000000001",
} as const;

test("a legacy version-14 database is adopted without resetting its projection", () => {
  assert.deepEqual(
    planIndexerIdentityTransition(
      {
        rawJournalVersion: null,
        dashboardProjectionVersion: null,
        stateSnapshotVersion: null,
        legacyIndexerVersion: "14",
        dashboardProjectionGovernanceAddress: null,
        legacyGovernanceAddress: expectedIdentity.governanceAddress,
      },
      expectedIdentity
    ),
    {
      initializeRawJournalIdentity: true,
      initializeStateSnapshotIdentity: true,
      resetProjection: false,
      resetStateSnapshots: false,
      restartScanFromDeployment: false,
    }
  );
});

test("projection drift rebuilds disposable state but preserves the raw cursor", () => {
  assert.deepEqual(
    planIndexerIdentityTransition(
      {
        rawJournalVersion: "1",
        dashboardProjectionVersion: "13",
        stateSnapshotVersion: "1",
        legacyIndexerVersion: "14",
        dashboardProjectionGovernanceAddress:
          expectedIdentity.governanceAddress,
        legacyGovernanceAddress: expectedIdentity.governanceAddress,
      },
      expectedIdentity
    ),
    {
      initializeRawJournalIdentity: false,
      initializeStateSnapshotIdentity: false,
      resetProjection: true,
      resetStateSnapshots: false,
      restartScanFromDeployment: false,
    }
  );
});

test("Governance-address drift rebuilds projections and restarts scanning without deleting the journal", () => {
  assert.deepEqual(
    planIndexerIdentityTransition(
      {
        rawJournalVersion: "1",
        dashboardProjectionVersion: "14",
        stateSnapshotVersion: "1",
        legacyIndexerVersion: "14",
        dashboardProjectionGovernanceAddress: null,
        legacyGovernanceAddress: "none",
      },
      expectedIdentity
    ),
    {
      initializeRawJournalIdentity: false,
      initializeStateSnapshotIdentity: false,
      resetProjection: true,
      resetStateSnapshots: false,
      restartScanFromDeployment: true,
    }
  );
});

test("the additive Governance identity takes precedence over the retained legacy value", () => {
  assert.deepEqual(
    planIndexerIdentityTransition(
      {
        rawJournalVersion: "1",
        dashboardProjectionVersion: "14",
        stateSnapshotVersion: "1",
        legacyIndexerVersion: "14",
        dashboardProjectionGovernanceAddress:
          expectedIdentity.governanceAddress,
        legacyGovernanceAddress: "none",
      },
      expectedIdentity
    ),
    {
      initializeRawJournalIdentity: false,
      initializeStateSnapshotIdentity: false,
      resetProjection: false,
      resetStateSnapshots: false,
      restartScanFromDeployment: false,
    }
  );
});

test("state-snapshot drift clears only replaceable snapshots", () => {
  assert.deepEqual(
    planIndexerIdentityTransition(
      {
        rawJournalVersion: "1",
        dashboardProjectionVersion: "14",
        stateSnapshotVersion: "0",
        legacyIndexerVersion: "14",
        dashboardProjectionGovernanceAddress:
          expectedIdentity.governanceAddress,
        legacyGovernanceAddress: expectedIdentity.governanceAddress,
      },
      expectedIdentity
    ),
    {
      initializeRawJournalIdentity: false,
      initializeStateSnapshotIdentity: false,
      resetProjection: false,
      resetStateSnapshots: true,
      restartScanFromDeployment: false,
    }
  );
});

test("unknown raw-journal versions fail closed", () => {
  assert.throws(
    () =>
      planIndexerIdentityTransition(
        {
          rawJournalVersion: "2",
          dashboardProjectionVersion: "14",
          stateSnapshotVersion: "1",
          legacyIndexerVersion: "14",
          dashboardProjectionGovernanceAddress:
            expectedIdentity.governanceAddress,
          legacyGovernanceAddress: expectedIdentity.governanceAddress,
        },
        expectedIdentity
      ),
    /Raw journal version 2 is incompatible with 1/
  );
});

test("the compatibility transition cannot delete raw logs and keeps legacy rollback identity", () => {
  const indexer = readFileSync(
    new URL("../server/onchain-indexer/indexer.ts", import.meta.url),
    "utf8"
  );
  const transition = indexer.slice(
    indexer.indexOf("async function ensureIndexerVersion"),
    indexer.indexOf("async function persistLogs")
  );

  assert.match(transition, /return withTransaction/);
  assert.match(transition, /planIndexerIdentityTransition/);
  assert.match(transition, /INDEXER_STATE_KEY_RAW_JOURNAL_VERSION/);
  assert.match(transition, /INDEXER_STATE_KEY_DASHBOARD_PROJECTION_VERSION/);
  assert.match(transition, /INDEXER_STATE_KEY_STATE_SNAPSHOT_VERSION/);
  assert.match(transition, /LEGACY_INDEXER_VERSION/);
  assert.match(transition, /clearHolderCache\(config, transactionQuery\)/);
  assert.match(
    transition,
    /transition\.resetStateSnapshots[\s\S]*clearReadModelSnapshots\(config, transactionQuery\)/
  );
  assert.match(
    transition,
    /transition\.restartScanFromDeployment[\s\S]*deleteProjectedLogsForAddress\([\s\S]*storedProjectionGovernanceAddress/
  );
  assert.doesNotMatch(transition, /deleteLogsFromBlock/);
  assert.doesNotMatch(transition, /DELETE FROM onchain_event_logs/);
  assert.doesNotMatch(transition, /onchain_raw_logs/);
});

test("Safe cursor incompatibility fails before reorg deletion", () => {
  const safeIndexer = readFileSync(
    new URL("../server/safe-events/indexer.ts", import.meta.url),
    "utf8"
  );
  const reconcileStart = safeIndexer.indexOf(
    "async function reconcileSafeExecutionEvents"
  );
  const ensurePosition = safeIndexer.indexOf(
    "await ensureSafeCursorVersion",
    reconcileStart
  );
  const deletionPosition = safeIndexer.indexOf(
    "await deleteIndexedSafeExecutionLogs",
    reconcileStart
  );

  assert.ok(reconcileStart >= 0);
  assert.ok(ensurePosition > reconcileStart);
  assert.ok(deletionPosition > ensurePosition);
  assert.match(safeIndexer, /snapshotIdentity\.safeCursorVersion/);
  assert.match(safeIndexer, /Safe cursor version .* is incompatible/);
});
