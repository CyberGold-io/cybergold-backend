
import type { QueryResultRow } from "pg";
import type { Address } from "viem";

import type {
  CachedPoolCandidate,
  PoolCacheLookupParams,
  PoolCacheObservation,
  PoolCacheRecordParams,
} from "@/types";
import { ensureSchema, query } from "@/server/onchain-indexer/db";
import {
  buildPoolCacheEntryKey,
  mergePoolObservation,
  normalizePoolPair,
} from "@/utils/poolCachePair";

type CachedPoolRow = QueryResultRow & {
  dex: string;
  token0: string;
  token1: string;
  fee: number;
  poolAddress: string | null;
  exists: boolean;
  successCount: number;
  activeLiquidityRaw: string | null;
  sqrtPriceX96Raw: string | null;
  tick: number | null;
  token0BalanceRaw: string | null;
  token1BalanceRaw: string | null;
  liquidityCheckedAt: Date | string | null;
  lastCheckedAt: Date | string | null;
};

const POOL_EXISTENCE_CACHE_MAX_AGE_SQL = "24 hours";

function normalizeAddress(value: Address) {
  return value.toLowerCase() as Address;
}

function normalizeObservations(entries: readonly PoolCacheObservation[]) {
  const deduped = new Map<string, PoolCacheObservation>();

  for (const entry of entries) {
    const key = buildPoolCacheEntryKey({
      ...entry,
      chainId: entry.chainId,
      dex: entry.dex,
      tokenA: entry.tokenA,
      tokenB: entry.tokenB,
      fee: entry.fee,
    });
    const merged = mergePoolObservation(
      deduped.get(key),
      {
        ...entry,
        tokenA: normalizeAddress(entry.tokenA),
        tokenB: normalizeAddress(entry.tokenB),
        poolAddress: entry.poolAddress
          ? normalizeAddress(entry.poolAddress)
          : undefined,
      }
    );
    deduped.set(key, merged);
  }

  return Array.from(deduped.values());
}

export async function listCachedPools(
  params: PoolCacheLookupParams
): Promise<CachedPoolCandidate[]> {
  await ensureSchema();

  const normalizedPairs = Array.from(
    new Map(
      params.pairs.map((pair) => {
        const normalized = normalizePoolPair(pair);
        return [`${normalized.token0}:${normalized.token1}`, normalized] as const;
      })
    ).values()
  );

  if (normalizedPairs.length === 0) {
    return [];
  }

  const sqlParams: unknown[] = [
    params.chainId,
    params.dex,
    POOL_EXISTENCE_CACHE_MAX_AGE_SQL,
  ];
  const pairClauses = normalizedPairs.map((pair) => {
    const token0Index = sqlParams.push(pair.token0);
    const token1Index = sqlParams.push(pair.token1);
    return `(token0 = $${token0Index} AND token1 = $${token1Index})`;
  });

  const result = await query<CachedPoolRow>(
    `
      SELECT
        dex,
        token0,
        token1,
        fee,
        pool_address AS "poolAddress",
        exists,
        success_count AS "successCount",
        active_liquidity_raw AS "activeLiquidityRaw",
        sqrt_price_x96_raw AS "sqrtPriceX96Raw",
        tick,
        token0_balance_raw AS "token0BalanceRaw",
        token1_balance_raw AS "token1BalanceRaw",
        liquidity_checked_at AS "liquidityCheckedAt",
        last_checked_at AS "lastCheckedAt"
      FROM quote_pool_cache
      WHERE chain_id = $1
        AND dex = $2
        AND last_checked_at >= NOW() - $3::interval
        AND (${pairClauses.join(" OR ")})
      ORDER BY exists DESC, success_count DESC, fee ASC;
    `,
    sqlParams
  );

  return result.rows.map((row) => ({
    dex: row.dex as CachedPoolCandidate["dex"],
    token0: normalizeAddress(row.token0 as Address),
    token1: normalizeAddress(row.token1 as Address),
    fee: row.fee,
    poolAddress: row.poolAddress
      ? normalizeAddress(row.poolAddress as Address)
      : undefined,
    exists: row.exists,
    successCount: row.successCount,
    activeLiquidityRaw: row.activeLiquidityRaw ?? undefined,
    sqrtPriceX96Raw: row.sqrtPriceX96Raw ?? undefined,
    tick: row.tick ?? undefined,
    token0BalanceRaw: row.token0BalanceRaw ?? undefined,
    token1BalanceRaw: row.token1BalanceRaw ?? undefined,
    liquidityCheckedAt: row.liquidityCheckedAt
      ? new Date(row.liquidityCheckedAt).toISOString()
      : undefined,
    lastCheckedAt: row.lastCheckedAt
      ? new Date(row.lastCheckedAt).toISOString()
      : undefined,
  }));
}

export async function recordPoolObservations(params: PoolCacheRecordParams) {
  await ensureSchema();

  const normalizedEntries = normalizeObservations(params.entries);
  for (const entry of normalizedEntries) {
    const { token0, token1 } = normalizePoolPair({
      tokenA: entry.tokenA,
      tokenB: entry.tokenB,
    });

    await query(
      `
        INSERT INTO quote_pool_cache (
          chain_id,
          dex,
          token0,
          token1,
          fee,
          pool_address,
          exists,
          success_count,
          active_liquidity_raw,
          sqrt_price_x96_raw,
          tick,
          token0_balance_raw,
          token1_balance_raw,
          liquidity_checked_at,
          last_checked_at,
          last_success_at
        )
        VALUES (
          $1,
          $2,
          $3,
          $4,
          $5,
          $6,
          $7,
          $8,
          $9,
          $10,
          $11,
          $12,
          $13,
          CASE WHEN $9::text IS NOT NULL THEN NOW() ELSE NULL END,
          NOW(),
          CASE WHEN $8 > 0 THEN NOW() ELSE NULL END
        )
        ON CONFLICT (chain_id, dex, token0, token1, fee)
        DO UPDATE SET
          pool_address = COALESCE(EXCLUDED.pool_address, quote_pool_cache.pool_address),
          exists = quote_pool_cache.exists OR EXCLUDED.exists,
          success_count = quote_pool_cache.success_count + EXCLUDED.success_count,
          active_liquidity_raw = COALESCE(EXCLUDED.active_liquidity_raw, quote_pool_cache.active_liquidity_raw),
          sqrt_price_x96_raw = COALESCE(EXCLUDED.sqrt_price_x96_raw, quote_pool_cache.sqrt_price_x96_raw),
          tick = COALESCE(EXCLUDED.tick, quote_pool_cache.tick),
          token0_balance_raw = COALESCE(EXCLUDED.token0_balance_raw, quote_pool_cache.token0_balance_raw),
          token1_balance_raw = COALESCE(EXCLUDED.token1_balance_raw, quote_pool_cache.token1_balance_raw),
          liquidity_checked_at = COALESCE(EXCLUDED.liquidity_checked_at, quote_pool_cache.liquidity_checked_at),
          last_checked_at = NOW(),
          last_success_at = CASE
            WHEN EXCLUDED.success_count > 0 THEN NOW()
            ELSE quote_pool_cache.last_success_at
          END,
          updated_at = NOW();
      `,
      [
        entry.chainId,
        entry.dex,
        token0,
        token1,
        entry.fee,
        entry.poolAddress ? normalizeAddress(entry.poolAddress) : null,
        entry.exists,
        entry.quoteSucceeded ? 1 : 0,
        entry.activeLiquidityRaw ?? null,
        entry.sqrtPriceX96Raw ?? null,
        entry.tick ?? null,
        entry.token0BalanceRaw ?? null,
        entry.token1BalanceRaw ?? null,
      ]
    );
  }
}
