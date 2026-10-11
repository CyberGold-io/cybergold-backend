import { observeRpcHttp } from "@/server/metrics";
import { serverEnv } from "../../server/environment.ts";
import {
  MAX_RPC_REQUEST_BYTES,
  isValidRpcResponsePayload,
  parseRpcUpstreamUrl,
  validateRpcPayload,
} from "../../server/rpcProxyPolicy.ts";
import { countContractReads, rpcRetryDelayMs, sandboxRpcReadPacer } from "../../server/rpcReadPacer.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const RPC_UPSTREAM_TIMEOUT_MS = 15_000;
const NO_STORE_HEADERS = { "Cache-Control": "no-store" } as const;

class RequestBodyTooLargeError extends Error {}

async function readRequestBody(request: Request) {
  const contentLength = request.headers.get("content-length");
  if (contentLength !== null) {
    const declaredBytes = Number(contentLength);
    if (Number.isFinite(declaredBytes) && declaredBytes > MAX_RPC_REQUEST_BYTES) {
      throw new RequestBodyTooLargeError();
    }
  }

  if (!request.body) {
    return "";
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let receivedBytes = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    receivedBytes += value.byteLength;
    if (receivedBytes > MAX_RPC_REQUEST_BYTES) {
      await reader.cancel();
      throw new RequestBodyTooLargeError();
    }
    chunks.push(value);
  }

  const body = new Uint8Array(receivedBytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }

  return new TextDecoder("utf-8", { fatal: true }).decode(body);
}

function jsonRpcError(
  status: number,
  code: number,
  message: string,
  payload?: unknown,
  headers: Record<string, string> = {}
) {
  const errorFor = (call: unknown) => ({
    jsonrpc: "2.0",
    id: call && typeof call === "object" && "id" in call ? call.id : null,
    error: { code, message },
  });
  return Response.json(
    Array.isArray(payload) ? payload.map(errorFor) : errorFor(payload),
    { status, headers: { ...NO_STORE_HEADERS, ...headers } }
  );
}

function upstreamFailure(status: 502 | 504, payload?: unknown) {
  return jsonRpcError(
    status,
    -32603,
    status === 504
      ? "RPC upstream request timed out."
      : "RPC upstream is unavailable.",
    payload
  );
}

export async function POST(request: Request) {
  let rawBody: string;

  try {
    rawBody = await readRequestBody(request);
  } catch (error) {
    if (error instanceof RequestBodyTooLargeError) {
      return jsonRpcError(413, -32600, "JSON-RPC request is too large.");
    }
    return jsonRpcError(400, -32700, "Invalid JSON request body.");
  }

  let payload: unknown;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return jsonRpcError(400, -32700, "Invalid JSON request body.");
  }

  const validation = validateRpcPayload(payload);
  if (!validation.ok) {
    return jsonRpcError(
      validation.code === -32601 ? 403 : 400,
      validation.code,
      validation.message
    );
  }

  const upstreamUrl = parseRpcUpstreamUrl(serverEnv.RPC_URL);
  if (!upstreamUrl) {
    console.error("[rpc-proxy] invalid or missing RPC_URL");
    return upstreamFailure(502, payload);
  }
  const rpcAuthorization = serverEnv.RPC_AUTHORIZATION;

  const controller = new AbortController();
  const signal = AbortSignal.any([controller.signal, request.signal]);
  const deadline = Date.now() + RPC_UPSTREAM_TIMEOUT_MS;
  const timeout = setTimeout(() => controller.abort(), RPC_UPSTREAM_TIMEOUT_MS);
  const pacer = sandboxRpcReadPacer(upstreamUrl);
  const readCount = countContractReads(payload);

  try {
    const send = async () => {
      await pacer?.wait(readCount, signal);
      signal.throwIfAborted();
      return observeRpcHttp(() => fetch(upstreamUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          ...(rpcAuthorization ? { Authorization: rpcAuthorization } : {}),
        },
        body: rawBody,
        cache: "no-store",
        redirect: "error",
        signal,
      }));
    };
    let upstreamResponse = await send();
    // A single retry after a shared cooldown absorbs transient throttling.
    if (upstreamResponse.status === 429 && pacer) {
      const delay = rpcRetryDelayMs(upstreamResponse.headers.get("retry-after"));
      pacer.pause(delay);
      // Preserve the rate-limit response when its cooldown outlasts this request.
      if (Date.now() + delay < deadline) {
        await upstreamResponse.body?.cancel();
        upstreamResponse = await send();
      }
    }

    if (upstreamResponse.status === 429) {
      const delay = rpcRetryDelayMs(upstreamResponse.headers.get("retry-after"));
      pacer?.pause(delay);
      await upstreamResponse.body?.cancel();
      return jsonRpcError(429, -32005, "RPC rate limit reached. Please retry shortly.", payload, {
        "Retry-After": String(Math.ceil(delay / 1000)),
      });
    }

    if (!upstreamResponse.ok) {
      console.error("[rpc-proxy] upstream HTTP error", { status: upstreamResponse.status });
      return upstreamFailure(502, payload);
    }

    const responseBody = await upstreamResponse.text();
    let responsePayload: unknown;
    try {
      responsePayload = JSON.parse(responseBody);
    } catch {
      console.error("[rpc-proxy] upstream returned invalid JSON");
      return upstreamFailure(502, payload);
    }

    if (!isValidRpcResponsePayload(responsePayload)) {
      console.error("[rpc-proxy] upstream returned invalid JSON-RPC");
      return upstreamFailure(502, payload);
    }

    return new Response(responseBody, {
      status: upstreamResponse.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "application/json",
      },
    });
  } catch (error) {
    // Log only error codes, never URLs, credentials, or upstream response bodies.
    const cause = error instanceof Error ? error.cause : undefined;
    const code = cause && typeof cause === "object" && "code" in cause
      ? cause.code : undefined;
    console.error("[rpc-proxy] upstream connection failed", {
      name: error instanceof Error ? error.name : "UnknownError",
      code: typeof code === "string" && /^[A-Z0-9_]+$/.test(code) ? code : undefined,
    });
    return upstreamFailure(
      signal.aborted ? 504 : 502,
      payload
    );
  } finally {
    clearTimeout(timeout);
  }
}
