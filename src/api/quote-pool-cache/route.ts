import type { Address } from "viem";

import type { PoolCacheObservation, QuoteDex } from "@/types";
import {
  listCachedPools,
  recordPoolObservations,
} from "@/server/quote-pool-cache/repository";
import { publicApiError } from "@/server/public-api-errors";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function jsonError(message: string, status = 400) {
  return Response.json({ error: message }, { status });
}

function isAddress(value: unknown): value is Address {
  return typeof value === "string" && /^0x[a-fA-F0-9]{40}$/.test(value);
}

function parseDex(value: unknown): QuoteDex | undefined {
  return value === "uniswap_v3" ? value : undefined;
}

function parseChainId(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return undefined;
  }
  return value;
}

function parseUintString(value: unknown) {
  return typeof value === "string" && /^(0|[1-9][0-9]*)$/.test(value)
    ? value
    : undefined;
}

function parseLookupPairs(value: unknown) {
  if (!Array.isArray(value)) {
    return undefined;
  }

  const pairs = value.flatMap((entry) => {
    if (!entry || typeof entry !== "object") {
      return [];
    }
    const pair = entry as Record<string, unknown>;
    return isAddress(pair.tokenA) && isAddress(pair.tokenB)
      ? [{ tokenA: pair.tokenA, tokenB: pair.tokenB }]
      : [];
  });

  return pairs.length === value.length ? pairs : undefined;
}

function parseObservations(value: unknown): PoolCacheObservation[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }

  const entries = value.flatMap((entry) => {
    if (!entry || typeof entry !== "object") {
      return [];
    }

    const item = entry as Record<string, unknown>;
    const chainId = parseChainId(item.chainId);
    const dex = parseDex(item.dex);
    const tokenA = item.tokenA;
    const tokenB = item.tokenB;
    const fee = item.fee;
    const poolAddress = item.poolAddress;
    const exists = item.exists;
    const quoteSucceeded = item.quoteSucceeded;
    const activeLiquidityRaw = item.activeLiquidityRaw;
    const sqrtPriceX96Raw = item.sqrtPriceX96Raw;
    const tick = item.tick;
    const token0BalanceRaw = item.token0BalanceRaw;
    const token1BalanceRaw = item.token1BalanceRaw;
    const hasLiquiditySnapshot =
      activeLiquidityRaw !== undefined ||
      sqrtPriceX96Raw !== undefined ||
      tick !== undefined ||
      token0BalanceRaw !== undefined ||
      token1BalanceRaw !== undefined;
    const parsedActiveLiquidityRaw = parseUintString(activeLiquidityRaw);
    const parsedSqrtPriceX96Raw = parseUintString(sqrtPriceX96Raw);
    const parsedToken0BalanceRaw = parseUintString(token0BalanceRaw);
    const parsedToken1BalanceRaw = parseUintString(token1BalanceRaw);

    if (
      chainId === undefined ||
      !dex ||
      !isAddress(tokenA) ||
      !isAddress(tokenB) ||
      typeof fee !== "number" ||
      !Number.isInteger(fee) ||
      typeof exists !== "boolean" ||
      (poolAddress !== undefined && !isAddress(poolAddress)) ||
      (hasLiquiditySnapshot &&
        (parsedActiveLiquidityRaw === undefined ||
          parsedSqrtPriceX96Raw === undefined ||
          typeof tick !== "number" ||
          !Number.isInteger(tick) ||
          parsedToken0BalanceRaw === undefined ||
          parsedToken1BalanceRaw === undefined))
    ) {
      return [];
    }

    return [
      {
        chainId,
        dex,
        tokenA,
        tokenB,
        fee,
        poolAddress,
        exists,
        quoteSucceeded: typeof quoteSucceeded === "boolean" ? quoteSucceeded : undefined,
        activeLiquidityRaw: parsedActiveLiquidityRaw,
        sqrtPriceX96Raw: parsedSqrtPriceX96Raw,
        tick: typeof tick === "number" ? tick : undefined,
        token0BalanceRaw: parsedToken0BalanceRaw,
        token1BalanceRaw: parsedToken1BalanceRaw,
      } satisfies PoolCacheObservation,
    ];
  });

  return entries.length === value.length ? entries : undefined;
}

export async function POST(request: Request) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return jsonError("Invalid JSON payload");
  }

  if (!body || typeof body !== "object") {
    return jsonError("Invalid quote-pool-cache payload");
  }

  const payload = body as Record<string, unknown>;
  const action = payload.action;

  try {
    if (action === "list-pools") {
      const chainId = parseChainId(payload.chainId);
      const dex = parseDex(payload.dex);
      const pairs = parseLookupPairs(payload.pairs);
      if (chainId === undefined || !dex || !pairs) {
        return jsonError("Invalid pool-cache lookup payload");
      }

      const entries = await listCachedPools({
        chainId,
        dex,
        pairs,
      });

      return Response.json(
        { entries },
        {
          headers: {
            "Cache-Control": "no-store",
          },
        }
      );
    }

    if (action === "record-observations") {
      const entries = parseObservations(payload.entries);
      if (!entries) {
        return jsonError("Invalid pool-cache observation payload");
      }

      await recordPoolObservations({ entries });
      return Response.json({ ok: true });
    }

    return jsonError("Unknown quote-pool-cache action");
  } catch (error) {
    return publicApiError("Failed to process quote-pool-cache request.", {
      context: "quote-pool-cache",
      error,
    });
  }
}
