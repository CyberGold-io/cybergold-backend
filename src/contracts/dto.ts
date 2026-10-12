import type { GoldMarketDataPayload, FxMarketDataPayload } from "../utils/marketDataValidation";
import type { RecoverySharePortfolio } from "../utils/recoveryPortfolio";
import type { RecoveryFundSnapshot } from "../server/onchain-indexer/recoveryFundSnapshot";
import type { PortfolioPool } from "../server/onchain-indexer/recoveryPortfolioModel";
import type { GovernanceOwnerAliasEntry } from "../server/governance-owner-aliases/repository";
import type { PoolCacheObservation, PoolCacheLookupParams, CachedPoolCandidate, PoolStateFields, PoolDex } from "../types";
import type { buildInternalReconcileResponse, InternalReconcileMode } from "../server/onchain-indexer/internalReconcileContract";
import type { OnchainIndexerReconciliationReceipt } from "../server/onchain-indexer/reconciliationReceipt";
import type { OnchainDashboardSnapshot, getSandboxForkGenerationStatus } from "../server/onchain-indexer/indexer";
import type { getSafeExecutionStatuses } from "../server/safe-events/indexer";
import type { FaucetErrorCode, FaucetSuccessPayload } from "../server/faucet/forkFaucet";
import type { ClientDiagnostic } from "../server/clientDiagnostics";
import type { getCoreActivity } from "../server/onchain-indexer/coreActivity";
import type { getSafeActivity } from "../server/safe-events/activity";
import type { RpcBlock, RpcTransaction, RpcTransactionReceipt } from "viem";

/** App deployment configuration; routing infrastructure stays server-owned. */
export type ProtocolConfiguredToken = {
  id: string; symbol: string; name: string; decimals: number; chainId: number;
} & ({ type: "erc20"; address: string } | { type: "native" });
export type ProtocolConfiguration = {
  chainId: number;
  contracts: { core: string | null; helpers: string | null; governance: string | null;
    staking: string | null; safe: string | null; uniswapAdapter: string | null };
  tokens: ProtocolConfiguredToken[];
  sandboxForkGeneration: string | null;
  adapter: { status: "success" | "unavailable";
    encoding: "uniswap-multi-protocol-v1" | "uniswap-v3" | null;
    observation: { blockNumber: string; blockHash: string; observedAt: string } | null };
};

/** Market swaps transfer existing CYGLD; never use Core basket economics. */
export type MarketQuoteRequest = {
  side: "buy" | "sell"; mode: "exact-in" | "exact-out";
  counterToken: string; amount: string; adapter?: string; recipient: string;
  deadline: string; slippageBps?: number; retainedPlan?: MarketRetainedPlan;
};
export type MarketModelRequest = Pick<MarketQuoteRequest, "side" | "mode" | "counterToken" | "adapter">;
export type MarketPoolRef = {
  id: string; protocol: "v2" | "v3" | "v4";
  token0: { address: string; decimals: number; chainId: number; decimalsKnown?: boolean };
  token1: { address: string; decimals: number; chainId: number; decimalsKnown?: boolean };
  address?: string; feePips: number; tickSpacing?: number; poolManager?: string; hooks?: string;
};
export type PoolIdentifier = { tokenA: string; tokenB: string; id?: string } & (
  | { protocol?: "v3"; fee: number }
  | { protocol: "v2"; fee?: number }
  | { protocol: "v4"; fee: number; tickSpacing: number; hooks: string; poolManager?: string; poolId?: string }
);
export type PoolSnapshot = PoolStateFields & {
  context: { chainId: number; blockNumber: string; blockHash: string; observedAt: string };
  dex: PoolDex; token0: string; token1: string; fee: number; exists: boolean;
  poolAddress?: string; activeLiquidityRaw?: string; sqrtPriceX96Raw?: string; tick?: number;
  /** Observed V3 ERC20 pool balances. V2 uses reserve fields; absent for V4. */
  token0BalanceRaw?: string; token1BalanceRaw?: string;
};
export type PoolCatalog = {
  context: PoolSnapshot["context"]; entries: MarketPoolRef[]; catalogMonth: string | null;
};
/** Observed pool events; raw amounts are not wallet receipts, reserves or TVL. */
export type PoolActivityEvent = {
  identity: string; pool: MarketPoolRef; blockNumber: string; blockHash: string;
  transactionHash: string; transactionIndex: number; logIndex: number; address: string;
  eventName: string; arguments: Record<string, string> | null; topics: string[]; data: string;
};
export type PoolActivityRollup = {
  eventCount: number; swapCount: number; liquidityAdditionCount: number; liquidityRemovalCount: number;
  stateUpdateCount: number; feeChangeCount: number; undecodedCount: number;
  amount0InRaw: string; amount1InRaw: string; amount0OutRaw: string; amount1OutRaw: string;
  /** Range liquidity units, never active liquidity or token deposit/withdrawal amounts. */
  liquidityAddedRaw: string; liquidityRemovedRaw: string;
};
export type PoolActivity = { enabled: false; events: []; pools: [] } | {
  enabled: true; chainId: number; source: "retained-uniswap-pool-events"; hasMore: boolean;
  events: PoolActivityEvent[];
  pools: { pool: MarketPoolRef; journalStartBlock: string; indexedThroughBlock: string;
    indexedThroughBlockHash: string; hasMore: boolean;
    rollups: { startBlock: string; blockNumber: string; blockHash: string; rollup: PoolActivityRollup }[] }[];
  retention: { eventsPerPool: number; rangesPerPool: number; publicEvents: number };
};
export type MarketRoutePlan = {
  version: 1; executionContext: "helpers-market" | "helpers-core";
  mode: "exactIn" | "exactOut"; tokenIn: string; tokenOut: string;
  branches: { amountIn: string; hops: { pool: MarketPoolRef; zeroForOne: boolean }[] }[];
  inputAmount: string; outputAmount: string; limit: string; deadline: string;
};
export type MarketSwapParams = {
  side: 0 | 1; counterToken: string; amount: string; bound: string; routedInput: string;
  feeCygld: string; recipient: string; deadline: string; adapter: string; data: string;
};
export type MarketRetainedPlan = {
  side: "buy" | "sell"; mode: "exact-in" | "exact-out"; amount: string;
  slippageBps: number; route: MarketRoutePlan; params: MarketSwapParams;
  fee: { asset: string; ratePpm: number; amount: string; basis: "quoted"; notional: string };
};
export type MarketQuote = {
  operation: "market"; side: "buy" | "sell"; mode: "exact-in" | "exact-out";
  tokenIn: string; tokenOut: string; amountIn: string; amountOut: string;
  totalInput: string; netOutput: string; grossOutput: string; routedAmountIn: string;
  inputMaximum: string; outputMinimum: string; refundDust: string;
  outputRefundEstimate?: string;
  fee: MarketRetainedPlan["fee"]; params: MarketSwapParams; adapterData: string;
  plan: MarketRetainedPlan; context: { chainId: number; blockNumber: string; blockHash: string; observedAt: string };
  feeBeneficiaryDisplay?: { address: string; observedAt: string };
  /** AMM price impact excluding LP/protocol/application fees; absent without a coherent baseline. */
  priceImpactPpm?: string;
  qualification: "sdk" | "quoter" | "sdk-and-quoter";
  executionSimulationRequired?: boolean; quoteVerificationUnavailable?: string;
  searchCoverage?: { scope: "selected-inventory"; maxHops: number; splitPercentages: number[];
    inventoryPools: number; catalogMonth: string | null };
  metrics: { candidateCalls: number; totalMs: number };
};
export type MarketQuoteModelPacket = {
  namespace: "market"; family: string; context?: MarketQuote["context"];
  intent: { side: "buy" | "sell"; mode: "exact-in" | "exact-out"; counterToken: string; adapter: string };
  cygld: string; feeRatePpm: number;
  routes: { route: MarketRoutePlan; amountIn: string; amountOut: string;
    points: { amountIn: string; amountOut: string }[];
    exchangeRate?: { numerator: string; denominator: string };
    feeRetention?: { numerator: string; denominator: string };
    localImpact?: { numerator: string; denominator: string } }[];
};
export type MarketQuoteEvent =
  | { type: "model"; value: MarketQuoteModelPacket }
  | { type: "estimate"; amount: string }
  | { type: "qualified" | "complete"; value: MarketQuote }
  | { type: "progress"; completedCandidates: number; totalCandidates?: number }
  | { type: "invalidated" }
  | { type: "error"; error: string; code?: string };

type ReceiptWaitContext = { chainId: number; observedAt: string };
export type GovernanceTargetCode = { context: ProtocolFacts["context"]; address: string; hasCode: boolean };
export type ReceiptWaitHead = ReceiptWaitContext & { blockNumber: string; blockHash: string; blockTimestamp: string };
export type ReceiptWaitTransaction = ReceiptWaitContext & { transaction: RpcTransaction | null };
export type ReceiptWaitReceipt = ReceiptWaitContext & { receipt: RpcTransactionReceipt | null };
export type ReceiptWaitBlock = ReceiptWaitContext & { block: RpcBlock<"latest", true> | null };

export type SignedAliasAuthorization = { nonce: string; issuedAt: string; signature: string };
export type OwnerAliasesRequest =
  | { action: "list"; editorAddress: string; ownerAddresses: string[] }
  | { action: "upsert"; editorAddress: string; ownerAddress: string; alias: string; auth: SignedAliasAuthorization }
  | { action: "delete"; editorAddress: string; ownerAddress: string; auth: SignedAliasAuthorization };
export type PoolCacheRequest =
  | ({ action: "list-pools" } & PoolCacheLookupParams)
  | { action: "record-observations"; entries: PoolCacheObservation[] };
export type SafeRequest = {
  action: "safe-info" | "pending-transactions" | "executed-transactions" |
    "propose-transaction" | "confirm-transaction" | "transaction-details";
  safeAddress?: string; safeTxHash?: string; payload?: Record<string, unknown>;
};
export type RpcCall = { jsonrpc?: "2.0"; id?: string | number | null; method: string; params?: unknown[] };
type CoreActivity = Awaited<ReturnType<typeof getCoreActivity>>;
type HelpersActivity = (Omit<Extract<CoreActivity, { enabled: true }>, "source"> & { source: "retained-helpers-journal" }) |
  Extract<CoreActivity, { enabled: false }>;
type ForkAnchor = { generation: string; forkBlock: string; forkBlockHash: string };
type ForkRequest = { kind: "cybergold-sandbox-fork-generation"; formatVersion: 1 } & (
  { action: "prepare"; current: ForkAnchor } | { action: "apply"; previous: ForkAnchor; current: ForkAnchor }
);

/** Live configured product facts; amounts stay lossless over JSON. */
export type FactRead<T> = { status: "success"; value: T } |
  { status: "failure"; error: "contract-read-failed" | "not-configured" };
export type ProtocolFacts = {
  basketModel?: QuoteModelPacket["protocol"];
  /** Current mint-capacity facts, available without quote-model history. */
  issuanceCapacity?: { totalSupply: FactRead<string>; maxTotalSupply: FactRead<string>;
    effectiveCygldSupplyCap: FactRead<string> };
  context: { chainId: number; blockNumber: string; blockHash: string; blockTimestamp: string; observedAt: string };
  core: string;
  helpers: string | null;
  basket: {
    assets: FactRead<string[]>;
    targetsPpm: FactRead<string[]>;
    goldRefGramsFp18: FactRead<string[]>;
    cygldPerUnitFp18: FactRead<string[]>;
    metadata: { address: string; decimals: FactRead<number>; name: FactRead<string>; symbol: FactRead<string> }[];
  };
  reference: FactRead<string>;
  fees: { issuancePpm: FactRead<string>; helpersPpm: FactRead<string> };
  pause: FactRead<boolean>;
};

type PreviewFees = { protocolFeeCygld: string; helperFeeCygld: string };
export type GovernanceCoreFacts = {
  context: ProtocolFacts["context"];
  core: string;
  configuration: { treasury: FactRead<string>; basketConfigHash: FactRead<string>;
    issuanceFeePpm: FactRead<string>; redemptionFeePpm: FactRead<string>;
    maxFeePpm: FactRead<string>; maxTotalSupply: FactRead<string>; totalSupply: FactRead<string>;
    safeWallet?: FactRead<string> };
};
export type TransactionRevert = { chainId: number; observedAt: string; transactionHash: string; data: string | null; reverted: boolean };
export type EnsName = { context: ProtocolFacts["context"]; holder: string; name: string | null };
export type EnsAvatarRecord = { context: ProtocolFacts["context"]; name: string; avatarRecord: string | null;
  nftTokenUri?: { status: "success"; value: string } | { status: "failure"; error: string } };
export type NativeBalance = { context: ProtocolFacts["context"]; holder: string; balance: string };
export type WalletTokenBalance = {
  context: ProtocolFacts["context"];
  holder: string;
  tokenId: "eth" | "cygld" | "xaut" | "paxg" | "usdt" | "usdc" | "weth";
  balance: FactRead<string>;
};
export type LiquidityPositions = {
  /** Each NFT's token quantities include deposited principal and unclaimed LP fees. */
  positions: { tokenId: string; paxgAmount: string; cygldAmount: string }[];
  /** Aggregate PAXG principal plus unclaimed PAXG LP fees, in decimal token units. */
  paxgAmount: string;
  /** Aggregate CYGLD principal plus unclaimed CYGLD LP fees, in decimal token units. */
  cygldAmount: string;
  blockNumber: string;
};
export type WalletBalances = {
  context: ProtocolFacts["context"];
  holder: string;
  native: FactRead<string>;
  tokens: { id: "cygld" | "xaut" | "paxg" | "usdt" | "usdc" | "weth"; address: string; balance: FactRead<string> }[];
};
export type GovernanceRoles = { context: ProtocolFacts["context"]; surface: "core" | "staking" | "governance-diamond";
  address: string | null; memberDisplayLimit: 50; roles: { id: string; count: FactRead<string>; members: FactRead<string>[] }[] };
export type GovernanceAuthority = { context: ProtocolFacts["context"]; surface: GovernanceRoles["surface"];
  address: string | null; account: string | null; safeWallet: FactRead<string>; paused: FactRead<boolean>;
  accountCanPause: FactRead<boolean>; accountCanUnpause: FactRead<boolean>; safeCanUnpause: FactRead<boolean> };
export type RecoveryRedemptionRequest = { holder: string; asset: string; shares: string; minRawOut: string };
export type RecoveryRedemption = RecoveryRedemptionRequest & { context: ProtocolFacts["context"]; core: string; rawOut: string };
export type Permit2ApprovalGasRequest = { owner: string; token: string };
export type Permit2ApprovalGas = Permit2ApprovalGasRequest & { context: ProtocolFacts["context"]; permit2: string; gas: string; blockTag: "latest" };
export type SafeNonce = { context: ProtocolFacts["context"]; address: string; nonce: string };
export type SafeTransactionHash = { context: ProtocolFacts["context"]; address: string; safeTxHash: string };
export type SafeTransactionHashRequest = { address: string; to: string; value: string; data: string; operation: number;
  safeTxGas: string; baseGas: string; gasPrice: string; gasToken: string; refundReceiver: string; nonce: string };
export type SafeExecutionRequest = Omit<SafeTransactionHashRequest, "nonce"> & { executor: string; executorNonce: string; signatures: string };
export type SafeExecution = { context: ProtocolFacts["context"]; address: string; executor: string; executorNonce: string;
  success: boolean; blockTag: "latest" };
export type HelpersExecutionRequest = { owner: string; operation: "issueFromBasketExactInWithPermit2" | "issueFromBasketExactOutWithPermit2"
  | "issueFromBasketExactInWithMixedPermits" | "issueFromBasketExactOutWithMixedPermits"
  | "issueFromTokenExactOutWithPermit2" | "issueFromTokenExactOutWithPermit" | "issueFromTokenExactOut" | "issueFromNativeExactOut"
  | "redeemToBasketExactIn" | "redeemToBasketExactInWithPermit"
  | "redeemToTokenExactIn" | "redeemToTokenExactInWithPermit"
  | "redeemToNativeExactIn" | "redeemToNativeExactInWithPermit" | "swapExactInput" | "swapExactOutput"; args: unknown[]; value?: string };
export type HelpersExecution = { context: ProtocolFacts["context"]; helpers: string; owner: string;
  operation: HelpersExecutionRequest["operation"]; gas: string; blockTag: "latest" };
export type TransactionFees = { context: ProtocolFacts["context"]; maxFeePerGas: string; maxPriorityFeePerGas: string };
export type TransactionNonce = { context: ProtocolFacts["context"]; owner: string; blockTag: "pending"; nonce: string };
export type TransactionReceiptObservation = { chainId: number; observedAt: string; transactionHash: string;
  receipt: { transactionHash: string; blockHash: string; blockNumber: string; status: "success" | "reverted";
    logs: { address: string; data: string; topics: string[] }[] } | null };
export type CoreRecoveryAssets = { context: ProtocolFacts["context"]; core: string; assets: string[] };
export type RecoverySharePrecision = { context: ProtocolFacts["context"]; core: string; asset: string; shareDecimals: number };
export type CorePermit = {
  context: ProtocolFacts["context"];
  owner: string;
  spender: string | null;
  nonce: string;
  domain: { name: string; version: "1"; chainId: number; verifyingContract: string };
};
export type TokenIdentity = { chainId: number; address: string };
export type TokenPermitDomain = { name?: string; version?: string; chainId?: number | string; verifyingContract?: string; salt?: string };
export type TokenAuthorization = {
  kind: "erc2612" | "variant" | "none" | "unknown" | "unavailable";
  confidence: "qualified" | "observed" | "unknown";
  domain?: TokenPermitDomain;
  variant?: "dai";
  source?: "seed" | "erc5267" | "reconstruction";
  reason?: string;
  observation?: { blockNumber: string; blockHash: string };
};
export type TokenMetadata = { context: ProtocolFacts["context"]; token: TokenIdentity;
  metadata: { name: FactRead<string>; symbol: FactRead<string>; decimals: FactRead<number> };
  holder?: string; balance?: FactRead<string>; authorization: TokenAuthorization };
export type TokenPermitContext = { context: ProtocolFacts["context"]; token: TokenIdentity; owner: string;
  spender: string | null; nonce: FactRead<string>; allowance: FactRead<string>; authorization: TokenAuthorization };
export type TokenApprovalGasRequest = { owner: string; token: string; amount: string };
export type TokenApprovalGas = TokenApprovalGasRequest & { context: ProtocolFacts["context"]; spender: string; gas: string; blockTag: "latest" };
export type Permit2ContextRequest = { mode: "verify" } | { mode: "nonce"; owner: string }
  | { mode: "allowances"; owner: string; tokens: string[] };
export type Permit2Context = { context: ProtocolFacts["context"]; helpers: string | null; permit2: string } & (
  { mode: "verify"; result: { code: string } } |
  { mode: "nonce"; result: { owner: string; nonce: string } } |
  { mode: "allowances"; result: { owner: string; allowances: { token: string; value: string }[] } }
);
export type HelpersRouterFacts = {
  adapter?: { address: string; codePresent: FactRead<boolean> };
  context: ProtocolFacts["context"];
  helpers: string | null;
  configuration: { helperFeePpm: FactRead<string>; permit2: FactRead<string>;
    wrappedNative: FactRead<string>; owner: FactRead<string>;
    approvedAdapters: FactRead<string[]>; paused: FactRead<boolean>; tokenPermitIssuance?: FactRead<boolean>;
    basketPermitIssuanceExactIn?: FactRead<boolean>; basketPermitIssuanceExactOut?: FactRead<boolean>;
    marketSwapExactInput?: FactRead<boolean>; marketSwapExactOutput?: FactRead<boolean> };
};
export type GovernanceSafePrincipal = {
  context: ProtocolFacts["context"];
  address: string;
  code: FactRead<string>;
  owners: FactRead<string[]>;
  threshold: FactRead<string>;
};
type PreviewOutput = { kind: number; token: string; id: string; amount: string };
export type BasketPreviewRequest =
  | { mode: "issue-exact-in"; maximumAmountsIn: string[] }
  | { mode: "issue-exact-out"; netCygldOut: string }
  | { mode: "redeem-exact-in"; grossCygldIn: string }
  | { mode: "redeem-exact-out"; minimumOutputs: { kind: number; token: string; id: string; minimumAmount: string }[] };
export type BasketPreview = {
  basketModel?: QuoteModelPacket["protocol"];
  context: { chainId: number; blockNumber: string; blockHash: string; observedAt: string };
  helpers: string;
} & (
  | { mode: "issue-exact-in"; result: { netCygldOut: string; fees: PreviewFees; amountsInExact: string[]; orderedCoreAssets: string[] } }
  | { mode: "issue-exact-out"; result: { fees: PreviewFees; amountsInExact: string[]; orderedCoreAssets: string[] } }
  | { mode: "redeem-exact-in"; result: { projectedCoreOutputs: PreviewOutput[]; fees: PreviewFees } }
  | { mode: "redeem-exact-out"; result: { grossCygldIn: string; projectedCoreOutputs: PreviewOutput[]; fees: PreviewFees } }
);

type IssuePreviewLeg = { adapter: string; amountIn: string; minimumAmountOut: string; data: string; routePlan?: MarketRoutePlan };
type RedemptionPreviewLeg = { adapter: string; minimumAmountOut: string; data: string; routePlan?: MarketRoutePlan };
export type TokenPreviewRequest =
  | { mode: "issue-token-exact-in"; inputToken: string; inputAmount: string; quotes: IssuePreviewLeg[] }
  | { mode: "issue-native-exact-in"; inputAmount: string; quotes: IssuePreviewLeg[] }
  | { mode: "issue-token-exact-out"; inputToken: string; maximumInputAmount: string; netCygldOut: string; quotes: IssuePreviewLeg[] }
  | { mode: "issue-native-exact-out"; maximumNativeIn: string; netCygldOut: string; quotes: IssuePreviewLeg[] }
  | { mode: "redeem-token-exact-in"; outputToken: string; grossCygldIn: string; quotes: RedemptionPreviewLeg[] }
  | { mode: "redeem-native-exact-in"; grossCygldIn: string; quotes: RedemptionPreviewLeg[] };
export type TokenPreview = { context: BasketPreview["context"]; helpers: string } & (
  | { mode: "issue-token-exact-in" | "issue-native-exact-in"; result: { netCygldOut: string; fees: PreviewFees; orderedCoreAssets: string[] } }
  | { mode: "issue-token-exact-out" | "issue-native-exact-out"; result: { fees: PreviewFees; orderedCoreAssets: string[] } }
  | { mode: "redeem-token-exact-in" | "redeem-native-exact-in"; result: { minimumAmountOut: string; projectedCoreOutputs: PreviewOutput[]; fees: PreviewFees } }
);
export type UniswapQuoteRequest = { mode: "exact-in" | "exact-out"; path: string; amount: string };
export type UniswapQuote = { context: BasketPreview["context"]; quoter: string;
  mode: UniswapQuoteRequest["mode"]; result: { amount: string } };
export type RouteSearchTarget = { inputAsset: string; outputAsset: string; amount: string };
export type RouteSearchRequest = { mode: UniswapQuoteRequest["mode"]; targets: RouteSearchTarget[]; adapter?: string };
export type RouteSearch = { mode: RouteSearchRequest["mode"]; quoter: string; context: BasketPreview["context"];
  results: { target: RouteSearchTarget; best: { path: string; quote: string; route: "direct" | "viaWeth" | "mixed";
    feeInfo: string; routePlan?: MarketRoutePlan } | null; attempted: number; succeeded: number; failures: { path: string; rpcCode: number; code?: QuoteErrorCode; diagnostics?: RpcErrorDiagnostics }[] }[];
  metrics: { candidateCalls: number; rpcReads: number; rpcReadsRequested: number;
    rpcReadsCoalesced: number; rpcReadsReused: number; contextMs: number; quotesMs: number;
    canonicalityMs: number; totalMs: number } };

export type RouteSearchEvent =
  | { type: "progress"; results: (RouteSearch["results"][number] & { total: number })[] }
  | { type: "complete"; value: RouteSearch }
  | { type: "error"; error: string; correlationId: string; code?: QuoteErrorCode; diagnostics?: RpcErrorDiagnostics };

/** Optional observed RPC failure context; provider text is sanitized before publication. */
export type RpcErrorDiagnostics = {
  rpcMethod?: string;
  stage?: string;
  elapsedMs?: number;
  upstreamErrorCode?: number;
  providerMessage?: string;
  httpStatus?: number;
  failureType?: "rpc-error" | "http-error" | "provider-timeout" | "backend-deadline" | "transport-error";
};

export type QuoteErrorCode = "insufficient-protocol-supply" | "issuance-cap-exceeded"
  | "rpc-rate-limit" | "rpc-timeout" | "rpc-unavailable" | "rpc-access-denied" | "quote-timeout"
  | "quote-no-route" | "quote-contract-reverted" | "quote-unavailable";

export type QuoteIntentRequest = {
  mode: "issue-exact-in" | "issue-exact-out" | "redeem-exact-in" | "redeem-exact-out";
  token: string; quoteToken: string; native: boolean; amount: string; adapter?: string;
  deadline: string; orderedAssets: string[]; targets: RouteSearchTarget[];
  /** Execution tolerance in basis points; omitted defaults to 100 (1%).
   * @TJS-type integer
   * @minimum 0
   * @maximum 10000
   * @default 100
   */
  slippageBps?: number;
  retainedPlan?: {
    slippageBps?: number;
    expectedInputAmount?: string;
    executionAmount: string; maximumInputAmount: string; minimumAmountOut: string;
    quotes: (IssuePreviewLeg & { outputAsset: string } | RedemptionPreviewLeg & { inputAsset: string; inputAmount: string })[];
    expectedCoreOutputs: { kind: number; token: string; id: string; minimumAmount: string }[];
  };
};
export type QuoteIntent = {
  mode: QuoteIntentRequest["mode"]; context: BasketPreview["context"];
  quotes: (IssuePreviewLeg & { outputAsset: string } | RedemptionPreviewLeg & { inputAsset: string; inputAmount: string })[];
  preview: TokenPreview["result"]; initialPreview: TokenPreview["result"] | BasketPreview["result"] | null;
  basketPreview: BasketPreview["result"]; displayAmount: string; executionAmount: string; maximumInputAmount: string;
  slippageBps?: number;
  /** Expected input before execution cushions, including direct basket input. */
  expectedInputAmount?: string;
  requestedGrossCygldOut?: string; requestedNetCygldOut?: string;
  remainingGrossCapacity?: string; remainingNetCapacity?: string;
  expectedOutputAmount?: string;
  expectedCoreOutputs?: { kind: number; token: string; id: string; minimumAmount: string }[];
  metrics: { rpcReads: number; rpcReadsRequested: number; rpcReadsCoalesced: number; rpcReadsReused: number;
    candidateCalls: number; iterations: number; totalMs: number };
};
/** Display-only source data. No transaction tuples or execution readiness. */
export type QuoteModelPacket = {
  revision: number;
  intent: Omit<QuoteIntentRequest, "deadline" | "retainedPlan">;
  routes: {
    tokens: string[]; fees: number[]; context: BasketPreview["context"];
    routePlan?: MarketRoutePlan; protocols?: ("v2" | "v3" | "v4")[]; poolIds?: string[];
    points: { input: string; output: string; context?: BasketPreview["context"]; recordedAt?: number }[];
    exchangeRate?: { numerator: string; denominator: string };
    exchangeContext?: BasketPreview["context"];
    feeRetention: { numerator: string; denominator: string };
    localImpact?: { numerator: string; denominator: string };
  }[];
  whole: { input: string; display: string; context: BasketPreview["context"]; recordedAt: number }[];
  protocol: null | {
    context: BasketPreview["context"];
    state: {
      assets: string[]; weights: string[]; conversions: string[];
      issueFee: string; helperFee: string; redeemFee: string;
      supply: string; maxSupply: string; effectiveCap: string; available: string[];
      recoveryShares: string[]; recoveryValues: string[];
      descriptors: { kind: number; token: string; id: string }[];
    };
  };
};
export type QuoteIntentEvent =
  | { type: "model"; value: QuoteModelPacket }
  | { type: "progress"; stage: string; completed: number; total: number }
  | { type: "estimate"; amount: string; context: BasketPreview["context"] }
  | { type: "qualified"; value: QuoteIntent }
  | { type: "invalidated"; context: BasketPreview["context"]; reason?: "snapshot-changed" }
  | { type: "complete"; value: QuoteIntent }
  | { type: "error"; error: string; correlationId: string; code?: QuoteErrorCode; diagnostics?: RpcErrorDiagnostics };

/** One user trade; Backend chooses a complete Core or market execution. */
export type TradeModelRequest = {
  side: "buy" | "sell"; mode: "exact-in" | "exact-out"; counterToken: string;
  native: boolean; amount: string; slippageBps?: number;
};
export type TradeRetainedPlan =
  | { strategy: "core"; request: QuoteIntentRequest; quote: QuoteIntent }
  | { strategy: "market"; request: MarketQuoteRequest; quote: MarketQuote };
export type TradeQuoteRequest = TradeModelRequest & {
  recipient: string; deadline: string; retainedPlan?: TradeRetainedPlan;
};
export type TradeEvaluation = Record<"core" | "market", "running" | "complete" | "unavailable" | "unsupported">;
type TradeEconomics = {
  side: TradeModelRequest["side"]; mode: TradeModelRequest["mode"];
  tokenIn: string; tokenOut: string; quotedInput: string; quotedOutput: string;
  inputMaximum: string; outputMinimum: string; context: QuoteIntent["context"];
  evaluation: TradeEvaluation; metrics: { totalMs: number; targetReads: number };
};
export type TradeQuote = TradeEconomics & (
  | { strategy: "core"; providerRequest: QuoteIntentRequest; providerQuote: QuoteIntent }
  | { strategy: "market"; providerRequest: MarketQuoteRequest; providerQuote: MarketQuote }
);
export type TradeQuoteModelPacket = {
  namespace: "trade"; intent: TradeModelRequest;
  models: ({ strategy: "core"; value: QuoteModelPacket } | { strategy: "market"; value: MarketQuoteModelPacket })[];
  estimate?: { strategy: "core" | "market"; amount: string };
};
export type TradeQuoteEvent =
  | { type: "model"; value: TradeQuoteModelPacket }
  | { type: "estimate"; strategy: "core" | "market"; amount: string }
  | { type: "qualified" | "complete"; value: TradeQuote }
  | { type: "progress"; strategy: "core" | "market"; value: { stage?: string; completed?: number; total?: number; completedCandidates?: number; totalCandidates?: number } }
  | { type: "provider-error"; strategy: "core" | "market"; error: string; code?: QuoteErrorCode }
  | { type: "invalidated"; strategy: "core" | "market" }
  | { type: "error"; error: string; code?: QuoteErrorCode };

/** Documentation/client schemas only: runtime handlers retain their own parsers. */
export interface ContractSchemas {
  TradeModelRequest: TradeModelRequest;
  TradeQuoteRequest: TradeQuoteRequest;
  TradeQuote: TradeQuote;
  TradeQuoteEvent: TradeQuoteEvent;
  TradeQuoteModelPacket: TradeQuoteModelPacket;
  ProtocolConfiguration: ProtocolConfiguration;
  MarketQuoteRequest: MarketQuoteRequest;
  MarketQuote: MarketQuote;
  MarketQuoteEvent: MarketQuoteEvent;
  MarketQuoteModelPacket: MarketQuoteModelPacket;
  MarketModelRequest: MarketModelRequest;
  MarketRoutePlan: MarketRoutePlan;
  GovernanceTargetCode: GovernanceTargetCode;
  PoolIdentifier: PoolIdentifier;
  PoolSnapshot: PoolSnapshot;
  PoolCatalog: PoolCatalog;
  PoolActivity: PoolActivity;
  ProtocolFacts: ProtocolFacts;
  GovernanceCoreFacts: GovernanceCoreFacts;
  HelpersRouterFacts: HelpersRouterFacts;
  GovernanceSafePrincipal: GovernanceSafePrincipal;
  TransactionRevert: TransactionRevert;
  EnsName: EnsName;
  EnsAvatarRecord: EnsAvatarRecord;
  NativeBalance: NativeBalance;
  LiquidityPositions: LiquidityPositions;
  WalletBalances: WalletBalances;
  WalletTokenBalance: WalletTokenBalance;
  GovernanceRoles: GovernanceRoles;
  GovernanceAuthority: GovernanceAuthority;
  RecoveryRedemptionRequest: RecoveryRedemptionRequest;
  RecoveryRedemption: RecoveryRedemption;
  Permit2ApprovalGasRequest: Permit2ApprovalGasRequest;
  Permit2ApprovalGas: Permit2ApprovalGas;
  SafeNonce: SafeNonce;
  SafeTransactionHash: SafeTransactionHash;
  SafeTransactionHashRequest: SafeTransactionHashRequest;
  SafeExecutionRequest: SafeExecutionRequest;
  SafeExecution: SafeExecution;
  HelpersExecutionRequest: HelpersExecutionRequest;
  HelpersExecution: HelpersExecution;
  TransactionFees: TransactionFees;
  TransactionNonce: TransactionNonce;
  TransactionReceiptObservation: TransactionReceiptObservation;
  ReceiptWaitHead: ReceiptWaitHead;
  ReceiptWaitTransaction: ReceiptWaitTransaction;
  ReceiptWaitReceipt: ReceiptWaitReceipt;
  ReceiptWaitBlock: ReceiptWaitBlock;
  CoreRecoveryAssets: CoreRecoveryAssets;
  RecoverySharePrecision: RecoverySharePrecision;
  CorePermit: CorePermit;
  TokenMetadata: TokenMetadata;
  TokenPermitContext: TokenPermitContext;
  TokenApprovalGasRequest: TokenApprovalGasRequest;
  TokenApprovalGas: TokenApprovalGas;
  Permit2ContextRequest: Permit2ContextRequest;
  Permit2Context: Permit2Context;
  BasketPreviewRequest: BasketPreviewRequest;
  BasketPreview: BasketPreview;
  TokenPreviewRequest: TokenPreviewRequest;
  TokenPreview: TokenPreview;
  UniswapQuoteRequest: UniswapQuoteRequest;
  UniswapQuote: UniswapQuote;
  RouteSearchRequest: RouteSearchRequest;
  RouteSearch: RouteSearch;
  RouteSearchEvent: RouteSearchEvent;
  QuoteIntentRequest: QuoteIntentRequest;
  QuoteIntent: QuoteIntent;
  QuoteModelPacket: QuoteModelPacket;
  QuoteIntentEvent: QuoteIntentEvent;
  RpcErrorDiagnostics: RpcErrorDiagnostics;
  ClientDiagnostic: ClientDiagnostic;
  CoreActivity: CoreActivity;
  HelpersActivity: HelpersActivity;
  SafeActivity: Awaited<ReturnType<typeof getSafeActivity>>;
  Gold: GoldMarketDataPayload;
  Fx: FxMarketDataPayload;
  Recovery: RecoverySharePortfolio;
  RecoveryFundSnapshot: RecoveryFundSnapshot;
  PortfolioPool: PortfolioPool;
  Dashboard: (OnchainDashboardSnapshot | { enabled: false; protocolLogicUpdate: null; protocolParameterUpdate: null; lastScannedBlock: null }) & {
    sandboxForkGeneration?: string | null;
  };
  PublicError: { error: string; correlationId?: string; code?: QuoteErrorCode; diagnostics?: RpcErrorDiagnostics };
  AliasesRequest: OwnerAliasesRequest;
  AliasesResult: { entries: GovernanceOwnerAliasEntry[] } | { entry: GovernanceOwnerAliasEntry } | { ok: true; deleted: boolean };
  PoolRequest: PoolCacheRequest;
  PoolResult: { entries: CachedPoolCandidate[] } | { ok: true };
  SafeRequest: SafeRequest;
  SafeEventsRequest: { safeAddress: string; safeTxHashes: string[] };
  SafeEventsResult: { results: Awaited<ReturnType<typeof getSafeExecutionStatuses>> };
  FaucetRequest: { address: string; requestId?: string };
  FaucetResult: FaucetSuccessPayload;
  FaucetFailure: { error: string; code: FaucetErrorCode; correlationId: string };
  RpcRequest: RpcCall | RpcCall[];
  ReconcileRequest: { kind: "cybergold-b2b-reconcile-request"; formatVersion: 1; mode: InternalReconcileMode };
  ReconcileResult: ReturnType<typeof buildInternalReconcileResponse>["body"];
  Receipt: OnchainIndexerReconciliationReceipt;
  ForkRequest: ForkRequest;
  ForkStatus: { kind: "cybergold-sandbox-fork-generation-status"; formatVersion: 1; current: Awaited<ReturnType<typeof getSandboxForkGenerationStatus>> };
  ForkResult: { status: "prepared" | "busy" | "already-ready" | "already-applied" } | { status: "applied"; plan: { kind: string; invalidateFrom: string; retainedThrough: string | null } };
}
