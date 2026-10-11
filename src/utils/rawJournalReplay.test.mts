import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  assertRawJournalReplayCoverage,
  parseRawJournalCoverageRows,
  planRawJournalCoverageMerge,
  rawJournalProjectionReplayEnabled,
  normalizeStoredRawJournalRows,
  RAW_JOURNAL_CURSOR_VERSION_KEY,
  RAW_JOURNAL_LAST_SCANNED_BLOCK_HASH_KEY,
  RAW_JOURNAL_LAST_SCANNED_BLOCK_KEY,
  RAW_JOURNAL_START_BLOCK_KEY,
  type RawJournalCoverage,
} from "../server/onchain-indexer/rawJournalCoverage.ts";
import type { Address, Hex } from "viem";

const ADDRESS = "0x00000000000000000000000000000000000000c0" as Address;
const CURSOR_HASH = `0x${"a".repeat(64)}` as Hex;
const OTHER_HASH = `0x${"b".repeat(64)}` as Hex;
const TX_A = `0x${"1".repeat(64)}`;
const TX_B = `0x${"2".repeat(64)}`;
const TOPIC = `0x${"3".repeat(64)}`;

function coverageRows(start = "100", cursor = "120", hash = CURSOR_HASH) {
  return [
    { state_key: RAW_JOURNAL_CURSOR_VERSION_KEY, state_value: "1" },
    { state_key: RAW_JOURNAL_START_BLOCK_KEY, state_value: start },
    { state_key: RAW_JOURNAL_LAST_SCANNED_BLOCK_KEY, state_value: cursor },
    { state_key: RAW_JOURNAL_LAST_SCANNED_BLOCK_HASH_KEY, state_value: hash },
  ];
}

function coverage(): RawJournalCoverage {
  const parsed = parseRawJournalCoverageRows({
    address: ADDRESS,
    expectedVersion: "1",
    rows: coverageRows(),
  });
  assert.ok(parsed);
  return parsed;
}

test("raw replay stays separately off by default", () => {
  assert.equal(rawJournalProjectionReplayEnabled(undefined), false);
  assert.equal(rawJournalProjectionReplayEnabled("0"), false);
  assert.equal(rawJournalProjectionReplayEnabled("true"), true);
  assert.throws(() => rawJournalProjectionReplayEnabled("yes"), /must be one of/);
});

test("coverage state requires one exact canonical four-key interval", () => {
  assert.equal(
    parseRawJournalCoverageRows({
      address: ADDRESS,
      expectedVersion: "1",
      rows: [],
    }),
    null
  );
  assert.deepEqual(coverage(), {
    address: ADDRESS,
    journalVersion: "1",
    startBlock: 100n,
    cursorBlock: 120n,
    cursorBlockHash: CURSOR_HASH,
  });
  assert.throws(
    () =>
      parseRawJournalCoverageRows({
        address: ADDRESS,
        expectedVersion: "1",
        rows: coverageRows().slice(1),
      }),
    /incomplete/
  );
  assert.throws(
    () =>
      parseRawJournalCoverageRows({
        address: ADDRESS,
        expectedVersion: "2",
        rows: coverageRows(),
      }),
    /version/
  );
  assert.throws(
    () =>
      parseRawJournalCoverageRows({
        address: ADDRESS,
        expectedVersion: "1",
        rows: coverageRows("121", "120"),
      }),
    /inverted/
  );
});

test("first interval starts at recovery origin and later intervals overlap or abut without end regression", () => {
  assert.throws(
    () =>
      planRawJournalCoverageMerge({
        current: null,
        address: ADDRESS,
        journalVersion: "1",
        authoritativeStartBlock: 100n,
        fromBlock: 110n,
        toBlock: 120n,
        toBlockHash: CURSOR_HASH,
      }),
    /configured recovery start/
  );
  const initial = planRawJournalCoverageMerge({
    current: null,
    address: ADDRESS,
    journalVersion: "1",
    authoritativeStartBlock: 100n,
    fromBlock: 100n,
    toBlock: 120n,
    toBlockHash: CURSOR_HASH,
  });
  const containedOverlap = planRawJournalCoverageMerge({
    current: initial,
    address: ADDRESS,
    journalVersion: "1",
    authoritativeStartBlock: 100n,
    fromBlock: 105n,
    toBlock: 110n,
    toBlockHash: OTHER_HASH,
  });
  assert.equal(containedOverlap.cursorBlock, 120n);
  assert.equal(containedOverlap.cursorBlockHash, CURSOR_HASH);

  const extended = planRawJournalCoverageMerge({
    current: initial,
    address: ADDRESS,
    journalVersion: "1",
    authoritativeStartBlock: 100n,
    fromBlock: 121n,
    toBlock: 130n,
    toBlockHash: OTHER_HASH,
  });
  assert.equal(extended.cursorBlock, 130n);
  assert.equal(extended.cursorBlockHash, OTHER_HASH);
  assert.throws(
    () =>
      planRawJournalCoverageMerge({
        current: initial,
        address: ADDRESS,
        journalVersion: "1",
        authoritativeStartBlock: 100n,
        fromBlock: 122n,
        toBlock: 130n,
        toBlockHash: OTHER_HASH,
      }),
    /coverage gap/
  );
});

test("restored coverage fails closed on start, cursor, or canonical-hash mismatch", () => {
  assert.equal(
    assertRawJournalReplayCoverage({
      coverage: coverage(),
      requiredStartBlock: 100n,
      maximumBlock: 120n,
      canonicalCursorHash: CURSOR_HASH,
    }).cursorBlock,
    120n
  );
  for (const input of [
    {
      coverage: { ...coverage(), startBlock: 101n },
      requiredStartBlock: 100n,
      maximumBlock: 120n,
      canonicalCursorHash: CURSOR_HASH,
    },
    {
      coverage: { ...coverage(), cursorBlock: 121n },
      requiredStartBlock: 100n,
      maximumBlock: 120n,
      canonicalCursorHash: CURSOR_HASH,
    },
    {
      coverage: coverage(),
      requiredStartBlock: 100n,
      maximumBlock: 120n,
      canonicalCursorHash: OTHER_HASH,
    },
  ]) {
    assert.throws(() => assertRawJournalReplayCoverage(input), /coverage/);
  }
});

test("a contiguous provider-verified prefix backfill restores authoritative coverage", () => {
  const incomplete = parseRawJournalCoverageRows({
    address: ADDRESS,
    expectedVersion: "1",
    rows: coverageRows("20", "30"),
  });
  assert.ok(incomplete);
  const repaired = planRawJournalCoverageMerge({
    current: incomplete,
    address: ADDRESS,
    journalVersion: "1",
    authoritativeStartBlock: 10n,
    fromBlock: 10n,
    toBlock: 19n,
    toBlockHash: OTHER_HASH,
  });
  assert.equal(repaired.startBlock, 10n);
  assert.equal(repaired.cursorBlock, 30n);
  assert.equal(repaired.cursorBlockHash, CURSOR_HASH);
  assert.throws(
    () =>
      planRawJournalCoverageMerge({
        current: incomplete,
        address: ADDRESS,
        journalVersion: "1",
        authoritativeStartBlock: 10n,
        fromBlock: 11n,
        toBlock: 19n,
        toBlockHash: OTHER_HASH,
      }),
    /non-authoritative; reset its coverage metadata before provider backfill/
  );
});

test("a contiguous provider-verified forward bridge reaches the current recovery boundary", () => {
  const olderCoverage = parseRawJournalCoverageRows({
    address: ADDRESS,
    expectedVersion: "1",
    rows: coverageRows("10", "30"),
  });
  assert.ok(olderCoverage);
  const bridged = planRawJournalCoverageMerge({
    current: olderCoverage,
    address: ADDRESS,
    journalVersion: "1",
    authoritativeStartBlock: 100n,
    fromBlock: 31n,
    toBlock: 99n,
    toBlockHash: OTHER_HASH,
  });
  assert.equal(bridged.startBlock, 10n);
  assert.equal(bridged.cursorBlock, 99n);
  assert.equal(bridged.cursorBlockHash, OTHER_HASH);
  assert.throws(
    () =>
      planRawJournalCoverageMerge({
        current: olderCoverage,
        address: ADDRESS,
        journalVersion: "1",
        authoritativeStartBlock: 100n,
        fromBlock: 32n,
        toBlock: 99n,
        toBlockHash: OTHER_HASH,
      }),
    /coverage gap/
  );
});

test("bounded replay preserves unknown logs and uses canonical block/log-index order", () => {
  const journalSource = readFileSync(
    new URL("../server/onchain-indexer/rawLogJournal.ts", import.meta.url),
    "utf8"
  );
  assert.match(
    journalSource,
    /ORDER BY block_number ASC, log_index ASC, tx_hash ASC/
  );
  const rows = [
    {
      contract_address: ADDRESS,
      block_number: "110",
      block_hash: OTHER_HASH,
      tx_hash: TX_B,
      log_index: 1,
      topics: [TOPIC],
      data: "0x1234",
      block_timestamp_seconds: "1700000000",
    },
    {
      contract_address: ADDRESS,
      block_number: "110",
      block_hash: OTHER_HASH,
      tx_hash: TX_A,
      log_index: 2,
      topics: [],
      data: "0x",
      block_timestamp_seconds: "1700000000",
    },
  ];
  const logs = normalizeStoredRawJournalRows({
    rows,
    address: ADDRESS,
    fromBlock: 100n,
    toBlock: 119n,
    coverage: coverage(),
  });
  assert.equal(logs.length, 2);
  assert.deepEqual(logs[0].topics, [TOPIC]);
  assert.deepEqual(logs[1].topics, []);

  assert.throws(
    () => normalizeStoredRawJournalRows({
      rows: [...rows].reverse(),
      address: ADDRESS,
      fromBlock: 100n,
      toBlock: 119n,
      coverage: coverage(),
    }),
    /uniquely ordered/
  );
});
