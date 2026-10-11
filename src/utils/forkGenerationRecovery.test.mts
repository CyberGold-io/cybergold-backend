import assert from "node:assert/strict";
import test from "node:test";

import {
  applySandboxForkGeneration,
  markSandboxForkGenerationReady,
  prepareSandboxForkGeneration,
  readSandboxForkGeneration,
} from "../server/onchain-indexer/forkGenerationRecovery.ts";
import type { TransactionQuery } from "../server/onchain-indexer/db.ts";

const core = `0x${"a".repeat(40)}`;
const safe = `0x${"b".repeat(40)}`;
const old = {
  generation: "93a43d60-117e-4a58-b036-619b1ca03747",
  forkBlock: 1000n,
  forkBlockHash: `0x${"1".repeat(64)}`,
};
const next = {
  generation: "02c38061-3cdc-4fa0-8e65-838016c8e2e3",
  forkBlock: 1200n,
  forkBlockHash: `0x${"2".repeat(64)}`,
};

function database() {
  const state = new Map<string, string>();
  const operations: Array<{ sql: string; params: unknown[] }> = [];
  const key = (chain: string, address: string, name: string) => `${chain}/${address}/${name}`;
  const put = (chain: string, address: string, name: string, value: string) =>
    state.set(key(chain, address, name), value);
  const get = (chain: string, address: string, name: string) =>
    state.get(key(chain, address, name));
  const execute = (async (sql: string, params: unknown[] = []) => {
    operations.push({ sql, params });
    if (sql.includes("SELECT state_key, state_value FROM onchain_sync_state") && params.length === 2) {
      const [chain, names] = params as [string, string[]];
      return { rows: [...state].flatMap(([identity, value]) => {
        const [rowChain, , name] = identity.split("/");
        return rowChain === chain && names.includes(name)
          ? [{ state_key: name, state_value: value }]
          : [];
      }) };
    }
    if (sql.includes("SELECT state_key, state_value FROM onchain_sync_state")) {
      const [chain, address, names] = params as [string, string, string[]];
      return { rows: names.flatMap((name) => {
        const value = get(chain, address, name);
        return value === undefined ? [] : [{ state_key: name, state_value: value }];
      }) };
    }
    if (sql.includes("SELECT contract_address, state_key, state_value")) {
      const [chain, names] = params as [string, string[]];
      return { rows: [...state].flatMap(([identity, value]) => {
        const [rowChain, address, name] = identity.split("/");
        return rowChain === chain && names.includes(name)
          ? [{ contract_address: address, state_key: name, state_value: value }]
          : [];
      }) };
    }
    if (sql.includes("INSERT INTO onchain_sync_state")) {
      const [chain, address, name, value] = params as string[];
      put(chain, address, name, value);
    } else if (sql.includes("UPDATE onchain_sync_state")) {
      const [chain, address, name, value] = params as string[];
      put(chain, address, name, value);
    } else if (sql.includes("DELETE FROM onchain_sync_state")) {
      const [chain, names] = params as [string, string[]];
      for (const identity of state.keys()) {
        const [rowChain, , name] = identity.split("/");
        if (rowChain === chain && names.includes(name)) state.delete(identity);
      }
    }
    return { rows: [] };
  }) as TransactionQuery;
  return { execute, operations, put, get };
}

test("a matching prefix with pre-fork projections preserves their balances", async () => {
  const db = database();
  db.put("31338", core, "last_scanned_block", "900");
  db.put("31338", core, "finalized_projection_block_hash", `0x${"3".repeat(64)}`);
  db.put("31338", safe, "safe_execution_last_scanned_block", "890");
  db.put("31338", safe, "safe_execution_last_scanned_block_hash", `0x${"4".repeat(64)}`);
  db.put("1", core, "last_scanned_block", "9999");
  await prepareSandboxForkGeneration({ execute: db.execute, coreAddress: core, current: old });
  const applied = await applySandboxForkGeneration({
    execute: db.execute,
    coreAddress: core,
    previous: old,
    current: next,
    deploymentStartBlock: 100n,
    currentHashAtPreviousForkBlock: old.forkBlockHash,
  });
  assert.equal(applied.status, "applied");
  if (applied.status !== "applied") return;
  assert.equal(applied.plan.kind, "reuse-prefix");
  for (const table of ["onchain_event_logs", "onchain_raw_logs"]) {
    assert.ok(db.operations.some(({ sql, params }) =>
      sql.includes(`DELETE FROM ${table}`) &&
      params[0] === "31338" && params[1] === "1001"));
  }
  assert.equal(db.get("31338", core, "last_scanned_block"), "900");
  assert.equal(db.get("31338", safe, "safe_execution_last_scanned_block"), "890");
  assert.equal(db.get("31338", safe, "safe_execution_last_scanned_block_hash"), `0x${"4".repeat(64)}`);
  assert.ok(!db.operations.some(({ sql }) => sql.includes("DELETE FROM onchain_token_balances")));
  assert.equal(db.get("1", core, "last_scanned_block"), "9999");
  await markSandboxForkGenerationReady({ execute: db.execute, coreAddress: core, reachedBlock: 999n });
  assert.equal((await readSandboxForkGeneration(db.execute, core))?.status, "refreshing");
  await markSandboxForkGenerationReady({ execute: db.execute, coreAddress: core, reachedBlock: 1200n });
  assert.equal((await readSandboxForkGeneration(db.execute, core))?.status, "ready");
});

test("a matching chain prefix with post-fork projections replays retained raw history", async () => {
  const db = database();
  db.put("31338", core, "last_scanned_block", "1100");
  db.put("31338", core, "raw_log_start_block", "100");
  db.put("31338", core, "raw_log_last_scanned_block", "1100");
  db.put("31338", core, "recovery_share_v2_block", "1100");
  db.put("31338", safe, "safe_execution_last_scanned_block", "1090");
  await prepareSandboxForkGeneration({ execute: db.execute, coreAddress: core, current: old });
  const applied = await applySandboxForkGeneration({
    execute: db.execute,
    coreAddress: core,
    previous: old,
    current: next,
    deploymentStartBlock: 100n,
    currentHashAtPreviousForkBlock: old.forkBlockHash,
  });
  assert.equal(applied.status, "applied");
  if (applied.status !== "applied") return;
  assert.equal(applied.plan.kind, "replay-prefix");
  assert.equal(db.get("31338", core, "last_scanned_block"), undefined);
  assert.equal(db.get("31338", safe, "safe_execution_last_scanned_block"), undefined);
  assert.equal(db.get("31338", core, "raw_log_start_block"), "100");
  assert.equal(db.get("31338", core, "raw_log_last_scanned_block"), "1000");
  assert.equal(db.get("31338", core, "recovery_share_v2_block"), undefined);
  assert.ok(db.operations.some(({ sql, params }) =>
    sql.includes("DELETE FROM onchain_event_logs") && params[1] === "100"));
  assert.ok(db.operations.some(({ sql, params }) =>
    sql.includes("DELETE FROM onchain_raw_logs") && params[1] === "1001"));
  assert.ok(db.operations.some(({ sql }) => sql.includes("DELETE FROM onchain_token_balances")));
});

test("a divergent prefix clears cursors and raw coverage for full replay", async () => {
  const db = database();
  db.put("31338", core, "last_scanned_block", "1100");
  db.put("31338", core, "raw_log_journal_version", "v1");
  db.put("31338", core, "raw_log_start_block", "100");
  db.put("31338", core, "raw_log_last_scanned_block", "1100");
  db.put("31338", core, "raw_log_last_scanned_block_hash", `0x${"3".repeat(64)}`);
  await prepareSandboxForkGeneration({ execute: db.execute, coreAddress: core, current: old });
  const applied = await applySandboxForkGeneration({
    execute: db.execute,
    coreAddress: core,
    previous: old,
    current: next,
    deploymentStartBlock: 100n,
    currentHashAtPreviousForkBlock: `0x${"f".repeat(64)}`,
  });
  assert.equal(applied.status, "applied");
  if (applied.status !== "applied") return;
  assert.equal(applied.plan.kind, "full-replay");
  assert.equal(db.get("31338", core, "last_scanned_block"), undefined);
  assert.equal(db.get("31338", core, "raw_log_journal_version"), undefined);
  assert.equal(db.get("31338", core, "raw_log_start_block"), undefined);
  assert.ok(db.operations.some(({ sql, params }) =>
    sql.includes("DELETE FROM onchain_event_logs") && params[1] === "100"));
});
