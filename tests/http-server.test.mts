import assert from "node:assert/strict";
import { test } from "node:test";
import { createBackendServer } from "../src/http-server.ts";

test("API preserves raw JSON-RPC parsing and does not expose worker controls", async () => {
  const api = await createBackendServer("api", { logger: false });
  try {
    const malformed = await api.inject({ method: "POST", url: "/api/rpc", payload: "{", headers: { "content-type": "application/json" } });
    assert.equal(malformed.statusCode, 400);
    assert.equal(malformed.json().error.code, -32700);
    assert.equal(malformed.headers["cache-control"], "no-store");
    const forbidden = await api.inject({ method: "POST", url: "/api/rpc", payload: { jsonrpc: "2.0", id: 7, method: "eth_sendRawTransaction", params: ["0x00"] } });
    assert.equal(forbidden.statusCode, 403);
    assert.equal(forbidden.json().error.code, -32601);
    assert.equal((await api.inject({ method: "POST", url: "/api/internal/onchain-indexer/reconcile" })).statusCode, 404);
    const activity = await api.inject({ method: "GET", url: "/api/activity/core" });
    assert.equal(activity.statusCode, 200);
    assert.equal(activity.json().enabled, false, "an unconfigured activity view must not initialize a database");
    assert.equal(activity.headers["cache-control"], "no-store");
    const safeActivity = await api.inject({ method: "GET", url: "/api/activity/safe" });
    assert.equal(safeActivity.statusCode, 200);
    assert.equal(safeActivity.json().enabled, false);
    assert.equal(safeActivity.headers["cache-control"], "no-store");
    const large = await api.inject({ method: "POST", url: "/api/rpc", payload: "x".repeat(1024 * 1024 + 1), headers: { "content-type": "text/plain" } });
    assert.equal(large.statusCode, 413);
    assert.equal(large.headers["cache-control"], "no-store");
  } finally { await api.close(); }
});

test("worker controls retain authentication and never register public API routes", async () => {
  const previous = process.env.ONCHAIN_INDEXER_WORKER_TOKEN;
  process.env.ONCHAIN_INDEXER_WORKER_TOKEN = "a".repeat(64);
  const worker = await createBackendServer("worker", { logger: false });
  try {
    const response = await worker.inject({ method: "POST", url: "/api/internal/onchain-indexer/reconcile", payload: "{}" });
    assert.equal(response.statusCode, 401);
    assert.equal(response.headers["cache-control"], "no-store");
    assert.equal((await worker.inject({ method: "GET", url: "/api/gold" })).statusCode, 404);
    assert.equal((await worker.inject({ method: "GET", url: "/api/activity/core" })).statusCode, 404);
    assert.equal((await worker.inject({ method: "GET", url: "/api/activity/safe" })).statusCode, 404);
    assert.equal(globalThis.__cybergoldDashboardPgPool, undefined, "starting a worker must not open/reconcile its database");
  } finally {
    await worker.close();
    if (previous === undefined) delete process.env.ONCHAIN_INDEXER_WORKER_TOKEN;
    else process.env.ONCHAIN_INDEXER_WORKER_TOKEN = previous;
  }
});

test("invalid recovery queries retain their current validation response", async () => {
  const api = await createBackendServer("api", { logger: false });
  try {
    const response = await api.inject({ method: "GET", url: "/api/recovery/shares?holder=invalid" });
    assert.equal(response.statusCode, 400);
    assert.equal(response.headers["cache-control"], "no-store");
  } finally { await api.close(); }
});
