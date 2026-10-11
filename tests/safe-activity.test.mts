import assert from "node:assert/strict";
import test from "node:test";
import { toEventHash, type Hex } from "viem";
import { decodeSafeActivity } from "../src/server/safe-events/activity.ts";

const hash = `0x${"a".repeat(64)}` as Hex;
const payment = "0".repeat(63) + "7";
const base = { contract_address: "0xsafe", block_number: "10", block_hash: hash,
  tx_hash: hash, log_index: 3, block_timestamp_seconds: "20" };

test("retained Safe execution uses both historical ABI layouts and distinguishes failure", () => {
  for (const eventName of ["ExecutionSuccess", "ExecutionFailure"] as const) {
    const selector = toEventHash(`${eventName}(bytes32,uint256)`);
    for (const row of [
      { ...base, topics: [selector, hash], data: `0x${payment}` as Hex },
      { ...base, topics: [selector], data: `${hash}${payment}` as Hex },
    ]) {
      const result = decodeSafeActivity(row);
      assert.equal(result.eventName, eventName);
      assert.equal(result.safeTxHash, hash);
      assert.equal(result.paymentWei, "7");
      assert.equal(result.transactionHash, base.tx_hash);
      assert.equal("data" in result, false);
      assert.equal("topics" in result, false);
    }
  }
});

test("unknown and malformed historical Safe logs remain visible without an execution outcome", () => {
  for (const row of [
    { ...base, topics: [hash], data: `${hash}${payment}` as Hex },
    { ...base, topics: [toEventHash("ExecutionSuccess(bytes32,uint256)")], data: "0x01" as Hex },
  ]) {
    const result = decodeSafeActivity(row);
    assert.equal(result.eventName, null);
    assert.equal(result.safeTxHash, null);
    assert.equal(result.paymentWei, null);
    assert.equal(result.blockNumber, "10");
  }
});
