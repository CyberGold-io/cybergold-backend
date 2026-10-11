import assert from "node:assert/strict";
import test from "node:test";
import { createBackendServer } from "../src/http-server.ts";

async function configured(values: Record<string, string | undefined>, action: () => Promise<void>) {
  const previous = Object.fromEntries(Object.keys(values).map(key => [key, process.env[key]]));
  try {
    for (const [key, value] of Object.entries(values)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await action();
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

test("private faucet accepts localhost or absent Origin and preserves funding-service isolation", async () => {
  await configured({ FORK_FAUCET_ENABLED: "1",
    FORK_FAUCET_SERVICE_URL: "http://127.0.0.1:43123/fund",
    FORK_FAUCET_SERVICE_TOKEN: "a".repeat(64), NODE_ENV: "production" }, async () => {
    const api = await createBackendServer("api", { logger: false });
    const oldFetch = globalThis.fetch;
    let calls = 0;
    const address = "0x0000000000000000000000000000000000000001";
    globalThis.fetch = (async (_url, init) => {
      calls++;
      assert.equal(new Headers(init?.headers).get("authorization"), "Bearer " + "a".repeat(64));
      return Response.json({ status: "ok", address, ethWei: "1", tokens: [], dryRun: false });
    }) as typeof fetch;
    try {
      const payload = { address, requestId: "123e4567-e89b-42d3-a456-426614174000" };
      const headers = { "content-type": "application/json", "x-real-ip": "203.0.113.7", "x-forwarded-for": "203.0.113.7" };
      for (const origin of [undefined, "http://localhost:3000"]) {
        const result = await api.inject({ method: "POST", url: "/api/faucet", payload,
          headers: { ...headers, ...(origin ? { origin } : {}) } });
        assert.equal(result.statusCode, 200, result.body);
      }
      assert.equal(calls, 2);
      process.env.FORK_FAUCET_ENABLED = "0";
      const disabled = await api.inject({ method: "POST", url: "/api/faucet", payload,
        headers: headers });
      assert.equal(disabled.statusCode, 403);
      assert.equal(calls, 2, "an enabled API entry does not enable a disabled faucet");
    } finally { globalThis.fetch = oldFetch; await api.close(); }
  });
});
