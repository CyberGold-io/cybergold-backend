/** Published UniRoute quote/split nomination over canonical quote callbacks. */
import { createRequire } from 'node:module';
import { discoverLocal } from './uniroute-local.ts';
import type { LocalRequest } from './uniroute-local.ts';

const require = createRequire(import.meta.url);
const { DeepQuoteStrategy } = require('../../vendor/uniroute-public/runtime/core/strategy/DeepQuoteStrategy.js');
const { RouteQuoteAllocator } = require('../../vendor/uniroute-public/runtime/core/route/RouteQuoteAllocator.js');
const { SimpleQuoteSelector } = require('../../vendor/uniroute-public/runtime/core/quote/selector/SimpleQuoteSelector.js');
const { RouteBasic } = require('../../vendor/uniroute-public/runtime/models/route/RouteBasic.js');
const { QuoteBasic } = require('../../vendor/uniroute-public/runtime/models/quote/QuoteBasic.js');
const { TradeType } = require('../../vendor/uniroute-public/runtime/models/quote/TradeType.js');
const { configureWrappedCurrency } = require('../../vendor/uniroute-public/runtime/lib/tokenUtils.js');

const ZERO = '0x0000000000000000000000000000000000000000';
const WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2';
type Hop = { pool?: any; zeroForOne?: boolean; kind?: string; currencyOut?: string };
export type LocalCandidate = { amountIn: string; hops: Hop[] }[];
export type LocalQuote = (request: { mode: 'exactIn'; amount: string; branches: LocalCandidate }) => Promise<{ quote: string | null }>;
export type DeepOptions = { finderOnly?: boolean; percentageStep?: 5 | 25 };

/** Same physical execution keys as Python pool_identity, independent of aliases. */
export function localPoolKey(pool: any): string {
  const tokens = [pool.token0.address.toLowerCase(), pool.token1.address.toLowerCase()].sort();
  return JSON.stringify(pool.protocol === 'v2' ? [pool.protocol, ...tokens]
    : pool.protocol === 'v3' ? [pool.protocol, ...tokens, Number(pool.feePips)]
      : [pool.protocol, ...tokens, Number(pool.feePips), Number(pool.tickSpacing), (pool.hooks ?? ZERO).toLowerCase()]);
}

class Address {
  address: string;
  lowerCased: string;
  constructor(value: string) { this.address = value; this.lowerCased = value.toLowerCase(); }
  toString() { return this.address; }
  toLowerCase() { return this.lowerCased; }
  equals(value: unknown) { return this.lowerCased === String(value).toLowerCase(); }
}

const context = { logger: { debug() {}, info() {}, warn() {}, error() {} },
  metrics: { async count() {}, async dist() {} } };
const gasDetails = () => ({ gasPriceInWei: 0n, gasCostInWei: 0n, gasCostInEth: 0, gasUse: 0n, gasCostInQuoteToken: 0n });

export async function quoteLocalSplits(request: LocalRequest, linears: LocalCandidate[], quote: LocalQuote,
                                      options: DeepOptions = {}): Promise<LocalCandidate[]> {
  configureWrappedCurrency(request.chainId, WETH);
  const physical = new Map<string, any>();
  const semantic = new WeakMap<any[], Hop[]>();
  const routes = linears.map(candidate => {
    const hops = candidate[0].hops;
    const path = hops.filter(hop => hop.pool).map(hop => {
      const key = localPoolKey(hop.pool);
      if (!physical.has(key)) physical.set(key, { address: new Address(key), protocol: hop.pool.protocol,
        token0: new Address(hop.pool.token0.address), token1: new Address(hop.pool.token1.address),
        hooks: hop.pool.hooks ?? ZERO, tickSpacing: hop.pool.tickSpacing });
      return physical.get(key);
    });
    semantic.set(path, hops);
    return new RouteBasic(new Set(path.map(pool => pool.protocol)).size === 1 ? path[0].protocol : 'mixed', path);
  });
  const fetcher = { async fetchQuotes(_chain: unknown, _input: unknown, _output: unknown,
      amount: bigint, percentageRoutes: any[], _mode: unknown, _context: unknown, _tags: unknown,
      _block: unknown, _tokens: unknown, _overrides: unknown, report: { droppedRoutes: number }) {
    const observations = await Promise.all(percentageRoutes.map(async route => {
      const portion = amount*BigInt(route.percentage)/100n;
      try {
        const result = await quote({ mode: 'exactIn', amount: portion.toString(),
          branches: [{ amountIn: portion.toString(), hops: semantic.get(route.path)! }] });
        return result.quote === null ? null : new QuoteBasic(route, BigInt(result.quote));
      } catch {
        // A missing percentage observation cannot retract the early finder
        // hints or exclude other canonically quoted paths/percentages.
        report.droppedRoutes += 1;
        return null;
      }
    }));
    return observations.filter(observation => observation !== null);
  } };
  const selector = new SimpleQuoteSelector();
  const strategy = new DeepQuoteStrategy(fetcher,
    { async getCurrentGasPrice() { return 0; }, async estimateGas() { return gasDetails(); } },
    { async updateQuoteBasicsGasDetails() {} }, new RouteQuoteAllocator(), selector,
    {}, new Map(), {}, new Map());
  const config = { RouteFinder: { RouteSplitPercentage: options.percentageStep ?? 5,
    MaxSplits: 2, MaxSplitRoutes: Infinity, RouteSplitTimeoutMs: Infinity },
    GasEstimation: { Enabled: false }, L1L2GasCostFetcher: { ArbitrumEnabled: false, OpStackEnabled: false } };
  const currency = (address: string) => ({ wrappedAddress: new Address(address.toLowerCase() === ZERO ? WETH : address) });
  const stitched = await strategy.findBestQuoteCandidates(context, { chainId: request.chainId },
    currency(request.source), currency(request.target), BigInt(request.amount), TradeType.ExactIn,
    [...new Set(request.pools.map(pool => pool.protocol))], config, routes, new Map(), []);
  // Execute the published selector with every result retained. It only orders
  // nominations; CyberGold still compares complete canonically replayed plans.
  const ranked = await selector.getBestQuotes(stitched, TradeType.ExactIn, stitched.length, [], context);
  const result: LocalCandidate[] = [];
  const seen = new Set<string>();
  for (const split of ranked) {
    if (split.quotes.length === 1) continue; // Already published as finder hints.
    const branches = split.quotes.map((item: any) => ({
      // Exact percentage weights avoid pre-flooring into a different ppm ratio.
      // Helpers-compatible runtime replay owns all actual input and remainder.
      amountIn: String(item.route.percentage), hops: semantic.get(item.route.path)!,
    }));
    const key = JSON.stringify(branches.map((branch: LocalCandidate[number]) => [branch.amountIn,
      branch.hops.map(hop => hop.pool ? [localPoolKey(hop.pool), hop.zeroForOne] : [hop.kind, hop.currencyOut]) ]));
    if (!seen.has(key)) { seen.add(key); result.push(branches); }
  }
  return result;
}

/** Publish raw finder paths before any optimizer callback or failure can wait. */
export async function discoverDeepLocal(request: LocalRequest, quote: LocalQuote,
    publish: (candidates: LocalCandidate[]) => void | Promise<void>, options: DeepOptions = {}): Promise<LocalCandidate[]> {
  const linears = await discoverLocal(request);
  await publish(linears);
  return options.finderOnly ? [] : quoteLocalSplits(request, linears, quote, options);
}
