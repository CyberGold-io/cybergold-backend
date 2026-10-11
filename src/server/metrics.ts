import { Counter, Gauge, Histogram, Registry } from "@prometheus-io/client";
import type { InternalReconcileResult } from "./onchain-indexer/internalReconcileContract";

// One registry per backend process. Scraping reads memory only: no DB/RPC calls,
// background scheduler, request bodies, credentials or account identifiers.
export const metricsRegistry = new Registry();
const registers = [metricsRegistry];
export const httpRequests = new Counter({ name: "cybergold_backend_http_requests_total",
  help: "Completed backend HTTP requests, excluding metrics scrapes.",
  labelNames: ["operation", "method", "status"] as const, registers });
export const httpDuration = new Histogram({ name: "cybergold_backend_http_duration_seconds",
  help: "Backend response duration, excluding metrics scrapes.",
  labelNames: ["operation", "method"] as const,
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 120], registers });
export const cacheRequests = new Counter({ name: "cybergold_backend_market_cache_requests_total",
  help: "Market cache requests: hit, miss (including expiry), or coalesced in-flight refresh.",
  labelNames: ["feed", "result"] as const, registers });
export const marketRefreshes = new Counter({ name: "cybergold_backend_market_refreshes_total",
  help: "Supplier refresh resolutions: fresh, fallback, or thrown error; coalesced callers count once.",
  labelNames: ["feed", "outcome"] as const, registers });
export const marketDuration = new Histogram({ name: "cybergold_backend_market_refresh_duration_seconds",
  help: "Supplier refresh duration including response parsing and validation.",
  labelNames: ["feed"] as const, buckets: [0.05, 0.1, 0.5, 1, 2.5, 5, 10, 15], registers });
export const marketLastFresh = new Gauge({ name: "cybergold_backend_market_last_fresh_timestamp_seconds",
  help: "Acquisition time of the last fresh market observation in this process; absent until fresh data.",
  labelNames: ["feed"] as const, registers });
export const rpcAttempts = new Counter({ name: "cybergold_backend_rpc_http_attempts_total",
  help: "RPC proxy wire attempts by HTTP status or transport_error; HTTP 200 does not imply JSON-RPC success.",
  labelNames: ["outcome"] as const, registers });
export const rpcDuration = new Histogram({ name: "cybergold_backend_rpc_http_duration_seconds",
  help: "RPC proxy wire time to response headers or transport failure, excluding pacing and body parsing.",
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30], registers });
export const indexerRuns = new Counter({ name: "cybergold_backend_indexer_runs_total",
  help: "Authenticated reconcile outcomes (reconciled, incomplete, deferred-cadence, busy, error).",
  labelNames: ["outcome"] as const, registers });
export const indexerLag = new Gauge({ name: "cybergold_backend_indexer_history_lag_blocks",
  help: "Dashboard history lag relative to the finalized head observed by the last run with progress.", registers });
export const indexerObserved = new Gauge({ name: "cybergold_backend_indexer_progress_timestamp_seconds",
  help: "Time the worker last observed dashboard history progress; absent until observed.", registers });
export const indexerReconciled = new Gauge({ name: "cybergold_backend_indexer_reconciled_timestamp_seconds",
  help: "Time of the last reconciled outcome in this process; absent until reconciled.", registers });

// Unlabelled gauges default to zero in the client; unknown progress is absent,
// never a fabricated zero lag or a successful reconciliation at process start.
indexerLag.remove();
indexerObserved.remove();
indexerReconciled.remove();

export function observeMetrics(record: () => void): void {
  try { record(); } catch { /* Telemetry must not change product behavior. */ }
}

export function observeIndexer(result: InternalReconcileResult): void {
  observeMetrics(() => {
    indexerRuns.inc({ outcome: result.status });
    const now = Date.now() / 1000;
    if (result.status === "reconciled") indexerReconciled.set(now);
    if (result.dashboardHistoryProgress) {
      const progress = result.dashboardHistoryProgress;
      indexerLag.set(Number(BigInt(progress.networkFinalizedBlock) - BigInt(progress.indexedThroughBlock)));
      indexerObserved.set(now);
    }
  });
}

export async function observeRpcHttp(send: () => Promise<Response>): Promise<Response> {
  const start = performance.now();
  let outcome = "transport_error";
  try {
    const response = await send();
    outcome = String(response.status);
    return response;
  } finally {
    observeMetrics(() => {
      rpcAttempts.inc({ outcome });
      rpcDuration.observe((performance.now() - start) / 1000);
    });
  }
}
