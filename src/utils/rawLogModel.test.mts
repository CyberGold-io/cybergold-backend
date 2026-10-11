import assert from "node:assert/strict";
import test from "node:test";
import {
  padHex,
  parseAbiItem,
  toEventSelector,
  toHex,
  type Address,
  type Hex,
} from "viem";
import {
  addressScopedRawLogsEnabled,
  createKnownRawLogDecoder,
  normalizeAddressScopedRpcLogs,
} from "../server/onchain-indexer/rawLogModel.ts";

const CONTRACT = "0x00000000000000000000000000000000000000aa" as Address;
const FROM = "0x00000000000000000000000000000000000000bb" as Address;
const TO = "0x00000000000000000000000000000000000000cc" as Address;
const BLOCK_HASH = `0x${"11".repeat(32)}` as Hex;
const TX_HASH = `0x${"22".repeat(32)}` as Hex;
const UNKNOWN_TX_HASH = `0x${"33".repeat(32)}` as Hex;
const TRANSFER_EVENT = parseAbiItem(
  "event Transfer(address indexed from, address indexed to, uint256 value)"
);

function rpcLog(overrides: Record<string, unknown> = {}) {
  return {
    address: CONTRACT,
    blockNumber: "0x64",
    blockHash: BLOCK_HASH,
    transactionHash: TX_HASH,
    logIndex: "0x0",
    topics: [
      toEventSelector(TRANSFER_EVENT),
      padHex(FROM, { size: 32 }),
      padHex(TO, { size: 32 }),
    ],
    data: toHex(5n, { size: 32 }),
    removed: false,
    ...overrides,
  };
}

async function normalize(value: unknown) {
  return normalizeAddressScopedRpcLogs({
    value,
    expectedAddress: CONTRACT,
    fromBlock: 100n,
    toBlock: 100n,
    readBlockHeader: async () => ({ hash: BLOCK_HASH, timestamp: 1_700_000_000n }),
  });
}

test("address-scoped normalization retains unknown topics and exact raw identity", async () => {
  const unknownTopic = `0x${"99".repeat(32)}` as Hex;
  const logs = await normalize([
    rpcLog(),
    rpcLog({
      transactionHash: UNKNOWN_TX_HASH,
      logIndex: "0x1",
      topics: [unknownTopic],
      data: "0x1234",
    }),
  ]);

  assert.equal(logs.length, 2);
  assert.deepEqual(logs[1], {
    contractAddress: CONTRACT,
    blockNumber: 100n,
    blockHash: BLOCK_HASH,
    transactionHash: UNKNOWN_TX_HASH,
    logIndex: 1,
    topics: [unknownTopic],
    data: "0x1234",
    blockTimestampSeconds: 1_700_000_000n,
  });

  const decode = createKnownRawLogDecoder([
    { name: "Transfer", abi: TRANSFER_EVENT },
  ] as const);
  const decoded = decode(logs[0]);
  assert.equal(decoded?.eventName, "Transfer");
  assert.deepEqual(decoded?.args, { from: FROM, to: TO, value: 5n });
  assert.equal(decode(logs[1]), null);
});

test("raw normalization fails closed on inconsistent block hashes and duplicates", async () => {
  await assert.rejects(
    normalizeAddressScopedRpcLogs({
      value: [rpcLog()],
      expectedAddress: CONTRACT,
      fromBlock: 100n,
      toBlock: 100n,
      readBlockHeader: async () => ({
        hash: `0x${"44".repeat(32)}` as Hex,
        timestamp: 1_700_000_000n,
      }),
    }),
    /block hash does not match/
  );
  await assert.rejects(
    normalize([rpcLog(), rpcLog({ data: toHex(6n, { size: 32 }) })]),
    /conflicting duplicates/
  );
  await assert.rejects(
    normalize([rpcLog({ address: FROM })]),
    /unexpected address/
  );
  await assert.rejects(
    normalize([rpcLog({ blockNumber: "0x064" })]),
    /invalid numeric identity/
  );
  await assert.rejects(
    normalize([rpcLog({ logIndex: "0x00" })]),
    /invalid numeric identity/
  );
  await assert.rejects(
    normalize([rpcLog({ data: "0x1" })]),
    /invalid data/
  );
  await assert.rejects(
    normalizeAddressScopedRpcLogs({
      value: [rpcLog()],
      expectedAddress: CONTRACT,
      fromBlock: 100n,
      toBlock: 100n,
      readBlockHeader: async () => ({ hash: BLOCK_HASH, timestamp: -1n }),
    }),
    /block header is invalid/
  );
});

test("the address-scoped path is explicit and off by default", () => {
  assert.equal(addressScopedRawLogsEnabled(undefined), false);
  assert.equal(addressScopedRawLogsEnabled(""), false);
  assert.equal(addressScopedRawLogsEnabled("0"), false);
  assert.equal(addressScopedRawLogsEnabled("false"), false);
  assert.equal(addressScopedRawLogsEnabled("1"), true);
  assert.equal(addressScopedRawLogsEnabled("true"), true);
  assert.throws(() => addressScopedRawLogsEnabled("yes"), /must be one of/);
});
