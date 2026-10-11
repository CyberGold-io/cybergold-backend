import assert from "node:assert/strict";
import test from "node:test";

import { indexerRpcHeaders } from "../server/onchain-indexer/rpcTransport.ts";

test("the indexer transport adds ordinary authorization only when configured", () => {
  assert.equal(indexerRpcHeaders(undefined), undefined);
  assert.deepEqual(indexerRpcHeaders("Bearer private-gateway-token"), {
    Authorization: "Bearer private-gateway-token",
  });
});

test("the indexer transport rejects malformed authorization values", () => {
  assert.throws(
    () => indexerRpcHeaders("Bearer token\nnext"),
    /ONCHAIN_INDEXER_RPC_AUTHORIZATION is invalid/
  );
});
