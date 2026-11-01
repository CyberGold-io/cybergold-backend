import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const sdk: any = { core: require('@uniswap/sdk-core'), v2: require('@uniswap/v2-sdk'),
  v3: require('@uniswap/v3-sdk'), v4: require('@uniswap/v4-sdk') };

const { Token } = sdk.core;
export const BLOCK = 101;
export const A = '0x1111111111111111111111111111111111111111';
export const B = '0x2222222222222222222222222222222222222222';
export const C = '0x3333333333333333333333333333333333333333';
export const WETH = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2';
export const USDC = '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48';
const ZERO = '0x' + '00'.repeat(20);
const L = 10n ** 24n;

function token(address: string, decimals = 18, chainId = 1) {
  return { address, decimals, chainId };
}

function coverage(ticks: any[], spacing: number) {
  const words = new Map();
  const first = Math.floor(Math.floor(-887272 / spacing) / 256);
  const last = Math.floor(Math.floor(887272 / spacing) / 256);
  for (let position = first; position <= last; position++) words.set(position, 0n);
  for (const tick of ticks) {
    const compressed = Math.floor(tick.index / spacing), position = compressed >> 8;
    words.set(position, words.get(position)! | (1n << BigInt(compressed & 255)));
  }
  return [...words].map(([wordPosition, bitmap]) => ({ wordPosition, bitmap: bitmap.toString() }));
}

export function v3(a: any, b: any, fee = 3000, tick = 0, liquidity = L, range = [-60000, 60000]) {
  const [token0, token1] = [a, b].sort((x, y) => x.address.toLowerCase().localeCompare(y.address.toLowerCase()));
  const spacing = ({ 100: 1, 500: 10, 3000: 60, 10000: 200 } as Record<number, number>)[fee]!;
  const rangeLiquidity = liquidity === 0n ? L : liquidity;
  const ticks = [
    { index: range[0], liquidityGross: rangeLiquidity.toString(), liquidityNet: rangeLiquidity.toString() },
    { index: range[1], liquidityGross: rangeLiquidity.toString(), liquidityNet: (-rangeLiquidity).toString() },
  ];
  const id = sdk.v3.Pool.getAddress(new Token(token0.chainId, token0.address, token0.decimals),
    new Token(token1.chainId, token1.address, token1.decimals), fee);
  return { id, address: id, protocol: 'v3', token0, token1, feePips: fee, tickSpacing: spacing,
    sqrtRatioX96: sdk.v3.TickMath.getSqrtRatioAtTick(tick).toString(), tick, liquidity: liquidity.toString(),
    ticks, bitmapWords: coverage(ticks, spacing),
    context: { chainId: token0.chainId, blockNumber: String(BLOCK), blockHash: '0x' + 'ab'.repeat(32) } };
}

function v2(a: any, b: any, r0 = L, r1 = 2n * L) {
  const [token0, token1] = [a, b].sort((x, y) => x.address.toLowerCase().localeCompare(y.address.toLowerCase()));
  const pair = new sdk.v2.Pair(sdk.core.CurrencyAmount.fromRawAmount(new Token(1, token0.address, token0.decimals), r0.toString()),
    sdk.core.CurrencyAmount.fromRawAmount(new Token(1, token1.address, token1.decimals), r1.toString()));
  return { id: pair.liquidityToken.address, address: pair.liquidityToken.address, protocol: 'v2', token0, token1,
    reserve0: r0.toString(), reserve1: r1.toString(), feePips: 3000 };
}

function v4(a: any, b: any) {
  const base = v3(a, b, 500);
  const p = new sdk.v4.Pool(new Token(1, base.token0.address, base.token0.decimals),
    new Token(1, base.token1.address, base.token1.decimals), 500, 10, ZERO,
    base.sqrtRatioX96, base.liquidity, 0, base.ticks);
  const { address: _address, ...state } = base;
  return { ...state, protocol: 'v4', id: p.poolId, lpFee: 500, protocolFee: 0, hooks: ZERO };
}

const a = token(A), b = token(B), c = token(C, 6), weth = token(WETH), usdc = token(USDC, 6);
export const gasSupportPools = [v3(weth, usdc, 500)];
const amount = '1000000000000000007';
const direct = [v3(a, c)];
const multi = [v3(a, c), v3(a, b, 500), v3(b, c, 3000, 6930)];
const sparse = [v3(a, c, 100, 0, 0n, [-136192, -131072])];
const mixed = [v2(a, b), v3(b, c)];
const mixedViaBase = [v2(a, weth), v3(weth, c)];
const split = [v3(a, c, 500, 0, 10n ** 20n), v3(a, c, 3000, 0, 10n ** 20n)];

export const cases = [
  { id: 'v3-direct-exact-in', mode: 'exactIn', tokenIn: a, tokenOut: c, amount, pools: direct },
  { id: 'v3-direct-exact-out', mode: 'exactOut', tokenIn: a, tokenOut: c, amount, pools: direct },
  { id: 'v3-reverse-exact-out', mode: 'exactOut', tokenIn: c, tokenOut: a, amount, pools: direct },
  { id: 'v3-two-hop-exact-in', mode: 'exactIn', tokenIn: a, tokenOut: c, amount, pools: multi },
  { id: 'v3-two-hop-exact-out', mode: 'exactOut', tokenIn: a, tokenOut: c, amount, pools: multi },
  { id: 'v2-exact-in', mode: 'exactIn', tokenIn: a, tokenOut: c, amount: '101', pools: [v2(a, c)] },
  { id: 'v2-exact-out-rounding', mode: 'exactOut', tokenIn: a, tokenOut: c, amount: '1000', pools: [v2(a, c, 100000n, 200000n)] },
  { id: 'v4-exact-in', mode: 'exactIn', tokenIn: a, tokenOut: c, amount, pools: [v4(a, c)] },
  { id: 'v4-exact-out', mode: 'exactOut', tokenIn: a, tokenOut: c, amount, pools: [v4(a, c)] },
  { id: 'mixed-exact-in', mode: 'exactIn', tokenIn: a, tokenOut: c, amount, pools: mixed,
    expectedNull: true, expectedNullReason: 'Upstream default mixed candidate categories omit this global-top-TVL-only V2 leg.' },
  { id: 'mixed-exact-out', mode: 'exactOut', tokenIn: a, tokenOut: c, amount, pools: mixed, expectedNull: true },
  { id: 'mixed-base-exact-in', mode: 'exactIn', tokenIn: a, tokenOut: c, amount, pools: mixedViaBase },
  { id: 'mixed-base-exact-out', mode: 'exactOut', tokenIn: a, tokenOut: c, amount, pools: mixedViaBase, expectedNull: true },
  { id: 'native-output-via-weth', mode: 'exactOut', tokenIn: a, tokenOut: weth, nativeOutput: true, amount,
    pools: [v3(a, weth)] },
  { id: 'sparse-512-words-exact-out', mode: 'exactOut', tokenIn: a, tokenOut: c, amount: '1000', pools: sparse },
  { id: 'split-exact-in', mode: 'exactIn', tokenIn: a, tokenOut: c, amount: '100000000000000000007', pools: split },
  { id: 'split-exact-out', mode: 'exactOut', tokenIn: a, tokenOut: c, amount: '50000000000000000007', pools: split },
  { id: 'no-route', mode: 'exactOut', tokenIn: a, tokenOut: c, amount, pools: [], expectedNull: true },
];
