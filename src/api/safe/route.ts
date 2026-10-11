import { serverEnv } from "../../server/environment.ts";
import { publicApiError } from "../../server/public-api-errors.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const SAFE_SERVICE_TIMEOUT_MS = 15_000;

type SafeAction =
  | "safe-info"
  | "pending-transactions"
  | "executed-transactions"
  | "propose-transaction"
  | "confirm-transaction"
  | "transaction-details";

type SafeApiRequest = {
  action?: SafeAction;
  safeAddress?: string;
  safeTxHash?: string;
  payload?: Record<string, unknown>;
};

function jsonError(message: string, status = 400) {
  return Response.json({ error: message }, { status, headers: { "Cache-Control": "no-store" } });
}

function isAddress(value: unknown): value is string {
  return typeof value === "string" && /^0x[a-fA-F0-9]{40}$/.test(value);
}

function isHex32(value: unknown): value is string {
  return typeof value === "string" && /^0x[a-fA-F0-9]{64}$/.test(value);
}

function getSafeServiceBaseUrl() {
  const configured = serverEnv.SAFE_TX_SERVICE_URL ?? "";
  return configured.trim().replace(/\/+$/, "");
}

async function safeServiceFetch(
  path: string,
  init?: RequestInit
): Promise<{
  ok: boolean;
  status: number;
  body: unknown;
  failureError?: unknown;
  retryAfterSeconds?: number;
}> {
  const baseUrl = getSafeServiceBaseUrl();
  if (!baseUrl) {
    return {
      ok: false,
      status: 503,
      body: null,
      failureError: new Error("Safe Transaction Service is not configured"),
    };
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
      signal: AbortSignal.timeout(SAFE_SERVICE_TIMEOUT_MS),
    });
  } catch (error) {
    return {
      ok: false,
      status: 503,
      body: null,
      failureError: error,
    };
  }

  const retryAfterHeader = response.headers.get("retry-after");
  const retryAfterSeconds =
    retryAfterHeader && /^\d{1,4}$/.test(retryAfterHeader)
      ? Number(retryAfterHeader)
      : undefined;
  const boundedRetryAfterSeconds =
    retryAfterSeconds !== undefined &&
    retryAfterSeconds >= 1 &&
    retryAfterSeconds <= 3_600
      ? retryAfterSeconds
      : undefined;

  let body: unknown;
  try {
    const raw = await response.text();
    // Safe proposal creation returns 201 with no response body.
    // Successful writes need no JSON result; reads still do.
    body = response.ok && init?.method === "POST" && raw.trim() === ""
      ? {} : JSON.parse(raw);
  } catch (error) {
    return {
      ok: false,
      status: response.ok ? 502 : response.status,
      body: null,
      failureError: error,
      retryAfterSeconds: boundedRetryAfterSeconds,
    };
  }

  if (response.ok && (body === null || typeof body !== "object")) {
    return {
      ok: false,
      status: 502,
      body: null,
      failureError: new Error("Safe Transaction Service returned an invalid JSON body"),
      retryAfterSeconds: boundedRetryAfterSeconds,
    };
  }

  return {
    ok: response.ok,
    status: response.status,
    body,
    retryAfterSeconds: boundedRetryAfterSeconds,
  };
}

function safeServiceError(
  message: string,
  context: string,
  response: Awaited<ReturnType<typeof safeServiceFetch>>
) {
  const result = publicApiError(message, {
    context,
    error: response.failureError,
    status: response.status,
  });
  if (response.retryAfterSeconds !== undefined) {
    result.headers.set("Retry-After", String(response.retryAfterSeconds));
  }
  return result;
}

export async function POST(request: Request) {
  let body: SafeApiRequest;

  try {
    body = (await request.json()) as SafeApiRequest;
  } catch {
    return jsonError("Invalid JSON payload.");
  }

  const action = body.action;
  if (!action) {
    return jsonError("Missing action.");
  }

  if (action === "safe-info") {
    if (!isAddress(body.safeAddress)) {
      return jsonError("Invalid safeAddress.");
    }
    const response = await safeServiceFetch(`/api/v1/safes/${body.safeAddress}/`, {
      method: "GET",
    });
    if (!response.ok) {
      return safeServiceError("Failed to fetch Safe info.", "safe-info", response);
    }
    return Response.json(response.body, { headers: { "Cache-Control": "no-store" } });
  }

  if (action === "pending-transactions") {
    if (!isAddress(body.safeAddress)) {
      return jsonError("Invalid safeAddress.");
    }
    const response = await safeServiceFetch(
      `/api/v1/safes/${body.safeAddress}/multisig-transactions/?executed=false&limit=100`,
      { method: "GET" }
    );
    if (!response.ok) {
      return safeServiceError(
        "Failed to fetch pending multisig transactions.",
        "safe-pending-transactions",
        response
      );
    }
    return Response.json(response.body, { headers: { "Cache-Control": "no-store" } });
  }

  if (action === "executed-transactions") {
    if (!isAddress(body.safeAddress)) {
      return jsonError("Invalid safeAddress.");
    }
    const response = await safeServiceFetch(
      `/api/v1/safes/${body.safeAddress}/multisig-transactions/?executed=true&limit=25`,
      { method: "GET" }
    );
    if (!response.ok) {
      return safeServiceError(
        "Failed to fetch executed multisig transactions.",
        "safe-executed-transactions",
        response
      );
    }
    return Response.json(response.body, { headers: { "Cache-Control": "no-store" } });
  }

  if (action === "propose-transaction") {
    if (!isAddress(body.safeAddress)) {
      return jsonError("Invalid safeAddress.");
    }
    if (!body.payload || typeof body.payload !== "object") {
      return jsonError("Invalid payload.");
    }
    const response = await safeServiceFetch(`/api/v1/safes/${body.safeAddress}/multisig-transactions/`, {
      method: "POST",
      body: JSON.stringify(body.payload),
    });
    if (!response.ok) {
      return safeServiceError(
        "Failed to propose multisig transaction.",
        "safe-propose-transaction",
        response
      );
    }
    return Response.json(response.body, { headers: { "Cache-Control": "no-store" } });
  }

  if (action === "confirm-transaction") {
    if (!isHex32(body.safeTxHash)) {
      return jsonError("Invalid safeTxHash.");
    }
    if (!body.payload || typeof body.payload !== "object") {
      return jsonError("Invalid payload.");
    }
    const response = await safeServiceFetch(`/api/v1/multisig-transactions/${body.safeTxHash}/confirmations/`, {
      method: "POST",
      body: JSON.stringify(body.payload),
    });
    if (!response.ok) {
      return safeServiceError(
        "Failed to confirm multisig transaction.",
        "safe-confirm-transaction",
        response
      );
    }
    return Response.json(response.body, { headers: { "Cache-Control": "no-store" } });
  }

  if (action === "transaction-details") {
    if (!isHex32(body.safeTxHash)) {
      return jsonError("Invalid safeTxHash.");
    }
    const response = await safeServiceFetch(`/api/v1/multisig-transactions/${body.safeTxHash}/`, {
      method: "GET",
    });
    if (!response.ok) {
      return safeServiceError(
        "Failed to fetch multisig transaction details.",
        "safe-transaction-details",
        response
      );
    }
    return Response.json(response.body, { headers: { "Cache-Control": "no-store" } });
  }

  return jsonError("Unsupported action.");
}
