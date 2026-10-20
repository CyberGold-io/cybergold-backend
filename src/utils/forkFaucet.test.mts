import assert from "node:assert/strict";
import test from "node:test";

import { POST, createFaucetPostHandler } from "../api/faucet/route.ts";
import {
  ForkFaucetError,
  fundForkWallet,
  type FaucetErrorCode,
  type FaucetSuccessPayload,
} from "../server/faucet/forkFaucet.ts";

const ADDRESS = "0x0000000000000000000000000000000000000001";
const REQUEST_ID = "123e4567-e89b-42d3-a456-426614174000";
const SERVICE_URL = "http://127.0.0.1:43123/fund";
const SERVICE_TOKEN = "a".repeat(64);
const APP_ORIGIN = "https://sandbox.example";
const SUCCESS_PAYLOAD: FaucetSuccessPayload = {
  status: "ok",
  address: ADDRESS,
  ethWei: "10000000000000000000",
  tokens: [
    { symbol: "PAXG", amount: "5000000000000000000" },
    { symbol: "USDC", amount: "10000000000" },
  ],
  dryRun: false,
};

const MANAGED_ENV_KEYS = [
  "FORK_FAUCET_ENABLED",
  "FORK_FAUCET_SERVICE_TOKEN",
  "FORK_FAUCET_SERVICE_URL",
  "NEXT_PUBLIC_APP_ORIGIN",
  "NODE_ENV",
  "SECRET_SHOULD_NOT_LEAK",
] as const;

async function withEnvironment(
  values: Partial<Record<(typeof MANAGED_ENV_KEYS)[number], string>>,
  run: () => Promise<void>
) {
  const previous = new Map<string, string | undefined>();
  for (const key of MANAGED_ENV_KEYS) {
    previous.set(key, process.env[key]);
    delete process.env[key];
  }
  Object.assign(process.env, values);

  try {
    await run();
  } finally {
    for (const key of MANAGED_ENV_KEYS) {
      const value = previous.get(key);
      if (value === undefined) {
        delete process.env[key];
      } else {
        Reflect.set(process.env, key, value);
      }
    }
  }
}

function adapterEnvironment(
  overrides: Record<string, string> = {}
): Record<string, string> {
  return {
    FORK_FAUCET_ENABLED: "1",
    FORK_FAUCET_SERVICE_TOKEN: SERVICE_TOKEN,
    FORK_FAUCET_SERVICE_URL: SERVICE_URL,
    NODE_ENV: "production",
    ...overrides,
  };
}

function routeRequest(
  body: unknown,
  headerOverrides: Record<string, string> = {},
  rawBody = false
) {
  return new Request(`${APP_ORIGIN}/api/faucet`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Origin: APP_ORIGIN,
      "X-Real-IP": "203.0.113.7",
      "X-Forwarded-For": "203.0.113.7",
      ...headerOverrides,
    },
    body: rawBody ? String(body) : JSON.stringify(body),
  });
}

async function assertFaucetError(
  action: () => Promise<unknown>,
  code: ForkFaucetError["code"],
  status: number,
  forbiddenText?: string
) {
  await assert.rejects(action, (error: unknown) => {
    assert.ok(error instanceof ForkFaucetError);
    assert.equal(error.code, code);
    assert.equal(error.status, status);
    if (forbiddenText) {
      assert.doesNotMatch(error.message, new RegExp(forbiddenText));
    }
    return true;
  });
}

async function assertRouteError(response: Response, error: string, code: FaucetErrorCode) {
  const payload = await response.json() as { error: string; code: string; correlationId: string };
  assert.deepEqual(Object.keys(payload).sort(), ["code", "correlationId", "error"]);
  assert.equal(payload.error, error);
  assert.equal(payload.code, code);
  assert.match(payload.correlationId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.notEqual(payload.correlationId, REQUEST_ID, "diagnostic correlation is distinct from funding idempotency");
  return payload;
}

test("adapter sends only the authenticated, idempotent funding contract", async () => {
  await withEnvironment(
    adapterEnvironment({ SECRET_SHOULD_NOT_LEAK: "internal-secret-value" }),
    async () => {
      let calls = 0;
      const fetchImpl = (async (input: URL | RequestInfo, init?: RequestInit) => {
        calls += 1;
        assert.equal(String(input), SERVICE_URL);
        assert.equal(init?.method, "POST");
        assert.equal(init?.cache, "no-store");
        assert.equal(init?.credentials, "omit");
        assert.equal(init?.redirect, "error");
        assert.ok(init?.signal instanceof AbortSignal);

        const headers = Object.fromEntries(new Headers(init?.headers).entries());
        assert.deepEqual(headers, {
          accept: "application/json",
          authorization: `Bearer ${SERVICE_TOKEN}`,
          "content-type": "application/json",
        });
        assert.doesNotMatch(JSON.stringify(headers), /internal-secret-value/);

        assert.equal(typeof init?.body, "string");
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        assert.deepEqual(Object.keys(body), ["address", "requestId", "requesterIp"]);
        assert.deepEqual(body, {
          address: ADDRESS,
          requestId: REQUEST_ID,
          requesterIp: "203.0.113.7",
        });
        assert.doesNotMatch(JSON.stringify(body), /internal-secret-value/);
        return Response.json(SUCCESS_PAYLOAD);
      }) as typeof fetch;

      const result = await fundForkWallet(
        ADDRESS,
        { requestId: REQUEST_ID, requesterIp: "203.0.113.7" },
        { fetchImpl }
      );

      assert.equal(calls, 1);
      assert.deepEqual(result, SUCCESS_PAYLOAD);
    }
  );
});

test("adapter has a bounded timeout with a stable public error", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const fetchImpl = ((_input: URL | RequestInfo, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("backend details", "AbortError")),
          { once: true }
        );
      })) as typeof fetch;

    await assertFaucetError(
      () =>
        fundForkWallet(
          ADDRESS,
          { requestId: REQUEST_ID, requesterIp: "203.0.113.7" },
          { fetchImpl, adapterTimeoutMs: 5 }
        ),
      "TIMEOUT",
      504,
      "backend details"
    );
  });
});

test("adapter accepts only the exact live success response schema", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const invalidPayloads: unknown[] = [
      { ...SUCCESS_PAYLOAD, internal: "do-not-leak" },
      { ...SUCCESS_PAYLOAD, dryRun: true },
      { ...SUCCESS_PAYLOAD, address: "0x0000000000000000000000000000000000000002" },
      {
        ...SUCCESS_PAYLOAD,
        tokens: [{ symbol: "USDC", amount: "1", internal: "do-not-leak" }],
      },
      {
        ...SUCCESS_PAYLOAD,
        tokens: [
          { symbol: "USDC", amount: "1" },
          { symbol: "usdc", amount: "2" },
        ],
      },
      { ...SUCCESS_PAYLOAD, ethWei: `${1n << 256n}` },
    ];

    for (const payload of invalidPayloads) {
      const fetchImpl = (async () => Response.json(payload)) as typeof fetch;
      await assertFaucetError(
        () =>
          fundForkWallet(
            ADDRESS,
            { requestId: REQUEST_ID, requesterIp: "203.0.113.7" },
            { fetchImpl }
          ),
        "INVALID_RESPONSE",
        502,
        "do-not-leak"
      );
    }

    const wrongContentType = (async () =>
      new Response(JSON.stringify(SUCCESS_PAYLOAD), {
        headers: { "Content-Type": "text/plain" },
      })) as typeof fetch;
    await assertFaucetError(
      () =>
        fundForkWallet(
          ADDRESS,
          { requestId: REQUEST_ID, requesterIp: "203.0.113.7" },
          { fetchImpl: wrongContentType }
        ),
      "INVALID_RESPONSE",
      502
    );
  });
});

test("adapter maps upstream statuses and preserves request ID retry disposition", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const backendSecret = "backend-auth-secret";
    const mappings = [
      [400, "INVALID_ADDRESS", "REQUEST_REJECTED", 400, "retain"],
      [401, "UNAUTHORIZED", "AUTHENTICATION_FAILED", 502, "retain"],
      [404, "NOT_FOUND", "BAD_GATEWAY", 502, "retain"],
      [405, "METHOD_NOT_ALLOWED", "BAD_GATEWAY", 502, "retain"],
      [408, "REQUEST_TIMEOUT", "TIMEOUT", 504, "retain"],
      [409, "REQUEST_ID_CONFLICT", "REQUEST_CONFLICT", 409, "replace"],
      [409, "REQUEST_IN_PROGRESS", "REQUEST_IN_PROGRESS", 409, "retain"],
      [409, "REQUEST_UNCERTAIN", "REQUEST_UNCERTAIN", 409, "replace"],
      [411, "LENGTH_REQUIRED", "BAD_GATEWAY", 502, "retain"],
      [413, "REQUEST_TOO_LARGE", "BAD_GATEWAY", 502, "retain"],
      [415, "UNSUPPORTED_MEDIA_TYPE", "BAD_GATEWAY", 502, "retain"],
      [429, "RATE_LIMITED", "RATE_LIMITED", 429, "retain"],
      [429, "ADDRESS_QUOTA_EXHAUSTED", "ADDRESS_QUOTA_EXHAUSTED", 429, "retain"],
      [429, "IP_QUOTA_EXHAUSTED", "IP_QUOTA_EXHAUSTED", 429, "retain"],
      [429, "GLOBAL_QUOTA_EXHAUSTED", "GLOBAL_QUOTA_EXHAUSTED", 429, "retain"],
      [500, "INTERNAL_ERROR", "BAD_GATEWAY", 502, "retain"],
      [502, "FUNDING_FAILED", "FUNDING_FAILED", 502, "replace"],
      [503, "CHAIN_UNAVAILABLE", "CHAIN_UNAVAILABLE", 503, "retain"],
    ] as const;

    for (const [upstreamStatus, upstreamCode, code, publicStatus, disposition] of mappings) {
      const fetchImpl = (async () =>
        Response.json(
          { error: { code: upstreamCode, message: backendSecret } },
          {
            status: upstreamStatus,
            headers: upstreamStatus === 429 ? { "Retry-After": "45" } : undefined,
          }
        )) as typeof fetch;
      await assert.rejects(
        () =>
          fundForkWallet(
            ADDRESS,
            { requestId: REQUEST_ID, requesterIp: "203.0.113.7" },
            { fetchImpl }
          ),
        (error: unknown) => {
          assert.ok(error instanceof ForkFaucetError);
          assert.equal(error.code, code);
          assert.equal(error.status, publicStatus);
          assert.equal(error.requestIdDisposition, disposition);
          assert.equal(error.retryAfterSeconds, upstreamStatus === 429 ? 45 : undefined);
          assert.equal(error.diagnostics?.httpStatus, upstreamStatus);
          assert.equal(error.diagnostics?.upstreamErrorCode, upstreamCode);
          assert.equal(error.diagnostics?.failureType, "http-error");
          assert.doesNotMatch(error.message, new RegExp(backendSecret));
          return true;
        }
      );
    }
  });
});

test("adapter rejects malformed error envelopes instead of trusting their status", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const malformedResponses = [
      new Response("backend stack trace", {
        status: 503,
        headers: { "Content-Type": "text/plain" },
      }),
      Response.json({ error: { code: "INTERNAL", message: "safe", extra: true } }, { status: 503 }),
      Response.json({ error: { code: "bad code", message: "safe" } }, { status: 429 }),
      Response.json({ error: { code: "UNAUTHORIZED", message: "safe" } }, { status: 429 }),
    ];

    for (const backendResponse of malformedResponses) {
      const fetchImpl = (async () => backendResponse) as typeof fetch;
      await assertFaucetError(
        () =>
          fundForkWallet(
            ADDRESS,
            { requestId: REQUEST_ID, requesterIp: "203.0.113.7" },
            { fetchImpl }
          ),
        "INVALID_RESPONSE",
        502,
        "backend stack trace"
      );
    }
  });
});

test("adapter refuses partial or unsafe service configuration", async () => {
  const invalidConfigurations = [
    { FORK_FAUCET_SERVICE_URL: SERVICE_URL },
    { FORK_FAUCET_SERVICE_TOKEN: SERVICE_TOKEN },
    {
      FORK_FAUCET_SERVICE_URL: "http://localhost:43123/fund",
      FORK_FAUCET_SERVICE_TOKEN: SERVICE_TOKEN,
    },
    {
      FORK_FAUCET_SERVICE_URL: "http://127.0.0.1:43123/fund?mode=unsafe",
      FORK_FAUCET_SERVICE_TOKEN: SERVICE_TOKEN,
    },
    {
      FORK_FAUCET_SERVICE_URL: SERVICE_URL,
      FORK_FAUCET_SERVICE_TOKEN: SERVICE_TOKEN.toUpperCase(),
    },
  ];

  for (const configuration of invalidConfigurations) {
    await withEnvironment(
      {
        FORK_FAUCET_ENABLED: "1",
        NODE_ENV: "production",
        ...configuration,
      },
      async () => {
        let called = false;
        const fetchImpl = (async () => {
          called = true;
          return Response.json(SUCCESS_PAYLOAD);
        }) as typeof fetch;
        await assertFaucetError(
          () =>
            fundForkWallet(
              ADDRESS,
              { requestId: REQUEST_ID, requesterIp: "203.0.113.7" },
              { fetchImpl }
            ),
          "CONFIGURATION_ERROR",
          503
        );
        assert.equal(called, false);
      }
    );
  }
});

test("disabled faucet fails before adapter configuration or network access", async () => {
  await withEnvironment(
    adapterEnvironment({ FORK_FAUCET_ENABLED: "0" }),
    async () => {
      let called = false;
      const fetchImpl = (async () => {
        called = true;
        return Response.json(SUCCESS_PAYLOAD);
      }) as typeof fetch;
      await assertFaucetError(
        () =>
          fundForkWallet(
            ADDRESS,
            { requestId: REQUEST_ID, requesterIp: "203.0.113.7" },
            { fetchImpl }
          ),
        "DISABLED",
        403
      );
      assert.equal(called, false);

      const response = await POST(new Request(`${APP_ORIGIN}/api/faucet`, { method: "POST" }));
      assert.equal(response.status, 403);
      await assertRouteError(response, "Fork faucet is disabled.", "DISABLED");
    }
  );
});

test("faucet handler accepts localhost or absent Origin behind the API bearer boundary", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const previousFetch = globalThis.fetch;
    globalThis.fetch = (async () => Response.json(SUCCESS_PAYLOAD)) as typeof fetch;
    try {
      for (const origin of ["http://localhost:3000", "https://sandbox.example", ""]) {
        const response = await POST(routeRequest(
          { address: ADDRESS, requestId: REQUEST_ID }, { Origin: origin }
        ));
        assert.equal(response.status, 200);
        assert.deepEqual(await response.json(), SUCCESS_PAYLOAD);
      }
    } finally { globalThis.fetch = previousFetch; }
  });
});

test("enabled route requires JSON and an exact bounded request object", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const wrongContentType = await POST(
      routeRequest(
        { address: ADDRESS, requestId: REQUEST_ID },
        { "Content-Type": "text/plain" }
      )
    );
    assert.equal(wrongContentType.status, 415);
    await assertRouteError(wrongContentType, "Content-Type must be application/json.", "UNSUPPORTED_MEDIA_TYPE");

    const invalidBodies = [
      null,
      [],
      { address: ADDRESS },
      { address: ADDRESS, requestId: REQUEST_ID, requesterIp: "203.0.113.9" },
      { address: ADDRESS, requestId: REQUEST_ID, unexpected: true },
      { address: ADDRESS, requestId: REQUEST_ID.toUpperCase() },
    ];
    for (const body of invalidBodies) {
      const response = await POST(routeRequest(body));
      assert.equal(response.status, 400);
      await assertRouteError(response, "Invalid request body.", "INVALID_REQUEST");
    }

    const declaredTooLarge = await POST(
      routeRequest(
        { address: ADDRESS, requestId: REQUEST_ID },
        { "Content-Length": "513" }
      )
    );
    assert.equal(declaredTooLarge.status, 413);
    await assertRouteError(declaredTooLarge, "Faucet request body is too large.", "REQUEST_TOO_LARGE");

    const actualTooLarge = await POST(routeRequest("x".repeat(513), {}, true));
    assert.equal(actualTooLarge.status, 413);
    await assertRouteError(actualTooLarge, "Faucet request body is too large.", "REQUEST_TOO_LARGE");
  });
});

test("adapter route requires matching normalized trusted forwarding headers", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const previousFetch = globalThis.fetch;
    const requesterIps: string[] = [];
    globalThis.fetch = (async (_input: URL | RequestInfo, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { requesterIp: string };
      requesterIps.push(body.requesterIp);
      return Response.json(SUCCESS_PAYLOAD);
    }) as typeof fetch;

    try {
      const realIpResponse = await POST(
        routeRequest(
          { address: ADDRESS, requestId: REQUEST_ID },
          {
            "X-Real-IP": "2001:0DB8:0:0:0:0:0:1",
            "X-Forwarded-For": "2001:db8::1",
          }
        )
      );
      assert.equal(realIpResponse.status, 200);

      const mismatchedResponse = await POST(
        routeRequest(
          { address: ADDRESS, requestId: "f47ac10b-58cc-4372-a567-0e02b2c3d479" },
          {
            "X-Real-IP": "203.0.113.18",
            "X-Forwarded-For": "203.0.113.19, 10.0.0.2",
          }
        )
      );
      assert.equal(mismatchedResponse.status, 400);
      await assertRouteError(mismatchedResponse, "Requester IP is unavailable.", "INVALID_REQUESTER_IP");

      const missingRealIpResponse = await POST(
        new Request(`${APP_ORIGIN}/api/faucet`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            Origin: APP_ORIGIN,
            "X-Forwarded-For": "203.0.113.19, 10.0.0.2",
          },
          body: JSON.stringify({
            address: ADDRESS,
            requestId: "f47ac10b-58cc-4372-a567-0e02b2c3d479",
          }),
        })
      );
      assert.equal(missingRealIpResponse.status, 400);
      await assertRouteError(missingRealIpResponse, "Requester IP is unavailable.", "INVALID_REQUESTER_IP");
      assert.deepEqual(requesterIps, ["2001:db8::1"]);
    } finally {
      globalThis.fetch = previousFetch;
    }
  });
});

test("route maps adapter failures to safe statuses and never returns backend text", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const previousFetch = globalThis.fetch;
    const backendSecret = "upstream-debug-trace-secret";
    const mappings = [
      [400, "INVALID_ADDRESS", 400, null, "REQUEST_REJECTED"],
      [401, "UNAUTHORIZED", 502, null, "AUTHENTICATION_FAILED"],
      [408, "REQUEST_TIMEOUT", 504, null, "TIMEOUT"],
      [409, "REQUEST_ID_CONFLICT", 409, "replace", "REQUEST_CONFLICT"],
      [409, "REQUEST_IN_PROGRESS", 409, null, "REQUEST_IN_PROGRESS"],
      [409, "REQUEST_UNCERTAIN", 409, "replace", "REQUEST_UNCERTAIN"],
      [429, "RATE_LIMITED", 429, null, "RATE_LIMITED"],
      [429, "ADDRESS_QUOTA_EXHAUSTED", 429, null, "ADDRESS_QUOTA_EXHAUSTED"],
      [429, "IP_QUOTA_EXHAUSTED", 429, null, "IP_QUOTA_EXHAUSTED"],
      [429, "GLOBAL_QUOTA_EXHAUSTED", 429, null, "GLOBAL_QUOTA_EXHAUSTED"],
      [500, "INTERNAL_ERROR", 502, null, "BAD_GATEWAY"],
      [502, "FUNDING_FAILED", 502, "replace", "FUNDING_FAILED"],
      [503, "CHAIN_UNAVAILABLE", 503, null, "CHAIN_UNAVAILABLE"],
    ] as const;

    try {
      for (const [upstreamStatus, upstreamCode, expectedStatus, disposition, code] of mappings) {
        globalThis.fetch = (async () =>
          Response.json(
            { error: { code: upstreamCode, message: backendSecret } },
            { status: upstreamStatus, headers: upstreamStatus === 429 ? { "Retry-After": "45" } : undefined }
          )) as typeof fetch;
        const response = await POST(
          routeRequest({ address: ADDRESS, requestId: REQUEST_ID })
        );
        assert.equal(response.status, expectedStatus);
        const payload = await response.clone().json() as { error: string };
        await assertRouteError(response, payload.error, code);
        assert.doesNotMatch(JSON.stringify(payload), new RegExp(backendSecret));
        assert.equal(response.headers.get("retry-after"), upstreamStatus === 429 ? "45" : null);
        assert.equal(response.headers.get("cache-control"), "no-store");
        assert.equal(
          response.headers.get("x-cybergold-faucet-request-id"),
          disposition
        );
      }
    } finally {
      globalThis.fetch = previousFetch;
    }
  });
});

test("route correlates bounded adapter diagnostics without exposing funding context or private text", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const previousConsoleError = console.error;
    const logs: unknown[][] = [];
    console.error = (...args: unknown[]) => { logs.push(args); };
    const privateText = `${SERVICE_URL} ${SERVICE_TOKEN} ${ADDRESS} 203.0.113.7 private-error-text`;
    const cases = [
      {
        fetchImpl: (async () => { throw new TypeError(privateText); }) as typeof fetch,
        code: "BAD_GATEWAY", message: "Fork faucet is temporarily unavailable.",
        failureType: "transport-error", httpStatus: undefined, upstreamErrorCode: undefined,
      },
      {
        fetchImpl: ((_input: URL | RequestInfo, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error(privateText)), { once: true });
        })) as typeof fetch,
        code: "TIMEOUT", message: "Fork faucet request timed out.",
        failureType: "backend-deadline", httpStatus: undefined, upstreamErrorCode: undefined,
      },
      {
        fetchImpl: (async () => Response.json({ error: { code: "CHAIN_UNAVAILABLE", message: privateText, extra: true } }, { status: 503 })) as typeof fetch,
        code: "INVALID_RESPONSE", message: "Fork faucet is temporarily unavailable.",
        failureType: "invalid-response", httpStatus: 503, upstreamErrorCode: undefined,
      },
      {
        fetchImpl: (async () => Response.json({ error: { code: "REQUEST_UNCERTAIN", message: privateText } }, { status: 409 })) as typeof fetch,
        code: "REQUEST_UNCERTAIN", message: "Fork faucet funding could not be confirmed.",
        failureType: "http-error", httpStatus: 409, upstreamErrorCode: "REQUEST_UNCERTAIN",
      },
    ] as const;
    try {
      for (const scenario of cases) {
        const post = createFaucetPostHandler({
          fundWallet: (address, context) => fundForkWallet(address, context, { fetchImpl: scenario.fetchImpl, adapterTimeoutMs: 5 }),
        });
        const response = await post(routeRequest({ address: ADDRESS, requestId: REQUEST_ID }));
        const body = await assertRouteError(response, scenario.message, scenario.code);
        assert.equal(logs.length, 1);
        const [message, metadata] = logs.pop()! as [string, Record<string, unknown>];
        assert.equal(message, "[fork-faucet] request failed");
        assert.equal(metadata.correlationId, body.correlationId);
        assert.equal(metadata.code, body.code);
        assert.equal(metadata.stage, "faucet-adapter");
        assert.equal(metadata.failureType, scenario.failureType);
        assert.equal(metadata.httpStatus, scenario.httpStatus);
        assert.equal(metadata.upstreamErrorCode, scenario.upstreamErrorCode);
        assert.equal(typeof metadata.elapsedMs, "number");
        assert.ok(Number.isInteger(metadata.elapsedMs) && Number(metadata.elapsedMs) >= 0);
        const serialized = JSON.stringify({ body, metadata });
        for (const forbidden of [SERVICE_URL, SERVICE_TOKEN, ADDRESS, "203.0.113.7", "private-error-text", REQUEST_ID]) {
          assert.ok(!serialized.includes(forbidden), `private value escaped: ${forbidden}`);
        }
      }
      const post = createFaucetPostHandler({ fundWallet: async () => { throw new Error(privateText); } });
      const response = await post(routeRequest({ address: ADDRESS, requestId: REQUEST_ID }));
      const body = await assertRouteError(response, "Fork faucet is temporarily unavailable.", "INTERNAL_ERROR");
      assert.equal(response.status, 500);
      const [, metadata] = logs.pop()! as [string, Record<string, unknown>];
      assert.equal(metadata.correlationId, body.correlationId);
      assert.equal(metadata.failureType, "unexpected-error");
      assert.ok(!JSON.stringify(metadata).includes(privateText));
    } finally { console.error = previousConsoleError; }
  });
});

test("failed diagnostic logging preserves the original faucet response and request ID disposition", async () => {
  await withEnvironment(adapterEnvironment(), async () => {
    const previousConsoleError = console.error;
    console.error = () => { throw new Error("diagnostic sink failed"); };
    try {
      const post = createFaucetPostHandler({
        fundWallet: async () => { throw new ForkFaucetError("REQUEST_UNCERTAIN", undefined, "replace"); },
      });
      const response = await post(routeRequest({ address: ADDRESS, requestId: REQUEST_ID }));
      assert.equal(response.status, 409);
      assert.equal(response.headers.get("x-cybergold-faucet-request-id"), "replace");
      await assertRouteError(response, "Fork faucet funding could not be confirmed.", "REQUEST_UNCERTAIN");
    } finally { console.error = previousConsoleError; }
  });
});

test("legacy local route stays origin-optional and requestId-optional", async () => {
  await withEnvironment(
    { FORK_FAUCET_ENABLED: "1", NODE_ENV: "development" },
    async () => {
      const response = await POST(
        new Request("http://localhost:3000/api/faucet", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: "not-an-address" }),
        })
      );
      assert.equal(response.status, 400);
      await assertRouteError(response, "Invalid wallet address.", "INVALID_ADDRESS");
    }
  );
});
