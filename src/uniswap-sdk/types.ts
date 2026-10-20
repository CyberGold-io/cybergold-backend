export interface TokenSnapshot {
  address: string;
  decimals: number;
  chainId: number;
  symbol?: string;
}

export interface PoolSnapshot {
  id: string;
  protocol: "v2" | "v3" | "v4";
  token0: TokenSnapshot;
  token1: TokenSnapshot;
  reserve0?: string;
  reserve1?: string;
  sqrtRatioX96?: string;
  tick?: number;
  liquidity?: string;
  tickSpacing?: number;
  feePips?: number;
  lpFee?: number;
  protocolFee?: number;
  hooks?: string;
  ticks?: { index: number; liquidityGross: string; liquidityNet: string }[];
  bitmapWords?: { wordPosition: number; bitmap: string }[];
  context?: unknown;
}

export interface RouteHop { poolId: string; zeroForOne: boolean }
export interface RouteBranch { amountIn: string; hops: RouteHop[] }
export type PoolCoverage = Pick<PoolSnapshot, "id" | "ticks" | "bitmapWords">;
export type StateLoader = (request: MissingPoolState) => Promise<PoolCoverage[]>;
export interface SdkRequest {
  id: string | number;
  operation: "quote" | "simulateRoute" | "cancel" | "resume";
  mode?: "exactIn" | "exactOut";
  amount?: string;
  poolId?: string;
  zeroForOne?: boolean;
  sqrtPriceLimitX96?: string;
  pools?: PoolSnapshot[];
  route?: { branches: RouteBranch[] };
  continueState?: boolean;
  coverage?: PoolCoverage[];
  acknowledge?: boolean;
}

export interface SwapResult {
  amountIn: string;
  amountOut: string;
  fullyFilled: boolean;
  remainingAmount: string;
  postState: PoolSnapshot;
}

export class MissingPoolState extends Error {
  poolId: string;
  wordPositions: number[];
  ticks: number[];
  zeroForOne?: boolean;
  activeLiquidity?: string;
  constructor(poolId: string, words: number[] = [], ticks: number[] = [], zeroForOne?: boolean, activeLiquidity?: string) {
    super(`Missing canonical state for ${poolId}`);
    this.poolId = poolId;
    this.wordPositions = words;
    this.ticks = ticks;
    this.zeroForOne = zeroForOne;
    this.activeLiquidity = activeLiquidity;
  }
}
