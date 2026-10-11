import assert from "node:assert/strict";
import test from "node:test";

import {
  recoveryFundCumulativePayout,
  recoveryFundCurrentTerms,
  recoveryFundTreasuryAccounting,
  recoveryFundUncoveredInterest,
} from "./recoveryFund.ts";

test("current Fund terms derive all remaining values from four stored fields", () => {
  assert.deepEqual(
    recoveryFundCurrentTerms({
      generation: 3n,
      coverageShares: 100n,
      purchasedShares: 20n,
      initialCygldCommitment: 80n,
    }),
    {
      active: true,
      remainingCoverageShares: 80n,
      paidCygld: 16n,
      remainingCygldCommitment: 64n,
    }
  );

  assert.deepEqual(
    recoveryFundCurrentTerms({
      generation: 3n,
      coverageShares: 0n,
      purchasedShares: 0n,
      initialCygldCommitment: 0n,
    }),
    {
      active: false,
      remainingCoverageShares: 0n,
      paidCygld: 0n,
      remainingCygldCommitment: 0n,
    }
  );
});

test("invalid or internally exhausted active Fund tuples fail closed", () => {
  assert.throws(
    () =>
      recoveryFundCurrentTerms({
        generation: 0n,
        coverageShares: 100n,
        purchasedShares: 0n,
        initialCygldCommitment: 80n,
      }),
    /Invalid Recovery Fund current terms/
  );
  assert.throws(
    () =>
      recoveryFundCurrentTerms({
        generation: 1n,
        coverageShares: 100n,
        purchasedShares: 100n,
        initialCygldCommitment: 80n,
      }),
    /Invalid Recovery Fund current terms/
  );
  assert.throws(
    () =>
      recoveryFundCurrentTerms({
        generation: 2n,
        coverageShares: 0n,
        purchasedShares: 1n,
        initialCygldCommitment: 0n,
      }),
    /Invalid exhausted Recovery Fund terms/
  );
});

test("native shares and CYGLD commitments have different units; frozen offers are not repriced", () => {
  const terms = recoveryFundCurrentTerms({
    generation: 1n, coverageShares: 100_000_000n,
    purchasedShares: 25_000_000n, initialCygldCommitment: 100n * 10n ** 18n,
  });
  assert.equal(terms.paidCygld, 25n * 10n ** 18n);
  assert.equal(terms.remainingCygldCommitment, 75n * 10n ** 18n);
  // No current admission anchors are used to revalidate this already-frozen offer.
});

test("cumulative-floor payouts are exact across partial purchases", () => {
  const first = recoveryFundCumulativePayout({
    commitment: 80n,
    purchasedBefore: 0n,
    shares: 20n,
    coverageShares: 90n,
  });
  const second = recoveryFundCumulativePayout({
    commitment: 80n,
    purchasedBefore: 20n,
    shares: 20n,
    coverageShares: 90n,
  });
  const final = recoveryFundCumulativePayout({
    commitment: 80n,
    purchasedBefore: 40n,
    shares: 50n,
    coverageShares: 90n,
  });

  assert.equal(first, 17n);
  assert.equal(second, 18n);
  assert.equal(final, 45n);
  assert.equal(first + second + final, 80n);
  assert.throws(
    () =>
      recoveryFundCumulativePayout({
        commitment: 80n,
        purchasedBefore: 90n,
        shares: 1n,
        coverageShares: 90n,
      }),
    /Invalid Recovery Fund cumulative-payout inputs/
  );
});

test("uncovered interest derives from current Core and Governance balances", () => {
  assert.equal(
    recoveryFundUncoveredInterest({
      coreAttachedShares: 80n,
      externalShares: 20n,
      governanceBalance: 10n,
    }),
    90n
  );
  assert.throws(
    () =>
      recoveryFundUncoveredInterest({
        coreAttachedShares: 0n,
        externalShares: 1n,
        governanceBalance: 2n,
      }),
    /Invalid Recovery Fund uncovered-interest inputs/
  );
});

test("the three-field treasury tuple derives unallowanced capacity and deficit", () => {
  assert.deepEqual(
    recoveryFundTreasuryAccounting({
      balance: 100n,
      allowanceExposure: 15n,
      committed: 60n,
    }),
    { unallowanced: 85n, available: 25n, deficit: 0n }
  );
  assert.deepEqual(
    recoveryFundTreasuryAccounting({
      balance: 100n,
      allowanceExposure: 30n,
      committed: 80n,
    }),
    { unallowanced: 70n, available: 0n, deficit: 10n }
  );
  assert.throws(
    () =>
      recoveryFundTreasuryAccounting({
        balance: 100n,
        allowanceExposure: 101n,
        committed: 0n,
      }),
    /Invalid Recovery Fund treasury accounting/
  );
});
