import type { Address, Hex } from "viem";
import { RECOVERY_RPC_SCHEMA, type RecoveryPool, type RecoveryShareBalance,
  type RecoverySharePortfolio, type RecoveryFundPortfolioStatus } from "../../utils/recoveryPortfolio.ts";

export const RECOVERY_PAGE_SIZE = 64n;
const CACHE_TTL_MS = 10_000;
const MAX_CACHE_ENTRIES = 128;
export type RecoveryPageRequest = { offset?: bigint; blockHash?: Hex };
export type RecoveryBlock = { number: bigint; hash: Hex };
export interface RecoveryRpcReader {
  chainId: bigint;
  core: Address;
  block(hash?: Hex): Promise<RecoveryBlock>;
  assertCanonical(block: RecoveryBlock): Promise<void>;
  count(block: RecoveryBlock): Promise<bigint>;
  assets(block: RecoveryBlock, offset: bigint): Promise<readonly [readonly Address[], bigint]>;
  paused(block: RecoveryBlock): Promise<boolean>;
  pools(block: RecoveryBlock, assets: readonly Address[]): Promise<RecoveryPool[]>;
  balances(block: RecoveryBlock, holder: Address, assets: readonly Address[]): Promise<readonly bigint[]>;
  preview(block: RecoveryBlock, asset: Address, shares: bigint): Promise<bigint>;
  fund(block: RecoveryBlock, holder: Address, entries: RecoveryShareBalance[]): Promise<{
    status: RecoveryFundPortfolioStatus; offers: RecoveryShareBalance["fundOffer"][];
  }>;
}

type PoolPage = { pools: RecoveryPool[]; total: bigint; next: bigint; paused: boolean };
type Cached<T> = { expires: number; value: Promise<T> };

/** Bounded in-memory caches only. Hash identity prevents same-height fork reset reuse. */
export function createRecoveryPortfolioReader(reader: RecoveryRpcReader, now = Date.now) {
  const pages = new Map<string, Cached<PoolPage>>();
  const wallets = new Map<string, Cached<readonly bigint[]>>();
  async function cached<T>(cache: Map<string, Cached<T>>, key: string, read: () => Promise<T>) {
    const entry = cache.get(key);
    if (entry && entry.expires > now()) return entry.value;
    cache.delete(key);
    if (cache.size >= MAX_CACHE_ENTRIES) cache.delete(cache.keys().next().value!);
    const value = read();
    cache.set(key, { expires: now() + CACHE_TTL_MS, value });
    try { return await value; } catch (error) { cache.delete(key); throw error; }
  }
  return async (holder: Address, request: RecoveryPageRequest = {}): Promise<RecoverySharePortfolio> => {
    const offset = request.offset ?? 0n;
    if (offset < 0n || (offset > 0n && !request.blockHash)) {
      throw new Error("Recovery continuation requires its snapshot block hash");
    }
    const block = await reader.block(request.blockHash);
    const identity = `${RECOVERY_RPC_SCHEMA}:${reader.chainId}:${reader.core.toLowerCase()}:${block.hash.toLowerCase()}`;
    // Canonicality is checked even on cache hits. EIP-1898 reads also requireCanonical.
    await reader.assertCanonical(block);
    const page = await cached(pages, `${identity}:${offset}`, async () => {
      const [total, [assets, next], paused] = await Promise.all([
        reader.count(block), reader.assets(block, offset), reader.paused(block),
      ]);
      const remaining = total > offset ? total - offset : 0n;
      const expected = remaining < RECOVERY_PAGE_SIZE ? remaining : RECOVERY_PAGE_SIZE;
      if (BigInt(assets.length) !== expected || next !== (offset >= total ? total : offset + expected) ||
          new Set(assets.map((asset) => asset.toLowerCase())).size !== assets.length) {
        throw new Error("Recovery registry page is incomplete or inconsistent");
      }
      const pools = await reader.pools(block, assets);
      if (pools.length !== assets.length || pools.some((pool, i) => pool.asset.toLowerCase() !== assets[i]?.toLowerCase())) {
        throw new Error("Recovery pool page does not match the registry");
      }
      return { pools, total, next, paused };
    });
    const assets = page.pools.map((pool) => pool.asset);
    const balances = await cached(wallets, `${identity}:${holder.toLowerCase()}:${offset}`, () => reader.balances(block, holder, assets));
    if (balances.length !== page.pools.length) throw new Error("Recovery balance batch is incomplete");
    const entries = await Promise.all(page.pools.flatMap((pool, index) => {
      const shares = balances[index]!;
      if (shares < 0n || shares > BigInt(pool.externalShares)) throw new Error("Recovery holder supply is inconsistent");
      if (shares === 0n) return [];
      return [(async (): Promise<RecoveryShareBalance> => {
        let payoutRaw: string | null = null;
        let payoutProblem: RecoveryShareBalance["payoutProblem"] = null;
        if (!pool.custody.liveBalanceAvailable) payoutProblem = "custody-unavailable";
        else {
          try { payoutRaw = (await reader.preview(block, pool.asset, shares)).toString(); }
          catch { payoutProblem = "preview-unavailable"; }
        }
        return { shareId: BigInt(pool.asset).toString(), balanceRaw: shares.toString(),
          pool, payoutRaw, payoutProblem, fundOffer: null };
      })()];
    }));
    // Fund failures are not discovery failures, and do not erase ownership.
    let fund: RecoveryFundPortfolioStatus;
    try {
      const optional = await reader.fund(block, holder, entries);
      fund = optional.status;
      entries.forEach((entry, index) => { entry.fundOffer = optional.offers[index] ?? null; });
    } catch {
      fund = { configured: true, available: false, reason: "unavailable-or-inconsistent",
        problem: "Governance Fund is unavailable", governance: null, governancePaused: null };
    }
    await reader.assertCanonical(block);
    return { enabled: true, status: "ready", schemaVersion: RECOVERY_RPC_SCHEMA,
      chainId: reader.chainId.toString(), collection: reader.core,
      snapshotBlock: block.number.toString(), snapshotBlockHash: block.hash,
      complete: page.next === page.total, nextOffset: page.next === page.total ? null : page.next.toString(),
      totalAssets: page.total.toString(), corePaused: page.paused, fund, balances: entries, pools: page.pools };
  };
}
