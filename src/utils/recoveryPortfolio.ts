import type { Address } from "viem";
import type { CurrentRecoveryPoolSnapshot, CurrentReserveCustodySnapshot,
  CurrentReserveLifecycleSnapshot } from "./recovery.ts";

export type RecoveryPool = CurrentRecoveryPoolSnapshot & {
  asset: Address;
  referenceShares: string;
  referenceValueCygld: string;
  shareDecimals: number;
  lifecycle: CurrentReserveLifecycleSnapshot;
  custody: CurrentReserveCustodySnapshot;
};

export type RecoveryFundPortfolioStatus = {
  configured: boolean;
  available: boolean;
  reason: "not-configured" | "unavailable-or-inconsistent" | null;
  problem: string | null;
  governance: Address | null;
  governancePaused: boolean | null;
};

export type RecoveryShareBalance = {
  shareId: string;
  balanceRaw: string;
  pool: RecoveryPool;
  payoutRaw: string | null;
  payoutProblem: "custody-unavailable" | "preview-unavailable" | null;
  fundOffer: {
    available: true;
    impairedAsset: Address;
    generation: string;
    governancePaused: boolean;
    holderShares: string;
    acceptedShares: string;
    remainingCapacity: string;
    cygldToken: Address;
    cygldAmount: string;
  } | { available: false; generation: string; problem: string } | null;
};

export type RecoverySharePortfolio = {
  enabled: boolean;
  status: "ready" | "not-configured";
  schemaVersion: string;
  chainId: string;
  collection: Address | null;
  snapshotBlock: string | null;
  snapshotBlockHash: string | null;
  complete: boolean;
  nextOffset: string | null;
  totalAssets: string;
  corePaused: boolean | null;
  fund: RecoveryFundPortfolioStatus | null;
  balances: RecoveryShareBalance[];
  pools: RecoveryPool[];
};

export const RECOVERY_RPC_SCHEMA = "recovery-rpc-native-v1";
export const EMPTY_RECOVERY_PORTFOLIO: RecoverySharePortfolio = {
  enabled: false, status: "not-configured", schemaVersion: RECOVERY_RPC_SCHEMA,
  chainId: "", collection: null, snapshotBlock: null, snapshotBlockHash: null,
  complete: false, nextOffset: null, totalAssets: "0", corePaused: null,
  fund: null, balances: [], pools: [],
};

/** The displayed portfolio must belong to the deployment the wallet will call. */
export function assertRecoveryPortfolioDeployment(
  page: RecoverySharePortfolio, chainId: number, collection: Address
) {
  if (!page.enabled) return;
  if (page.chainId !== String(chainId)) throw new Error("Recovery snapshot chain differs from the configured wallet chain");
  if (page.collection?.toLowerCase() !== collection.toLowerCase()) {
    throw new Error("Recovery snapshot Core differs from the configured settlement Core");
  }
}

export function recoverySettlementFailureMessage(submitted: boolean, reverted: boolean) {
  if (reverted) return "The transaction reverted. This transaction did not burn your recovery shares.";
  if (submitted) return "The transaction was submitted, but its outcome is not confirmed. It may still complete or already have completed. Check your wallet and refresh before retrying.";
  return "Redemption was not confirmed. The token transfer, wallet or RPC may be unavailable. Check your wallet and refresh before retrying; a submission error does not prove the chain outcome.";
}

export function recoveryActiveBackingLabel(pool: RecoveryPool) {
  if (pool.lifecycle.lifecycle !== 1) return "N/A (asset is not Active)";
  return pool.custody.liveBalanceAvailable
    ? `${pool.custody.activeAvailableRaw} asset base units`
    : "Unavailable; custody balance is unreadable";
}

/** Never promote partial discovery, or pages from another state, to a portfolio. */
export function mergeRecoveryPortfolioPages(
  previous: RecoverySharePortfolio | undefined,
  page: RecoverySharePortfolio
): RecoverySharePortfolio {
  if (!page.enabled || page.status !== "ready") return page;
  if (!page.snapshotBlockHash || !page.snapshotBlock || !page.collection) {
    throw new Error("Recovery snapshot identity is missing");
  }
  if (!previous) return page;
  if (previous.complete || previous.snapshotBlockHash !== page.snapshotBlockHash ||
      previous.snapshotBlock !== page.snapshotBlock || previous.chainId !== page.chainId ||
      previous.collection !== page.collection || previous.schemaVersion !== page.schemaVersion ||
      previous.totalAssets !== page.totalAssets || previous.corePaused !== page.corePaused) {
    throw new Error("Recovery portfolio pages do not share one snapshot");
  }
  const seen = new Set(previous.pools.map((pool) => pool.asset.toLowerCase()));
  if (page.pools.some((pool) => seen.has(pool.asset.toLowerCase()))) {
    throw new Error("Recovery portfolio contains duplicate assets");
  }
  return { ...page,
    // A later healthy Fund read must not erase an earlier page's missing offers.
    fund: previous.fund?.configured && !previous.fund.available ? previous.fund : page.fund,
    pools: [...previous.pools, ...page.pools],
    balances: [...previous.balances, ...page.balances] };
}
