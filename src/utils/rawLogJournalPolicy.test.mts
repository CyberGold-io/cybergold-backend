import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath: string) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

test("the raw journal migration is additive and preserves complete log evidence", () => {
  const db = read("../server/onchain-indexer/db.ts");
  const identity = JSON.parse(
    read("../server/onchain-indexer/snapshot-identity.json")
  ) as {
    databaseSchemaVersion: string;
    dashboardIndexerVersion: string;
    rawJournalTables: string[];
  };

  assert.match(db, /CREATE TABLE IF NOT EXISTS onchain_raw_logs/);
  for (const field of [
    "chain_id BIGINT NOT NULL",
    "contract_address TEXT NOT NULL",
    "block_number BIGINT NOT NULL",
    "block_hash TEXT NOT NULL",
    "tx_hash TEXT NOT NULL",
    "log_index INTEGER NOT NULL",
    "topics JSONB NOT NULL",
    "data TEXT NOT NULL",
    "block_timestamp_seconds BIGINT NOT NULL",
  ]) {
    assert.ok(db.includes(field), `missing raw journal field: ${field}`);
  }
  assert.match(
    db,
    /PRIMARY KEY \(chain_id, contract_address, tx_hash, log_index\)/
  );
  assert.deepEqual(identity.rawJournalTables, ["onchain_raw_logs"]);
  assert.equal(identity.databaseSchemaVersion, "12");
  assert.equal(identity.dashboardIndexerVersion, "15");
});

test("range replacement and cursor advancement are one block-hash-aware transaction", () => {
  const journal = read("../server/onchain-indexer/rawLogJournal.ts");
  const coverage = read("../server/onchain-indexer/rawJournalCoverage.ts");

  assert.match(journal, /await withTransaction\(async \(transactionQuery\) =>/);
  assert.match(journal, /DELETE FROM onchain_raw_logs/);
  assert.match(
    journal,
    /ON CONFLICT \(chain_id, contract_address, tx_hash, log_index\)/
  );
  assert.match(
    journal,
    /onchain_raw_logs\.block_hash IS DISTINCT FROM EXCLUDED\.block_hash/
  );
  assert.match(coverage, /raw_log_journal_version/);
  assert.match(coverage, /raw_log_start_block/);
  assert.match(coverage, /raw_log_last_scanned_block/);
  assert.match(coverage, /raw_log_last_scanned_block_hash/);
  assert.match(
    journal,
    /executeAdaptiveBlockRanges[\s\S]*normalizeAddressScopedRpcLogs[\s\S]*replaceRawJournalRange/
  );
  assert.match(journal, /fromBlock: range\.fromBlock/);
  assert.match(journal, /toBlock: range\.toBlock/);
  assert.match(journal, /recordEthGetLogsPlan/);
  assert.match(journal, /instrumentEthGetLogsAttempt/);
  assert.match(journal, /duplicate raw log identity/);
});

test("legacy deletion and identity paths cannot target the additive raw journal", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const legacyDelete = indexer.slice(
    indexer.indexOf("async function deleteLogsFromBlock"),
    indexer.indexOf("async function deleteReadModelSnapshotsFromBlock")
  );
  const identityTransition = indexer.slice(
    indexer.indexOf("async function ensureIndexerVersion"),
    indexer.indexOf("async function persistLogs")
  );

  assert.match(legacyDelete, /DELETE FROM onchain_event_logs/);
  assert.doesNotMatch(legacyDelete, /onchain_raw_logs/);
  assert.doesNotMatch(identityTransition, /onchain_raw_logs/);
  assert.doesNotMatch(identityTransition, /deleteLogsFromBlock/);
  assert.match(
    identityTransition,
    /if \(!storedValues\.has\(INDEXER_STATE_KEY_GOVERNANCE_ADDRESS\)\)/
  );
  assert.match(
    identityTransition,
    /INDEXER_STATE_KEY_DASHBOARD_PROJECTION_GOVERNANCE_ADDRESS/
  );
  assert.match(
    identityTransition,
    /deleteProjectedLogsForAddress\([\s\S]*storedProjectionGovernanceAddress/
  );
});

test("the flagged path fetches once per address and decodes locally", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const safeIndexer = read("../server/safe-events/indexer.ts");

  assert.match(indexer, /requestSource: "core-address"/);
  assert.match(indexer, /requestSource: "governance-address"/);
  assert.match(indexer, /decodeCoreRawLog\(log\)/);
  assert.match(indexer, /decodeGovernanceRawLog\(log\)/);
  assert.match(safeIndexer, /requestSource: "safe-address"/);
  assert.match(
    safeIndexer,
    /SAFE_EXECUTION_EVENTS\.find\([\s\S]*log\.topics\[0\]/
  );
  assert.match(
    indexer,
    /addressScopedRawLogsEnabled\([\s\S]*ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS/
  );
  assert.match(
    indexer,
    /retryCount: ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT/
  );
  assert.match(
    safeIndexer,
    /retryCount: ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT/
  );
  assert.match(
    indexer,
    /requestLogs: \(range\)[\s\S]*fromBlock: toHex\(range\.fromBlock\)[\s\S]*toBlock: toHex\(range\.toBlock\)/
  );
  assert.match(
    safeIndexer,
    /requestLogs: \(range\)[\s\S]*fromBlock: toHex\(range\.fromBlock\)[\s\S]*toBlock: toHex\(range\.toBlock\)/
  );
});

test("raw fetch and decode complete before legacy projection or Safe mutation", () => {
  const indexer = read("../server/onchain-indexer/indexer.ts");
  const safeIndexer = read("../server/safe-events/indexer.ts");
  const reconcileStart = indexer.indexOf("async function reconcileInternal");
  const corePreparation = indexer.indexOf(
    "await collectAddressScopedRawChunk",
    reconcileStart
  );
  const coreDelete = indexer.indexOf(
    "await deleteLogsFromBlock(config, fromBlock)",
    reconcileStart
  );
  const coreCursorAdvance = indexer.indexOf(
    "await setLastScannedBlock(config, chunkEnd)",
    reconcileStart
  );
  assert.ok(corePreparation > reconcileStart);
  assert.ok(coreDelete > corePreparation);
  assert.ok(coreCursorAdvance > coreDelete);

  const safeReconcileStart = safeIndexer.indexOf(
    "async function reconcileSafeExecutionEvents"
  );
  const safeRawFetch = safeIndexer.indexOf(
    "await ingestRawRange",
    safeReconcileStart
  );
  const safeDelete = safeIndexer.indexOf(
    "await deleteIndexedSafeExecutionLogs",
    safeReconcileStart
  );
  const safeCursorAdvance = safeIndexer.indexOf(
    "await setLastScannedSafeBlock",
    safeReconcileStart
  );
  assert.ok(safeRawFetch > safeReconcileStart);
  assert.ok(safeDelete > safeRawFetch);
  assert.ok(safeCursorAdvance > safeDelete);
  assert.match(
    safeIndexer,
    /if \(!decodedArgs\) \{[\s\S]*Failed to decode known \$\{event\.name\} Safe raw log[\s\S]*await deleteIndexedSafeExecutionLogs/
  );
  assert.match(
    safeIndexer,
    /const ingestRawRange = \(fromBlock: bigint, toBlock: bigint\) =>[\s\S]*ingestAddressScopedRawLogs/
  );
  assert.match(
    safeIndexer,
    /existingCoverage\.cursorBlock \+ 1n < firstLookback[\s\S]*existingCoverage\.cursorBlock \+ 1n,[\s\S]*firstLookback - 1n/
  );
});
