import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_RPC_BATCH_SIZE,
  isValidRpcResponsePayload,
  parseRpcUpstreamUrl,
  validateRpcPayload,
} from "../server/rpcProxyPolicy.ts";

function request(method: string, id: number | string | null = 1) {
  return { jsonrpc: "2.0", id, method, params: [] };
}

test("allows the read methods used by viem and wagmi", () => {
  for (const method of [
    "eth_chainId",
    "eth_blockNumber",
    "eth_call",
    "eth_estimateGas",
    "eth_feeHistory",
    "eth_getBalance",
    "eth_getBlockByNumber",
    "eth_getCode",
    "eth_getLogs",
    "eth_getTransactionCount",
    "eth_getTransactionReceipt",
    "eth_maxPriorityFeePerGas",
  ]) {
    assert.deepEqual(validateRpcPayload(request(method)), { ok: true });
  }
});

test("accepts bounded batches of read requests", () => {
  assert.deepEqual(
    validateRpcPayload([
      request("eth_chainId", 1),
      request("eth_getBalance", "balance"),
      request("eth_call", null),
    ]),
    { ok: true }
  );

  assert.equal(
    validateRpcPayload(
      Array.from({ length: MAX_RPC_BATCH_SIZE + 1 }, (_, id) =>
        request("eth_chainId", id)
      )
    ).ok,
    false
  );
});

test("rejects transaction submission and node administration", () => {
  for (const method of [
    "eth_sendTransaction",
    "eth_sendRawTransaction",
    "personal_unlockAccount",
    "anvil_setBalance",
    "hardhat_reset",
    "admin_peers",
    "debug_traceTransaction",
  ]) {
    assert.deepEqual(validateRpcPayload(request(method)), {
      ok: false,
      code: -32601,
      message: "JSON-RPC method is not allowed.",
    });
  }
});

test("rejects malformed individual and batch requests", () => {
  for (const payload of [
    null,
    [],
    { jsonrpc: "1.0", id: 1, method: "eth_chainId" },
    { jsonrpc: "2.0", method: "eth_chainId" },
    { jsonrpc: "2.0", id: 1, method: "eth_chainId", params: null },
    [request("eth_chainId"), request("eth_sendRawTransaction")],
  ]) {
    assert.equal(validateRpcPayload(payload).ok, false);
  }
});

test("recognizes only JSON-RPC response envelopes", () => {
  assert.equal(
    isValidRpcResponsePayload({ jsonrpc: "2.0", id: 1, result: "0x1" }),
    true
  );
  assert.equal(
    isValidRpcResponsePayload([
      { jsonrpc: "2.0", id: 1, result: "0x1" },
      {
        jsonrpc: "2.0",
        id: 2,
        error: { code: -32000, message: "execution reverted" },
      },
    ]),
    true
  );
  assert.equal(isValidRpcResponsePayload({ error: "gateway failure" }), false);
  assert.equal(
    isValidRpcResponsePayload({
      jsonrpc: "2.0",
      id: 1,
      result: "0x1",
      error: { code: -32000, message: "ambiguous" },
    }),
    false
  );
});

test("accepts only HTTP(S) RPC upstream URLs", () => {
  assert.equal(parseRpcUpstreamUrl("http://host.docker.internal:18548")?.port, "18548");
  assert.equal(parseRpcUpstreamUrl("https://rpc.example.invalid/path")?.protocol, "https:");
  assert.equal(parseRpcUpstreamUrl("file:///etc/passwd"), null);
  assert.equal(parseRpcUpstreamUrl("not a URL"), null);
  assert.equal(parseRpcUpstreamUrl(undefined), null);
});
