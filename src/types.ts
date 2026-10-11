import type { Address } from "viem";
import type { basket, spendableToken } from "./config/tokens.ts";

export type TokenType = spendableToken | basket;

export type ProtocolBasketData =
  | readonly [
      assets: readonly `0x${string}`[],
      targetsPpm: readonly bigint[],
      goldRefGramsFp18: readonly bigint[],
      decimals: readonly number[],
      names: readonly string[],
      symbols: readonly string[],
      cygldPerUnitFp18: readonly bigint[]
    ]
  | undefined;

export type BasketToken = {
  id: string;
  symbol: string;
  name: string;
  type: "erc20";
  address: `0x${string}`;
  decimals: number;
};

export type BasketComponent = {
      token: BasketToken;
      targetWeight: bigint; // target weight as a bigint in parts per million (ppm), e.g. 500,000 for 50% weight
};

export type GoldBasket = {
  id: "goldbasket";
  symbol: "BASKET";
  name: "Gold basket";
  type: "basket";
  components: BasketComponent[];
};

export type ProtocolBasketShape = {
  data?: ProtocolBasketData;
};
export type BasketComponentsMapBigInt = Record<`0x${string}`, bigint>; // token address + amount as bigint

export type Prefill = {
  main: string;
  mainRaw: bigint;
  components: string[];
  componentRaws: bigint[];
}

export type FlowState = {
  direction: "issue" | "redeem";
  route: "basket" | "token";
  inputMode: "exact-in" | "exact-out";
}

export type SwapToQuote = {
  adapter: Address;
  outputAsset: Address;
  amountIn: bigint;
  minimumAmountOut: bigint;
  data: `0x${string}`;
};

export type SwapFromQuote = {
  adapter: Address;
  inputAsset: Address;
  minimumAmountOut: bigint;
  data: `0x${string}`;
};

/** App-local route quote. `inputAmount` is never encoded in Helpers calldata. */
export type RoutedSwapFromQuote = SwapFromQuote & {
  inputAmount: bigint;
};

export type SwapQuote = SwapToQuote | RoutedSwapFromQuote;

export const CORE_TOKEN_KIND = {
  ERC20: 0,
  ERC1155: 1,
} as const;

export type CoreTokenKind =
  (typeof CORE_TOKEN_KIND)[keyof typeof CORE_TOKEN_KIND];

export type CoreTokenAmount = {
  kind: CoreTokenKind;
  token: Address;
  id: bigint;
  amount: bigint;
};

export type CoreTokenMinimum = {
  kind: CoreTokenKind;
  token: Address;
  id: bigint;
  minimumAmount: bigint;
};

export type HelperFees = {
  protocolFeeCygld: bigint;
  helperFeeCygld: bigint;
};

export type BasketComponentsMapString = Record<`0x${string}`, string>;

export type QuoteMode = "exact-in" | "exact-out";

export type QuoteRoute = "direct" | "viaWeth";
export type QuoteDex = "uniswap_v3";
export type PoolDex = "uniswap_v2" | "uniswap_v3" | "uniswap_v4";
export type PoolIdentityFields = {
  protocol?: "v2" | "v3" | "v4";
  id?: string; poolId?: string; poolManager?: string; tickSpacing?: number; hooks?: string;
  poolKey?: { currency0: string; currency1: string; fee: number; tickSpacing: number; hooks: string };
};
export type PoolStateFields = PoolIdentityFields & {
  pool?: import("./contracts/dto").MarketPoolRef;
  reserve0Raw?: string; reserve1Raw?: string;
  /** V3 nominal fee tier; V4 current StateView LP fee pips. */
  lpFee?: number;
  /** V3 packed 4-bit protocol-share divisors; V4 packed 12-bit protocol fee pips. */
  protocolFee?: number;
  /** Raw token1/token0 marginal rate, without token decimals or swap fees. */
  marginalPrice?: { numerator: string; denominator: string };
  ticks?: { index: number; liquidityGross: string; liquidityNet: string }[];
  bitmapWords?: { wordPosition: number; bitmap: string }[];
};

export type QuoteTarget = {
  inputAsset: Address;
  outputAsset: Address;
  amount: bigint;
};

export type RouteQuoteCandidate = {
  path: `0x${string}`;
  quote: bigint;
  route: QuoteRoute;
  feeInfo: string;
};

export type CachedPoolCandidate = PoolStateFields & {
  dex: PoolDex;
  token0: Address;
  token1: Address;
  fee: number;
  poolAddress?: Address;
  exists: boolean;
  successCount?: number;
  activeLiquidityRaw?: string;
  sqrtPriceX96Raw?: string;
  tick?: number;
  token0BalanceRaw?: string;
  token1BalanceRaw?: string;
  liquidityCheckedAt?: string;
  lastCheckedAt?: string;
};

export type PoolCacheLookupPair = PoolIdentityFields & {
  tokenA: Address;
  tokenB: Address;
  fee?: number;
};

export type PoolCacheLookupParams = {
  chainId: number;
  dex: PoolDex | "uniswap";
  pairs: readonly PoolCacheLookupPair[];
};

export type PoolCacheObservation = PoolStateFields & {
  chainId: number;
  dex: PoolDex;
  tokenA: Address;
  tokenB: Address;
  fee: number;
  poolAddress?: Address;
  exists: boolean;
  quoteSucceeded?: boolean;
  activeLiquidityRaw?: string;
  sqrtPriceX96Raw?: string;
  tick?: number;
  token0BalanceRaw?: string;
  token1BalanceRaw?: string;
};

export type PoolCacheRecordParams = {
  entries: readonly PoolCacheObservation[];
};

export type QuotePoolCacheClient = {
  listPools: (params: PoolCacheLookupParams) => Promise<CachedPoolCandidate[]>;
  recordObservations: (params: PoolCacheRecordParams) => Promise<void>;
};

export type RouteSearchProgress = {
  completed: number;
  total: number;
  percent: number;
};

export type NetworkFeeEstimate = {
    wei: bigint;
    gas: bigint;
    maxFeePerGas: bigint;
    mode: "simulated" | "approx";
  };

export type TokenIssueQuoteStatus = "idle" | "loading" | "success" | "failed";
