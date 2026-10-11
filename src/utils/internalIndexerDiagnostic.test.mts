import assert from "node:assert/strict";
import test from "node:test";

import { internalIndexerDiagnostic } from "../server/onchain-indexer/internalIndexerDiagnostic.ts";

test("indexer diagnostics retain bounded operational messages", () => {
  assert.equal(
    internalIndexerDiagnostic(
      new Error("Address-scoped log request failed for one block")
    ),
    "Address-scoped log request failed for one block"
  );
});

test("indexer diagnostics redact URLs, credentials, and opaque tokens", () => {
  for (const message of [
    "request to https://provider.invalid/key/secret failed",
    "Bearer internal-worker-token-value-must-not-leak",
    "database_url=postgresql://user:password@db.invalid/app",
    "InternalDatabaseCredentialAlphaNumeric987654321",
  ]) {
    assert.equal(
      internalIndexerDiagnostic(new Error(message)),
      "unexpected-worker-error"
    );
  }
});

test("indexer diagnostics do not stringify unexpected thrown values", () => {
  assert.equal(internalIndexerDiagnostic({ message: "safe-looking" }), "unexpected-worker-error");
});

test("indexer diagnostics use a safe library short message when its full message is redacted", () => {
  const error = Object.assign(
    new Error("HTTP request failed for https://provider.example/secret"),
    { shortMessage: "HTTP request failed" }
  );

  assert.equal(internalIndexerDiagnostic(error), "HTTP request failed");
});
