import assert from "node:assert/strict";
import test from "node:test";
import { countContractReads, RpcReadPacer, rpcRetryDelayMs } from "../server/rpcReadPacer.ts";

test("contract read batches share a budget and are spaced according to their size", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1_000 });
  const pacer = new RpcReadPacer();
  const signal = new AbortController().signal;
  const started: number[] = [];
  const waits = [5, 2, 5].map((count) => pacer.wait(count, signal).then(() => started.push(Date.now())));
  await Promise.resolve();
  assert.deepEqual(started, [1_000]);
  t.mock.timers.tick(624);
  await Promise.resolve();
  assert.equal(started.length, 1);
  t.mock.timers.tick(1);
  await Promise.resolve();
  assert.deepEqual(started, [1_000, 1_625]);
  t.mock.timers.tick(250);
  await Promise.all(waits);
  assert.deepEqual(started, [1_000, 1_625, 1_875]);
});

test("an upstream cooldown delays requests that are already queued", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1_000 });
  const pacer = new RpcReadPacer();
  const signal = new AbortController().signal;
  await pacer.wait(5, signal);
  let started = false;
  const queued = pacer.wait(5, signal).then(() => { started = true; });
  pacer.pause(2_000);
  t.mock.timers.tick(1_999);
  await Promise.resolve();
  assert.equal(started, false);
  t.mock.timers.tick(1);
  await queued;
  assert.equal(started, true);
});

test("cancelled requests leave the queue without consuming another time slot", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1_000 });
  const pacer = new RpcReadPacer();
  const signal = new AbortController().signal;
  await pacer.wait(5, signal);
  const cancelled = new AbortController();
  const rejected = assert.rejects(pacer.wait(5, cancelled.signal), { name: "AbortError" });
  const following = pacer.wait(1, signal);
  cancelled.abort();
  await rejected;
  t.mock.timers.tick(625);
  await following;
  await assert.rejects(pacer.wait(1, cancelled.signal), { name: "AbortError" });
});

test("only known eth_call costs are counted, and Retry-After supports seconds and dates", () => {
  assert.equal(countContractReads([{ method: "eth_call" }, { method: "eth_chainId" }, { method: "eth_call" }]), 2);
  assert.equal(countContractReads({ method: "eth_call" }), 1);
  assert.equal(rpcRetryDelayMs("2"), 2_000);
  assert.equal(rpcRetryDelayMs("Wed, 01 Jan 2025 00:00:05 GMT", Date.parse("2025-01-01T00:00:00Z")), 5_000);
  for (const header of [null, "", "invalid", "0"]) assert.equal(rpcRetryDelayMs(header), 1_000);
});
