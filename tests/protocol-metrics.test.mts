import assert from "node:assert/strict";
import { test } from "node:test";
import { Registry } from "@prometheus-io/client";
import { createProtocolMetrics } from "../src/server/protocolMetrics.ts";

test("committed product observations retain units, nulls, bounded activity and changing reserve assets", async () => {
  const registry = new Registry();
  const snapshot = { enabled: true, snapshotBlock: "26075596", chainHeadTimestampMs: 1_790_000_000_000,
    metrics: { currentTotalSupplyCygld: 124.5, netIssuance24hCygld: -2.5, holderCount: null, paused: false },
    basket: { assets: [{ address: "0xABC", reserveBalance: 25.5, actualPercent: 45, targetPercent: 50 }] } };
  let activityEnabled = true;
  const activity = { enabled: true as const, chainId: 1, address: "0xcore", source: "retained-core-journal" as const,
    journalStartBlock: "25615683", indexedThroughBlock: "26075596", indexedThroughBlockHash: "0xblock", hasMore: true,
    events: [{ eventName: "DiamondCut" }, { eventName: "DiamondCut" }, { eventName: null }] };
  const metrics = createProtocolMetrics(registry, async () => snapshot,
    async () => (activityEnabled ? activity : { enabled: false, events: [] }) as never, () => 1_790_000_010);
  await metrics.refresh();
  let text = await registry.metrics();
  assert.match(text, /cybergold_protocol_supply_cygld 124.5/);
  assert.match(text, /cybergold_protocol_net_issuance_24h_cygld -2.5/);
  assert.doesNotMatch(text, /^cybergold_protocol_holders /m);
  assert.match(text, /cybergold_protocol_paused 0/);
  assert.match(text, /cybergold_protocol_snapshot_timestamp_seconds 1790000000/);
  assert.match(text, /cybergold_protocol_reserve_tokens\{asset="0xabc"\} 25.5/);
  assert.match(text, /cybergold_protocol_activity_sample_events\{event="DiamondCut"\} 2/);
  assert.match(text, /cybergold_protocol_activity_sample_events\{event="unknown"\} 1/);
  assert.match(text, /cybergold_protocol_activity_has_more 1/);
  assert.doesNotMatch(text, /0xcore|0xblock/);
  snapshot.basket.assets = [];
  activityEnabled = false;
  await metrics.refresh();
  text = await registry.metrics();
  assert.doesNotMatch(text, /asset="0xabc"|^cybergold_protocol_activity_sample_logs /m);
});

test("database failures never reject collection, retain observation age, and do not block independent sources", async () => {
  const registry = new Registry();
  let fail = false;
  let time = 10;
  const metrics = createProtocolMetrics(registry, async () => {
    if (fail) throw new Error("database credential must not leak");
    return { enabled: false };
  }, async () => ({ enabled: false as const, events: [] }), () => time);
  await metrics.refresh();
  fail = true; time = 20;
  await metrics.refresh();
  const text = await registry.metrics();
  assert.match(text, /cybergold_protocol_read_success\{source="snapshot"\} 0/);
  assert.match(text, /cybergold_protocol_observed_timestamp_seconds\{source="snapshot"\} 10/);
  assert.match(text, /cybergold_protocol_observed_timestamp_seconds\{source="activity"\} 20/);
  assert.doesNotMatch(text, /credential/);
});

test("overlapping requests coalesce; repeated Prometheus scrapes never re-read product data", async () => {
  const registry = new Registry();
  let finish!: () => void;
  const held = new Promise<void>(resolve => { finish = resolve; });
  let reads = 0;
  const metrics = createProtocolMetrics(registry, async () => { reads++; await held; return { enabled: false }; },
    async () => ({ enabled: false as const, events: [] }));
  const first = metrics.refresh();
  assert.equal(metrics.refresh(), first);
  assert.equal(reads, 1);
  for (let i = 0; i < 10; i++) await registry.metrics();
  assert.equal(reads, 1);
  finish(); await first;
  await metrics.refresh();
  assert.equal(reads, 2);
});
