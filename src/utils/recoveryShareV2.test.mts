import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  reconcileRecoveryShareBalancesV2,
  recoveryShareV2Enabled,
  RECOVERY_SHARE_V2_STATE_KEYS,
  type RecoveryQuery,
} from "../server/onchain-indexer/recoverySharePersistence.ts";

const CORE = "0x00000000000000000000000000000000000000c0";
const ALICE = "0x00000000000000000000000000000000000000a1";
const BOB = "0x00000000000000000000000000000000000000b2";
const ZERO = "0x0000000000000000000000000000000000000000";
const OPERATOR = "0x00000000000000000000000000000000000000c3";
const HASH_10 = `0x${"10".repeat(32)}` as const;
const HASH_20 = `0x${"20".repeat(32)}` as const;
const HASH_30 = `0x${"30".repeat(32)}` as const;
const CONFIG = { chainId: 1n, coreAddress: CORE } as const;

type Log = { block: bigint; event_name: string; payload: unknown };

class FakeV2Database {
  logs: Log[] = [];
  state = new Map<string, string>();
  balances = new Map<string, bigint>();
  queriedLowerBounds: Array<bigint | null> = [];

  query: RecoveryQuery = async (sql, params = []) => {
    const statement = sql.replace(/\s+/g, " ").trim();
    if (statement.startsWith("SELECT state_key, state_value")) {
      const rows = [...this.state].map(([state_key, state_value]) => ({
        state_key,
        state_value,
      }));
      return { rows, rowCount: rows.length };
    }
    if (statement.startsWith("SELECT event_name, payload")) {
      const upper = BigInt(String(params[2]));
      const lower = params.length === 4 ? BigInt(String(params[3])) : null;
      this.queriedLowerBounds.push(lower);
      const rows = this.logs
        .filter((log) => log.block <= upper && (lower === null || log.block > lower))
        .map(({ event_name, payload }) => ({ event_name, payload }));
      return { rows, rowCount: rows.length };
    }
    if (statement.startsWith("SELECT share_id, holder_address, balance_raw")) {
      const rows = [...this.balances].map(([key, balance]) => {
        const separator = key.lastIndexOf(":");
        return {
          holder_address: key.slice(0, separator),
          share_id: key.slice(separator + 1),
          balance_raw: balance.toString(),
        };
      });
      return { rows, rowCount: rows.length };
    }
    if (statement.startsWith("DELETE FROM onchain_recovery_share_balances_v2")) {
      this.balances.clear();
      return { rows: [], rowCount: 0 };
    }
    if (statement.startsWith("INSERT INTO onchain_recovery_share_balances_v2")) {
      this.balances.set(`${params[3]}:${params[2]}`, BigInt(String(params[4])));
      return { rows: [], rowCount: 1 };
    }
    if (statement.startsWith("INSERT INTO onchain_sync_state")) {
      this.state.set(String(params[2]), String(params[3]));
      return { rows: [], rowCount: 1 };
    }
    throw new Error(`Unexpected v2 query: ${statement}`);
  };
}

function transfer(block: bigint, from: string, to: string, value: bigint): Log {
  return {
    block,
    event_name: "TransferSingle",
    payload: { args: { operator: OPERATOR, from, to, id: 17n, value } },
  };
}

test("recovery-share v2 remains independently off by default", () => {
  assert.equal(recoveryShareV2Enabled(undefined), false);
  assert.equal(recoveryShareV2Enabled("false"), false);
  assert.equal(recoveryShareV2Enabled("1"), true);
  assert.throws(() => recoveryShareV2Enabled("yes"), /must be one of/);
});

test("rollback coexistence explicitly retains the bounded legacy full replay", () => {
  const indexer = readFileSync(
    new URL("../server/onchain-indexer/indexer.ts", import.meta.url),
    "utf8"
  );
  assert.match(indexer, /retained rollback image[\s\S]*100k ceiling/);
  assert.match(indexer, /await rebuildRecoveryShareBalances/);
  assert.match(
    indexer,
    /finalizedSnapshotIsComplete[\s\S]*recoveryShareV2Checkpoint[\s\S]*RECOVERY_SHARE_V2_VERSION/
  );
  const repository = readFileSync(
    new URL("../server/onchain-indexer/recoveryPortfolioRepository.ts", import.meta.url),
    "utf8"
  );
  assert.match(
    repository,
    /checkpoint\.blockNumber\.toString\(\) !== model\.snapshotBlock/
  );
  assert.match(repository, /finalized_snapshot_block_hash/);
});

test("v2 performs one local rebuild then applies only the indexed tail", async () => {
  const database = new FakeV2Database();
  database.logs = [transfer(5n, ZERO, ALICE, 10n)];
  const first = await reconcileRecoveryShareBalancesV2({
    config: CONFIG,
    snapshotBlock: 10n,
    snapshotBlockHash: HASH_10,
    profile: "profile-a",
    canonicalPreviousCheckpointHash: null,
    transactionQuery: database.query,
  });
  assert.deepEqual(first, { rebuilt: true, appliedLogCount: 1 });
  assert.equal(database.balances.get(`${ALICE}:17`), 10n);

  database.logs.push(transfer(15n, ALICE, BOB, 4n));
  const second = await reconcileRecoveryShareBalancesV2({
    config: CONFIG,
    snapshotBlock: 20n,
    snapshotBlockHash: HASH_20,
    profile: "profile-a",
    canonicalPreviousCheckpointHash: HASH_10,
    transactionQuery: database.query,
  });
  assert.deepEqual(second, { rebuilt: false, appliedLogCount: 1 });
  assert.deepEqual(database.queriedLowerBounds, [null, 10n]);
  assert.equal(database.balances.get(`${ALICE}:17`), 6n);
  assert.equal(database.balances.get(`${BOB}:17`), 4n);
  assert.equal(database.state.get(RECOVERY_SHARE_V2_STATE_KEYS.block), "20");
});

test("checkpoint hash/profile drift rebuilds locally and target hash drift fails closed", async () => {
  const database = new FakeV2Database();
  database.logs = [transfer(5n, ZERO, ALICE, 10n)];
  await reconcileRecoveryShareBalancesV2({
    config: CONFIG,
    snapshotBlock: 10n,
    snapshotBlockHash: HASH_10,
    profile: "profile-a",
    canonicalPreviousCheckpointHash: null,
    transactionQuery: database.query,
  });
  database.logs = [transfer(6n, ZERO, BOB, 7n)];
  const rebuilt = await reconcileRecoveryShareBalancesV2({
    config: CONFIG,
    snapshotBlock: 30n,
    snapshotBlockHash: HASH_30,
    profile: "profile-a",
    canonicalPreviousCheckpointHash: HASH_20,
    transactionQuery: database.query,
  });
  assert.equal(rebuilt.rebuilt, true);
  assert.equal(database.balances.has(`${ALICE}:17`), false);
  assert.equal(database.balances.get(`${BOB}:17`), 7n);

  await assert.rejects(
    reconcileRecoveryShareBalancesV2({
      config: CONFIG,
      snapshotBlock: 30n,
      snapshotBlockHash: HASH_20,
      profile: "profile-a",
      canonicalPreviousCheckpointHash: null,
      transactionQuery: database.query,
    }),
    /snapshot hash changed/
  );
});
