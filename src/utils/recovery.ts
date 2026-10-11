import { isAddress, zeroAddress, type Address } from "viem";

export const RESERVE_LIFECYCLE_LABELS = ["Inactive", "Active", "Exiting"] as const;

export type ReserveLifecycleLabel =
  | (typeof RESERVE_LIFECYCLE_LABELS)[number]
  | "Unknown";

export type CurrentRecoveryPoolSnapshot = {
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
};

export type CurrentReserveLifecycleSnapshot = {
  asset: string;
  lifecycle: number;
  exitEntitlementRaw: string;
};

export type CurrentReserveCustodySnapshot = {
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

export type IndexedRecoveryShareTransfer = {
  operator: Address;
  from: Address;
  to: Address;
  ids: readonly bigint[];
  amounts: readonly bigint[];
};

export type IndexedRecoveryShareBalance = {
  holder: Address;
  shareId: bigint;
  balance: bigint;
};

const RECOVERY_SHARE_KEY_SEPARATOR = ":";

function normalizeAddress(value: Address) {
  return value.toLowerCase() as Address;
}

export function reserveLifecycleLabel(value: number): ReserveLifecycleLabel {
  return RESERVE_LIFECYCLE_LABELS[value] ?? "Unknown";
}

function canonicalUint(value: string, label: string) {
  if (!/^(0|[1-9][0-9]*)$/.test(value)) {
    throw new Error(`${label} must be a canonical unsigned integer`);
  }
  return BigInt(value);
}

/**
 * Reconcile the three current Core recovery lenses at one pinned block.
 * Indexed events discover candidate assets only; none of their historical
 * payload is authoritative for this snapshot.
 */
export function reconcileRecoveryPoolLifecycleSnapshot(
  pool: CurrentRecoveryPoolSnapshot,
  lifecycle: CurrentReserveLifecycleSnapshot,
  custody: CurrentReserveCustodySnapshot
) {
  if (lifecycle.asset.toLowerCase() !== pool.asset.toLowerCase()) {
    throw new Error("Recovery pool and reserve lifecycle views are inconsistent");
  }
  if (
    !Number.isInteger(lifecycle.lifecycle) ||
    lifecycle.lifecycle < 0 ||
    lifecycle.lifecycle >= RESERVE_LIFECYCLE_LABELS.length ||
    custody.lifecycle !== lifecycle.lifecycle ||
    custody.poolImpaired !== pool.impaired
  ) {
    throw new Error("Recovery pool, lifecycle, and custody views are inconsistent");
  }

  const poolCoreAttachedShares = canonicalUint(
    pool.coreAttachedShares,
    "Core-attached recovery shares"
  );
  const poolExternalShares = canonicalUint(
    pool.externalShares,
    "External recovery shares"
  );
  const poolRedeemableRaw = canonicalUint(
    pool.redeemableRaw,
    "Recovery-pool liability"
  );
  if (
    canonicalUint(pool.totalShares, "Total recovery shares") !==
    poolCoreAttachedShares + poolExternalShares
  ) {
    throw new Error("Recovery pool share totals are inconsistent");
  }
  const lifecycleExitEntitlement = canonicalUint(
    lifecycle.exitEntitlementRaw,
    "Reserve exit entitlement"
  );
  if (
    canonicalUint(custody.coreAttachedShares, "Custody Core-attached shares") !==
      poolCoreAttachedShares ||
    canonicalUint(custody.externalShares, "Custody external shares") !==
      poolExternalShares ||
    canonicalUint(custody.redeemablePoolRaw, "Custody pool liability") !==
      poolRedeemableRaw ||
    canonicalUint(custody.exitEntitlementRaw, "Custody exit entitlement") !==
      lifecycleExitEntitlement
  ) {
    throw new Error("Recovery pool, lifecycle, and custody views are inconsistent");
  }

  canonicalUint(pool.cygldPerAssetRawFp18, "Recovery conversion");
  canonicalUint(pool.cygldSupplyCap, "Recovery CYGLD supply cap");
  const liveRawCustody = canonicalUint(
    custody.liveRawCustody,
    "Live reserve custody"
  );
  if (!custody.liveBalanceAvailable && liveRawCustody !== 0n) {
    throw new Error("Recovery pool, lifecycle, and custody views are inconsistent");
  }
  canonicalUint(custody.activeAvailableRaw, "Active available custody");
  canonicalUint(custody.poolRawDeficit, "Recovery-pool deficit");
  canonicalUint(custody.exitEntitlementDeficitRaw, "Exit-entitlement deficit");

  return {
    ...pool,
    lifecycle: {
      asset: lifecycle.asset,
      lifecycle: lifecycle.lifecycle,
      exitEntitlementRaw: lifecycle.exitEntitlementRaw,
    },
    custody: { ...custody },
  };
}

export function recoveryShareIdForAsset(asset: Address) {
  if (!isAddress(asset) || asset.toLowerCase() === zeroAddress.toLowerCase()) {
    throw new Error("Recovery-share asset must be a nonzero address");
  }
  return BigInt(asset);
}

export function recoveryShareBalanceKey(holder: Address, shareId: bigint) {
  return `${normalizeAddress(holder)}${RECOVERY_SHARE_KEY_SEPARATOR}${shareId.toString()}`;
}

/** Apply one canonical ERC-1155 transfer to a balance map. */
export function applyIndexedRecoveryShareTransfer(
  balances: Map<string, bigint>,
  transfer: IndexedRecoveryShareTransfer
) {
  if (transfer.ids.length !== transfer.amounts.length) {
    throw new Error("Malformed ERC-1155 recovery-share transfer vector");
  }

  const from = normalizeAddress(transfer.from);
  const to = normalizeAddress(transfer.to);
  const normalizedZero = zeroAddress.toLowerCase();

  transfer.ids.forEach((shareId, index) => {
    const amount = transfer.amounts[index] ?? 0n;
    // ERC-1155 permits zero-value transfers for arbitrary IDs, including the
    // reserved share ID zero. They are canonical no-ops and must not be able
    // to poison a full balance replay.
    if (amount === 0n) return;
    if (shareId <= 0n || shareId >= 1n << 160n || amount < 0n) {
      throw new Error("Invalid ERC-1155 recovery-share transfer");
    }
    if (from === to) return;

    if (from !== normalizedZero) {
      const fromKey = recoveryShareBalanceKey(from, shareId);
      const nextFrom = (balances.get(fromKey) ?? 0n) - amount;
      if (nextFrom < 0n) {
        throw new Error("ERC-1155 recovery-share replay underflow");
      }
      if (nextFrom === 0n) balances.delete(fromKey);
      else balances.set(fromKey, nextFrom);
    }

    if (to !== normalizedZero) {
      const toKey = recoveryShareBalanceKey(to, shareId);
      balances.set(toKey, (balances.get(toKey) ?? 0n) + amount);
    }
  });
}

export function replayIndexedRecoveryShareTransfers(
  transfers: readonly IndexedRecoveryShareTransfer[]
): IndexedRecoveryShareBalance[] {
  const balances = new Map<string, bigint>();
  transfers.forEach((transfer) =>
    applyIndexedRecoveryShareTransfer(balances, transfer)
  );

  return [...balances.entries()]
    .map(([key, balance]) => {
      const separator = key.lastIndexOf(RECOVERY_SHARE_KEY_SEPARATOR);
      return {
        holder: key.slice(0, separator) as Address,
        shareId: BigInt(key.slice(separator + 1)),
        balance,
      };
    })
    .sort((left, right) => {
      if (left.shareId !== right.shareId) {
        return left.shareId < right.shareId ? -1 : 1;
      }
      return left.holder.localeCompare(right.holder);
    });
}

export function recoverySharePayout(params: {
  redeemableRaw: bigint;
  liveRawCustody: bigint;
  externalShares: bigint;
  shares: bigint;
  impaired?: boolean;
  coreAttachedShares?: bigint;
}) {
  const { redeemableRaw, liveRawCustody, externalShares, shares,
    impaired = false, coreAttachedShares = 0n } = params;
  if (
    redeemableRaw < 0n ||
    liveRawCustody < 0n ||
    externalShares <= 0n ||
    shares <= 0n ||
    shares > externalShares || coreAttachedShares < 0n
  ) {
    throw new Error("Invalid recovery-share payout inputs");
  }
  if (impaired) {
    const total = coreAttachedShares + externalShares;
    const cappedCustody = liveRawCustody < total ? liveRawCustody : total;
    return (cappedCustody * shares) / total;
  }
  const payableRaw =
    liveRawCustody < redeemableRaw ? liveRawCustody : redeemableRaw;
  return shares === externalShares
    ? payableRaw
    : (payableRaw * shares) / externalShares;
}
