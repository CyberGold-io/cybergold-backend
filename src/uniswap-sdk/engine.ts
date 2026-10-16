import { createRequire } from "node:module";
import { setImmediate } from "node:timers/promises";
import type { TickDataProvider } from "@uniswap/v3-sdk";
import { MissingPoolState } from "./types.ts";
import type { PoolSnapshot, SdkRequest, StateLoader, SwapResult } from "./types.ts";

// Select the supported CommonJS exports; no dependency owns an RPC provider.
const require = createRequire(import.meta.url);
const { Token, CurrencyAmount } = require("@uniswap/sdk-core") as typeof import("@uniswap/sdk-core");
const { Pair } = require("@uniswap/v2-sdk") as typeof import("@uniswap/v2-sdk");
const { Pool: V3Pool, TickList, TickMath, v3Swap } = require("@uniswap/v3-sdk") as typeof import("@uniswap/v3-sdk");
const { Pool: V4Pool } = require("@uniswap/v4-sdk") as typeof import("@uniswap/v4-sdk");
const { MixedRouteSDK } = require("@uniswap/router-sdk") as typeof import("@uniswap/router-sdk");
const JSBI = require("jsbi") as typeof import("jsbi").default;
const j = (value: string | number) => JSBI.BigInt(value);
const token = (value: PoolSnapshot["token0"]) => new Token(value.chainId, value.address, value.decimals, value.symbol);

class CoveredTicks implements TickDataProvider {
  pool: PoolSnapshot;
  words: Map<number, bigint>;
  data: Map<number, { liquidityGross: string; liquidityNet: string }>;
  signal?: AbortSignal;
  loader?: StateLoader;
  steps = 0;
  constructor(pool: PoolSnapshot, signal?: AbortSignal, loader?: StateLoader) {
    this.pool = pool;
    this.words = new Map((pool.bitmapWords ?? []).map(w => [w.wordPosition, BigInt(w.bitmap)]));
    this.data = new Map((pool.ticks ?? []).map(t => [t.index, t]));
    this.signal = signal;
    this.loader = loader;
  }
  async acquire(words: number[], ticks: number[]) {
    if (!this.loader) throw new MissingPoolState(this.pool.id, words, ticks);
    const observations = await this.loader(new MissingPoolState(this.pool.id, words, ticks));
    this.signal?.throwIfAborted();
    for (const observed of observations) {
      if (observed.id !== this.pool.id) continue;
      for (const word of observed.bitmapWords ?? []) this.words.set(word.wordPosition, BigInt(word.bitmap));
      for (const tick of observed.ticks ?? []) this.data.set(tick.index, tick);
    }
    // Preserve the in-flight price, tick and liquidity. Only immutable coverage
    // follows this pool into the next hop or branch of the same calculation.
    this.pool.bitmapWords = [...this.words].map(([wordPosition, bitmap]) => ({ wordPosition, bitmap: bitmap.toString() }));
    this.pool.ticks = [...this.data].map(([index, tick]) => ({ index, ...tick }));
  }
  async getTick(index: number) {
    this.signal?.throwIfAborted();
    let value = this.data.get(index);
    if (!value) { await this.acquire([], [index]); value = this.data.get(index); }
    if (!value) throw new MissingPoolState(this.pool.id, [], [index]);
    return { liquidityGross: j(value.liquidityGross), liquidityNet: j(value.liquidityNet) };
  }
  async nextInitializedTickWithinOneWord(tick: number, lte: boolean, spacing: number): Promise<[number, boolean]> {
    this.signal?.throwIfAborted();
    if (++this.steps % 64 === 0) await setImmediate(undefined, { signal: this.signal });
    const compressed = Math.floor(tick / spacing);
    const position = (lte ? compressed : compressed + 1) >> 8;
    let bitmap = this.words.get(position);
    if (bitmap === undefined) { await this.acquire([position], []); bitmap = this.words.get(position); }
    if (bitmap === undefined) throw new MissingPoolState(this.pool.id, [position]);
    // Bitmap proves absence as well as presence. Use SDK traversal, not an
    // incomplete TickListDataProvider that would assert global net liquidity.
    const indexes: number[] = [];
    for (let bit = 0; bit < 256; bit++) {
      if (bitmap & (1n << BigInt(bit))) indexes.push(((position << 8) + bit) * spacing);
    }
    if (indexes.length === 0) return [lte ? (position << 8) * spacing : (((position + 1) << 8) - 1) * spacing, false];
    const ticks = indexes.map(index => ({ index, liquidityGross: j("0"), liquidityNet: j("0") }));
    return TickList.nextInitializedTickWithinOneWord(ticks, tick, lte, spacing);
  }
}

// Route composition is supplied by the upstream SDK. Each branch is represented
// independently so overlapping pools can advance in actual execution order.
function sdkPool(pool: PoolSnapshot, signal?: AbortSignal, loader?: StateLoader) {
  const a = token(pool.token0), b = token(pool.token1);
  if (pool.protocol === "v2") return new Pair(CurrencyAmount.fromRawAmount(a, pool.reserve0!), CurrencyAmount.fromRawAmount(b, pool.reserve1!));
  const ticks = new CoveredTicks(pool, signal, loader);
  if (pool.protocol === "v3") return new V3Pool(a, b, pool.feePips!, pool.sqrtRatioX96!, pool.liquidity!, pool.tick!, ticks);
  return new V4Pool(a, b, pool.lpFee!, pool.tickSpacing!, pool.hooks ?? "0x0000000000000000000000000000000000000000", pool.sqrtRatioX96!, pool.liquidity!, pool.tick!, ticks);
}

export async function quotePool(pool: PoolSnapshot, mode: "exactIn" | "exactOut", amount: string,
  zeroForOne: boolean, sqrtPriceLimitX96?: string, signal?: AbortSignal, loader?: StateLoader): Promise<SwapResult> {
  signal?.throwIfAborted();
  pool = { ...pool };
  const t0 = token(pool.token0), t1 = token(pool.token1);
  if (pool.protocol === "v2") {
    const pair = new Pair(CurrencyAmount.fromRawAmount(t0, pool.reserve0!), CurrencyAmount.fromRawAmount(t1, pool.reserve1!));
    const currency = mode === "exactIn" ? (zeroForOne ? t0 : t1) : (zeroForOne ? t1 : t0);
    const [calculated, quotedNext] = mode === "exactIn"
      ? pair.getOutputAmount(CurrencyAmount.fromRawAmount(currency, amount))
      : pair.getInputAmount(CurrencyAmount.fromRawAmount(currency, amount));
    // Router 2.2 plans V2 exact-output funding backwards, then swaps forwards
    // from actual pair balances. Integer input rounding can produce extra output.
    const [executedOutput, next] = mode === "exactIn" ? [calculated, quotedNext]
      : pair.getOutputAmount(CurrencyAmount.fromRawAmount(zeroForOne ? t0 : t1, calculated.quotient));
    return { amountIn: mode === "exactIn" ? amount : calculated.quotient.toString(),
      amountOut: executedOutput.quotient.toString(),
      remainingAmount: "0", fullyFilled: true,
      postState: { ...pool, reserve0: next.reserve0.quotient.toString(), reserve1: next.reserve1.quotient.toString() } };
  }
  const provider = new CoveredTicks(pool, signal, loader);
  let fee = pool.feePips!;
  const spacing = pool.tickSpacing!;
  if (pool.protocol === "v4") {
    // Validate canonical PoolKey inputs with the V4 SDK, retaining original fee.
    new V4Pool(t0, t1, pool.lpFee!, spacing, pool.hooks ?? "0x0000000000000000000000000000000000000000",
      pool.sqrtRatioX96!, pool.liquidity!, pool.tick!, provider);
    const packed = pool.protocolFee ?? 0;
    const protocolFee = zeroForOne ? packed & 0xfff : (packed >> 12) & 0xfff;
    const lp = pool.lpFee!;
    fee = protocolFee + lp - Math.floor(protocolFee * lp / 1_000_000);
  }
  // Public SDK engine signs amounts oppositely to V4 core: positive is input.
  const specified = mode === "exactIn" ? j(amount) : JSBI.unaryMinus(j(amount));
  const result = await v3Swap(j(fee), j(pool.sqrtRatioX96!), pool.tick!, j(pool.liquidity!),
    spacing, provider, zeroForOne, specified, sqrtPriceLimitX96 ? j(sqrtPriceLimitX96) : undefined);
  const remaining = result.amountSpecifiedRemaining;
  if (remaining === undefined) throw new Error("SDK remaining-amount accessor is not installed");
  const remainingAbsolute = JSBI.lessThan(remaining, j(0)) ? JSBI.unaryMinus(remaining) : remaining;
  return { amountIn: mode === "exactIn" ? JSBI.subtract(j(amount), remaining).toString() : result.amountCalculated.toString(),
    amountOut: mode === "exactIn" ? JSBI.unaryMinus(result.amountCalculated).toString() : JSBI.subtract(j(amount), remainingAbsolute).toString(),
    fullyFilled: JSBI.equal(remaining, j(0)), remainingAmount: remainingAbsolute.toString(),
    postState: { ...pool, sqrtRatioX96: result.sqrtRatioX96.toString(), tick: result.tickCurrent, liquidity: result.liquidity.toString() } };
}

export async function runRequest(request: SdkRequest, signal?: AbortSignal, loader?: StateLoader) {
  const pools = new Map((request.pools ?? []).map(p => [p.id, structuredClone(p)]));
  const poolAt = (id: string) => {
    const pool = pools.get(id);
    if (!pool) throw new MissingPoolState(id);
    return pool;
  };
  const mode = request.mode ?? "exactIn";
  if (request.operation === "quote") return quotePool(poolAt(request.poolId ?? request.pools![0].id), mode,
    request.amount!, request.zeroForOne!, request.sqrtPriceLimitX96, signal, loader);
  if (request.operation !== "simulateRoute") throw new Error(`Unknown SDK operation ${request.operation}`);
  const branches = request.route!.branches;
  let totalInput = 0n, totalOutput = 0n;
  let fullyFilled = true;
  const residuals: { poolId: string; amount: string; originalInput: boolean }[] = [];
  for (const branch of branches) {
    const first = branch.hops[0], last = branch.hops.at(-1)!;
    const firstPool = poolAt(first.poolId), lastPool = poolAt(last.poolId);
    new MixedRouteSDK(branch.hops.map(h => sdkPool(poolAt(h.poolId), signal, loader)),
      token(first.zeroForOne ? firstPool.token0 : firstPool.token1),
      token(last.zeroForOne ? lastPool.token1 : lastPool.token0));
    if (mode === "exactOut" && branch.hops.every(hop => poolAt(hop.poolId).protocol === "v2")) {
      let funding = request.amount!;
      // Backward input planning observes each original pair without mutating it.
      for (const hop of [...branch.hops].reverse()) {
        const planned = await quotePool(poolAt(hop.poolId), "exactOut", funding, hop.zeroForOne, undefined, signal, loader);
        funding = planned.amountIn;
      }
      totalInput += BigInt(funding);
      // Then advance pairs in actual execution order, carrying rounding surplus.
      let proceeds = funding;
      for (const hop of branch.hops) {
        const executed = await quotePool(poolAt(hop.poolId), "exactIn", proceeds, hop.zeroForOne, undefined, signal, loader);
        pools.set(hop.poolId, executed.postState);
        proceeds = executed.amountOut;
      }
      totalOutput += BigInt(proceeds);
      continue;
    }
    let current = mode === "exactIn" ? branch.amountIn : request.amount!;
    const hops = mode === "exactIn" ? branch.hops : [...branch.hops].reverse();
    for (let i = 0; i < hops.length; i++) {
      const hop = hops[i];
      if (BigInt(current) === 0n) continue;
      const result = await quotePool(poolAt(hop.poolId), mode, current, hop.zeroForOne, undefined, signal, loader);
      pools.set(hop.poolId, result.postState);
      fullyFilled &&= result.fullyFilled;
      if (!result.fullyFilled) residuals.push({ poolId: hop.poolId, amount: result.remainingAmount, originalInput: mode === "exactIn" && i === 0 });
      if (mode === "exactIn" && i === 0) totalInput += BigInt(result.amountIn);
      if (mode === "exactOut" && i === 0) totalOutput += BigInt(result.amountOut);
      current = mode === "exactIn" ? result.amountOut : result.amountIn;
    }
    if (mode === "exactIn") totalOutput += BigInt(current);
    else totalInput += BigInt(current);
  }
  return { amountIn: totalInput.toString(), amountOut: totalOutput.toString(), fullyFilled,
    remainingAmount: mode === "exactIn" ? (BigInt(request.amount!) - totalInput).toString()
      : (totalOutput >= BigInt(request.amount!) ? 0n : BigInt(request.amount!) - totalOutput).toString(),
    settled: !residuals.some(r => !r.originalInput), residuals, postState: [...pools.values()] };
}

export const sqrtRatioAtTick = (tick: number) => TickMath.getSqrtRatioAtTick(tick).toString();
