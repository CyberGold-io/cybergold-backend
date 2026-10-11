import assert from "node:assert/strict";
import test from "node:test";

import { POST } from "../api/rpc/route.ts";
import { sandboxRpcReadPacer } from "../server/rpcReadPacer.ts";

const authorization = `Bearer ${"a".repeat(64)}`;
const payload = { jsonrpc: "2.0", id: 17, method: "eth_chainId", params: [] };

test("the App RPC route forwards its configured bearer to its configured upstream", async (t) => {
  const previousUrl = process.env.RPC_URL;
  const previousAuthorization = process.env.RPC_AUTHORIZATION;
  t.after(() => {
    if (previousUrl === undefined) delete process.env.RPC_URL;
    else process.env.RPC_URL = previousUrl;
    if (previousAuthorization === undefined) delete process.env.RPC_AUTHORIZATION;
    else process.env.RPC_AUTHORIZATION = previousAuthorization;
  });

  process.env.RPC_AUTHORIZATION = authorization;
  for (const upstream of [
    "http://rpc-broker:19546",
    "https://rpc-fork.cybergold.io/",
    "https://rpc-mainnet.cybergold.io/",
    "https://ethereum-rpc.publicnode.com",
    "http://anvil:8545",
  ]) {
    process.env.RPC_URL = upstream;
    const fetchMock = t.mock.method(globalThis, "fetch", async (input: Parameters<typeof fetch>[0], options?: RequestInit) => {
      assert.equal(String(input), new URL(upstream).href);
      const headers = new Headers(options?.headers);
      assert.equal(headers.get("authorization"), authorization);
      assert.equal(headers.get("cookie"), null);
      assert.equal(options?.redirect, "error");
      assert.deepEqual(JSON.parse(String(options?.body)), payload);
      return Response.json({ jsonrpc: "2.0", id: 17, result: "0x1" });
    });
    const response = await POST(new Request("https://app.cybergold.io/api/rpc", {
      method: "POST",
      headers: { Authorization: "Bearer browser-input", Cookie: "session=private" },
      body: JSON.stringify(payload),
    }));
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { jsonrpc: "2.0", id: 17, result: "0x1" });
    assert.equal(response.headers.get("authorization"), null);
    assert.equal(fetchMock.mock.callCount(), 1);
    fetchMock.mock.restore();
  }

  delete process.env.RPC_AUTHORIZATION;
  process.env.RPC_URL = "https://rpc-fork.cybergold.io/";
  const fetchMock = t.mock.method(globalThis, "fetch", async (_input: Parameters<typeof fetch>[0], options?: RequestInit) => {
    assert.equal(new Headers(options?.headers).get("authorization"), null);
    return Response.json({ jsonrpc: "2.0", id: 17, result: "0x1" });
  });
  const response = await POST(new Request("https://app.cybergold.io/api/rpc", {
    method: "POST",
    headers: { Authorization: "Bearer browser-input" },
    body: JSON.stringify(payload),
  }));
  assert.equal(response.status, 200);
  assert.equal(fetchMock.mock.callCount(), 1);
  fetchMock.mock.restore();
});

test("the public App route rejects writes before the private broker is called", async (t) => {
  const fetchMock = t.mock.method(globalThis, "fetch", async () => {
    throw new Error("the write must not reach the broker");
  });
  const response = await POST(new Request("https://app.cybergold.io/api/rpc", {
    method: "POST",
    body: JSON.stringify({ ...payload, method: "eth_sendRawTransaction", params: ["0x00"] }),
  }));
  assert.equal(response.status, 403);
  assert.equal(fetchMock.mock.callCount(), 0);
});

test("the App route hides broker authentication errors and makes no fallback request", async (t) => {
  const previousUrl = process.env.RPC_URL;
  const previousAuthorization = process.env.RPC_AUTHORIZATION;
  t.after(() => {
    if (previousUrl === undefined) delete process.env.RPC_URL;
    else process.env.RPC_URL = previousUrl;
    if (previousAuthorization === undefined) delete process.env.RPC_AUTHORIZATION;
    else process.env.RPC_AUTHORIZATION = previousAuthorization;
  });
  process.env.RPC_URL = "http://rpc-broker:19546";
  process.env.RPC_AUTHORIZATION = authorization;
  const fetchMock = t.mock.method(globalThis, "fetch", async () =>
    new Response(`private diagnostic: ${authorization}`, { status: 401 })
  );
  const response = await POST(new Request("https://app.cybergold.io/api/rpc", {
    method: "POST", body: JSON.stringify(payload),
  }));
  assert.equal(response.status, 502);
  const body = await response.text();
  assert.equal(body.includes(authorization), false);
  assert.equal(body.includes("rpc-broker"), false);
  assert.equal(fetchMock.mock.callCount(), 1);
});

test("sandbox rate limits pause the shared queue and retry the read once", async (t) => {
  const previousUrl = process.env.RPC_URL;
  t.after(() => {
    if (previousUrl === undefined) delete process.env.RPC_URL;
    else process.env.RPC_URL = previousUrl;
  });
  process.env.RPC_URL = "https://rpc.cybergold.io/";
  const pacer = sandboxRpcReadPacer(new URL(process.env.RPC_URL))!;
  const waitMock = t.mock.method(pacer, "wait", async () => {});
  const pauseMock = t.mock.method(pacer, "pause", () => {});
  const batch = [1, 2].map((id) => ({ ...payload, id, method: "eth_call", params: [{ to: "0x0000000000000000000000000000000000000001", data: "0x" }, "latest"] }));
  let attempts = 0;
  t.mock.method(globalThis, "fetch", async () => ++attempts === 1
    ? new Response("private gateway diagnostic", { status: 429, headers: { "Retry-After": "2" } })
    : Response.json(batch.map(({ id }) => ({ jsonrpc: "2.0", id, result: "0x" })))
  );
  const response = await POST(new Request("http://localhost/api/rpc", { method: "POST", body: JSON.stringify(batch) }));
  assert.equal(response.status, 200);
  assert.equal(attempts, 2);
  assert.deepEqual(waitMock.mock.calls.map((call) => call.arguments[0]), [2, 2]);
  assert.equal(pauseMock.mock.calls[0].arguments[0], 2_000);
});

test("persistent rate limits preserve batch IDs, HTTP 429 and Retry-After without private details", async (t) => {
  const previousUrl = process.env.RPC_URL;
  t.after(() => {
    if (previousUrl === undefined) delete process.env.RPC_URL;
    else process.env.RPC_URL = previousUrl;
  });
  process.env.RPC_URL = "https://rpc.cybergold.io/";
  const pacer = sandboxRpcReadPacer(new URL(process.env.RPC_URL))!;
  t.mock.method(pacer, "wait", async () => {});
  t.mock.method(pacer, "pause", () => {});
  const fetchMock = t.mock.method(globalThis, "fetch", async () =>
    new Response(authorization, { status: 429, headers: { "Retry-After": "3" } })
  );
  const batch = [payload, { ...payload, id: "second" }];
  const response = await POST(new Request("http://localhost/api/rpc", { method: "POST", body: JSON.stringify(batch) }));
  assert.equal(response.status, 429);
  assert.equal(response.headers.get("retry-after"), "3");
  assert.deepEqual(await response.json(), batch.map(({ id }) => ({ jsonrpc: "2.0", id, error: { code: -32005, message: "RPC rate limit reached. Please retry shortly." } })));
  assert.equal(fetchMock.mock.callCount(), 2);
});

test("a cooldown beyond the request timeout preserves 429 instead of attempting an impossible retry", async (t) => {
  const previousUrl = process.env.RPC_URL;
  t.after(() => {
    if (previousUrl === undefined) delete process.env.RPC_URL;
    else process.env.RPC_URL = previousUrl;
  });
  process.env.RPC_URL = "https://rpc.cybergold.io/";
  const pacer = sandboxRpcReadPacer(new URL(process.env.RPC_URL))!;
  t.mock.method(pacer, "wait", async () => {});
  const pauseMock = t.mock.method(pacer, "pause", () => {});
  const fetchMock = t.mock.method(globalThis, "fetch", async () =>
    new Response("private rate-limit diagnostic", { status: 429, headers: { "Retry-After": "20" } })
  );
  const response = await POST(new Request("http://localhost/api/rpc", { method: "POST", body: JSON.stringify(payload) }));
  assert.equal(response.status, 429);
  assert.equal(response.headers.get("retry-after"), "20");
  assert.deepEqual(await response.json(), {
    jsonrpc: "2.0", id: payload.id,
    error: { code: -32005, message: "RPC rate limit reached. Please retry shortly." },
  });
  assert.equal(fetchMock.mock.callCount(), 1);
  assert.equal(pauseMock.mock.calls[0].arguments[0], 20_000);
});

test("generic upstream failures preserve every ID in a batch", async (t) => {
  const previousUrl = process.env.RPC_URL;
  t.after(() => {
    if (previousUrl === undefined) delete process.env.RPC_URL;
    else process.env.RPC_URL = previousUrl;
  });
  process.env.RPC_URL = "http://rpc-broker:19546";
  t.mock.method(globalThis, "fetch", async () => new Response("private", { status: 503 }));
  const batch = [payload, { ...payload, id: 18 }];
  const response = await POST(new Request("http://localhost/api/rpc", { method: "POST", body: JSON.stringify(batch) }));
  assert.equal(response.status, 502);
  assert.deepEqual((await response.json()).map((item: { id: number }) => item.id), [17, 18]);
});
