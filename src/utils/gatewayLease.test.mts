import assert from "node:assert/strict";
import test from "node:test";
import { inspect } from "node:util";
import { createPublicClient } from "viem";

import {
  INDEXER_GATEWAY_LEASE_TOKEN_HEADER,
  INDEXER_GATEWAY_RECONCILIATION_HEADER,
  PrivateIndexerGatewayClient,
  indexerGatewayHealthIsSuppressed,
  privateIndexerGatewayFromEnvironment,
} from "../server/onchain-indexer/gatewayLease.ts";
import {
  IndexerGatewayRpcMethodRejectedError,
  createIndexerRpcRequestCounter,
  instrumentEthGetLogsAttempt,
} from "../server/onchain-indexer/rpcRequestInstrumentation.ts";

const CLIENT_TOKEN = "c".repeat(43);
const LEASE_TOKEN = "l".repeat(43);
const CONFIG_REVISION = "a".repeat(64);
const ANCHOR_HASH = `0x${"12".repeat(32)}` as `0x${string}`;
const RPC_URL = "http://gateway.internal:18443/rpc/indexer";

function jsonResponse(url: string, value: unknown, status = 200) {
  const response = new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
  Object.defineProperty(response, "url", { value: url });
  return response;
}

function acquirePayload(reconciliationId: string) {
  return {
    kind: "cybergold-rpc-indexer-lease",
    formatVersion: 1,
    leaseToken: LEASE_TOKEN,
    reconciliationId,
    finalizedAnchor: { number: 1_234, hash: ANCHOR_HASH },
    expiresInSeconds: 300,
    configRevision: CONFIG_REVISION,
  };
}

function acquireExpectation(reconciliationId: string) {
  return {
    reconciliationId,
    expectedRuntimeRevision: CONFIG_REVISION,
    expectedFinalizedAnchor: {
      blockNumber: 1_234n,
      blockHash: ANCHOR_HASH as `0x${string}`,
    },
  };
}

test("gateway mode is explicit and rejects partial or malformed secret configuration", () => {
  assert.equal(privateIndexerGatewayFromEnvironment({}), null);
  assert.throws(
    () =>
      privateIndexerGatewayFromEnvironment({
        ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN: CLIENT_TOKEN,
      }),
    /Disabled indexer gateway configuration/
  );
  assert.throws(
    () =>
      privateIndexerGatewayFromEnvironment({
        ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED: "1",
        ONCHAIN_INDEXER_RPC_URL: `${RPC_URL}/wrong`,
        ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN: CLIENT_TOKEN,
      }),
    /ending exactly/
  );
});

test("ambiguous failed releases suppress health only until the lease expiry", () => {
  assert.equal(
    indexerGatewayHealthIsSuppressed({
      activeReconciliationId: "app-active",
      ambiguousUntilMs: 2_000,
      nowMs: 1_999,
    }),
    true
  );
  assert.equal(
    indexerGatewayHealthIsSuppressed({
      activeReconciliationId: "app-active",
      ambiguousUntilMs: 2_000,
      nowMs: 2_000,
    }),
    false
  );
  assert.equal(
    indexerGatewayHealthIsSuppressed({
      activeReconciliationId: null,
      ambiguousUntilMs: Number.NaN,
      nowMs: Number.NaN,
    }),
    false
  );
});

test("one lease binds acquire, RPC, anchor, release, redirects, and secret headers", async () => {
  const reconciliationId = "app-reconcile-1";
  const observations: Array<{
    url: string;
    init?: RequestInit;
    body: unknown;
  }> = [];
  const fetchMock: typeof fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    observations.push({ url, init, body });
    if (url.endsWith("/leases")) {
      return jsonResponse(url, acquirePayload(reconciliationId));
    }
    if (url.endsWith("/leases/release")) {
      return jsonResponse(url, {
        kind: "cybergold-rpc-indexer-lease-release",
        formatVersion: 1,
        reconciliationId,
        released: true,
      });
    }
    return jsonResponse(url, {
      jsonrpc: "2.0",
      id: (body as { id: unknown }).id,
      result: "0x4d2",
    });
  };
  const gateway = new PrivateIndexerGatewayClient(
    new URL(RPC_URL),
    CLIENT_TOKEN,
    { fetch: fetchMock, now: () => 1_000 }
  );
  const lease = await gateway.acquire(acquireExpectation(reconciliationId));
  assert.deepEqual(lease.finalizedAnchor, {
    blockNumber: 1_234n,
    blockHash: ANCHOR_HASH,
  });
  const requestCounter = createIndexerRpcRequestCounter();
  const client = createPublicClient({
    transport: lease.createRpcTransport(requestCounter),
  });
  assert.equal(
    await client.request({ method: "eth_chainId" }),
    "0x4d2"
  );
  await lease.release();

  assert.equal(observations.length, 3);
  for (const observation of observations) {
    assert.equal(observation.init?.redirect, "error");
    assert.equal(
      new Headers(observation.init?.headers).get("authorization"),
      `Bearer ${CLIENT_TOKEN}`
    );
  }
  const rpcHeaders = new Headers(observations[1].init?.headers);
  assert.equal(rpcHeaders.get(INDEXER_GATEWAY_LEASE_TOKEN_HEADER), LEASE_TOKEN);
  assert.equal(
    rpcHeaders.get(INDEXER_GATEWAY_RECONCILIATION_HEADER),
    reconciliationId
  );
  assert.deepEqual(observations[0].body, {
    kind: "cybergold-rpc-indexer-lease-acquire-request",
    formatVersion: 2,
    reconciliationId,
    expectedRuntimeRevision: CONFIG_REVISION,
    expectedFinalizedAnchor: { number: 1_234, hash: ANCHOR_HASH },
  });
  assert.deepEqual(observations[2].body, {
    kind: "cybergold-rpc-indexer-lease-release-request",
    formatVersion: 1,
    reconciliationId,
  });
  assert.equal(requestCounter.snapshot().byMethod.eth_chainId, 1);
  await assert.rejects(client.request({ method: "eth_chainId" }));
  assert.equal(observations.length, 3, "no RPC may follow successful release");
  assert.doesNotMatch(inspect(lease), new RegExp(LEASE_TOKEN));
});

test("the caller can pace every gateway-backed RPC before it reaches the gateway", async () => {
  const reconciliationId = "app-paced-rpc";
  const observations: string[] = [];
  const fetchMock: typeof fetch = async (input, init) => {
    const url = input.toString();
    if (url.endsWith("/leases")) {
      return jsonResponse(url, acquirePayload(reconciliationId));
    }
    const body = JSON.parse(String(init?.body)) as { id: unknown };
    observations.push("rpc");
    return jsonResponse(url, {
      jsonrpc: "2.0",
      id: body.id,
      result: "0x1",
    });
  };
  const gateway = new PrivateIndexerGatewayClient(
    new URL(RPC_URL),
    CLIENT_TOKEN,
    { fetch: fetchMock, now: () => 1_000 }
  );
  const lease = await gateway.acquire(acquireExpectation(reconciliationId));
  const counter = createIndexerRpcRequestCounter();
  const client = createPublicClient({
    transport: lease.createRpcTransport(counter, async () => {
      observations.push("paced");
    }),
  });

  await client.request({ method: "eth_chainId" });
  await client.request({ method: "eth_chainId" });

  assert.deepEqual(observations, ["paced", "rpc", "paced", "rpc"]);
});

test("transport accounting covers sequential headers, Multicall, and an adaptive log failure", async () => {
  const reconciliationId = "app-accounting";
  let logAttempts = 0;
  const fetchMock: typeof fetch = async (input, init) => {
    const url = input.toString();
    if (url.endsWith("/leases")) {
      return jsonResponse(url, acquirePayload(reconciliationId));
    }
    const body = JSON.parse(String(init?.body)) as {
      id: unknown;
      method: string;
    };
    if (body.method === "eth_getLogs" && logAttempts++ === 0) {
      return jsonResponse(
        url,
        {
          kind: "cybergold-rpc-indexer-range-reduction-required",
          formatVersion: 1,
        },
        413
      );
    }
    return jsonResponse(url, {
      jsonrpc: "2.0",
      id: body.id,
      result:
        body.method === "eth_getBlockByHash"
          ? { number: "0x4d2", hash: ANCHOR_HASH }
          : body.method === "eth_getLogs"
            ? []
            : "0x",
    });
  };
  const gateway = new PrivateIndexerGatewayClient(
    new URL(RPC_URL),
    CLIENT_TOKEN,
    { fetch: fetchMock, now: () => 1_000 }
  );
  const lease = await gateway.acquire(acquireExpectation(reconciliationId));
  const counter = createIndexerRpcRequestCounter();
  const client = createPublicClient({
    transport: lease.createRpcTransport(counter),
  });

  await client.request({
    method: "eth_getBlockByHash",
    params: [ANCHOR_HASH, false],
  });
  await client.request({
    method: "eth_call",
    params: [
      {
        to: "0xca11bde05977b3631167028862be2a173976ca11",
        data: "0x",
      },
      { blockHash: ANCHOR_HASH, requireCanonical: true },
    ],
  });
  counter.recordEthGetLogsPlan("core-address");
  await assert.rejects(
    instrumentEthGetLogsAttempt(counter, "core-address", false, () =>
      client.request({ method: "eth_getLogs", params: [{}] })
    ),
    (error: unknown) => lease.isRangeReductionRequiredError(error)
  );
  await instrumentEthGetLogsAttempt(counter, "core-address", true, () =>
    client.request({ method: "eth_getLogs", params: [{}] })
  );

  assert.deepEqual(counter.snapshot(), {
    totalAttempts: 4,
    failedAttempts: 1,
    adaptiveRetryAttempts: 1,
    byMethod: {
      eth_call: 1,
      eth_chainId: 0,
      eth_getBlockByHash: 1,
      eth_getBlockByNumber: 0,
      eth_getCode: 0,
      eth_getLogs: 2,
    },
    ethGetLogs: {
      attempts: 2,
      plannedAttempts: 1,
      adaptiveAttempts: 1,
      failedAttempts: 1,
      addressScopedViemTransportRetries: 0,
      legacyViemTransportRetriesObserved: null,
      bySource: {
        "core-event": 0,
        "governance-event": 0,
        "safe-event": 0,
        "core-address": 2,
        "governance-address": 0,
        "safe-address": 0,
      },
      plannedBySource: {
        "core-event": 0,
        "governance-event": 0,
        "safe-event": 0,
        "core-address": 1,
        "governance-address": 0,
        "safe-address": 0,
      },
    },
  });
});

test("the worker transport does not impose an App-side request cap and rejects methods outside the frozen allowlist", async () => {
  const reconciliationId = "app-attempt-ceiling";
  let rpcFetches = 0;
  const fetchMock: typeof fetch = async (input, init) => {
    const url = input.toString();
    if (url.endsWith("/leases")) {
      return jsonResponse(url, acquirePayload(reconciliationId));
    }
    rpcFetches += 1;
    const body = JSON.parse(String(init?.body)) as { id: unknown };
    return jsonResponse(url, {
      jsonrpc: "2.0",
      id: body.id,
      result: "0x1",
    });
  };
  const gateway = new PrivateIndexerGatewayClient(
    new URL(RPC_URL),
    CLIENT_TOKEN,
    { fetch: fetchMock, now: () => 1_000 }
  );
  const lease = await gateway.acquire(acquireExpectation(reconciliationId));
  const counter = createIndexerRpcRequestCounter();
  const transport = lease.createRpcTransport(counter)({});

  for (let attempt = 0; attempt < 73; attempt += 1) {
    await transport.request({ method: "eth_chainId" });
  }
  assert.equal(rpcFetches, 73);
  assert.equal(counter.snapshot().totalAttempts, 73);

  const methodCounter = createIndexerRpcRequestCounter();
  const methodTransport = lease.createRpcTransport(methodCounter)({});
  await assert.rejects(
    methodTransport.request({ method: "eth_blockNumber" }),
    IndexerGatewayRpcMethodRejectedError
  );
  assert.equal(methodCounter.snapshot().totalAttempts, 0);
  assert.equal(rpcFetches, 73);
});

test("only the exact gateway range-reduction response splits; 429 and outages restart", async () => {
  async function leasedWithRpcResponse(responseFactory: (url: string) => Response) {
    const reconciliationId = `app-${Math.random().toString(36).slice(2)}`;
    const fetchMock: typeof fetch = async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/leases")) {
        return jsonResponse(url, acquirePayload(reconciliationId));
      }
      return responseFactory(url);
    };
    const gateway = new PrivateIndexerGatewayClient(
      new URL(RPC_URL),
      CLIENT_TOKEN,
      { fetch: fetchMock, now: () => 1_000 }
    );
    const lease = await gateway.acquire(acquireExpectation(reconciliationId));
    const client = createPublicClient({
      transport: lease.createRpcTransport(createIndexerRpcRequestCounter()),
    });
    let failure: unknown;
    try {
      await client.request({ method: "eth_getLogs", params: [{}] });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure);
    return { lease, failure };
  }

  const exact = await leasedWithRpcResponse((url) =>
    jsonResponse(
      url,
      {
        kind: "cybergold-rpc-indexer-range-reduction-required",
        formatVersion: 1,
      },
      413
    )
  );
  assert.equal(exact.lease.isRangeReductionRequiredError(exact.failure), true);
  assert.equal(exact.lease.isRestartRequiredError(exact.failure), false);

  const rateLimited = await leasedWithRpcResponse((url) =>
    jsonResponse(url, { error: "rate-limited" }, 429)
  );
  assert.equal(
    rateLimited.lease.isRangeReductionRequiredError(rateLimited.failure),
    false
  );
  assert.equal(rateLimited.lease.isRestartRequiredError(rateLimited.failure), true);

  const wrongShape = await leasedWithRpcResponse((url) =>
    jsonResponse(
      url,
      {
        kind: "cybergold-rpc-indexer-range-reduction-required",
        formatVersion: 1,
        extra: true,
      },
      413
    )
  );
  assert.equal(
    wrongShape.lease.isRangeReductionRequiredError(wrongShape.failure),
    false
  );
  assert.equal(wrongShape.lease.isRestartRequiredError(wrongShape.failure), true);

  const oversized = await leasedWithRpcResponse((url) => {
    const response = new Response("x".repeat(4_097), {
      status: 413,
      headers: { "Content-Type": "application/json" },
    });
    Object.defineProperty(response, "url", { value: url });
    return response;
  });
  assert.equal(
    oversized.lease.isRangeReductionRequiredError(oversized.failure),
    false
  );
  assert.equal(oversized.lease.isRestartRequiredError(oversized.failure), true);
});

test("redirected acquire responses fail closed without exposing gateway secrets", async () => {
  const redirected = "http://attacker.invalid/rpc/indexer/leases";
  const gateway = new PrivateIndexerGatewayClient(
    new URL(RPC_URL),
    CLIENT_TOKEN,
    {
      fetch: async () => jsonResponse(redirected, acquirePayload("app-redirect")),
    }
  );
  await assert.rejects(gateway.acquire(acquireExpectation("app-redirect")), (error: unknown) => {
    assert.ok(error instanceof Error);
    assert.equal(error.message, "Indexer gateway lease restart required");
    assert.doesNotMatch(error.message, new RegExp(CLIENT_TOKEN));
    return true;
  });
});

test("successful RPC responses require the exact JSON media type", async () => {
  const reconciliationId = "app-rpc-media-type";
  const fetchMock: typeof fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/leases")) {
      return jsonResponse(url, acquirePayload(reconciliationId));
    }
    const body = JSON.parse(String(init?.body)) as { id: unknown };
    const response = new Response(
      JSON.stringify({ jsonrpc: "2.0", id: body.id, result: "0x1" }),
      { status: 200, headers: { "Content-Type": "text/plain" } }
    );
    Object.defineProperty(response, "url", { value: url });
    return response;
  };
  const gateway = new PrivateIndexerGatewayClient(
    new URL(RPC_URL),
    CLIENT_TOKEN,
    { fetch: fetchMock, now: () => 1_000 }
  );
  const lease = await gateway.acquire(acquireExpectation(reconciliationId));
  const client = createPublicClient({
    transport: lease.createRpcTransport(createIndexerRpcRequestCounter()),
  });
  await assert.rejects(client.request({ method: "eth_chainId" }), (error: unknown) => {
    assert.equal(lease.isRestartRequiredError(error), true);
    return true;
  });
});

test("v2 acquire rejects a gateway lease bound to any other revision or anchor", async () => {
  for (const mutate of [
    (payload: ReturnType<typeof acquirePayload>) => ({ ...payload, configRevision: "b".repeat(64) }),
    (payload: ReturnType<typeof acquirePayload>) => ({
      ...payload,
      finalizedAnchor: { ...payload.finalizedAnchor, number: 1_235 },
    }),
  ]) {
    const gateway = new PrivateIndexerGatewayClient(
      new URL(RPC_URL),
      CLIENT_TOKEN,
      {
        fetch: async (input) => {
          const url = input.toString();
          return jsonResponse(url, mutate(acquirePayload("app-mismatch")));
        },
      }
    );
    await assert.rejects(
      gateway.acquire(acquireExpectation("app-mismatch")),
      /restart required/
    );
  }
});
