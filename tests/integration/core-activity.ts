/** Disposable PostgreSQL only: DATABASE_URL selects the fixture started by the caller. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ensureSchema, query, withTransaction } from "../../src/server/onchain-indexer/db";
import { selectCoreActivity } from "../../src/server/onchain-indexer/coreActivity";

const address = "0x601da021caf3db5aa63e700d239b5935c370601d";
const receipt = JSON.parse(readFileSync(new URL("../fixtures/core-upgrade-20260928.json", import.meta.url), "utf8"));
try {
  await ensureSchema();
  for (const log of receipt.logs) {
    await query(`INSERT INTO onchain_raw_logs(chain_id,contract_address,block_number,block_hash,tx_hash,log_index,block_timestamp_seconds,topics,data)
      VALUES (1,$1,$2,$3,$4,$5,1790611200,$6::jsonb,$7)`, [address, BigInt(log.blockNumber).toString(), log.blockHash, log.transactionHash, Number(BigInt(log.logIndex)), JSON.stringify(log.topics), log.data]);
  }
  await query("INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value) VALUES (1,$1,'raw_log_start_block','25615683'),(1,$1,'raw_log_last_scanned_block','26085438')", [address]);
  const read = (chainId: number, core = address) => withTransaction(async execute => {
    await execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY");
    return selectCoreActivity(execute, chainId, core);
  });
  const activity = await read(1);
  assert.equal(activity.events.length, 6); assert.equal(activity.events[0].eventName, "CoreOptionalInitializerCoordinatorMigrated");
  assert.equal(activity.journalStartBlock, "25615683"); assert.equal(activity.indexedThroughBlock, "26085438");
  assert.equal(activity.hasMore, false);
  assert.equal((await read(31338)).events.length, 0);
  assert.equal((await read(1, "0x0000000000000000000000000000000000000001")).events.length, 0);
  // Read views must not change the dashboard's existing event table or cursor.
  assert.equal((await query("SELECT count(*)::int AS count FROM onchain_event_logs")).rows[0].count, 0);
  await query(`INSERT INTO onchain_raw_logs(chain_id,contract_address,block_number,block_hash,tx_hash,log_index,block_timestamp_seconds,topics,data)
    SELECT 31338,$1,100+i,$2,'tx'||i,0,1790611200,'[]'::jsonb,'0x' FROM generate_series(1,110) i`, [address, receipt.logs[0].blockHash]);
  const bounded = await read(31338);
  assert.equal(bounded.events.length, 100); assert.equal(bounded.hasMore, true);
  assert.equal(bounded.events[0].blockNumber, "210"); assert.equal(bounded.events.at(-1)?.blockNumber, "111");
  await query("DELETE FROM onchain_raw_logs WHERE chain_id=31338 AND block_number>=200");
  assert.equal((await read(31338)).events[0].blockNumber, "199", "reorg invalidation is reflected directly; no stale derived activity cache");
  console.log("Core activity PostgreSQL fixture passed: exact receipt, read-only SQL, namespaces, range metadata, limit, and reorg deletion.");
} finally { await globalThis.__cybergoldDashboardPgPool?.end(); }
