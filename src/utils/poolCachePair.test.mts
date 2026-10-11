import assert from "node:assert/strict";
import test from "node:test";

import {
  buildPoolCacheEntryKey,
  mergePoolObservation,
  normalizePoolPair,
} from "./poolCachePair.ts";

const TOKEN_A = "0x00000000000000000000000000000000000000aa";
const TOKEN_B = "0x00000000000000000000000000000000000000bb";

test("normalizePoolPair sorts addresses lexicographically and lowercases them", () => {
  const normalized = normalizePoolPair({
    tokenA: "0x00000000000000000000000000000000000000BB",
    tokenB: "0x00000000000000000000000000000000000000aa",
  });

  assert.deepEqual(normalized, {
    token0: TOKEN_A,
    token1: TOKEN_B,
  });
});

test("buildPoolCacheEntryKey is symmetric for token ordering", () => {
  const left = buildPoolCacheEntryKey({
    chainId: 31337,
    dex: "uniswap_v3",
    tokenA: TOKEN_A,
    tokenB: TOKEN_B,
    fee: 500,
  });
  const right = buildPoolCacheEntryKey({
    chainId: 31337,
    dex: "uniswap_v3",
    tokenA: TOKEN_B,
    tokenB: TOKEN_A,
    fee: 500,
  });

  assert.equal(left, right);
});

test("V4 keys preserve spacing/hooks/manager and V3 omitted identity stays unchanged", () => {
  const base = { chainId: 1, dex: "uniswap_v4" as const, tokenA: TOKEN_A, tokenB: TOKEN_B,
    fee: 100, poolManager: TOKEN_A, tickSpacing: 1, hooks: TOKEN_A };
  const keys = [base, { ...base, tickSpacing: 60 }, { ...base, hooks: TOKEN_B },
    { ...base, poolManager: TOKEN_B }].map(buildPoolCacheEntryKey);
  assert.equal(new Set(keys).size, 4);
  assert.equal(buildPoolCacheEntryKey({ ...base, dex: "uniswap_v3", fee: 500 }),
    `1:uniswap_v3:${TOKEN_A}:${TOKEN_B}:500`);
});

test("mergePoolObservation preserves positive existence and quote success", () => {
  const merged = mergePoolObservation(
    {
      chainId: 31337,
      dex: "uniswap_v3",
      tokenA: TOKEN_A,
      tokenB: TOKEN_B,
      fee: 500,
      exists: false,
    },
    {
      chainId: 31337,
      dex: "uniswap_v3",
      tokenA: TOKEN_A,
      tokenB: TOKEN_B,
      fee: 500,
      exists: true,
      poolAddress: "0x0000000000000000000000000000000000000101",
      quoteSucceeded: true,
    }
  );

  assert.deepEqual(merged, {
    chainId: 31337,
    dex: "uniswap_v3",
    tokenA: TOKEN_A,
    tokenB: TOKEN_B,
    fee: 500,
    exists: true,
    poolAddress: "0x0000000000000000000000000000000000000101",
    quoteSucceeded: true,
  });
});
