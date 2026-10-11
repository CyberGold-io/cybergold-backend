import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const APP_ROOT = new URL("../../", import.meta.url);
const IDENTITY_PATH = new URL(
  "src/server/onchain-indexer/snapshot-identity.json",
  APP_ROOT
);

type SnapshotIdentity = {
  kind: string;
  formatVersion: number;
  databaseSchemaVersion: string;
  dashboardIndexerVersion: string;
  safeEventIndexerVersion: string;
  rawJournalVersion: string;
  dashboardProjectionVersion: string;
  stateSnapshotVersion: string;
  safeCursorVersion: string;
  dashboardReadModelVersion: string;
  recoveryReadModelVersion: string;
  rawJournalTables: string[];
  derivedTables: string[];
  compatibilitySources: string[];
};

const identity = JSON.parse(
  readFileSync(IDENTITY_PATH, "utf8")
) as SnapshotIdentity;

const REQUIRED_SEMANTIC_SOURCES = [
  "src/server/onchain-indexer/snapshot-identity.json",
  "package.json",
  "package-lock.json",
  "src/contracts/generated/coreDiamond.ts",
  "src/contracts/generated/governanceDiamond.ts",
  "src/server/onchain-indexer/adaptiveLogPagination.ts",
  "src/server/onchain-indexer/dashboardSnapshotRepository.ts",
  "src/server/onchain-indexer/db.ts",
  "src/server/onchain-indexer/finalizedReconciliation.ts",
  "src/server/onchain-indexer/finalizedSnapshotMulticall.ts",
  "src/server/onchain-indexer/gatewayLease.ts",
  "src/server/onchain-indexer/internalReconcileContract.ts",
  "src/server/onchain-indexer/indexer.ts",
  "src/server/onchain-indexer/indexerIdentity.ts",
  "src/server/onchain-indexer/recoveryFundSnapshot.ts",
  "src/server/onchain-indexer/recoveryPortfolioModel.ts",
  "src/server/onchain-indexer/recoveryPortfolioRepository.ts",
  "src/server/onchain-indexer/recoverySharePersistence.ts",
  "src/server/onchain-indexer/rawLogJournal.ts",
  "src/server/onchain-indexer/rawJournalCoverage.ts",
  "src/server/onchain-indexer/rawLogModel.ts",
  "src/server/onchain-indexer/reconciliationReceipt.ts",
  "src/server/onchain-indexer/rpcTransport.ts",
  "src/server/onchain-indexer/rpcRequestInstrumentation.ts",
  "src/server/safe-events/indexer.ts",
  "src/utils/recovery.ts",
  "src/utils/recoveryFund.ts",
  "src/utils/recoverySharesApi.ts",
] as const;

test("the on-chain indexer snapshot identity is explicit and complete", () => {
  assert.deepEqual(
    {
      kind: identity.kind,
      formatVersion: identity.formatVersion,
      databaseSchemaVersion: identity.databaseSchemaVersion,
      dashboardIndexerVersion: identity.dashboardIndexerVersion,
      safeEventIndexerVersion: identity.safeEventIndexerVersion,
      rawJournalVersion: identity.rawJournalVersion,
      dashboardProjectionVersion: identity.dashboardProjectionVersion,
      stateSnapshotVersion: identity.stateSnapshotVersion,
      safeCursorVersion: identity.safeCursorVersion,
      dashboardReadModelVersion: identity.dashboardReadModelVersion,
      recoveryReadModelVersion: identity.recoveryReadModelVersion,
    },
    {
      kind: "cybergold-indexer-snapshot-identity",
      formatVersion: 1,
      databaseSchemaVersion: "12",
      dashboardIndexerVersion: "15",
      safeEventIndexerVersion: "1",
      rawJournalVersion: "1",
      dashboardProjectionVersion: "15",
      stateSnapshotVersion: "2",
      safeCursorVersion: "1",
      dashboardReadModelVersion: "1",
      recoveryReadModelVersion: "2",
    }
  );

  assert.deepEqual(identity.derivedTables, [
    "onchain_event_logs",
    "onchain_sync_state",
    "onchain_token_balances",
    "onchain_holder_balance_deltas",
    "onchain_recovery_share_balances",
    "onchain_recovery_share_balances_v2",
    "onchain_read_model_snapshots",
  ]);
  assert.deepEqual(identity.rawJournalTables, ["onchain_raw_logs"]);
});

test("every compatibility source is unique, repository-relative, and present", () => {
  assert.equal(
    new Set(identity.compatibilitySources).size,
    identity.compatibilitySources.length
  );
  assert.equal(
    identity.compatibilitySources[0],
    "src/server/onchain-indexer/snapshot-identity.json"
  );

  for (const source of identity.compatibilitySources) {
    assert.ok(
      source.startsWith("src/") ||
        source === "package.json" ||
        source === "package-lock.json"
    );
    assert.ok(
      source
        .split("/")
        .every(
          (segment) =>
            segment !== "" &&
            segment !== "." &&
            segment !== ".." &&
            /^[A-Za-z0-9._-]+$/.test(segment)
        ),
      `unsafe snapshot compatibility source: ${source}`
    );
    assert.doesNotThrow(() => readFileSync(new URL(source, APP_ROOT)));
  }
});

test("the compatibility boundary includes every indexer data-semantic source", () => {
  for (const source of REQUIRED_SEMANTIC_SOURCES) {
    assert.ok(
      identity.compatibilitySources.includes(source),
      `missing snapshot compatibility source: ${source}`
    );
  }
});

test("database and split indexer identities derive from the snapshot identity", () => {
  const dbSource = readFileSync(
    new URL("src/server/onchain-indexer/db.ts", APP_ROOT),
    "utf8"
  );
  const indexerSource = readFileSync(
    new URL("src/server/onchain-indexer/indexer.ts", APP_ROOT),
    "utf8"
  );
  const safeIndexerSource = readFileSync(
    new URL("src/server/safe-events/indexer.ts", APP_ROOT),
    "utf8"
  );

  assert.match(
    dbSource,
    /const SCHEMA_VERSION = snapshotIdentity\.databaseSchemaVersion;/
  );
  assert.match(
    indexerSource,
    /const LEGACY_INDEXER_VERSION = snapshotIdentity\.dashboardIndexerVersion;/
  );
  assert.match(
    indexerSource,
    /const RAW_JOURNAL_VERSION = snapshotIdentity\.rawJournalVersion;/
  );
  assert.match(
    indexerSource,
    /const DASHBOARD_PROJECTION_VERSION = snapshotIdentity\.dashboardProjectionVersion;/
  );
  assert.match(
    indexerSource,
    /const STATE_SNAPSHOT_VERSION = snapshotIdentity\.stateSnapshotVersion;/
  );
  assert.match(
    safeIndexerSource,
    /const SAFE_CURSOR_VERSION = snapshotIdentity\.safeCursorVersion;/
  );
});
