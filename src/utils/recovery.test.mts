import assert from "node:assert/strict";
import test from "node:test";

import {
  applyIndexedRecoveryShareTransfer,
  reconcileRecoveryPoolLifecycleSnapshot,
  recoveryShareIdForAsset,
  recoverySharePayout,
  replayIndexedRecoveryShareTransfers,
  reserveLifecycleLabel,
  type IndexedRecoveryShareTransfer,
} from "./recovery.ts";

const ZERO = "0x0000000000000000000000000000000000000000";
const ALICE = "0x00000000000000000000000000000000000000a1";
const BOB = "0x00000000000000000000000000000000000000b2";
const ASSET_A = "0x0000000000000000000000000000000000000011";
const ASSET_B = "0x0000000000000000000000000000000000000022";
const OPERATOR = "0x00000000000000000000000000000000000000c3";

function transfer(
  from: typeof ZERO | typeof ALICE | typeof BOB,
  to: typeof ZERO | typeof ALICE | typeof BOB,
  ids: bigint[],
  amounts: bigint[]
): IndexedRecoveryShareTransfer {
  return { operator: OPERATOR, from, to, ids, amounts };
}

test("reserve lifecycle labels remain explicit without persisted cause labels", () => {
  assert.equal(reserveLifecycleLabel(0), "Inactive");
  assert.equal(reserveLifecycleLabel(1), "Active");
  assert.equal(reserveLifecycleLabel(2), "Exiting");
  assert.equal(reserveLifecycleLabel(3), "Unknown");
  assert.equal(reserveLifecycleLabel(99), "Unknown");
});

function lifecycleSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    asset: ASSET_A,
    lifecycle: 1,
    exitEntitlementRaw: "0",
    ...overrides,
  };
}

function poolSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    asset: ASSET_A,
    impaired: true,
    coreAttachedShares: "100",
    externalShares: "25",
    totalShares: "125",
    redeemableRaw: "25",
    cygldPerAssetRawFp18: "0",
    cygldSupplyCap: "0",
    ...overrides,
  };
}

function custodySnapshot(overrides: Record<string, unknown> = {}) {
  return {
    lifecycle: 1,
    poolImpaired: true,
    redeemablePoolRaw: "25",
    coreAttachedShares: "100",
    externalShares: "25",
    exitEntitlementRaw: "0",
    liveBalanceAvailable: true,
    liveRawCustody: "150",
    activeAvailableRaw: "125",
    poolRawDeficit: "0",
    exitEntitlementDeficitRaw: "0",
    ...overrides,
  };
}

test("pool/lifecycle reconciliation retains only current authoritative lenses", () => {
  const reconciled = reconcileRecoveryPoolLifecycleSnapshot(
    poolSnapshot(),
    lifecycleSnapshot(),
    custodySnapshot()
  );

  assert.equal(reconciled.lifecycle.lifecycle, 1);
  assert.equal(reconciled.lifecycle.exitEntitlementRaw, "0");
  assert.equal(reconciled.redeemableRaw, "25");
  assert.equal(reconciled.custody.liveRawCustody, "150");
  assert.equal(reconciled.custody.activeAvailableRaw, "125");
  assert.equal("transitionNonce" in reconciled, false);
  assert.equal("checkpointBlock" in reconciled, false);
  assert.equal("accountedRaw" in reconciled, false);
});

test("pool/lifecycle reconciliation rejects inconsistent current lenses", () => {
  assert.throws(
    () =>
      reconcileRecoveryPoolLifecycleSnapshot(
        poolSnapshot(),
        lifecycleSnapshot({ asset: ASSET_B }),
        custodySnapshot()
      ),
    /views are inconsistent/
  );
  assert.throws(
    () =>
      reconcileRecoveryPoolLifecycleSnapshot(
        poolSnapshot({ totalShares: "124" }),
        lifecycleSnapshot(),
        custodySnapshot()
      ),
    /share totals are inconsistent/
  );
  assert.throws(
    () =>
      reconcileRecoveryPoolLifecycleSnapshot(
        poolSnapshot(),
        lifecycleSnapshot(),
        custodySnapshot({ liveBalanceAvailable: false, liveRawCustody: "1" })
      ),
    /views are inconsistent/
  );
});

test("asset addresses map injectively to canonical recovery-share IDs", () => {
  assert.equal(recoveryShareIdForAsset(ASSET_A), BigInt(ASSET_A));
  assert.equal(recoveryShareIdForAsset(ASSET_B), BigInt(ASSET_B));
  assert.notEqual(recoveryShareIdForAsset(ASSET_A), recoveryShareIdForAsset(ASSET_B));
  assert.throws(() => recoveryShareIdForAsset(ZERO), /nonzero address/);
});

test("ERC-1155 replay aggregates repeated impairments into one asset balance", () => {
  const shareA = recoveryShareIdForAsset(ASSET_A);
  const shareB = recoveryShareIdForAsset(ASSET_B);
  const balances = replayIndexedRecoveryShareTransfers([
    transfer(ZERO, ALICE, [shareA, shareB], [100n, 40n]),
    transfer(ALICE, BOB, [shareA, shareB], [25n, 10n]),
    transfer(ZERO, ALICE, [shareA], [20n]),
    transfer(BOB, ZERO, [shareA], [5n]),
  ]);

  assert.deepEqual(balances, [
    { holder: ALICE, shareId: shareA, balance: 95n },
    { holder: BOB, shareId: shareA, balance: 20n },
    { holder: ALICE, shareId: shareB, balance: 30n },
    { holder: BOB, shareId: shareB, balance: 10n },
  ]);
});

test("zero-value ID-zero transfers are harmless while invalid value transfers fail", () => {
  const balances = new Map<string, bigint>();
  applyIndexedRecoveryShareTransfer(balances, transfer(ALICE, BOB, [0n], [0n]));
  assert.equal(balances.size, 0);

  const shareA = recoveryShareIdForAsset(ASSET_A);
  assert.deepEqual(
    replayIndexedRecoveryShareTransfers([
      transfer(ALICE, BOB, [0n], [0n]),
      transfer(ZERO, ALICE, [0n, shareA, 0n], [0n, 5n, 0n]),
    ]),
    [{ holder: ALICE, shareId: shareA, balance: 5n }]
  );
  assert.throws(
    () => replayIndexedRecoveryShareTransfers([transfer(ALICE, BOB, [0n], [1n])]),
    /Invalid ERC-1155/
  );
  assert.throws(
    () =>
      replayIndexedRecoveryShareTransfers([
        transfer(ALICE, BOB, [1n << 160n], [1n]),
      ]),
    /Invalid ERC-1155/
  );
});

test("malformed transfer replay is rejected", () => {
  const shareA = recoveryShareIdForAsset(ASSET_A);
  assert.throws(
    () =>
      replayIndexedRecoveryShareTransfers([
        transfer(ZERO, ALICE, [shareA, shareA], [1n]),
      ]),
    /Malformed/
  );
  assert.throws(
    () =>
      replayIndexedRecoveryShareTransfers([
        transfer(ALICE, BOB, [shareA], [1n]),
      ]),
    /underflow/
  );
});

test("pool payout follows current redeemable raw and external supply", () => {
  assert.equal(
    recoverySharePayout({ redeemableRaw: 10n, liveRawCustody: 10n, externalShares: 3n, shares: 1n }),
    3n
  );
  assert.equal(
    recoverySharePayout({ redeemableRaw: 7n, liveRawCustody: 5n, externalShares: 2n, shares: 1n }),
    2n
  );
  assert.equal(
    recoverySharePayout({ redeemableRaw: 7n, liveRawCustody: 5n, externalShares: 2n, shares: 2n }),
    5n
  );
  assert.equal(
    recoverySharePayout({ redeemableRaw: 7n, liveRawCustody: 10n, externalShares: 2n, shares: 1n }),
    3n
  );
  assert.equal(
    recoverySharePayout({ redeemableRaw: 0n, liveRawCustody: 10n, externalShares: 1n, shares: 1n }),
    0n
  );
  assert.throws(
    () => recoverySharePayout({ redeemableRaw: 1n, liveRawCustody: 1n, externalShares: 1n, shares: 2n }),
    /Invalid recovery-share payout inputs/
  );
});
