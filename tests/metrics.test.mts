import assert from "node:assert/strict";
import { test, mock } from "node:test";
import { setTimeout } from "node:timers/promises";
import { createBackendServer } from "../src/http-server.ts";
import { marketFeed } from "../src/server/market-cache.ts";
import { metricsRegistry, httpRequests, cacheRequests, marketRefreshes, marketLastFresh,
  rpcAttempts, observeRpcHttp, observeIndexer, indexerLag, indexerObserved,
  indexerReconciled } from "../src/server/metrics.ts";

async function values(metric: { get(): Promise<{ values: unknown[] }> }) {
  return (await metric.get()).values as { value: number; labels: Record<string, string> }[];
}

test("HTTP metrics use route templates, exclude scrapes, and leave worker controls private", async () => {
  httpRequests.reset();
  const api = await createBackendServer("api", { logger: false });
  try {
    await api.inject({ method: "POST", url: "/api/rpc?private=fixture-secret", payload: "{" });
    await api.inject({ method: "GET", url: "/private-wallet-0xabc?bearer=fixture-secret" });
    const response = await api.inject("/metrics");
    assert.equal(response.statusCode, 200);
    assert.match(response.headers["content-type"]!, /text\/plain/);
    assert.equal(response.headers["cache-control"], "no-store");
    assert.doesNotMatch(response.body, /fixture-secret|private-wallet|bearer|requestId/);
    await api.inject("/metrics");
    assert.deepEqual(await values(httpRequests), [
      { value: 1, labels: { operation: "/api/rpc", method: "POST", status: "400" } },
      { value: 1, labels: { operation: "unmatched", method: "GET", status: "404" } },
    ]);
    assert.equal((await api.inject({ method: "POST", url: "/api/internal/onchain-indexer/reconcile" })).statusCode, 404);
    const failure = mock.method(httpRequests, "inc", () => { throw new Error("collector unavailable"); });
    assert.equal((await api.inject({ method: "POST", url: "/api/rpc", payload: "{" })).statusCode, 400);
    failure.mock.restore();
    const failedScrape = mock.method(metricsRegistry, "metrics", async () => { throw new Error("fixture-secret"); });
    const failed = await api.inject("/metrics");
    assert.equal(failed.statusCode, 500);
    assert.doesNotMatch(failed.body, /fixture-secret/);
    assert.equal((await api.inject({ method: "POST", url: "/api/rpc", payload: "{" })).statusCode, 400);
    failedScrape.mock.restore();
  } finally { mock.restoreAll(); await api.close(); }
  const worker = await createBackendServer("worker", { logger: false });
  try {
    assert.equal((await worker.inject("/metrics")).statusCode, 200);
    assert.equal(globalThis.__cybergoldDashboardPgPool, undefined, "scraping does not open a DB");
    assert.equal((await worker.inject({ method: "POST", url: "/api/internal/onchain-indexer/reconcile" })).statusCode, 503);
  } finally { await worker.close(); }
});

test("twenty coalesced callers are one supplier refresh, hits preserve freshness, fallback retries", async () => {
  cacheRequests.reset(); marketRefreshes.reset(); marketLastFresh.reset();
  let calls = 0;
  const fetchedAt = "2026-09-28T00:00:00.000Z";
  const feed = marketFeed(async (previous: { fetchedAt: string; stale: boolean } | null) => {
    calls++;
    await setTimeout(10);
    return { payload: { fetchedAt: previous?.fetchedAt ?? fetchedAt, stale: calls > 1 }, isFresh: calls === 1 };
  }, 100, "gold");
  await Promise.all(Array.from({ length: 20 }, () => feed()));
  await feed();
  assert.equal(calls, 1);
  assert.deepEqual(await values(cacheRequests), [
    { value: 1, labels: { feed: "gold", result: "miss" } },
    { value: 19, labels: { feed: "gold", result: "coalesced" } },
    { value: 1, labels: { feed: "gold", result: "hit" } },
  ]);
  await setTimeout(120);
  assert.equal((await feed()).payload.stale, true);
  assert.equal((await feed()).payload.stale, true);
  assert.equal(calls, 3);
  assert.deepEqual(await values(marketRefreshes), [
    { value: 1, labels: { feed: "gold", outcome: "fresh" } },
    { value: 2, labels: { feed: "gold", outcome: "fallback" } },
  ]);
  assert.equal((await values(marketLastFresh))[0].value, Date.parse(fetchedAt) / 1000);
  const failure = mock.method(cacheRequests, "inc", () => { throw new Error("metrics failed"); });
  try { assert.equal((await feed()).payload.stale, true); }
  finally { failure.mock.restore(); }
});

test("RPC attempts retain HTTP/transport outcomes and return the original response or error", async () => {
  rpcAttempts.reset();
  for (const status of [429, 200]) {
    const response = new Response("{}", { status });
    assert.equal(await observeRpcHttp(async () => response), response);
  }
  const error = new Error("https://credential@upstream.example/private");
  await assert.rejects(observeRpcHttp(async () => { throw error; }), value => value === error);
  assert.deepEqual(await values(rpcAttempts), [
    { value: 1, labels: { outcome: "429" } },
    { value: 1, labels: { outcome: "200" } },
    { value: 1, labels: { outcome: "transport_error" } },
  ]);
  assert.doesNotMatch(await metricsRegistry.metrics(), /credential|upstream.example/);
});

test("unknown indexer progress stays absent; cadence/busy does not invent fresh progress", async () => {
  for (const gauge of [indexerLag, indexerObserved, indexerReconciled]) gauge.remove();
  observeIndexer({ status: "busy", dashboardHistoryProgress: null });
  assert.deepEqual(await values(indexerLag), []);
  assert.deepEqual(await values(indexerObserved), []);
  assert.deepEqual(await values(indexerReconciled), []);
  observeIndexer({ status: "incomplete", dashboardHistoryProgress: {
    formatVersion: 1, startBlock: "1", indexedThroughBlock: "100", networkFinalizedBlock: "150",
    indexedThroughDate: "2026-09-29T00:00:00Z", networkFinalizedDate: "2026-09-29T00:10:00Z", percent: 66,
  } });
  assert.equal((await values(indexerLag))[0].value, 50);
  const observed = await values(indexerObserved);
  observeIndexer({ status: "deferred-cadence", dashboardHistoryProgress: null });
  assert.deepEqual(await values(indexerObserved), observed);
  assert.deepEqual(await values(indexerReconciled), []);
  observeIndexer({ status: "reconciled", dashboardHistoryProgress: null });
  assert.ok((await values(indexerReconciled))[0].value > 0);
});
