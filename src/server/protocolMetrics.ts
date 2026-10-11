import { Gauge, type Registry } from "@prometheus-io/client";
import { metricsRegistry } from "./metrics";
import { getCoreActivity } from "./onchain-indexer/coreActivity";
import { getOnchainDashboardSummary, type OnchainDashboardSnapshot } from "./onchain-indexer/indexer";

// Read completed product data after reconciliation. Scrapes only read gauges;
// collection is best effort and cannot hold up the worker response or call RPC.
export function createProtocolMetrics(registry: Registry, readSnapshot = getOnchainDashboardSummary,
  readActivity = getCoreActivity, now = () => Date.now() / 1000) {
  const gauge = (suffix: string, help: string, labelNames: string[] = []) => {
    const value = new Gauge({ name: `cybergold_protocol_${suffix}`, help, labelNames, registers: [registry] });
    if (!labelNames.length) value.remove();
    return value;
  };
  const readOk = gauge("read_success", "Whether the most recent committed-product read succeeded.", ["source"]);
  const observed = gauge("observed_timestamp_seconds", "Time of the last successful product read, not chain freshness.", ["source"]);
  const block = gauge("snapshot_block", "Block of the completed product dashboard snapshot.");
  const timestamp = gauge("snapshot_timestamp_seconds", "Chain timestamp of the completed product snapshot.");
  const supply = gauge("supply_cygld", "CYGLD supply from the completed product snapshot.");
  const net = gauge("net_issuance_24h_cygld", "Net issuance over the product snapshot's trailing 24 hours; not a counter.");
  const holders = gauge("holders", "Indexed holder count; absent when unknown.");
  const paused = gauge("paused", "Snapshot pause state: 1 paused, 0 unpaused; absent when unknown.");
  const reserves = gauge("reserve_tokens", "Protocol reserve in token units, not executable DEX liquidity.", ["asset"]);
  const weights = gauge("basket_weight_percent", "Product basket actual and target weights in percent.", ["asset", "kind"]);
  const journalBlock = gauge("activity_indexed_through_block", "Core raw journal cursor for the recent activity sample.");
  const sampleSize = gauge("activity_sample_logs", "Size of the most recent Core journal sample, capped at 100 logs.");
  const sampleTruncated = gauge("activity_has_more", "1 means retained Core logs exist before the displayed sample.");
  const events = gauge("activity_sample_events", "Event counts in the latest up-to-100-log sample; not lifetime counts or rates.", ["event"]);
  const set = (metric: Gauge, value: unknown) => {
    if (typeof value === "number" && Number.isFinite(value)) metric.set(value);
    else metric.remove();
  };
  let pending: Promise<void> | undefined;
  const collect = async (source: string, work: () => Promise<void>) => {
    try {
      await work();
      readOk.set({ source }, 1);
      observed.set({ source }, now());
    } catch {
      // Keep the previous observation and its age, but expose the failed read.
      try { readOk.set({ source }, 0); } catch { /* Telemetry is optional. */ }
    }
  };
  return {
    refresh(): Promise<void> {
      if (pending) return pending;
      pending = Promise.all([
        collect("snapshot", async () => {
          const snapshot = await readSnapshot() as OnchainDashboardSnapshot;
          const snapshotGauges = [block, timestamp, supply, net, holders, paused, reserves, weights];
          if (!snapshot?.enabled) { snapshotGauges.forEach(metric => metric.reset());
            [block, timestamp, supply, net, holders, paused].forEach(metric => metric.remove()); return; }
          set(block, Number(snapshot.snapshotBlock));
          set(timestamp, snapshot.chainHeadTimestampMs / 1000);
          set(supply, snapshot.metrics.currentTotalSupplyCygld);
          set(net, snapshot.metrics.netIssuance24hCygld);
          set(holders, snapshot.metrics.holderCount);
          set(paused, typeof snapshot.metrics.paused === "boolean" ? Number(snapshot.metrics.paused) : null);
          reserves.reset(); weights.reset();
          for (const asset of snapshot.basket?.assets ?? []) {
            // Configured reserve assets only; never account/transaction labels.
            const labels = { asset: asset.address.toLowerCase() };
            if (asset.reserveBalance !== null && Number.isFinite(asset.reserveBalance)) reserves.set(labels, asset.reserveBalance);
            if (Number.isFinite(asset.actualPercent)) weights.set({ ...labels, kind: "actual" }, asset.actualPercent);
            if (Number.isFinite(asset.targetPercent)) weights.set({ ...labels, kind: "target" }, asset.targetPercent);
          }
        }),
        collect("activity", async () => {
          const activity = await readActivity();
          events.reset();
          if (!activity.enabled) { [journalBlock, sampleSize, sampleTruncated].forEach(metric => metric.remove()); return; }
          set(journalBlock, activity.indexedThroughBlock === null ? null : Number(activity.indexedThroughBlock));
          sampleSize.set(activity.events.length); sampleTruncated.set(Number(activity.hasMore));
          const counts = new Map<string, number>();
          for (const event of activity.events) {
            const name = event.eventName ?? "unknown";
            counts.set(name, (counts.get(name) ?? 0) + 1);
          }
          for (const [event, count] of counts) events.set({ event }, count);
        }),
      ]).then(() => {}).finally(() => { pending = undefined; });
      return pending;
    },
  };
}

export const protocolMetrics = createProtocolMetrics(metricsRegistry);
