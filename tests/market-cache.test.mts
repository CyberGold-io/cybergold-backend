import assert from "node:assert/strict";
import { test } from "node:test";
import { setTimeout } from "node:timers/promises";
import { marketFeed } from "../src/server/market-cache.ts";

test("market cache coalesces refreshes and keeps acquisition age on hits", async () => {
  let calls = 0;
  const feed = marketFeed(async () => {
    calls++;
    await setTimeout(5);
    return { payload: { price: 3000, fetchedAt: "2026-09-28T00:00:00.000Z", stale: false }, isFresh: true };
  }, 1000);
  const results = await Promise.all(Array.from({ length: 20 }, () => feed()));
  assert.equal(calls, 1);
  assert.equal((await feed()).payload.fetchedAt, results[0].payload.fetchedAt);
  assert.equal(calls, 1);
});

test("supplier failure retains last success without caching fallback as fresh", async () => {
  let calls = 0;
  const feed = marketFeed(async (previous: { price: number; fetchedAt: string; stale: boolean } | null) => {
    calls++;
    if (calls === 1) return { payload: { price: 3000, fetchedAt: "2026-09-28T00:00:00.000Z", stale: false }, isFresh: true };
    return { payload: { ...previous!, stale: true }, isFresh: false };
  }, 1);
  await feed();
  await setTimeout(10);
  assert.deepEqual((await feed()).payload, { price: 3000, fetchedAt: "2026-09-28T00:00:00.000Z", stale: true });
  await feed();
  assert.equal(calls, 3);
});
