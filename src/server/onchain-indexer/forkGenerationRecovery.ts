import type { TransactionQuery } from "./db.ts";
import { RECOVERY_SHARE_V2_STATE_KEYS } from "./recoverySharePersistence.ts";
import {
  planForkGenerationTransition,
  type ForkGenerationAnchor,
  type ForkGenerationPlan,
} from "./forkGenerationTransition.ts";

const CHAIN_ID = "31338";
const GENERATION_KEY = "sandbox_fork_generation";
const FORK_BLOCK_KEY = "sandbox_fork_block";
const FORK_HASH_KEY = "sandbox_fork_block_hash";
const STATUS_KEY = "sandbox_fork_projection_status";
const CURSOR_PAIRS = [
  ["last_scanned_block", "finalized_projection_block_hash"],
  ["raw_log_last_scanned_block", "raw_log_last_scanned_block_hash"],
  ["safe_execution_last_scanned_block", "safe_execution_last_scanned_block_hash"],
] as const;
const PROJECTION_BLOCK_KEYS = [
  "last_scanned_block",
  "safe_execution_last_scanned_block",
];
const DERIVED_STATE_KEYS = [
  "finalized_snapshot_block",
  "finalized_snapshot_block_hash",
  "finalized_snapshot_profile",
  "committed_finalized_block",
  "committed_finalized_block_hash",
  "committed_finalized_profile",
  "committed_reconciliation_id",
  "committed_gateway_config_revision",
  "safe_committed_finalized_block",
  "safe_committed_finalized_block_hash",
  "safe_committed_finalized_profile",
  "safe_committed_reconciliation_id",
  "completed_reconciliation_receipt_v2",
  "holder_count",
  "holder_cache_ready",
  "cygld_ref_grams_fp18",
] as const;

type StoredStateRow = { state_key: string; state_value: string };
type CursorRow = {
  contract_address: string;
  state_key: string;
  state_value: string;
};

async function setState(
  execute: TransactionQuery,
  coreAddress: string,
  key: string,
  value: string
) {
  await execute(
    `INSERT INTO onchain_sync_state (chain_id, contract_address, state_key, state_value)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (chain_id, contract_address, state_key)
     DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = NOW()`,
    [CHAIN_ID, coreAddress, key, value]
  );
}

export async function readSandboxForkGeneration(
  execute: TransactionQuery,
  coreAddress: string
) {
  const rows = await execute<StoredStateRow>(
    `SELECT state_key, state_value FROM onchain_sync_state
     WHERE chain_id = $1 AND contract_address = $2
       AND state_key = ANY($3::text[])`,
    [CHAIN_ID, coreAddress, [GENERATION_KEY, FORK_BLOCK_KEY, FORK_HASH_KEY, STATUS_KEY]]
  );
  const values = new Map(rows.rows.map((row) => [row.state_key, row.state_value]));
  const generation = values.get(GENERATION_KEY);
  const forkBlock = values.get(FORK_BLOCK_KEY);
  const forkBlockHash = values.get(FORK_HASH_KEY);
  if (!generation && !forkBlock && !forkBlockHash) return null;
  if (!generation || !forkBlock || !forkBlockHash) {
    throw new Error("stored Sandbox fork anchor is incomplete");
  }
  const status = values.get(STATUS_KEY);
  if (status !== "ready" && status !== "refreshing") {
    throw new Error("stored Sandbox fork recovery status is invalid");
  }
  let number: bigint;
  try {
    number = BigInt(forkBlock);
  } catch {
    throw new Error("stored Sandbox fork block is invalid");
  }
  return {
    anchor: { generation, forkBlock: number, forkBlockHash },
    status,
  };
}

function sameAnchor(a: ForkGenerationAnchor, b: ForkGenerationAnchor) {
  return a.generation === b.generation &&
    a.forkBlock === b.forkBlock &&
    a.forkBlockHash.toLowerCase() === b.forkBlockHash.toLowerCase();
}

/** Store the current Anvil anchor before Ops restarts it. No projections change. */
export async function prepareSandboxForkGeneration(input: {
  execute: TransactionQuery;
  coreAddress: string;
  current: ForkGenerationAnchor;
}) {
  const coreAddress = input.coreAddress.toLowerCase();
  const stored = await readSandboxForkGeneration(input.execute, coreAddress);
  if (stored && !sameAnchor(stored.anchor, input.current)) {
    throw new Error("stored Sandbox fork generation differs from the live pre-restart anchor");
  }
  if (stored?.status === "refreshing") {
    throw new Error("Sandbox projection recovery is still in progress");
  }
  await setState(input.execute, coreAddress, GENERATION_KEY, input.current.generation);
  await setState(input.execute, coreAddress, FORK_BLOCK_KEY, input.current.forkBlock.toString());
  await setState(input.execute, coreAddress, FORK_HASH_KEY, input.current.forkBlockHash.toLowerCase());
  await setState(input.execute, coreAddress, STATUS_KEY, "ready");
  return { status: "prepared" as const };
}

async function rewindCursors(
  execute: TransactionQuery,
  plan: Exclude<ForkGenerationPlan, { kind: "unchanged" }>
) {
  const blockKeys = CURSOR_PAIRS.map(([block]) => block);
  const hashKeys = CURSOR_PAIRS.map(([, hash]) => hash);
  if (plan.kind === "full-replay") {
    await execute(
      `DELETE FROM onchain_sync_state
       WHERE chain_id = $1 AND state_key = ANY($2::text[])`,
      [CHAIN_ID, [...blockKeys, ...hashKeys, "raw_log_journal_version", "raw_log_start_block"]]
    );
    return;
  }
  const result = await execute<CursorRow>(
    `SELECT contract_address, state_key, state_value FROM onchain_sync_state
     WHERE chain_id = $1 AND state_key = ANY($2::text[])`,
    [CHAIN_ID, blockKeys]
  );
  for (const row of result.rows) {
    let block: bigint;
    try {
      block = BigInt(row.state_value);
    } catch {
      throw new Error(`Sandbox ${row.state_key} cursor is invalid`);
    }
    if (block <= plan.retainedThrough) continue;
    const pair = CURSOR_PAIRS.find(([key]) => key === row.state_key);
    if (!pair) throw new Error("Sandbox cursor identity is unknown");
    await execute(
      `UPDATE onchain_sync_state SET state_value = $4, updated_at = NOW()
       WHERE chain_id = $1 AND contract_address = $2 AND state_key = $3`,
      [CHAIN_ID, row.contract_address, row.state_key, plan.retainedThrough.toString()]
    );
    await setState(execute, row.contract_address, pair[1], plan.retainedBlockHash);
  }
}

async function canRetainProjections(
  execute: TransactionQuery,
  retainedThrough: bigint
) {
  const rows = await execute<{ state_key: string; state_value: string }>(
    `SELECT state_key, state_value FROM onchain_sync_state
     WHERE chain_id = $1 AND state_key = ANY($2::text[])`,
    [CHAIN_ID, PROJECTION_BLOCK_KEYS]
  );
  if (!rows.rows.some((row) => row.state_key === "last_scanned_block")) return false;
  for (const row of rows.rows) {
    let block: bigint;
    try {
      block = BigInt(row.state_value);
    } catch {
      throw new Error(`Sandbox ${row.state_key} projection cursor is invalid`);
    }
    if (block > retainedThrough) return false;
  }
  return true;
}

/** Atomically invalidate one old fork suffix while preserving non-chain data. */
export async function applySandboxForkGeneration(input: {
  execute: TransactionQuery;
  coreAddress: string;
  previous: ForkGenerationAnchor;
  current: ForkGenerationAnchor;
  deploymentStartBlock: bigint;
  currentHashAtPreviousForkBlock: string | null;
}) {
  if (input.previous.generation === input.current.generation) {
    throw new Error("Sandbox process generation did not change");
  }
  const coreAddress = input.coreAddress.toLowerCase();
  const stored = await readSandboxForkGeneration(input.execute, coreAddress);
  if (!stored) throw new Error("Sandbox fork was not prepared before restart");
  if (sameAnchor(stored.anchor, input.current)) {
    return { status: stored.status === "ready" ? "already-ready" as const : "already-applied" as const };
  }
  if (!sameAnchor(stored.anchor, input.previous) || stored.status !== "ready") {
    throw new Error("prepared Sandbox fork anchor does not match the requested transition");
  }
  let plan = planForkGenerationTransition(input);
  if (plan.kind === "unchanged") {
    throw new Error("Sandbox process generation did not change");
  }
  if (plan.kind === "reuse-prefix" &&
      !(await canRetainProjections(input.execute, plan.retainedThrough))) {
    plan = { ...plan, kind: "replay-prefix" };
  }
  await input.execute(
    `DELETE FROM onchain_event_logs WHERE chain_id = $1 AND block_number >= $2`,
    [CHAIN_ID, (plan.kind === "replay-prefix"
      ? input.deploymentStartBlock
      : plan.invalidateFrom).toString()]
  );
  await input.execute(
    `DELETE FROM onchain_raw_logs WHERE chain_id = $1 AND block_number >= $2`,
    [CHAIN_ID, plan.invalidateFrom.toString()]
  );
  const projectionReplay = plan.kind !== "reuse-prefix";
  for (const table of [
    ...(projectionReplay ? [
      "onchain_token_balances",
      "onchain_holder_balance_deltas",
      "onchain_recovery_share_balances",
      "onchain_recovery_share_balances_v2",
    ] : ["onchain_holder_balance_deltas"]),
    "onchain_read_model_snapshots",
    "quote_pool_cache",
  ]) {
    if (table === "onchain_holder_balance_deltas" && !projectionReplay) {
      await input.execute(
        `DELETE FROM onchain_holder_balance_deltas
         WHERE chain_id = $1 AND block_number >= $2`,
        [CHAIN_ID, plan.invalidateFrom.toString()]
      );
      continue;
    }
    await input.execute(`DELETE FROM ${table} WHERE chain_id = $1`, [CHAIN_ID]);
  }
  await input.execute(
    `DELETE FROM onchain_sync_state WHERE chain_id = $1 AND state_key = ANY($2::text[])`,
    [CHAIN_ID, [
      ...DERIVED_STATE_KEYS,
      ...(projectionReplay ? Object.values(RECOVERY_SHARE_V2_STATE_KEYS) : []),
    ]]
  );
  if (plan.kind === "replay-prefix") {
    await input.execute(
      `DELETE FROM onchain_sync_state
       WHERE chain_id = $1 AND state_key = ANY($2::text[])`,
      [CHAIN_ID, PROJECTION_BLOCK_KEYS.flatMap((key) => {
        const pair = CURSOR_PAIRS.find(([block]) => block === key);
        return pair ? [pair[0], pair[1]] : [key];
      })]
    );
  }
  await rewindCursors(input.execute, plan);
  await setState(input.execute, coreAddress, GENERATION_KEY, input.current.generation);
  await setState(input.execute, coreAddress, FORK_BLOCK_KEY, input.current.forkBlock.toString());
  await setState(input.execute, coreAddress, FORK_HASH_KEY, input.current.forkBlockHash.toLowerCase());
  await setState(input.execute, coreAddress, STATUS_KEY, "refreshing");
  return { status: "applied" as const, plan };
}

export async function markSandboxForkGenerationReady(input: {
  execute: TransactionQuery;
  coreAddress: string;
  reachedBlock: bigint;
}) {
  const coreAddress = input.coreAddress.toLowerCase();
  const stored = await readSandboxForkGeneration(input.execute, coreAddress);
  if (stored?.status !== "refreshing") return;
  if (input.reachedBlock < stored.anchor.forkBlock) return;
  await setState(input.execute, coreAddress, STATUS_KEY, "ready");
}
