import type { RecoveryFundSnapshot } from "./recoveryFundSnapshot.ts";
import {
  buildRecoverySharePortfolio,
  type RecoveryShareBalanceRow,
} from "./recoverySharePersistence.ts";

export const RECOVERY_PORTFOLIO_MAX_POOLS = 256;
export const RECOVERY_PORTFOLIO_MAX_ACTIVE_FUNDS = 256;
export const RECOVERY_PORTFOLIO_MAX_BALANCES_PER_HOLDER = 256;

export type PortfolioPool = {
  asset: string;
  impaired: boolean;
  coreAttachedShares: string;
  externalShares: string;
  totalShares: string;
  redeemableRaw: string;
  cygldPerAssetRawFp18: string;
  cygldSupplyCap: string;
  referenceShares?: string;
  referenceValueCygld?: string;
  shareDecimals?: number;
  lifecycle: {
    asset: string;
    lifecycle: number;
    exitEntitlementRaw: string;
  };
  custody: {
    lifecycle: number;
    poolImpaired: boolean;
    redeemablePoolRaw: string;
    coreAttachedShares: string;
    externalShares: string;
    exitEntitlementRaw: string;
    liveBalanceAvailable: boolean;
    liveRawCustody: string;
    activeAvailableRaw: string;
    poolRawDeficit: string;
    exitEntitlementDeficitRaw: string;
  };
};

type CurrentFund = {
  impairedAsset: string;
  generation: string;
  coverageShares: string;
  purchasedShares: string;
  remainingCoverageShares: string;
  initialCygldCommitment: string;
  remainingCygldCommitment: string;
};

export type RecoveryPortfolioReadModel = {
  schemaVersion: "5.0";
  chainId: string;
  snapshotBlock: string;
  collection: string;
  recovery: {
    pools: PortfolioPool[];
    fund: {
      status: {
        configured: boolean;
        available: boolean;
        reason: RecoveryFundSnapshot["reason"];
        problem: string | null;
        governance: string | null;
        governancePaused: boolean | null;
        treasuryDeficit: string | null;
      };
      currentFunds: CurrentFund[];
    };
  } | null;
};

export function parseRecoveryPortfolioReadModel(
  value: unknown
): RecoveryPortfolioReadModel {
  const parsed = typeof value === "string" ? JSON.parse(value) : value;
  if (!parsed || typeof parsed !== "object") {
    throw new Error("Cached recovery portfolio read model is malformed");
  }
  const candidate = parsed as Record<string, unknown>;
  if (
    candidate.schemaVersion !== "5.0" ||
    typeof candidate.chainId !== "string" ||
    typeof candidate.snapshotBlock !== "string" ||
    typeof candidate.collection !== "string"
  ) {
    throw new Error("Cached recovery portfolio read model is malformed");
  }

  if (candidate.recovery !== null) {
    if (!candidate.recovery || typeof candidate.recovery !== "object") {
      throw new Error("Cached recovery portfolio read model is malformed");
    }
    const fund = (candidate.recovery as Record<string, unknown>).fund;
    if (!fund || typeof fund !== "object") {
      throw new Error("Cached recovery portfolio read model is malformed");
    }
    const status = (fund as Record<string, unknown>).status;
    if (!status || typeof status !== "object") {
      throw new Error("Cached recovery portfolio read model is malformed");
    }
    const pauseState = (status as Record<string, unknown>).governancePaused;
    if (pauseState !== null && typeof pauseState !== "boolean") {
      throw new Error("Cached recovery portfolio read model is malformed");
    }
  }

  return parsed as RecoveryPortfolioReadModel;
}

type RecoverySnapshotSource = {
  collection: string;
  pools: PortfolioPool[];
  fund: RecoveryFundSnapshot;
};

function canonicalUint(value: string, label: string) {
  if (!/^(0|[1-9][0-9]*)$/.test(value)) {
    throw new Error(`${label} is not a canonical unsigned integer`);
  }
  return BigInt(value);
}

function requireBoundedLength(value: unknown[], maximum: number, label: string) {
  if (value.length > maximum) {
    throw new Error(`${label} exceeds the configured cardinality limit of ${maximum}`);
  }
}

export function buildRecoveryPortfolioReadModel(
  chainId: bigint,
  snapshotBlock: bigint,
  collection: string,
  recovery: RecoverySnapshotSource | null
): RecoveryPortfolioReadModel {
  const base = {
    schemaVersion: "5.0" as const,
    chainId: chainId.toString(),
    snapshotBlock: snapshotBlock.toString(),
    collection: collection.toLowerCase(),
  };
  if (!recovery) return { ...base, recovery: null };
  if (recovery.collection.toLowerCase() !== base.collection) {
    throw new Error("Recovery portfolio collection differs from the configured Core");
  }
  requireBoundedLength(recovery.pools, RECOVERY_PORTFOLIO_MAX_POOLS, "Recovery pools");

  const currentFunds = recovery.fund.funds
    .filter((fund) => fund.active && fund.remainingCoverageShares !== "0")
    .map((fund) => ({
      impairedAsset: fund.impairedAsset,
      generation: fund.generation,
      coverageShares: fund.coverageShares,
      purchasedShares: fund.purchasedShares,
      remainingCoverageShares: fund.remainingCoverageShares,
      initialCygldCommitment: fund.initialCygldCommitment,
      remainingCygldCommitment: fund.remainingCygldCommitment,
    }));
  requireBoundedLength(
    currentFunds,
    RECOVERY_PORTFOLIO_MAX_ACTIVE_FUNDS,
    "Active Recovery Fund positions"
  );

  return {
    ...base,
    recovery: {
      pools: recovery.pools,
      fund: {
        status: {
          configured: recovery.fund.configured,
          available: recovery.fund.available,
          reason: recovery.fund.reason,
          problem: recovery.fund.problem,
          governance: recovery.fund.governance,
          governancePaused: recovery.fund.governancePaused,
          treasuryDeficit: recovery.fund.treasury?.deficit ?? null,
        },
        currentFunds,
      },
    },
  };
}

function holderFundOffers(
  model: RecoveryPortfolioReadModel,
  balances: RecoveryShareBalanceRow[]
) {
  const offers = new Map<string, unknown>();
  if (!model.recovery?.fund.status.available) return offers;

  const funds = new Map(
    model.recovery.fund.currentFunds.map((fund) => [
      BigInt(fund.impairedAsset).toString(),
      fund,
    ])
  );
  for (const row of balances) {
    const fund = funds.get(row.share_id);
    if (!fund) continue;
    const holderShares = canonicalUint(row.balance_raw, "Recovery-share holder balance");
    const coverageShares = canonicalUint(fund.coverageShares, "Recovery Fund coverage");
    const purchasedShares = canonicalUint(fund.purchasedShares, "Recovery Fund purchases");
    const remainingCapacity = canonicalUint(
      fund.remainingCoverageShares,
      "Recovery Fund remaining capacity"
    );
    if (
      coverageShares === 0n ||
      purchasedShares >= coverageShares ||
      remainingCapacity !== coverageShares - purchasedShares
    ) {
      throw new Error("Cached Recovery Fund capacity accounting is inconsistent");
    }
    const acceptedShares = holderShares < remainingCapacity ? holderShares : remainingCapacity;
    if (acceptedShares === 0n) continue;
    const generation = canonicalUint(fund.generation, "Recovery Fund generation");
    if (
      canonicalUint(
        model.recovery.fund.status.treasuryDeficit ?? "0",
        "Recovery Fund deficit"
      ) > 0n
    ) {
      offers.set(row.share_id, {
        available: false,
        generation: generation.toString(),
        problem: "CYGLD custody after allowance exposure is below current commitments",
      });
      continue;
    }

    const initial = canonicalUint(
      fund.initialCygldCommitment,
      "Recovery Fund initial commitment"
    );
    const remaining = canonicalUint(
      fund.remainingCygldCommitment,
      "Recovery Fund remaining commitment"
    );
    const before = (initial * purchasedShares) / coverageShares;
    const after = (initial * (purchasedShares + acceptedShares)) / coverageShares;
    const cygldAmount = after - before;
    if (cygldAmount === 0n || cygldAmount > remaining) {
      offers.set(row.share_id, {
        available: false,
        generation: generation.toString(),
        problem: "The bounded purchase amount produces no valid current payout",
      });
      continue;
    }
    offers.set(row.share_id, {
      available: true,
      impairedAsset: fund.impairedAsset,
      generation: generation.toString(),
      governancePaused: model.recovery.fund.status.governancePaused === true,
      holderShares: holderShares.toString(),
      acceptedShares: acceptedShares.toString(),
      remainingCapacity: remainingCapacity.toString(),
      cygldToken: model.collection,
      cygldAmount: cygldAmount.toString(),
    });
  }
  return offers;
}

export function materializeRecoverySharePortfolio(
  model: RecoveryPortfolioReadModel,
  balances: RecoveryShareBalanceRow[]
) {
  if (!model.recovery) {
    throw new Error("Cached Core recovery snapshot is unavailable");
  }
  requireBoundedLength(
    balances,
    RECOVERY_PORTFOLIO_MAX_BALANCES_PER_HOLDER,
    "Holder recovery-share balances"
  );
  if (new Set(balances.map((row) => row.share_id)).size !== balances.length) {
    throw new Error("Cached holder recovery-share balances contain duplicate share IDs");
  }
  return buildRecoverySharePortfolio({
    config: {
      chainId: BigInt(model.chainId),
      coreAddress: model.collection as `0x${string}`,
    },
    snapshotBlock: BigInt(model.snapshotBlock),
    balanceRows: balances,
    recovery: { pools: model.recovery.pools },
    fundStatus: model.recovery.fund.status,
    fundOffersByShareId: holderFundOffers(model, balances),
  });
}
