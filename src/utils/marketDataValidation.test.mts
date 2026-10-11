import assert from "node:assert/strict";
import test from "node:test";

import {
  parseFxMarketDataPayload,
  parseFxProviderRates,
  parseGoldMarketDataPayload,
  parseGoldProviderPrice,
  resolveFxMarketData,
  resolveGoldMarketData,
} from "./marketDataValidation.ts";

test("FX provider validation requires every finite positive bounded rate", () => {
  const validPayload = {
    amount: 1,
    base: "USD",
    date: "2026-07-23",
    rates: { EUR: 0.92, CHF: 0.89, RUB: 91.5 },
  };
  assert.deepEqual(
    parseFxProviderRates(validPayload),
    { EUR: 0.92, CHF: 0.89, RUB: 91.5 }
  );

  for (const invalid of [
    null,
    {},
    { ...validPayload, unexpected: true },
    { ...validPayload, amount: 2 },
    { ...validPayload, base: "EUR" },
    { ...validPayload, date: "23 July 2026" },
    { ...validPayload, rates: { EUR: 0.92, CHF: 0.89 } },
    {
      ...validPayload,
      rates: { EUR: 0.92, CHF: 0.89, RUB: 91.5, GBP: 0.8 },
    },
    { ...validPayload, rates: { EUR: "0.92", CHF: 0.89, RUB: 91.5 } },
    { ...validPayload, rates: { EUR: 0, CHF: 0.89, RUB: 91.5 } },
    { ...validPayload, rates: { EUR: -1, CHF: 0.89, RUB: 91.5 } },
    { ...validPayload, rates: { EUR: Number.NaN, CHF: 0.89, RUB: 91.5 } },
    {
      ...validPayload,
      rates: { EUR: Number.POSITIVE_INFINITY, CHF: 0.89, RUB: 91.5 },
    },
    { ...validPayload, rates: { EUR: 1_000_001, CHF: 0.89, RUB: 91.5 } },
  ]) {
    assert.equal(parseFxProviderRates(invalid), undefined);
  }
});

test("gold provider validation accepts decimal prices and rejects malformed values", () => {
  assert.equal(
    parseGoldProviderPrice({ symbol: "PAXGUSDT", price: "3320.25" }),
    3320.25
  );
  assert.equal(
    parseGoldProviderPrice({ symbol: "PAXGUSDT", price: 3320.25 }),
    3320.25
  );

  for (const invalid of [
    null,
    {},
    { symbol: "BTCUSDT", price: "3320.25" },
    { symbol: "PAXGUSDT", price: "3320.25", unexpected: true },
    { symbol: "PAXGUSDT", price: "" },
    { symbol: "PAXGUSDT", price: " 3320" },
    { symbol: "PAXGUSDT", price: "Infinity" },
    { symbol: "PAXGUSDT", price: "1e4" },
    { symbol: "PAXGUSDT", price: 0 },
    { symbol: "PAXGUSDT", price: -1 },
    { symbol: "PAXGUSDT", price: Number.NaN },
    { symbol: "PAXGUSDT", price: Number.POSITIVE_INFINITY },
    { symbol: "PAXGUSDT", price: 1_000_000_001 },
  ]) {
    assert.equal(parseGoldProviderPrice(invalid), undefined);
  }
});

test("client market-data envelopes preserve freshness and reject unexpected fields", () => {
  const gold = {
    price: 3320.25,
    fetchedAt: "2026-07-23T10:30:00.000Z",
    stale: true,
  };
  const fx = {
    base: "USD",
    rates: { USD: 1, EUR: 0.92, CHF: 0.89, RUB: 91.5 },
    fetchedAt: "2026-07-23T10:30:00.000Z",
    stale: false,
  };

  assert.deepEqual(parseGoldMarketDataPayload(gold), gold);
  assert.deepEqual(parseFxMarketDataPayload(fx), fx);
  assert.equal(
    parseGoldMarketDataPayload({ ...gold, providerInternalId: "secret" }),
    undefined
  );
  assert.equal(
    parseFxMarketDataPayload({
      ...fx,
      rates: { ...fx.rates, GBP: 0.8 },
    }),
    undefined
  );
  assert.equal(
    parseGoldMarketDataPayload({
      ...gold,
      fetchedAt: "2026-02-31T10:30:00.000Z",
    }),
    undefined
  );
});

test("gold resolver marks a timeout fallback stale and exposes its fetch time", async () => {
  const now = new Date("2026-07-23T11:00:00.000Z");
  let receivedSignal: AbortSignal | undefined;
  const timeoutFetch = (async (
    _input: URL | RequestInfo,
    init?: RequestInit
  ) => {
    receivedSignal = init?.signal ?? undefined;
    throw new DOMException("timed out", "TimeoutError");
  }) as typeof fetch;

  const resolution = await resolveGoldMarketData(null, {
    fetchImpl: timeoutFetch,
    now: () => now,
  });

  assert.ok(receivedSignal instanceof AbortSignal);
  assert.equal(resolution.isFresh, false);
  assert.deepEqual(resolution.payload, {
    price: 3320,
    fetchedAt: now.toISOString(),
    stale: true,
  });
});

test("FX resolver treats malformed JSON as stale and preserves last-known fetchedAt", async () => {
  const lastKnown = {
    base: "USD" as const,
    rates: { USD: 1, EUR: 0.93, CHF: 0.88, RUB: 92 },
    fetchedAt: "2026-07-23T09:00:00.000Z",
    stale: false,
  };
  const malformedFetch = (async () =>
    new Response("{malformed-json", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })) as typeof fetch;

  const resolution = await resolveFxMarketData(lastKnown, {
    fetchImpl: malformedFetch,
    now: () => new Date("2026-07-23T12:00:00.000Z"),
  });

  assert.equal(resolution.isFresh, false);
  assert.equal(resolution.payload.stale, true);
  assert.equal(resolution.payload.fetchedAt, lastKnown.fetchedAt);
  assert.deepEqual(resolution.payload.rates, lastKnown.rates);
});

test("failed gold refresh retains the observation until one hour, without renewing its age", async () => {
  const previous = { price: 3800.25, fetchedAt: "2026-09-30T10:00:00.000Z", stale: false };
  const unavailable = (async () => new Response("", { status: 503 })) as typeof fetch;
  for (const age of [1_800_000, 3_599_999, 3_600_000, 3_600_001]) {
    const resolution = await resolveGoldMarketData(previous, {
      fetchImpl: unavailable, now: () => new Date(Date.parse(previous.fetchedAt) + age),
    });
    assert.equal(resolution.isFresh, false);
    assert.deepEqual(resolution.payload, { ...previous, stale: age >= 3_600_000 });
  }
  const fallback = await resolveGoldMarketData({ ...previous, stale: true }, {
    fetchImpl: unavailable, now: () => new Date(previous.fetchedAt),
  });
  assert.equal(fallback.payload.stale, true);
});
