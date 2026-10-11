import { LRUCache } from "lru-cache";
import { resolveGoldMarketData, resolveFxMarketData } from "../utils/marketDataValidation";

import { cacheRequests, marketRefreshes, marketDuration, marketLastFresh, observeMetrics } from "./metrics";

type Observation = { fetchedAt: string; stale: boolean };
type Resolution<T> = { payload: T; isFresh: boolean };

export function marketFeed<T extends Observation>(
  resolve: (lastKnown: T | null) => Promise<Resolution<T>>, ttl: number, feed?: "gold" | "fx",
) {
  let lastKnown: T | null = null;
  const cache = new LRUCache<string, Resolution<T>>({
    max: 1, ttl, updateAgeOnGet: false,
    async fetchMethod() {
      const started = performance.now();
      let outcome = "error";
      try {
        const result = await resolve(lastKnown);
        outcome = result.isFresh ? "fresh" : "fallback";
        if (result.isFresh) {
          lastKnown = result.payload;
          if (feed) observeMetrics(() => marketLastFresh.set({ feed }, Date.parse(result.payload.fetchedAt) / 1000));
        }
        return result;
      } finally {
        if (feed) observeMetrics(() => {
          marketRefreshes.inc({ feed, outcome });
          marketDuration.observe({ feed }, (performance.now() - started) / 1000);
        });
      }
    },
  });
  return async () => {
    const status: LRUCache.Status<string, Resolution<T>> = {};
    const pending = cache.fetch("feed", { status });
    if (feed) observeMetrics(() => cacheRequests.inc({ feed,
      result: status.fetch === "hit" ? "hit" : status.fetch === "inflight" ? "coalesced" : "miss" }));
    const result = (await pending)!;
    // An unavailable supplier remains an ordinary retry on a later request;
    // a cached fallback must never masquerade as a successful new observation.
    if (!result.isFresh) cache.delete("feed");
    return result;
  };
}

export const goldMarketData = marketFeed(resolveGoldMarketData, 1_800_000, "gold");
export const fxMarketData = marketFeed(resolveFxMarketData, 300_000, "fx");
