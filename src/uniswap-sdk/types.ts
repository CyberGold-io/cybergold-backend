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
export interface SdkRequest {
  id: string | number;
  operation: "quote" | "simulateRoute" | "cancel";
  mode?: "exactIn" | "exactOut";
  amount?: string;
  poolId?: string;
  zeroForOne?: boolean;
  sqrtPriceLimitX96?: string;
  pools?: PoolSnapshot[];
  route?: { branches: RouteBranch[] };
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
  constructor(poolId: string, words: number[] = [], ticks: number[] = []) {
    super(`Missing canonical state for ${poolId}`);
    this.poolId = poolId;
    this.wordPositions = words;
    this.ticks = ticks;
  }
}
