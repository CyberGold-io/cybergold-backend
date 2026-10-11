import { BaseError, HttpRequestError, getAddress, type Address, type Hex } from "viem";

export type RecoverySharePortfolioLoader = (holder: Address, page?: { offset?: bigint; blockHash?: Hex }) => Promise<unknown>;

export class RecoverySharesApiError extends Error {
  readonly status: 429 | 503;
  readonly retryAfterSeconds?: number;

  constructor(
    message: string,
    status: 429 | 503,
    retryAfterSeconds?: number
  ) {
    super(message);
    this.name = "RecoverySharesApiError";
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export async function handleRecoverySharesRequest(
  request: Request,
  loadPortfolio: RecoverySharePortfolioLoader
) {
  const params = new URL(request.url).searchParams;
  const holderRaw = params.get("holder");
  if (!holderRaw) {
    return Response.json(
      { error: "holder query parameter is required" },
      { status: 400, headers: { "Cache-Control": "no-store" } }
    );
  }

  const offset = params.get("offset") ?? "0";
  const blockHash = params.get("blockHash");
  if (!/^(0|[1-9][0-9]{0,77})$/.test(offset) || BigInt(offset) >= 1n << 256n ||
      (blockHash !== null && !/^0x[0-9a-fA-F]{64}$/.test(blockHash)) ||
      (offset !== "0" && blockHash === null)) {
    return Response.json({ error: "Invalid recovery page; continuation requires its blockHash" },
      { status: 400, headers: { "Cache-Control": "no-store" } });
  }

  let holder: Address;
  try {
    holder = getAddress(holderRaw as `0x${string}`);
  } catch {
    return Response.json(
      { error: "holder query parameter must be a valid address" },
      { status: 400, headers: { "Cache-Control": "no-store" } }
    );
  }

  try {
    const portfolio = await loadPortfolio(holder, { offset: BigInt(offset), blockHash: (blockHash ?? undefined) as Hex | undefined });
    return Response.json(portfolio, {
      // Server caches are hash-keyed and revalidate canonicality. An HTTP cache cannot
      // detect a fork reset that retains chain ID, Core address and block height.
      headers: { "Cache-Control": "no-store" },
    });
  } catch (cause) {
    const upstream = cause instanceof BaseError
      ? cause.walk((error) => error instanceof HttpRequestError) : cause;
    if (upstream instanceof HttpRequestError && upstream.status === 429) {
      const rawRetry = upstream.headers?.get("Retry-After");
      const seconds = rawRetry && /^\d+$/.test(rawRetry) ? Number(rawRetry) :
        rawRetry ? Math.ceil((Date.parse(rawRetry) - Date.now()) / 1000) : 30;
      const retry = Number.isSafeInteger(seconds) && seconds > 0 ? seconds : 30;
      return Response.json({ error: "Recovery RPC capacity is temporarily unavailable" }, {
        status: 429, headers: { "Cache-Control": "no-store", "Retry-After": String(retry) },
      });
    }
    if (cause instanceof RecoverySharesApiError) {
      const headers: Record<string, string> = { "Cache-Control": "no-store" };
      if (cause.retryAfterSeconds) {
        headers["Retry-After"] = String(cause.retryAfterSeconds);
      }
      return Response.json(
        { error: cause.message },
        { status: cause.status, headers }
      );
    }
    return Response.json(
      { error: "Recovery-share RPC snapshot is unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
