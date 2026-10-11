import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { decodeCoreActivity, type CoreActivityRow } from "../src/server/onchain-indexer/coreActivity.ts";
import type { Hex } from "viem";

const receipt = JSON.parse(readFileSync(new URL("./fixtures/core-upgrade-20260928.json", import.meta.url), "utf8"));
export const receiptRows: CoreActivityRow[] = receipt.logs.map((log: Record<string, unknown>) => ({
  block_number: BigInt(log.blockNumber as string).toString(), block_hash: log.blockHash as string,
  tx_hash: log.transactionHash as string, log_index: Number(BigInt(log.logIndex as string)),
  block_timestamp_seconds: "1790611200", topics: log.topics as Hex[], data: log.data as Hex,
}));

test("retained real Core receipt decodes all six upgrade logs, including the four missing events", () => {
  const events = receiptRows.map(decodeCoreActivity);
  assert.deepEqual(events.map(event => event.eventName), ["DiamondCut", "CoreOptionalInitializerMigrationArmed",
    "FacetGenerationUpdated", "ValidatedDiamondCutExecuted", "DiamondCut", "CoreOptionalInitializerCoordinatorMigrated"]);
  assert.deepEqual(events.map(event => event.logIndex), [185, 186, 187, 188, 189, 190]);
  assert.equal(events[1].arguments?.commitment, events[5].arguments?.commitment);
  // The facet install and coordinator migration have independent generations.
  assert.equal(events[2].arguments?.resultingGeneration, "1");
  assert.equal(events[5].arguments?.resultingGeneration, "3");
  assert.equal(events[5].arguments?.newCoordinator, "0xab3624166B983De39f8B9203d0Ba47783A5e5710");
  assert.equal(events[0].transactionHash, "0x15c7585e67f287e97680eb4580242d171b8dbe9ce6f81c13f931450f08874e66");
});

test("unknown or malformed event versions remain visible without exposing raw bodies or failing the history", () => {
  for (const row of [{ ...receiptRows[0], topics: [`0x${"f".repeat(64)}` as Hex] }, { ...receiptRows[1], topics: [] }]) {
    const result = decodeCoreActivity(row);
    assert.equal(result.eventName, null); assert.equal(result.arguments, null);
    assert.equal(result.transactionHash, row.tx_hash); assert.equal("data" in result, false);
  }
});

test("historical constructor and migration events absent from the live facet ABI replay with their original layouts", () => {
  // Topics were observed in H11B. Bodies here are synthetic canonical ABI words,
  // independent of CORE_ACTIVITY_ABI: this is layout coverage, not a live receipt.
  // Definitions: Protocol 1b7652c, migration/{CoreDiamondCutMigrationBridgeInit,
  // CoreDiamondCutMigrationFacet,CoreFacetRegistryRetirementInit}.sol and its
  // pinned diamond-1-hardhat 3da037b contracts/libraries/LibDiamond.sol.
  const word = (value: number) => value.toString(16).padStart(64, "0");
  const topic = (value: number) => `0x${word(value)}` as Hex;
  const replay = (selector: Hex, indexed: number[], data: number[]) => decodeCoreActivity({
    ...receiptRows[0], topics: [selector, ...indexed.map(topic)],
    data: `0x${data.map(word).join("")}` as Hex,
  });
  const ownership = replay("0x8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e0", [1, 2], []);
  assert.equal(ownership.eventName, "OwnershipTransferred");
  assert.deepEqual(ownership.arguments, { previousOwner: `0x${"0".repeat(39)}1`, newOwner: `0x${"0".repeat(39)}2` });
  const armed = replay("0x9d7687643b4693556b6659288789d3ce133836761ded6187ab113ef1146c558b", [3, 1, 2], [4]);
  assert.equal(armed.eventName, "CoreDiamondCutMigrationArmed");
  assert.equal(armed.arguments?.migrationFacet, `0x${"0".repeat(39)}4`);
  const migrated = replay("0x1cb41588e17e0844eb44463776beb1455c89f55245f96a90516f50ee75c495ad", [3, 1, 2], [5, 6, 7, 8]);
  assert.equal(migrated.eventName, "CoreDiamondCutCoordinatorMigrated");
  assert.equal(migrated.arguments?.commitment, armed.arguments?.commitment);
  assert.equal(migrated.arguments?.resultingGeneration, "7");
  assert.equal(migrated.arguments?.manifestHash, topic(8));
  const retired = replay("0xe9efa1acf844b1bcdacd307244722de054aa93723932ecb9a6bc4e911f9944be", [8], [9]);
  assert.equal(retired.eventName, "CoreLegacyFacetRegistryRetired");
  assert.deepEqual(retired.arguments, { manifestHash: topic(8), namespaceCount: "9" });
});
