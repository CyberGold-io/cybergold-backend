/**
 * Derive the exact cumulative-floor payment for one current Recovery Fund
 * purchase. Governance stores only the current generation terms.
 */
export function recoveryFundCumulativePayout(params: {
  commitment: bigint;
  purchasedBefore: bigint;
  shares: bigint;
  coverageShares: bigint;
}) {
  const { commitment, purchasedBefore, shares, coverageShares } = params;
  const purchasedAfter = purchasedBefore + shares;
  if (
    commitment <= 0n ||
    purchasedBefore < 0n ||
    shares <= 0n ||
    coverageShares <= 0n ||
    purchasedAfter > coverageShares
  ) {
    throw new Error("Invalid Recovery Fund cumulative-payout inputs");
  }
  return (
    (commitment * purchasedAfter) / coverageShares -
    (commitment * purchasedBefore) / coverageShares
  );
}

export function recoveryFundCurrentTerms(params: {
  generation: bigint;
  coverageShares: bigint;
  purchasedShares: bigint;
  initialCygldCommitment: bigint;
}) {
  const {
    generation,
    coverageShares,
    purchasedShares,
    initialCygldCommitment,
  } = params;
  if (generation < 0n || coverageShares < 0n || purchasedShares < 0n) {
    throw new Error("Invalid Recovery Fund current terms");
  }
  if (coverageShares === 0n) {
    if (purchasedShares !== 0n || initialCygldCommitment !== 0n) {
      throw new Error("Invalid exhausted Recovery Fund terms");
    }
    return {
      active: false,
      remainingCoverageShares: 0n,
      paidCygld: 0n,
      remainingCygldCommitment: 0n,
    };
  }
  if (
    generation === 0n ||
    purchasedShares >= coverageShares ||
    initialCygldCommitment <= 0n
  ) {
    throw new Error("Invalid Recovery Fund current terms");
  }
  const paidCygld =
    (initialCygldCommitment * purchasedShares) / coverageShares;
  return {
    active: true,
    remainingCoverageShares: coverageShares - purchasedShares,
    paidCygld,
    remainingCygldCommitment: initialCygldCommitment - paidCygld,
  };
}

export function recoveryFundUncoveredInterest(params: {
  coreAttachedShares: bigint;
  externalShares: bigint;
  governanceBalance: bigint;
}) {
  const { coreAttachedShares, externalShares, governanceBalance } = params;
  if (
    coreAttachedShares < 0n ||
    externalShares < 0n ||
    governanceBalance < 0n ||
    governanceBalance > externalShares
  ) {
    throw new Error("Invalid Recovery Fund uncovered-interest inputs");
  }
  return coreAttachedShares + externalShares - governanceBalance;
}

export function recoveryFundTreasuryAccounting(params: {
  balance: bigint;
  allowanceExposure: bigint;
  committed: bigint;
}) {
  const { balance, allowanceExposure, committed } = params;
  if (
    balance < 0n ||
    allowanceExposure < 0n ||
    allowanceExposure > balance ||
    committed < 0n
  ) {
    throw new Error("Invalid Recovery Fund treasury accounting");
  }
  const unallowanced = balance - allowanceExposure;
  return {
    unallowanced,
    available: unallowanced > committed ? unallowanced - committed : 0n,
    deficit: committed > unallowanced ? committed - unallowanced : 0n,
  };
}
