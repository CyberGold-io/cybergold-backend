import assert from "node:assert/strict";
import test from "node:test";

import { POST } from "../api/safe/route.ts";
const SAFE_ADDRESS = "0x601dBc67EAb2822a3C44BdB6bbAB4147ad1F601D";

async function withFetch(
  fetchImpl: typeof fetch,
  action: () => Promise<void>
) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = fetchImpl;
  try {
    await action();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test("Safe proxy turns an unreadable successful upstream body into a retryable failure", async () => {
  const previousServiceUrl = process.env.SAFE_TX_SERVICE_URL;
  process.env.SAFE_TX_SERVICE_URL = "https://safe.example";
  const originalConsoleError = console.error;
  console.error = () => {};

  try {
    await withFetch(
      (async () =>
        new Response("{", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })) as typeof fetch,
      async () => {
        const response = await POST(
          new Request("https://app.example/api/safe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "safe-info", safeAddress: SAFE_ADDRESS }),
          })
        );
        const body = (await response.json()) as Record<string, unknown>;

        assert.equal(response.status, 502);
        assert.equal(body.error, "Failed to fetch Safe info.");
        assert.equal(typeof body.correlationId, "string");
      }
    );
  } finally {
    console.error = originalConsoleError;
    if (previousServiceUrl === undefined) {
      delete process.env.SAFE_TX_SERVICE_URL;
    } else {
      process.env.SAFE_TX_SERVICE_URL = previousServiceUrl;
    }
  }
});

test("Safe writes accept empty successful responses without resubmitting the signed payload", async () => {
  const previousServiceUrl = process.env.SAFE_TX_SERVICE_URL;
  process.env.SAFE_TX_SERVICE_URL = "https://safe.example";
  const originalConsoleError = console.error;
  console.error = () => {};
  const payload = { signature: "fixture-signature", nonce: 7 };
  const cases = [
    { status: 201, body: null, expectedStatus: 200, expectedBody: {} },
    { status: 201, body: " \r\n", expectedStatus: 200, expectedBody: {} },
    { status: 204, body: null, expectedStatus: 200, expectedBody: {} },
    { status: 201, body: '{"accepted":true}', expectedStatus: 200, expectedBody: { accepted: true } },
    { status: 201, body: "{", expectedStatus: 502 },
    { status: 422, body: null, expectedStatus: 422 },
  ];

  try {
    for (const action of ["propose-transaction", "confirm-transaction"]) {
      for (const entry of cases) {
        let calls = 0;
        await withFetch((async (_url, init) => {
          calls++;
          assert.equal(init?.method, "POST");
          assert.deepEqual(JSON.parse(String(init?.body)), payload);
          return new Response(entry.body, { status: entry.status });
        }) as typeof fetch, async () => {
          const response = await POST(new Request("https://app.example/api/safe", {
            method: "POST",
            body: JSON.stringify({ action, safeAddress: SAFE_ADDRESS,
              safeTxHash: "0x" + "b".repeat(64), payload }),
          }));
          const body = await response.json();
          assert.equal(response.status, entry.expectedStatus, `${action}: ${entry.status}`);
          assert.equal(response.headers.get("cache-control"), "no-store");
          if (entry.expectedBody !== undefined) assert.deepEqual(body, entry.expectedBody);
          else {
            assert.equal(body.error, action === "propose-transaction"
              ? "Failed to propose multisig transaction." : "Failed to confirm multisig transaction.");
            assert.equal(typeof body.correlationId, "string");
          }
        });
        assert.equal(calls, 1, "signed writes must never be retried by the proxy");
      }
    }
  } finally {
    console.error = originalConsoleError;
    if (previousServiceUrl === undefined) delete process.env.SAFE_TX_SERVICE_URL;
    else process.env.SAFE_TX_SERVICE_URL = previousServiceUrl;
  }
});
