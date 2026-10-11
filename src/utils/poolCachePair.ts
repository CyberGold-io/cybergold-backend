import type { Address } from "viem";

import type { PoolCacheObservation, PoolDex, PoolIdentityFields } from "../types";

export function normalizePoolPair(params: {
  tokenA: Address;
  tokenB: Address;
}) {
  const tokenA = params.tokenA.toLowerCase() as Address;
  const tokenB = params.tokenB.toLowerCase() as Address;
  return tokenA <= tokenB
    ? { token0: tokenA, token1: tokenB }
    : { token0: tokenB, token1: tokenA };
}

export function buildPoolCacheEntryKey(params: PoolIdentityFields & {
  chainId: number;
  dex: PoolDex;
  tokenA: Address;
  tokenB: Address;
  fee: number;
}) {
  const { token0, token1 } = normalizePoolPair({
    tokenA: params.tokenA,
    tokenB: params.tokenB,
  });

  const legacy = [
    params.chainId,
    params.dex,
    token0,
    token1,
    params.fee,
  ].join(":");
  if (params.dex === "uniswap_v4") {
    return [legacy, params.poolManager?.toLowerCase(), params.poolId?.toLowerCase() ?? params.id?.toLowerCase(),
      params.tickSpacing, params.hooks?.toLowerCase()].join(":");
  }
  return params.id ? `${legacy}:${params.id.toLowerCase()}` : legacy;
}

export function mergePoolObservation(
  current: PoolCacheObservation | undefined,
  next: PoolCacheObservation
) {
  if (!current) {
    return next;
  }

  const merged = {
    ...current,
    exists: current.exists || next.exists,
    poolAddress: next.poolAddress ?? current.poolAddress,
    quoteSucceeded: Boolean(current.quoteSucceeded || next.quoteSucceeded),
  } satisfies PoolCacheObservation;

  const activeLiquidityRaw = next.activeLiquidityRaw ?? current.activeLiquidityRaw;
  const sqrtPriceX96Raw = next.sqrtPriceX96Raw ?? current.sqrtPriceX96Raw;
  const tick = next.tick ?? current.tick;
  const token0BalanceRaw = next.token0BalanceRaw ?? current.token0BalanceRaw;
  const token1BalanceRaw = next.token1BalanceRaw ?? current.token1BalanceRaw;

  return {
    ...merged,
    ...(activeLiquidityRaw !== undefined ? { activeLiquidityRaw } : {}),
    ...(sqrtPriceX96Raw !== undefined ? { sqrtPriceX96Raw } : {}),
    ...(tick !== undefined ? { tick } : {}),
    ...(token0BalanceRaw !== undefined ? { token0BalanceRaw } : {}),
    ...(token1BalanceRaw !== undefined ? { token1BalanceRaw } : {}),
  } satisfies PoolCacheObservation;
}
