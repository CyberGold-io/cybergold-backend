import assert from "node:assert/strict";
import { test } from "node:test";
import { Writable } from "node:stream";
import { createBackendServer } from "../src/http-server.ts";
import { projectClientDiagnostic } from "../src/server/clientDiagnostics.ts";

test("diagnostics never serialize arbitrary fields, messages, credentials or malformed identifiers", () => {
  assert.deepEqual(projectClientDiagnostic({ operation: "swap", outcome: "failed", reason: "unknown",
    message: "Bearer secret", signature: "0xabc", payload: { password: "secret" }, address: "wallet",
    attemptId: "Bearer secret", transactionHash: "secret", durationMs: Infinity, route: "https://secret",
  }), { operation: "swap", outcome: "failed", reason: "unknown" });
  for (const value of [null, [], "Bearer secret", 1]) assert.deepEqual(projectClientDiagnostic(value), {});
});

test("diagnostics retain signed safe codes and only the four-byte selector", () => {
  for (const errorCode of [-32603, 4001, 0, -Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER]) {
    assert.deepEqual(projectClientDiagnostic({ errorCode, errorSelector: "0xAbCd0123", raw: "private raw error",
      args: ["private argument"], data: "0xAbCd0123" + "ab".repeat(32) }), { errorCode, errorSelector: "0xabcd0123" });
  }
  for (const errorCode of [true, false, "-32603", null, {}, 1.5, NaN, Infinity,
    -Infinity, Number.MAX_SAFE_INTEGER + 1, -Number.MAX_SAFE_INTEGER - 1]) {
    assert.deepEqual(projectClientDiagnostic({ errorCode, errorSelector: "0x12345678" }), { errorSelector: "0x12345678" });
  }
  for (const errorSelector of [true, null, {}, "12345678", "0X12345678", "0x", "0x1234567", "0x123456789",
    "0x1234567z", "0x12345678\n", "0x12345678" + "ab".repeat(32)]) {
    assert.deepEqual(projectClientDiagnostic({ errorCode: -32603, errorSelector }), { errorCode: -32603 });
  }
});

test("real API emits only projected diagnostic fields and retains ordinary JSON errors", async () => {
  let output = "";
  const stream = new Writable({ write(chunk, _encoding, done) { output += chunk.toString(); done(); } });
  const api = await createBackendServer("api", { logger: { stream } });
  try {
    const response = await api.inject({ method: "POST", url: "/api/diagnostics", headers: { authorization: "Bearer never-log-me" },
      payload: { operation: "swap", outcome: "submitted", attemptId: "2bebd34c-c513-4ff7-928b-3b1a526768a3",
        transactionHash: `0x${"a".repeat(64)}`, durationMs: 312, direction: "issue", errorCode: -32603,
        errorSelector: "0xAbCd0123", raw: "never-log-me", errorArgs: ["never-log-me"], signature: "never-log-me" } });
    assert.equal(response.statusCode, 202);
    assert.equal(response.headers["cache-control"], "no-store");
    assert.equal(output.includes("never-log-me"), false);
    const event = output.trim().split("\n").map(line => JSON.parse(line)).find(line => line.event === "client_diagnostic");
    assert.equal(event.source, "browser");
    assert.equal(event.durationMs, 312);
    assert.equal(event.transactionHash, `0x${"a".repeat(64)}`);
    assert.equal(event.errorCode, -32603);
    assert.equal(event.errorSelector, "0xabcd0123");
    const invalid = await api.inject({ method: "POST", url: "/api/diagnostics", payload: {
      operation: "swap", outcome: "failed", errorCode: true, errorSelector: `0x12345678${"ab".repeat(32)}`,
      error: { message: "never-log-me", data: "never-log-me" },
    } });
    assert.equal(invalid.statusCode, 202);
    assert.deepEqual(invalid.json(), { accepted: true });
    const invalidEvent = output.trim().split("\n").map(line => JSON.parse(line)).filter(line => line.event === "client_diagnostic").at(-1);
    assert.equal(invalidEvent.outcome, "failed");
    assert.equal("errorCode" in invalidEvent, false);
    assert.equal("errorSelector" in invalidEvent, false);
    assert.equal((await api.inject({ method: "POST", url: "/api/diagnostics", payload: "{", headers: { "content-type": "application/json" } })).statusCode, 400);
    assert.equal((await api.inject({ method: "POST", url: "/api/diagnostics", payload: `"${"x".repeat(1024 * 1024)}"`, headers: { "content-type": "application/json" } })).statusCode, 413);
    assert.equal((await api.inject({ method: "POST", url: "/api/diagnostics", payload: { unexpected: "never-log-me" } })).statusCode, 202);
    assert.equal(output.includes("never-log-me"), false);
  } finally { await api.close(); }
  const worker = await createBackendServer("worker", { logger: false });
  try { assert.equal((await worker.inject({ method: "POST", url: "/api/diagnostics", payload: {} })).statusCode, 404); }
  finally { await worker.close(); }
});
