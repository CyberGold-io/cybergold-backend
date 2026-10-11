import assert from "node:assert/strict";
import test from "node:test";

import { publicApiError } from "../server/public-api-errors.ts";

test("unexpected public API failures redact lower-level details", async () => {
  const secret = "InternalDatabaseCredentialAlphaNumeric987654321";
  const originalConsoleError = console.error;
  const logged: unknown[][] = [];
  console.error = (...args: unknown[]) => {
    logged.push(args);
  };

  try {
    const lowerLevelError = new Error(secret);
    lowerLevelError.name = secret;
    lowerLevelError.stack = `Error: ${secret}\n    at ${secret}`;
    lowerLevelError.cause = { credential: secret };
    const response = publicApiError("Service temporarily unavailable.", {
      context: "redaction-test",
      error: lowerLevelError,
      status: 503,
    });
    const body = (await response.json()) as {
      error: string;
      correlationId: string;
    };

    assert.equal(response.status, 503);
    assert.equal(body.error, "Service temporarily unavailable.");
    assert.match(
      body.correlationId,
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
    );
    assert.doesNotMatch(JSON.stringify(body), new RegExp(secret));
    assert.doesNotMatch(JSON.stringify(logged), new RegExp(secret));
    assert.match(JSON.stringify(logged), /redaction-test/);
    assert.match(JSON.stringify(logged), /unexpected-error/);
  } finally {
    console.error = originalConsoleError;
  }
});

test("public API failures reject non-error upstream statuses", async () => {
  const originalConsoleError = console.error;
  console.error = () => {};
  try {
    for (const status of [200, 304, 399, 600, Number.NaN]) {
      const response = publicApiError("Service temporarily unavailable.", {
        context: "invalid-status-test",
        status,
      });
      assert.equal(response.status, 500);
      assert.deepEqual(
        Object.keys((await response.json()) as Record<string, unknown>).sort(),
        ["correlationId", "error"]
      );
    }
  } finally {
    console.error = originalConsoleError;
  }
});
