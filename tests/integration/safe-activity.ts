/** Disposable PostgreSQL only; never use an installed product database. */
import assert from "node:assert/strict";
import { toEventHash } from "viem";
import { ensureSchema, query, withTransaction } from "../../src/server/onchain-indexer/db";
import { selectSafeActivity } from "../../src/server/safe-events/activity";

const safe = "0x0000000000000000000000000000000000000001";
const other = "0x0000000000000000000000000000000000000002";
const hash = `0x${"a".repeat(64)}`;
const payment = "0".repeat(63) + "7";
const read = (chain = 31338, addresses = [safe, other]) => withTransaction(async execute => {
  await execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY");
  return selectSafeActivity(execute, chain, addresses, 50_000n);
});
try {
  await ensureSchema();
  await query(`INSERT INTO onchain_raw_logs(chain_id,contract_address,block_number,block_hash,
      tx_hash,log_index,block_timestamp_seconds,topics,data)
    VALUES (31338,$1,100,$3,$3,0,1000,$4::jsonb,$5),
           (31338,$2,101,$3,$3,1,1001,$6::jsonb,$7)`,
    [safe, other, hash, JSON.stringify([toEventHash("ExecutionSuccess(bytes32,uint256)")]),
      hash + payment, JSON.stringify([toEventHash("ExecutionFailure(bytes32,uint256)"), hash]), "0x" + payment]);
  await query(`INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
    VALUES (31338,$1,'raw_log_start_block','90'),(31338,$1,'raw_log_last_scanned_block','60000'),
      (31338,$1,'safe_execution_last_scanned_block','60000')`, [safe]);
  const initial = await read();
  assert.deepEqual(initial.events.map(event => event.eventName), ["ExecutionFailure", "ExecutionSuccess"]);
  assert.equal(initial.events[1].paymentWei, "7");
  assert.equal(initial.coverage[0].journalStartBlock, "90");
  assert.equal(initial.coverage[0].projectionIndexedThroughBlock, "60000");
  assert.equal(initial.coverage[1].journalStartBlock, null);
  assert.equal(initial.projectionLookbackBlocks, "50000");
  assert.equal(initial.events[1].blockNumber, "100", "older retained execution is visible before the current lookback");
  assert.equal((await read(1)).events.length, 0);
  assert.equal((await read(31338, [other])).events.length, 1);
  assert.equal((await read(31338, [])).events.length, 0);
  assert.equal((await query("SELECT count(*)::int AS count FROM onchain_event_logs")).rows[0].count, 0);
  await assert.rejects(withTransaction(async execute => {
    await execute("SET TRANSACTION READ ONLY");
    await execute("DELETE FROM onchain_raw_logs");
  }), (error: { code?: string }) => error.code === "25006");
  await query(`INSERT INTO onchain_raw_logs(chain_id,contract_address,block_number,block_hash,
      tx_hash,log_index,block_timestamp_seconds,topics,data)
    SELECT 31338,$1,200+i,$2,'fixture'||i,0,1000,'[]'::jsonb,'0x'
      FROM generate_series(1,110) i`, [safe, hash]);
  const bounded = await read();
  assert.equal(bounded.events.length, 100);
  assert.equal(bounded.hasMore, true);
  assert.equal(bounded.events[0].blockNumber, "310");
  assert.equal(bounded.events.at(-1)?.blockNumber, "211");
  await query("DELETE FROM onchain_raw_logs WHERE chain_id=31338 AND block_number>=300");
  assert.equal((await read()).events[0].blockNumber, "299", "existing journal reorg deletion is immediately visible");
  assert.equal((await query("SELECT state_value FROM onchain_sync_state WHERE state_key='safe_execution_last_scanned_block'")).rows[0].state_value, "60000");
  console.log("PASS: Safe activity PostgreSQL replay, historical layouts, older history, read-only SQL, namespaces, bounded sample and reorg deletion; projection unchanged");
} finally { await globalThis.__cybergoldDashboardPgPool?.end(); }
