import assert from "node:assert/strict";
import test from "node:test";
import { planForkGenerationTransition } from "../server/onchain-indexer/forkGenerationTransition.ts";

const mainnetHash = `0x${"11".repeat(32)}`;
const nextMainnetHash = `0x${"22".repeat(32)}`;
const old = { generation: "old", forkBlock: 1000n, forkBlockHash: mainnetHash };
const next = { generation: "new", forkBlock: 1200n, forkBlockHash: nextMainnetHash };

test("a verified common fork point retains canonical history and replaces the suffix", () => {
  assert.deepEqual(
    planForkGenerationTransition({
      previous: old,
      current: next,
      deploymentStartBlock: 100n,
      currentHashAtPreviousForkBlock: mainnetHash.toUpperCase().replace("0X", "0x"),
    }),
    {
      kind: "reuse-prefix",
      invalidateFrom: 1001n,
      retainedThrough: 1000n,
      retainedBlockHash: mainnetHash,
    }
  );
});

test("a changed common hash or an older new fork requires full replay", () => {
  for (const [current, currentHash] of [
    [next, nextMainnetHash],
    [{ ...next, forkBlock: 900n }, null],
  ] as const) {
    assert.deepEqual(
      planForkGenerationTransition({
        previous: old,
        current,
        deploymentStartBlock: 100n,
        currentHashAtPreviousForkBlock: currentHash,
      }),
      {
        kind: "full-replay",
        invalidateFrom: 100n,
        retainedThrough: null,
        retainedBlockHash: null,
      }
    );
  }
});

test("a stable generation is unchanged but an in-process fork replacement is rejected", () => {
  assert.deepEqual(
    planForkGenerationTransition({
      previous: old,
      current: old,
      deploymentStartBlock: 100n,
      currentHashAtPreviousForkBlock: mainnetHash,
    }),
    { kind: "unchanged" }
  );
  assert.throws(
    () => planForkGenerationTransition({
      previous: old,
      current: { ...old, forkBlock: 1100n },
      deploymentStartBlock: 100n,
      currentHashAtPreviousForkBlock: mainnetHash,
    }),
    /history changed without a new process generation/
  );
});
