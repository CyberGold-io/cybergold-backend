import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createBackendServer } from "../src/http-server.ts";

const { fixtures } = JSON.parse(readFileSync(new URL("./contracts/private-next-baseline.json", import.meta.url), "utf8"));
const headersToKeep = ["content-type", "cache-control", "retry-after"];

test("worker HTTP preserves captured Next authorization and raw parser responses", async () => {
  const originalToken = process.env.ONCHAIN_INDEXER_WORKER_TOKEN;
  const originalDatabase = process.env.DATABASE_URL;
  delete process.env.DATABASE_URL;
  const worker = await createBackendServer("worker", { logger: false });
  try {
    for (const { configuredToken, request, response: expected } of fixtures) {
      if (configuredToken === null) delete process.env.ONCHAIN_INDEXER_WORKER_TOKEN;
      else process.env.ONCHAIN_INDEXER_WORKER_TOKEN = configuredToken;
      const response = await worker.inject({
        method: request.method, url: request.path, headers: request.headers,
        ...(request.body === undefined ? {} : { payload: request.body }),
      });
      assert.deepEqual({
        status: response.statusCode,
        headers: Object.fromEntries(headersToKeep.filter(name => name in response.headers)
          .map(name => [name, response.headers[name]])),
        body: response.body,
      }, expected, `${request.method} ${request.path}; configured token length ${configuredToken?.length ?? 0}; body ${JSON.stringify(request.body)?.slice(0, 100)}`);
    }
    assert.equal(globalThis.__cybergoldDashboardPgPool, undefined,
      "authentication and parser failures must not open a database");
  } finally {
    await worker.close();
    if (originalToken === undefined) delete process.env.ONCHAIN_INDEXER_WORKER_TOKEN;
    else process.env.ONCHAIN_INDEXER_WORKER_TOKEN = originalToken;
    if (originalDatabase === undefined) delete process.env.DATABASE_URL;
    else process.env.DATABASE_URL = originalDatabase;
  }
});
