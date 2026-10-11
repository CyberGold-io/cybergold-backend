import { createPublicClient, getAddress, http, zeroAddress, type Address } from "viem";
import { CORE_DIAMOND_ABI } from "../../contracts/generated/coreDiamond.ts";
import { GOVERNANCE_DIAMOND_ABI } from "../../contracts/generated/governanceDiamond.ts";
import { parseRpcUpstreamUrl } from "../rpcProxyPolicy.ts";
import { reconcileRecoveryPoolLifecycleSnapshot } from "../../utils/recovery.ts";
import { recoveryFundCurrentTerms, recoveryFundTreasuryAccounting } from "../../utils/recoveryFund.ts";
import { EMPTY_RECOVERY_PORTFOLIO, type RecoveryPool, type RecoveryShareBalance } from "../../utils/recoveryPortfolio.ts";
import { RecoverySharesApiError } from "../../utils/recoverySharesApi.ts";
import { createRecoveryPortfolioReader, RECOVERY_PAGE_SIZE,
  type RecoveryRpcReader, type RecoveryBlock, type RecoveryPageRequest } from "./portfolioReader.ts";

export function createRecoveryRpcReader(
  environment: Record<string, string | undefined> = process.env,
  fetchFn: typeof fetch = fetch
): RecoveryRpcReader {
  const url = parseRpcUpstreamUrl(environment.RPC_URL);
  const coreRaw = environment.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS;
  const chainRaw = environment.NEXT_PUBLIC_CHAIN_ID;
  if (!url || !coreRaw || !chainRaw || !/^[1-9][0-9]*$/.test(chainRaw)) {
    throw new RecoverySharesApiError("Recovery RPC, Core address or chain is not configured", 503);
  }
  const core = getAddress(coreRaw);
  if (core === zeroAddress) throw new RecoverySharesApiError("Recovery Core address is not configured", 503);
  const chainId = BigInt(chainRaw);
  const authorization = environment.RPC_AUTHORIZATION;
  const client = createPublicClient({ transport: http(url.toString(), { batch: { batchSize: 64 },
    fetchFn, retryCount: 0, timeout: 15_000, fetchOptions: { redirect: "error", cache: "no-store",
      headers: authorization ? { Authorization: authorization } : undefined } }) });
  const target = (block: RecoveryBlock) => ({ blockHash: block.hash, requireCanonical: true as const });
  return {
    core, chainId,
    async block(hash) {
      if (BigInt(await client.getChainId()) !== chainId) throw new Error("Recovery RPC chain mismatch");
      const block = await client.getBlock(hash ? { blockHash: hash } : { blockTag: "latest" });
      if (block.hash === null || block.number === null) throw new Error("Recovery block is unavailable");
      return { hash: block.hash, number: block.number };
    },
    async assertCanonical(block) {
      const canonical = await client.getBlock({ blockNumber: block.number });
      if (canonical.hash?.toLowerCase() !== block.hash.toLowerCase()) {
        throw new RecoverySharesApiError("Recovery snapshot changed; restart discovery", 503, 1);
      }
    },
    count: (block) => client.readContract({ address: core, abi: CORE_DIAMOND_ABI,
      functionName: "outstandingRecoveryAssetCount", ...target(block) }),
    assets: (block, offset) => client.readContract({ address: core, abi: CORE_DIAMOND_ABI,
      functionName: "outstandingRecoveryAssets", args: [offset, RECOVERY_PAGE_SIZE], ...target(block) }),
    paused: (block) => client.readContract({ address: core, abi: CORE_DIAMOND_ABI,
      functionName: "paused", ...target(block) }),
    async pools(block, assets) {
      return Promise.all(assets.map(async (asset): Promise<RecoveryPool> => {
        const [pool, lifecycle, custody] = await Promise.all([
          client.readContract({ address: core, abi: CORE_DIAMOND_ABI,
            functionName: "recoveryPool", args: [asset], ...target(block) }),
          client.readContract({ address: core, abi: CORE_DIAMOND_ABI,
            functionName: "reserveLifecycle", args: [asset], ...target(block) }),
          client.readContract({ address: core, abi: CORE_DIAMOND_ABI,
            functionName: "reserveCustodyStatus", args: [asset], ...target(block) }),
        ]);
        const reconciled = reconcileRecoveryPoolLifecycleSnapshot({
          asset, impaired: pool.impaired, coreAttachedShares: pool.coreAttachedShares.toString(),
          externalShares: pool.externalShares.toString(), totalShares: (pool.coreAttachedShares + pool.externalShares).toString(),
          redeemableRaw: pool.redeemableRaw.toString(), cygldPerAssetRawFp18: pool.cygldPerAssetRawFp18.toString(),
          cygldSupplyCap: pool.cygldSupplyCap.toString(), referenceShares: pool.referenceShares.toString(),
          referenceValueCygld: pool.referenceValueCygld.toString(), shareDecimals: pool.shareDecimals,
        }, { asset, lifecycle: Number(lifecycle.lifecycle), exitEntitlementRaw: lifecycle.exitEntitlementRaw.toString() }, {
          lifecycle: Number(custody.lifecycle), poolImpaired: custody.poolImpaired,
          redeemablePoolRaw: custody.redeemablePoolRaw.toString(), coreAttachedShares: custody.coreAttachedShares.toString(),
          externalShares: custody.externalShares.toString(), exitEntitlementRaw: custody.exitEntitlementRaw.toString(),
          liveBalanceAvailable: custody.liveBalanceAvailable, liveRawCustody: custody.liveRawCustody.toString(),
          activeAvailableRaw: custody.activeAvailableRaw.toString(), poolRawDeficit: custody.poolRawDeficit.toString(),
          exitEntitlementDeficitRaw: custody.exitEntitlementDeficitRaw.toString(),
        });
        return { ...reconciled, asset, referenceShares: pool.referenceShares.toString(),
          referenceValueCygld: pool.referenceValueCygld.toString(), shareDecimals: pool.shareDecimals };
      }));
    },
    balances: (block, holder, assets) => assets.length === 0 ? Promise.resolve([]) :
      client.readContract({ address: core, abi: CORE_DIAMOND_ABI, functionName: "balanceOfBatch",
        args: [assets.map(() => holder), assets.map((asset) => BigInt(asset))], ...target(block) }),
    preview: (block, asset, shares) => client.readContract({ address: core, abi: CORE_DIAMOND_ABI,
      functionName: "previewRedeemRecoveryShares", args: [asset, shares], ...target(block) }),
    async fund(block, _holder, entries) {
      const rawGovernance = environment.NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS;
      if (!rawGovernance || rawGovernance.toLowerCase() === zeroAddress) {
        return { status: { configured: false, available: false, reason: "not-configured",
          problem: null, governance: null, governancePaused: null }, offers: [] };
      }
      const governance = getAddress(rawGovernance);
      const [trustedCore, governancePaused, treasury] = await Promise.all([
        client.readContract({ address: governance, abi: GOVERNANCE_DIAMOND_ABI,
          functionName: "trustedRecoveryFundCore", ...target(block) }),
        client.readContract({ address: governance, abi: GOVERNANCE_DIAMOND_ABI,
          functionName: "paused", ...target(block) }),
        client.readContract({ address: governance, abi: GOVERNANCE_DIAMOND_ABI,
          functionName: "recoveryFundTreasuryStatus", ...target(block) }),
      ]);
      if (trustedCore.toLowerCase() !== core.toLowerCase()) throw new Error("Fund Core mismatch");
      const { deficit } = recoveryFundTreasuryAccounting({ balance: treasury[0], allowanceExposure: treasury[1], committed: treasury[2] });
      const offers = await Promise.all(entries.map(async (entry): Promise<RecoveryShareBalance["fundOffer"]> => {
        try {
          const terms = await client.readContract({ address: governance, abi: GOVERNANCE_DIAMOND_ABI,
            functionName: "assetRecoveryFund", args: [entry.pool.asset], ...target(block) });
          // Admission has already been proven by Governance. Never reprice frozen terms using current anchors.
          const current = recoveryFundCurrentTerms(terms);
          if (!current.active) return null;
          if (deficit > 0n) return { available: false, generation: terms.generation.toString(), problem: "Fund treasury is below its commitments" };
          const holderShares = BigInt(entry.balanceRaw);
          const accepted = holderShares < current.remainingCoverageShares ? holderShares : current.remainingCoverageShares;
          const [generation, amount] = await client.readContract({ address: governance, abi: GOVERNANCE_DIAMOND_ABI,
            functionName: "previewAssetRecoveryFundPurchase", args: [entry.pool.asset, accepted], ...target(block) });
          if (generation !== terms.generation) throw new Error("Fund preview generation mismatch");
          return { available: true, impairedAsset: entry.pool.asset, generation: generation.toString(),
            governancePaused, holderShares: entry.balanceRaw, acceptedShares: accepted.toString(),
            remainingCapacity: current.remainingCoverageShares.toString(), cygldToken: core, cygldAmount: amount.toString() };
        } catch {
          return { available: false, generation: "0", problem: "Fund offer unavailable" };
        }
      }));
      return { status: { configured: true, available: true, reason: null, problem: null, governance, governancePaused }, offers };
    },
  };
}

let loadPage: ReturnType<typeof createRecoveryPortfolioReader> | undefined;

/** Only this server module sees RPC_URL / RPC_AUTHORIZATION. No database is consulted. */
export async function getRecoverySharePortfolio(holder: Address, request: RecoveryPageRequest = {}) {
  if (process.env.RECOVERY_PORTFOLIO_MODE === "not-configured" && process.env.NODE_ENV !== "production") {
    return EMPTY_RECOVERY_PORTFOLIO;
  }
  if (process.env.RECOVERY_PORTFOLIO_MODE && process.env.RECOVERY_PORTFOLIO_MODE !== "rpc") {
    throw new RecoverySharesApiError("Recovery portfolio profile is invalid", 503);
  }
  loadPage ??= createRecoveryPortfolioReader(createRecoveryRpcReader());
  return loadPage(holder, request);
}
