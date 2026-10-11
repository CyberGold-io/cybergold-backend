import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createBackendServer } from "../src/http-server.ts";

const { fixtures } = JSON.parse(readFileSync(new URL("./contracts/next-baseline.json", import.meta.url), "utf8"));
const headersToKeep = ["content-type", "cache-control", "retry-after", "x-cybergold-faucet-request-id"];

test("extracted handlers match captured production Next responses", async () => {
  const api = await createBackendServer("api", { logger: false });
  try {
    for (const fixture of fixtures) {
      const { request, response: expected } = fixture;
      // Next remains the public method router; these are handler-level fixtures.
      if (!["GET", "POST"].includes(request.method) || expected.status === 405) continue;
      const response = await api.inject({ method: request.method as "GET" | "POST", url: request.path,
        headers: request.headers ?? {}, ...(request.body === undefined ? {} : { payload: request.body }) });
      let body = response.body;
      try {
        const parsed = JSON.parse(body);
        if (request.path === "/api/faucet" && expected.status === 403) {
          // The faucet adds stable diagnostics to the original captured error envelope.
          assert.equal(parsed.code, "DISABLED");
          assert.match(parsed.correlationId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
          assert.deepEqual(Object.keys(parsed).sort(), ["code", "correlationId", "error"]);
          body = JSON.stringify({ error: parsed.error });
        } else if (parsed?.correlationId) { parsed.correlationId = "<correlation-id>"; body = JSON.stringify(parsed); }
      } catch {}
      assert.deepEqual({ status: response.statusCode,
        headers: Object.fromEntries(headersToKeep.filter(name => name in response.headers).map(name => [name, response.headers[name]])), body,
      }, expected, JSON.stringify(request));
    }
  } finally { await api.close(); }
});
