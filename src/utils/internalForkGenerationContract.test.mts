import assert from "node:assert/strict";
import test from "node:test";

import {
  parseInternalForkGenerationRequest,
  readInternalForkGenerationRequest,
} from "../server/onchain-indexer/internalForkGenerationContract.ts";

const prior = {
  generation: "93a43d60-117e-4a58-b036-619b1ca03747",
  forkBlock: "26031324",
  forkBlockHash: `0x${"7d".repeat(32)}`,
};
const next = {
  generation: "02c38061-3cdc-4fa0-8e65-838016c8e2e3",
  forkBlock: "26032000",
  forkBlockHash: `0x${"8a".repeat(32)}`,
};

test("the internal fork contract carries two exact generation anchors", () => {
  const parsed = parseInternalForkGenerationRequest({
    kind: "cybergold-sandbox-fork-generation",
    formatVersion: 1,
    action: "apply",
    previous: prior,
    current: next,
  });
  assert.equal(parsed.action, "apply");
  if (parsed.action !== "apply") return;
  assert.equal(parsed.previous.forkBlock, 26031324n);
  assert.equal(parsed.current.generation, next.generation);
  assert.equal(parsed.current.forkBlockHash, next.forkBlockHash);
});

test("an invalid generation or added field cannot request a transition", () => {
  const base = {
    kind: "cybergold-sandbox-fork-generation",
    formatVersion: 1,
    action: "prepare",
    current: prior,
  };
  assert.throws(() => parseInternalForkGenerationRequest({ ...base, extra: true }), /shape/);
  assert.throws(() => parseInternalForkGenerationRequest({
    ...base,
    current: { ...prior, generation: "not-a-process-generation" },
  }), /identity/);
  assert.throws(() => parseInternalForkGenerationRequest({
    ...base,
    current: { ...prior, forkBlock: "0x18d34dc" },
  }), /identity/);
});

test("the route parser rejects oversized input before transition", async () => {
  const body = JSON.stringify({
    kind: "cybergold-sandbox-fork-generation",
    formatVersion: 1,
    action: "prepare",
    current: prior,
    padding: "x".repeat(1024),
  });
  await assert.rejects(readInternalForkGenerationRequest(new Request("http://app.internal", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
  })), /exceeds/);
});
