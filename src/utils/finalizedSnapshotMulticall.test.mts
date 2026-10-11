import assert from "node:assert/strict";
import test from "node:test";
import { parseAbiItem } from "viem";

import {
    createBoundedFinalizedMulticallClient,
    FinalizedMulticallProviderRequestBudgetExceededError,
  finalizedSnapshotMulticallEnabled,
  planBoundedMulticallBatches,
} from "../server/onchain-indexer/finalizedSnapshotMulticall.ts";

const ADDRESS = "0x00000000000000000000000000000000000000c0";
const HASH = `0x${"ab".repeat(32)}` as const;
const ABI = [parseAbiItem("function value(uint256) view returns (uint256)")];

test("finalized Multicall is off by default and planner preserves exact order", () => {
  assert.equal(finalizedSnapshotMulticallEnabled(undefined), false);
  assert.equal(finalizedSnapshotMulticallEnabled("1"), true);
  assert.throws(() => finalizedSnapshotMulticallEnabled("yes"), /must be one of/);
  assert.deepEqual(
    planBoundedMulticallBatches([4, 4, 7, 1], {
      maxCalls: 4,
      maxTotalCalldataBytes: 16,
      maxCallsPerBatch: 2,
      maxBatchCalldataBytes: 8,
    }),
    [
      { from: 0, to: 2, calldataBytes: 8 },
      { from: 2, to: 4, calldataBytes: 8 },
    ]
  );
  assert.throws(
    () =>
      planBoundedMulticallBatches([9], {
        maxCalls: 4,
        maxTotalCalldataBytes: 16,
        maxCallsPerBatch: 2,
        maxBatchCalldataBytes: 8,
      }),
    /budget exceeded/
  );
});

test("readContract calls share an exact canonical anchor and retain per-call failures", async () => {
  const requests: unknown[] = [];
  const client = {
    async readContract(_request: unknown) {
      void _request;
      throw new Error("individual read must not run");
    },
    async multicall(request: { contracts: Array<{ args?: readonly unknown[] }> }) {
      requests.push(request);
      return request.contracts.map((contract) =>
        contract.args?.[0] === 2n
          ? { status: "failure" as const, error: new Error("call two reverted") }
          : { status: "success" as const, result: contract.args?.[0] }
      );
    },
  };
  const batched = createBoundedFinalizedMulticallClient({ client, blockHash: HASH });
  const first = batched.readContract({
    address: ADDRESS,
    abi: ABI,
    functionName: "value",
    args: [1n],
    blockHash: HASH,
    requireCanonical: true,
  });
  const second = batched.readContract({
    address: ADDRESS,
    abi: ABI,
    functionName: "value",
    args: [2n],
    blockHash: HASH,
    requireCanonical: true,
  });
  assert.equal(await first, 1n);
  await assert.rejects(second, /call two reverted/);
  assert.equal(requests.length, 1);
  assert.deepEqual(
    Object.fromEntries(
      Object.entries(requests[0] as Record<string, unknown>).filter(([key]) =>
        ["allowFailure", "blockHash", "requireCanonical"].includes(key)
      )
    ),
    { allowFailure: true, blockHash: HASH, requireCanonical: true }
  );
});

test("wrong-anchor and oversized reads fail before transport", async () => {
  let calls = 0;
  const client = {
    async readContract(_request: unknown) {
      void _request;
      return 0n;
    },
    async multicall() {
      calls += 1;
      return [{ status: "success" as const, result: 1n }];
    },
  };
  const batched = createBoundedFinalizedMulticallClient({
    client,
    blockHash: HASH,
    limits: {
      maxCalls: 1,
      maxTotalCalldataBytes: 128,
      maxCallsPerBatch: 1,
      maxBatchCalldataBytes: 128,
      maxProviderRequests: 1,
    },
  });
  await assert.rejects(
    batched.readContract({
      address: ADDRESS,
      abi: ABI,
      functionName: "value",
      args: [1n],
      blockHash: `0x${"cd".repeat(32)}`,
      requireCanonical: true,
    }),
    /exact canonical anchor/
  );
  await batched.readContract({
    address: ADDRESS,
    abi: ABI,
    functionName: "value",
    args: [1n],
    blockHash: HASH,
    requireCanonical: true,
  });
  await assert.rejects(
    batched.readContract({
      address: ADDRESS,
      abi: ABI,
      functionName: "value",
      args: [2n],
      blockHash: HASH,
      requireCanonical: true,
    }),
    /budget exceeded/
  );
  assert.equal(calls, 1);
});

test("sequential microtask flushes cannot exceed 32 provider requests", async () => {
  let calls = 0;
  const client = {
    async readContract(_request: unknown) {
      void _request;
      return 0n;
    },
    async multicall(request: { contracts: unknown[] }) {
      calls += 1;
      return request.contracts.map(() => ({
        status: "success" as const,
        result: 1n,
      }));
    },
  };
  const batched = createBoundedFinalizedMulticallClient({
    client,
    blockHash: HASH,
  });
  const read = () =>
    batched.readContract({
      address: ADDRESS,
      abi: ABI,
      functionName: "value",
      args: [1n],
      blockHash: HASH,
      requireCanonical: true,
    });
  for (let index = 0; index < 32; index += 1) {
    assert.equal(await read(), 1n);
  }
  await assert.rejects(
    read(),
    FinalizedMulticallProviderRequestBudgetExceededError
  );
  assert.equal(calls, 32);
});
