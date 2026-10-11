import {
  ForkFaucetError,
  fundForkWallet,
  isForkFaucetAdapterMode,
  isForkFaucetEnabled,
  isValidFaucetRequestId,
  normalizeRequesterIp,
  type FaucetErrorCode,
  type FaucetAdapterDiagnostics,
  type ForkFaucetRequestContext,
} from "../../server/faucet/forkFaucet.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_REQUEST_BYTES = 512;
const NO_STORE_HEADERS = { "Cache-Control": "no-store" } as const;

type FaucetRequestBody = {
  address: string;
  requestId?: string;
};

type FaucetRouteDependencies = {
  fundWallet: (
    address: string,
    context?: ForkFaucetRequestContext
  ) => ReturnType<typeof fundForkWallet>;
  isAdapterMode: () => boolean;
  isEnabled: () => boolean;
};

class RequestBodyTooLargeError extends Error {}

function jsonError(
  message: string,
  status: number,
  code: FaucetErrorCode,
  retryAfterSeconds?: number,
  requestIdDisposition?: "retain" | "replace",
  diagnostics?: FaucetAdapterDiagnostics
) {
  const headers: Record<string, string> = { ...NO_STORE_HEADERS };
  if (retryAfterSeconds !== undefined) {
    headers["Retry-After"] = String(retryAfterSeconds);
  }
  if (requestIdDisposition === "replace") {
    headers["X-CyberGold-Faucet-Request-Id"] = "replace";
  }

  const correlationId = crypto.randomUUID();
  try {
    console.error("[fork-faucet] request failed", {
      correlationId,
      code,
      status,
      ...(diagnostics ?? {
        stage: "faucet-request",
        failureType: code === "INTERNAL_ERROR" ? "unexpected-error" : "request-error",
      }),
    });
  } catch { /* Diagnostics must not change funding behavior. */ }

  return Response.json({ error: message, code, correlationId }, { status, headers });
}

function hasJsonContentType(request: Request) {
  const contentType = request.headers.get("content-type");
  return contentType?.split(";", 1)[0].trim().toLowerCase() === "application/json";
}

async function readBoundedRequestBody(request: Request) {
  const declaredLength = request.headers.get("content-length");
  if (declaredLength !== null) {
    if (!/^\d+$/.test(declaredLength)) {
      throw new SyntaxError("invalid content length");
    }
    if (Number(declaredLength) > MAX_REQUEST_BYTES) {
      throw new RequestBodyTooLargeError();
    }
  }

  if (!request.body) {
    throw new SyntaxError("empty body");
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
    if (receivedBytes > MAX_REQUEST_BYTES) {
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

function hasExactKeys(value: Record<string, unknown>, expectedKeys: readonly string[]) {
  const actualKeys = Object.keys(value).sort();
  const sortedExpectedKeys = [...expectedKeys].sort();
  return (
    actualKeys.length === sortedExpectedKeys.length &&
    actualKeys.every((key, index) => key === sortedExpectedKeys[index])
  );
}

function parseRequestBody(rawBody: string, adapterMode: boolean): FaucetRequestBody | null {
  let value: unknown;
  try {
    value = JSON.parse(rawBody) as unknown;
  } catch {
    return null;
  }

  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const record = value as Record<string, unknown>;
  const exactKeys = adapterMode
    ? hasExactKeys(record, ["address", "requestId"])
    : hasExactKeys(record, ["address"]) || hasExactKeys(record, ["address", "requestId"]);
  if (
    !exactKeys ||
    typeof record.address !== "string" ||
    (record.requestId !== undefined &&
      (typeof record.requestId !== "string" || !isValidFaucetRequestId(record.requestId)))
  ) {
    return null;
  }

  if (adapterMode && typeof record.requestId !== "string") {
    return null;
  }

  return {
    address: record.address,
    requestId: record.requestId as string | undefined,
  };
}

function resolveTrustedRequesterIp(headers: Headers) {
  const realIp = headers.get("x-real-ip");
  const forwardedFor = headers.get("x-forwarded-for");
  if (realIp === null || forwardedFor === null) {
    return undefined;
  }

  const normalizedRealIp = normalizeRequesterIp(realIp.trim());
  const normalizedForwardedIp = normalizeRequesterIp(
    forwardedFor.split(",", 1)[0].trim()
  );
  if (!normalizedRealIp || normalizedRealIp !== normalizedForwardedIp) {
    return undefined;
  }
  return normalizedRealIp;
}

const DEFAULT_DEPENDENCIES: FaucetRouteDependencies = {
  fundWallet: fundForkWallet,
  isAdapterMode: isForkFaucetAdapterMode,
  isEnabled: isForkFaucetEnabled,
};

export function createFaucetPostHandler(
  overrides: Partial<FaucetRouteDependencies> = {}
) {
  const dependencies = { ...DEFAULT_DEPENDENCIES, ...overrides };

  return async function faucetPost(request: Request) {
    if (!dependencies.isEnabled()) {
      return jsonError("Fork faucet is disabled.", 403, "DISABLED");
    }

    if (!hasJsonContentType(request)) {
      return jsonError("Content-Type must be application/json.", 415, "UNSUPPORTED_MEDIA_TYPE");
    }

    const adapterMode = dependencies.isAdapterMode();

    let rawBody: string;
    try {
      rawBody = await readBoundedRequestBody(request);
    } catch (error) {
      if (error instanceof RequestBodyTooLargeError) {
        return jsonError("Faucet request body is too large.", 413, "REQUEST_TOO_LARGE");
      }
      return jsonError("Invalid request body.", 400, "INVALID_REQUEST");
    }

    const body = parseRequestBody(rawBody, adapterMode);
    if (!body) {
      return jsonError("Invalid request body.", 400, "INVALID_REQUEST");
    }

    const requesterIp = adapterMode
      ? resolveTrustedRequesterIp(request.headers)
      : undefined;
    if (adapterMode && !requesterIp) {
      return jsonError("Requester IP is unavailable.", 400, "INVALID_REQUESTER_IP");
    }

    try {
      const result = await dependencies.fundWallet(body.address, {
        requestId: body.requestId,
        requesterIp,
      });
      return Response.json(result, { headers: NO_STORE_HEADERS });
    } catch (error) {
      if (error instanceof ForkFaucetError) {
        return jsonError(
          error.message,
          error.status,
          error.code,
          error.retryAfterSeconds,
          error.requestIdDisposition,
          error.diagnostics
        );
      }

      return jsonError("Fork faucet is temporarily unavailable.", 500, "INTERNAL_ERROR");
    }
  };
}

export const POST = createFaucetPostHandler();
