/** Run only against the disposable Compose database; see the Ops profile README. */
import assert from "node:assert/strict";
import { fork } from "node:child_process";
import { once } from "node:events";
import { ensureSchema, query, withSharedAdvisoryLock } from "../../src/server/onchain-indexer/db";

const editor = "0x00000000000000000000000000000000000000a1";
const owner = "0x00000000000000000000000000000000000000b2";
const lockKey = `onchain-indexer:31337:${editor}`;

async function inspect() {
  await ensureSchema();
  const alias = await query("SELECT alias FROM governance_owner_aliases WHERE editor_address=$1 AND owner_address=$2", [editor, owner]);
  assert.equal(alias.rows[0]?.alias, "Split continuity fixture");
  await assert.rejects(query("INSERT INTO governance_owner_alias_auth_nonces (editor_address,nonce) VALUES ($1,$2)", [editor, "split-consumed-nonce"]),
    (error: unknown) => (error as { code?: string }).code === "23505");
  const cursor = await query("SELECT state_value FROM onchain_sync_state WHERE chain_id=31337 AND contract_address=$1 AND state_key='last_scanned_block'", [editor]);
  assert.equal(cursor.rows[0]?.state_value, "12345");
  const snapshots = await query("SELECT payload FROM onchain_read_model_snapshots WHERE chain_id=31337 AND contract_address=$1 AND model_key='split-continuity'", [editor]);
  assert.deepEqual(snapshots.rows[0]?.payload, { block: "12345", version: "preserved" });
}

async function main() {
  if (process.argv[2] === "hold") {
    await withSharedAdvisoryLock(lockKey, async () => {
      process.send?.("locked");
      await once(process, "message");
    });
    return;
  }
  if (process.argv[2] === "inspect") return inspect();
  await ensureSchema();
  await query("INSERT INTO governance_owner_aliases (editor_address,owner_address,alias) VALUES ($1,$2,'Split continuity fixture') ON CONFLICT DO NOTHING", [editor, owner]);
  await query("INSERT INTO governance_owner_alias_auth_nonces (editor_address,nonce) VALUES ($1,'split-consumed-nonce') ON CONFLICT DO NOTHING", [editor]);
  await query("INSERT INTO onchain_sync_state (chain_id,contract_address,state_key,state_value) VALUES (31337,$1,'last_scanned_block','12345') ON CONFLICT DO NOTHING", [editor]);
  await query("INSERT INTO onchain_read_model_snapshots (chain_id,contract_address,model_key,block_number,payload) VALUES (31337,$1,'split-continuity',12345,$2::jsonb) ON CONFLICT DO NOTHING", [editor, JSON.stringify({ block: "12345", version: "preserved" })]);

  const holder = fork(__filename, ["hold"], { stdio: ["ignore", "inherit", "inherit", "ipc"] });
  try {
    assert.deepEqual(await once(holder, "message"), ["locked", undefined]);
    let ran = false;
    const competing = await withSharedAdvisoryLock(lockKey, async () => { ran = true; });
    assert.deepEqual(competing, { acquired: false });
    assert.equal(ran, false);
    const exited = once(holder, "exit");
    holder.send("release");
    assert.deepEqual(await exited, [0, null]);
    assert.deepEqual(await withSharedAdvisoryLock(lockKey, async () => "resumed"), { acquired: true, result: "resumed" });
  } finally {
    if (holder.exitCode === null) holder.kill();
  }
  // Independent processes reinitialize schema like restarted API/worker roles.
  for (let i = 0; i < 2; i++) {
    const reader = fork(__filename, ["inspect"], { stdio: ["ignore", "inherit", "inherit", "ipc"] });
    assert.deepEqual(await once(reader, "exit"), [0, null]);
  }
  console.log("PostgreSQL continuity passed: shared lock excludes a concurrent worker; restart releases it; aliases, consumed nonce, cursor and snapshot survive fresh processes.");
}

main().catch((error) => { console.error(error); process.exitCode = 1; }).finally(async () => {
  await globalThis.__cybergoldDashboardPgPool?.end();
  process.disconnect?.();
});
