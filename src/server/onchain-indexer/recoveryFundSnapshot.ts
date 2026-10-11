import { createPublicClient, type Address, type Hex } from "viem";

import { GOVERNANCE_DIAMOND_ABI } from "@/contracts/generated/governanceDiamond";
import {
  recoveryFundCurrentTerms,
  recoveryFundTreasuryAccounting,
  recoveryFundUncoveredInterest,
} from "@/utils/recoveryFund";

type RecoveryFundReadClient = ReturnType<typeof createPublicClient>;

export type StateReadTarget =
  | Readonly<{
      blockNumber: bigint;
      blockHash?: undefined;
      requireCanonical?: undefined;
    }>
  | Readonly<{
      blockNumber?: undefined;
      blockHash: Hex;
      requireCanonical: true;
    }>;

export type CorePoolForRecoveryFund = {
  asset: string;
  impaired: boolean;
  coreAttachedShares: string;
  externalShares: string;
  redeemableRaw: string;
};

type AssetRecoveryFundRead = {
  generation: bigint;
  coverageShares: bigint;
  purchasedShares: bigint;
  initialCygldCommitment: bigint;
};

export type RecoveryFundSnapshot = {
  configured: boolean;
  available: boolean;
  reason: "not-configured" | "unavailable-or-inconsistent" | null;
  problem: string | null;
  governance: string | null;
  trustedCore: string | null;
  governancePaused: boolean | null;
  treasury: {
    balance: string;
    allowanceExposure: string;
    unallowanced: string;
    aggregateCommitment: string;
    available: string;
    deficit: string;
  } | null;
  funds: Array<{
    impairedAsset: string;
    generation: string;
    active: boolean;
    coverageShares: string;
    purchasedShares: string;
    remainingCoverageShares: string;
    initialCygldCommitment: string;
    paidCygld: string;
    remainingCygldCommitment: string;
    governanceBalance: string;
    uncoveredInterest: string;
    currentlyUnfundedInterest: string;
    acquiredShares: string;
    purchasePreview: {
      generation: string;
      shares: string;
      cygldAmount: string;
    } | null;
  }>;
};

function unavailableSnapshot(
  governance: Address | null,
  reason: RecoveryFundSnapshot["reason"],
  problem: string | null
): RecoveryFundSnapshot {
  return {
    configured: governance !== null,
    available: false,
    reason,
    problem,
    governance: governance?.toLowerCase() ?? null,
    trustedCore: null,
    governancePaused: null,
    treasury: null,
    funds: [],
  };
}

async function readAvailableRecoveryFundSnapshot(params: {
  coreAddress: Address;
  governanceAddress: Address;
  stateReadTarget: StateReadTarget;
  client: RecoveryFundReadClient;
  pools: CorePoolForRecoveryFund[];
}): Promise<RecoveryFundSnapshot> {
  const { coreAddress, governanceAddress, stateReadTarget, client, pools } = params;
  const [trustedCore, governancePaused, treasuryTuple] = await Promise.all([
    client.readContract({
      address: governanceAddress,
      abi: GOVERNANCE_DIAMOND_ABI,
      functionName: "trustedRecoveryFundCore",
      ...stateReadTarget,
    }),
    client.readContract({
      address: governanceAddress,
      abi: GOVERNANCE_DIAMOND_ABI,
      functionName: "paused",
      ...stateReadTarget,
    }),
    client.readContract({
      address: governanceAddress,
      abi: GOVERNANCE_DIAMOND_ABI,
      functionName: "recoveryFundTreasuryStatus",
      ...stateReadTarget,
    }),
  ]);

  if (trustedCore.toLowerCase() !== coreAddress.toLowerCase()) {
    throw new Error("Recovery Fund trusted Core does not match the indexed Core");
  }

  const [balance, allowanceExposure, committed] = treasuryTuple;
  const treasuryDerived = recoveryFundTreasuryAccounting({
    balance,
    allowanceExposure,
    committed,
  });

  const funds = await Promise.all(
    pools.map(async (pool) => {
      const impairedAsset = pool.asset as Address;
      const [fundRaw, acquiredShares] = await Promise.all([
        client.readContract({
          address: governanceAddress,
          abi: GOVERNANCE_DIAMOND_ABI,
          functionName: "assetRecoveryFund",
          args: [impairedAsset],
          ...stateReadTarget,
        }),
        client.readContract({
          address: governanceAddress,
          abi: GOVERNANCE_DIAMOND_ABI,
          functionName: "acquiredRecoveryShares",
          args: [impairedAsset],
          ...stateReadTarget,
        }),
      ]);
      const governanceBalance = acquiredShares;
      const fund = fundRaw as AssetRecoveryFundRead;
      const derived = recoveryFundCurrentTerms(fund);
      const uncoveredInterest = recoveryFundUncoveredInterest({
        coreAttachedShares: BigInt(pool.coreAttachedShares),
        externalShares: BigInt(pool.externalShares),
        governanceBalance,
      });
      const currentlyUnfundedInterest =
        uncoveredInterest > derived.remainingCoverageShares
          ? uncoveredInterest - derived.remainingCoverageShares
          : 0n;

      let purchasePreview: RecoveryFundSnapshot["funds"][number]["purchasePreview"] = null;
      if (derived.active && derived.remainingCoverageShares > 0n) {
        const [generation, cygldAmount] = await client.readContract({
          address: governanceAddress,
          abi: GOVERNANCE_DIAMOND_ABI,
          functionName: "previewAssetRecoveryFundPurchase",
          args: [impairedAsset, derived.remainingCoverageShares],
          ...stateReadTarget,
        });
        if (
          generation !== fund.generation ||
          cygldAmount !== derived.remainingCygldCommitment
        ) {
          throw new Error("Recovery Fund current purchase preview does not reconcile");
        }
        purchasePreview = {
          generation: generation.toString(),
          shares: derived.remainingCoverageShares.toString(),
          cygldAmount: cygldAmount.toString(),
        };
      }

      return {
        impairedAsset: impairedAsset.toLowerCase(),
        generation: fund.generation.toString(),
        active: derived.active,
        coverageShares: fund.coverageShares.toString(),
        purchasedShares: fund.purchasedShares.toString(),
        remainingCoverageShares: derived.remainingCoverageShares.toString(),
        initialCygldCommitment: fund.initialCygldCommitment.toString(),
        paidCygld: derived.paidCygld.toString(),
        remainingCygldCommitment: derived.remainingCygldCommitment.toString(),
        governanceBalance: governanceBalance.toString(),
        uncoveredInterest: uncoveredInterest.toString(),
        currentlyUnfundedInterest: currentlyUnfundedInterest.toString(),
        acquiredShares: acquiredShares.toString(),
        purchasePreview,
      };
    })
  );

  const summedCommitments = funds.reduce(
    (sum, fund) => sum + BigInt(fund.remainingCygldCommitment),
    0n
  );
  if (summedCommitments !== committed) {
    throw new Error("Recovery Fund aggregate commitment does not reconcile");
  }

  return {
    configured: true,
    available: true,
    reason: null,
    problem: null,
    governance: governanceAddress.toLowerCase(),
    trustedCore: trustedCore.toLowerCase(),
    governancePaused,
    treasury: {
      balance: balance.toString(),
      allowanceExposure: allowanceExposure.toString(),
      unallowanced: treasuryDerived.unallowanced.toString(),
      aggregateCommitment: committed.toString(),
      available: treasuryDerived.available.toString(),
      deficit: treasuryDerived.deficit.toString(),
    },
    funds,
  };
}

export async function readRecoveryFundSnapshot(params: {
  coreAddress: Address;
  governanceAddress: Address | null;
  stateReadTarget: StateReadTarget;
  client: RecoveryFundReadClient;
  pools: CorePoolForRecoveryFund[];
  isTerminalReadFailure?(error: unknown): boolean;
}): Promise<RecoveryFundSnapshot> {
  if (!params.governanceAddress) {
    return unavailableSnapshot(null, "not-configured", null);
  }
  try {
    return await readAvailableRecoveryFundSnapshot({
      ...params,
      governanceAddress: params.governanceAddress,
    });
  } catch (cause) {
    if (params.isTerminalReadFailure?.(cause)) throw cause;
    return unavailableSnapshot(
      params.governanceAddress,
      "unavailable-or-inconsistent",
      cause instanceof Error ? cause.message : "Recovery Fund snapshot failed"
    );
  }
}
