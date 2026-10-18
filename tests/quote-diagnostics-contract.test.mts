import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { QuoteWorkDiagnostics } from "../src/contracts/dto.ts";
import type { components } from "../contracts/http.d.ts";

const schemas = JSON.parse(readFileSync(new URL("../contracts/openapi.json", import.meta.url), "utf8")).components.schemas;
const work = schemas.QuoteWorkDiagnostics;
const properties = (schema: any): Record<string, any> => Object.assign({}, schema.properties,
  ...((schema.allOf ?? []).map(properties)));

// A consumer must be able to distinguish a stalled conversion leg from a
// completed route vector whose Core preview or tolerance check rejected it.
const observation = {
  phase: "initial-search", qualified: false,
  routeWave: { mode: "exact-out", legs: { count: 2, omittedRows: 0, rows: [{ index: 1,
    inputAsset: `0x${"1".repeat(40)}`, outputAsset: `0x${"2".repeat(40)}`, amount: "398826311934491",
    started: 3, succeeded: 1, failed: 1, cancelled: 0, pending: 1, bestAvailable: true,
    failureCounts: [{ code: "quote-no-route", count: 1 }], omittedFailureCodes: 0,
    bestPools: [{ protocol: "v3", poolId: `v3:0x${"1".repeat(40)}:0x${"2".repeat(40)}:3000` }], omittedPools: 0,
  }] } },
  providerQualifications: { provider: "core", attempts: 1, qualified: 0, rejected: 1, notImproved: 0,
    cancelled: 0, superseded: 0, pending: 0, omittedRows: 0,
    selectedAttempt: 1, selectionReason: "best-initial", firstQualifiedMs: 100.25, selectionMs: 5000,
    rows: [{ attempt: 1, stage: "tolerance", outcome: "rejected", code: "quote-unavailable",
      startedMs: 50.5, completedMs: 100.25, elapsedMs: 49.75, executionAmount: "398826311934491",
      quotedInput: "100", quotedOutput: "398826311934490", inputMaximum: "100", outputMinimum: "398826311934491",
      pools: [{ protocol: "v4", poolId: `0x${"a".repeat(64)}` }], omittedPools: 0,
      targetAmount: "398826311934491", minimumAmountOut: "398826311934491",
      maximumAmountOut: "402814575053836", observedAmountOut: "398826311934490" }] },
} satisfies QuoteWorkDiagnostics & NonNullable<components["schemas"]["TradeProviderAssessment"]["quoteDiagnostics"]>;

const marketObservation = { ...observation, providerQualifications: { ...observation.providerQualifications,
  provider: "market", rows: [{ attempt: 1, stage: "fee-bounds", outcome: "rejected", code: "quote-unavailable",
    maximumAmountIn: "100", observedAmountIn: "101" }] },
} satisfies QuoteWorkDiagnostics & NonNullable<components["schemas"]["TradeProviderAssessment"]["quoteDiagnostics"]>;

test("published quote errors expose the same optional leg and provider qualification evidence", () => {
  assert.equal(observation.routeWave.legs.rows[0].bestAvailable, true);
  assert.equal(observation.providerQualifications.rows[0].outcome, "rejected");
  assert.equal(marketObservation.providerQualifications.provider, "market");
  assert.equal(marketObservation.providerQualifications.rows[0].observedAmountIn, "101");
  assert.deepEqual(properties(schemas.PublicError).quoteDiagnostics, work);
  assert.deepEqual(properties(schemas.TradeProviderAssessment).quoteDiagnostics, work);
  for (const name of ["QuoteIntent", "MarketQuote"]) assert.deepEqual(properties(schemas[name]).quoteDiagnostics, work);
  for (const name of ["QuoteIntentEvent", "RouteSearchEvent", "TradeQuoteEvent", "MarketQuoteEvent"]) {
    const errors = schemas[name].anyOf.map(properties).filter((row: any) => row.type?.const === "error"
      || row.type?.enum?.includes("error"));
    assert.ok(errors.length > 0, `${name} declares its error envelope`);
    for (const row of errors) assert.deepEqual(row.quoteDiagnostics, work);
  }
  assert.equal(work.required?.includes("routeWave") ?? false, false);
  assert.equal(work.required?.includes("providerQualifications") ?? false, false);
  assert.equal(work.properties.routeWave.properties.subphase.enum.includes("structured-search"), true);
});

test("new diagnostic records are bounded and contain only public identities, counts and outcomes", () => {
  const legs = work.properties.routeWave.properties.legs;
  const leg = legs.properties.rows.items;
  const qualification = work.properties.providerQualifications;
  assert.deepEqual(qualification.properties.provider.enum, ["core", "market"]);
  const row = qualification.properties.rows.items;
  for (const value of [legs, leg, leg.properties.failureCounts.items, leg.properties.bestPools.items, qualification, row]) {
    assert.equal(value.additionalProperties, false);
  }
  assert.equal(legs.properties.rows.maxItems, 16);
  assert.equal(leg.properties.failureCounts.maxItems, 16);
  assert.equal(leg.properties.bestPools.maxItems, 8);
  assert.equal(qualification.properties.rows.maxItems, 8);
  assert.equal(row.properties.pools.maxItems, 8);
  assert.equal(row.properties.pools.items.additionalProperties, false);
  for (const value of [legs.properties.count, leg.properties.pending, qualification.properties.attempts, row.properties.attempt]) {
    assert.equal(value.type, "integer"); assert.equal(value.minimum, 0); assert.equal(value.maximum, 1e12);
  }
  const pools = leg.properties.bestPools.items.properties;
  assert.match(observation.routeWave.legs.rows[0].bestPools[0].poolId, new RegExp(pools.poolId.pattern));
  const v3Identity = `v3:0x${"1".repeat(40)}:0x${"2".repeat(40)}:`;
  for (const fee of ["0", "3000", "0000500", "1000000"]) assert.match(v3Identity + fee, new RegExp(pools.poolId.pattern));
  for (const fee of ["1000001", "9999999", "00000000"]) assert.doesNotMatch(v3Identity + fee, new RegExp(pools.poolId.pattern));
  for (const invalid of ["https://provider/private", "Bearer credential", `0x${"ab".repeat(65)}`]) {
    assert.equal(new RegExp(pools.poolId.pattern).test(invalid), false);
  }
  assert.deepEqual([...row.properties.code.enum].sort(), [...schemas.QuoteErrorCode.enum].sort());
  assert.equal(row.properties.stage.enum.includes("tolerance"), true);
  assert.equal(row.properties.stage.enum.includes("fee-bounds"), true);
  assert.equal(row.properties.stage.enum.includes("qualification"), true);
  assert.equal(row.properties.maximumAmountIn.pattern, row.properties.observedAmountIn.pattern);
  for (const name of ["executionAmount", "quotedInput", "quotedOutput", "inputMaximum", "outputMinimum"])
    assert.equal(row.properties[name].pattern, row.properties.maximumAmountIn.pattern);
  for (const field of [row.properties.startedMs, row.properties.completedMs, row.properties.elapsedMs,
    qualification.properties.firstQualifiedMs, qualification.properties.selectionMs,
    qualification.properties.canonicalCompletedMs, qualification.properties.cleanupCompletedMs]) {
    assert.equal(field.type, "number"); assert.equal(field.minimum, 0); assert.equal(field.maximum, 1e12);
  }
  assert.equal(qualification.properties.selectedAttempt.type, "integer");
  assert.deepEqual([...qualification.properties.selectionReason.enum].sort(), ["best-initial", "complete", "first-extension", "timeout"]);
  assert.equal(row.properties.outcome.enum.includes("not-improved"), true);
  assert.equal(row.properties.outcome.enum.includes("private error message"), false);
  for (const forbidden of ["message", "error", "calldata", "signature", "providerUrl", "inputMaximumUsd"]) {
    assert.equal(Object.hasOwn(row.properties, forbidden), false);
    assert.equal(Object.hasOwn(leg.properties, forbidden), false);
  }
});
