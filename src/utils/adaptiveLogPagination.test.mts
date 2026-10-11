import assert from "node:assert/strict";
import test from "node:test";
import {
  assertExactRangeCoverage,
  executeAdaptiveBlockRanges,
  shouldSplitDirectProviderLogRequest,
  splitInclusiveBlockRange,
  type InclusiveBlockRange,
} from "../server/onchain-indexer/adaptiveLogPagination.ts";

function key(range: InclusiveBlockRange) {
  return `${range.fromBlock}-${range.toBlock}`;
}

test("adaptive log pagination splits left-first and recomposes exact ascending coverage", async () => {
  const attempts: string[] = [];
  const result = await executeAdaptiveBlockRanges<bigint>({
    baseRange: { fromBlock: 0n, toBlock: 7n },
    shouldSplitRequestFailure: () => true,
    requestRange: async ({ range }) => {
      attempts.push(key(range));
      if (range.toBlock - range.fromBlock + 1n > 2n) {
        throw new Error("provider-specific range limit");
      }
      return range;
    },
    validateRange: (value) => {
      const range = value as InclusiveBlockRange;
      const blocks: bigint[] = [];
      for (let block = range.fromBlock; block <= range.toBlock; block += 1n) {
        blocks.push(block);
      }
      return blocks;
    },
  });

  assert.deepEqual(attempts, [
    "0-7",
    "0-3",
    "0-1",
    "2-3",
    "4-7",
    "4-5",
    "6-7",
  ]);
  assert.deepEqual(result.successfulRanges.map(key), [
    "0-1",
    "2-3",
    "4-5",
    "6-7",
  ]);
  assert.deepEqual(result.values, [0n, 1n, 2n, 3n, 4n, 5n, 6n, 7n]);
  assert.equal(result.attemptCount, 7);
  assert.equal(result.adaptiveAttemptCount, 6);
});

test("a one-block provider failure is terminal and does not expose provider text", async () => {
  let attempts = 0;
  await assert.rejects(
    executeAdaptiveBlockRanges({
      baseRange: { fromBlock: 5n, toBlock: 5n },
      shouldSplitRequestFailure: () => true,
      requestRange: async () => {
        attempts += 1;
        throw new Error("secret provider implementation detail");
      },
      validateRange: () => [],
    }),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.equal(
        error.message,
        "Address-scoped log request failed for one block"
      );
      assert.doesNotMatch(error.message, /secret|provider implementation/i);
      return true;
    }
  );
  assert.equal(attempts, 1);
});

test("successful response validation failures are terminal rather than split", async () => {
  let attempts = 0;
  await assert.rejects(
    executeAdaptiveBlockRanges({
      baseRange: { fromBlock: 0n, toBlock: 7n },
      requestRange: async () => {
        attempts += 1;
        return [];
      },
      validateRange: () => {
        throw new Error("malformed successful response");
      },
    }),
    /malformed successful response/
  );
  assert.equal(attempts, 1);
});

test("range, attempt, and response-cardinality caps fail closed", async () => {
  await assert.rejects(
    executeAdaptiveBlockRanges({
      baseRange: { fromBlock: 0n, toBlock: 3n },
      maxRanges: 1,
      shouldSplitRequestFailure: () => true,
      requestRange: async () => {
        throw new Error("failure");
      },
      validateRange: () => [],
    }),
    /range cap was exceeded/
  );
  await assert.rejects(
    executeAdaptiveBlockRanges({
      baseRange: { fromBlock: 0n, toBlock: 3n },
      maxAttempts: 1,
      shouldSplitRequestFailure: () => true,
      requestRange: async () => {
        throw new Error("failure");
      },
      validateRange: () => [],
    }),
    /attempt cap was exceeded/
  );
  await assert.rejects(
    executeAdaptiveBlockRanges({
      baseRange: { fromBlock: 0n, toBlock: 0n },
      maxCardinality: 1,
      requestRange: async () => [1, 2],
      validateRange: (value) => value as number[],
    }),
    /cardinality cap was exceeded/
  );
});

test("direct provider splitting uses typed status/code and rejects rate limits or outages", () => {
  assert.equal(
    shouldSplitDirectProviderLogRequest({
      name: "HttpRequestError",
      status: 413,
    }),
    true
  );
  assert.equal(
    shouldSplitDirectProviderLogRequest({
      name: "RpcRequestError",
      code: -32_005,
    }),
    true
  );
  assert.equal(
    shouldSplitDirectProviderLogRequest({
      name: "HttpRequestError",
      status: 429,
    }),
    false
  );
  assert.equal(
    shouldSplitDirectProviderLogRequest({ name: "TimeoutError" }),
    false
  );
  assert.equal(
    shouldSplitDirectProviderLogRequest(new Error("response too large")),
    false,
    "provider text must never drive range splitting"
  );
});

test("rate limits and outages make one terminal attempt instead of a split storm", async () => {
  for (const failure of [
    { name: "HttpRequestError", status: 429 },
    { name: "TimeoutError" },
  ]) {
    let attempts = 0;
    await assert.rejects(
      executeAdaptiveBlockRanges({
        baseRange: { fromBlock: 0n, toBlock: 1_023n },
        shouldSplitRequestFailure: shouldSplitDirectProviderLogRequest,
        requestRange: async () => {
          attempts += 1;
          throw failure;
        },
        validateRange: () => [],
      }),
      /without an approved range-reduction signal/
    );
    assert.equal(attempts, 1);
  }
});

test("coverage verification rejects gaps and overlaps", () => {
  const baseRange = { fromBlock: 0n, toBlock: 7n } as const;
  assert.deepEqual(splitInclusiveBlockRange(baseRange), [
    { fromBlock: 0n, toBlock: 3n },
    { fromBlock: 4n, toBlock: 7n },
  ]);
  assert.doesNotThrow(() =>
    assertExactRangeCoverage(baseRange, [
      { fromBlock: 0n, toBlock: 3n },
      { fromBlock: 4n, toBlock: 7n },
    ])
  );
  assert.throws(
    () =>
      assertExactRangeCoverage(baseRange, [
        { fromBlock: 0n, toBlock: 2n },
        { fromBlock: 4n, toBlock: 7n },
      ]),
    /do not exactly cover/
  );
  assert.throws(
    () =>
      assertExactRangeCoverage(baseRange, [
        { fromBlock: 0n, toBlock: 4n },
        { fromBlock: 4n, toBlock: 7n },
      ]),
    /do not exactly cover/
  );
});
