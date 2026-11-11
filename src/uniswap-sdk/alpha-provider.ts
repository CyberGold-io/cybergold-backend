/** Full unmodified AlphaRouter with topology-only pools and Python-owned canonical quotes.
 * Gas is zero for candidate nomination; CyberGold still ranks complete economic plans.
 * Supplied SDK objects never price swaps or claim complete tick observations.
 */
import { createRequire } from "node:module";
import { mapQuoteJobs } from './callback-work.ts';
const require = createRequire(import.meta.url);
const sor = require("@uniswap/smart-order-router");
const sdk: any = { sor, core: require("@uniswap/sdk-core"), v2: require("@uniswap/v2-sdk"),
  v3: require("@uniswap/v3-sdk"), v4: require("@uniswap/v4-sdk"),
  router: require("@uniswap/router-sdk"), BigNumber: require("@ethersproject/bignumber").BigNumber };
const sorRequire = require;
const { Token, Ether, CurrencyAmount } = sdk.core;
const { BigNumber } = sdk;
const ZERO = "0x0000000000000000000000000000000000000000";
const lower = (value: string) => value.toLowerCase();
const currencyAddress = (currency: any) => currency.isNative ? ZERO : lower(currency.address);
const tokenPairKey = (a: any, b: any) => [currencyAddress(a), currencyAddress(b)].sort().join("/");
type TokenSnapshot = { address: string; decimals?: number; chainId?: number; symbol?: string; name?: string; isNative?: boolean };
type PoolSnapshot = { id: string; address?: string; protocol: "v2" | "v3" | "v4"; token0: TokenSnapshot; token1: TokenSnapshot;
  reserve0?: string; reserve1?: string; feePips?: number; lpFee?: number; tickSpacing?: number; hooks?: string;
  sqrtRatioX96?: string; sqrtPriceX96?: string; liquidity?: string; tick?: number; tvlETH?: number; tvlUSD?: number };
type QuoteRequest = { route: any; amount: any; mode: "exactIn" | "exactOut"; pools: PoolSnapshot[]; blockNumber: number };
type QuoteObservation = { quote: string | null; sqrtPriceX96AfterList?: string[]; initializedTicksCrossedList?: number[]; gasEstimate?: string };
type AlphaOptions = { chainId: number; blockNumber: number; pools: PoolSnapshot[];
  nominateRoutes?: (routes: any[]) => void;
  quoteRoute: (request: QuoteRequest) => Promise<QuoteObservation>; gasSupportPools?: PoolSnapshot[];
  quoteSignal?: AbortSignal };
// The product Sandbox inherits these Mainnet deployments. Register the
// dependency addresses/currencies under its real ID; no quote/callback is
// labelled Mainnet and this offline router never owns a chain transport.
let sandboxRegistered = false;
function registerSandboxDependencies(chainId: number) {
  if (chainId !== 31338 || sandboxRegistered) return;
  const chains = sorRequire('@uniswap/smart-order-router/build/main/util/chains');
  const addresses = sorRequire('@uniswap/smart-order-router/build/main/util/addresses');
  const tokenAt = (token: any) => new Token(chainId, token.address, token.decimals, token.symbol, token.name);
  addresses.UNISWAP_MULTICALL_ADDRESSES[chainId] = addresses.UNISWAP_MULTICALL_ADDRESSES[1];
  chains.WRAPPED_NATIVE_CURRENCY[chainId] = tokenAt(chains.WRAPPED_NATIVE_CURRENCY[1]);
  sor.usdGasTokensByChain[chainId] = sor.usdGasTokensByChain[1].map(tokenAt);
  const pools = sorRequire('@uniswap/smart-order-router/build/main/util/pool');
  pools.V4_ETH_WETH_FAKE_POOL[chainId] = new sdk.v4.Pool(sandboxEther,
    chains.WRAPPED_NATIVE_CURRENCY[chainId], 0, 0, ZERO, '79228162514264337593543950336', '0', 0);
  const chainEnum = chains.ID_TO_CHAIN_ID, networkName = chains.ID_TO_NETWORK_NAME;
  chains.ID_TO_CHAIN_ID = (id: number) => id === chainId ? chainId : chainEnum(id);
  chains.ID_TO_NETWORK_NAME = (id: number) => id === chainId ? 'ethereum-mainnet-fork' : networkName(id);
  sandboxRegistered = true;
}
class SandboxEther extends Ether {
  constructor() { super(31338); }
  get wrapped() { return sor.WRAPPED_NATIVE_CURRENCY[31338]; }
}
const sandboxEther = new SandboxEther();

export function createAlphaRouter(options: AlphaOptions) {
  const { chainId, blockNumber } = options;
  registerSandboxDependencies(chainId);
  const counts: Record<string, number> = {};
  const record = (stage: string, details: any = {}) => {
    counts[stage] = (counts[stage] ?? 0) + 1;
  };
  const tokens = new Map<string, any>();
  const currency = (row: TokenSnapshot) => {
    if (row.isNative || lower(row.address) === ZERO) return (row.chainId ?? chainId) === 31338
      ? sandboxEther : Ether.onChain(row.chainId ?? chainId);
    const key = lower(row.address);
    if (!tokens.has(key)) tokens.set(key, new Token(row.chainId ?? chainId, row.address,
      row.decimals ?? 18, row.symbol, row.name));
    return tokens.get(key);
  };
  const snapshotBySdkPool = new WeakMap<object, PoolSnapshot>();
  const makePool = (row: PoolSnapshot) => {
    const a = currency(row.token0), b = currency(row.token1);
    let pool: any;
    if (row.protocol === 'v2') {
      pool = new sdk.v2.Pair(CurrencyAmount.fromRawAmount(a, row.reserve0 ?? '1'),
        CurrencyAmount.fromRawAmount(b, row.reserve1 ?? '1'));
    } else {
      const spacing = row.tickSpacing ?? sdk.v3.TICK_SPACINGS[row.feePips!];

      const provider = {
        async getTick(_index: number) { throw new Error('AlphaRouter must use canonical quote callbacks'); },
        async nextInitializedTickWithinOneWord(tick: number, lte: boolean, tickSpacing: number) {
          throw new Error('AlphaRouter must use canonical quote callbacks');
        },
      };
      pool = row.protocol === 'v3'
        ? new sdk.v3.Pool(a, b, row.feePips, row.sqrtRatioX96 ?? row.sqrtPriceX96 ?? '79228162514264337593543950336',
          row.liquidity ?? '0', row.tick ?? 0, provider)
        : new sdk.v4.Pool(a, b, row.lpFee ?? row.feePips, spacing, row.hooks ?? ZERO,
          row.sqrtRatioX96 ?? row.sqrtPriceX96 ?? '79228162514264337593543950336', row.liquidity ?? '0', row.tick ?? 0, provider);
    }
    snapshotBySdkPool.set(pool, row);
    return pool;
  };
  const routeRows = options.pools;
  // Upstream still resolves a USD/native pool before invoking even a zero gas
  // model. This reference is only constructor topology, outside the supplied
  // candidate catalog. Its SDK scalar placeholders never quote a swap.
  const usd = sor.usdGasTokensByChain[chainId]?.[0];
  const wrapped = sor.WRAPPED_NATIVE_CURRENCY[chainId];
  const gasTokens = usd && wrapped ? [usd, wrapped].sort((a: any, b: any) => a.sortsBefore(b) ? -1 : 1) : [];
  const gasSupport = options.gasSupportPools ?? (gasTokens.length ? [{ id: 'gas-topology-only', protocol: 'v3' as const,
    token0: { address: gasTokens[0].address, decimals: gasTokens[0].decimals, chainId },
    token1: { address: gasTokens[1].address, decimals: gasTokens[1].decimals, chainId },
    feePips: 500, tickSpacing: 10 }] : []);
  const allRows = [...gasSupport, ...routeRows];
  const built = allRows.map(row => ({ row, pool: makePool(row) }));
  const v2Rows = built.filter(({ row }) => row.protocol === 'v2');
  const v3Rows = built.filter(({ row }) => row.protocol === 'v3');
  const v4Rows = built.filter(({ row }) => row.protocol === 'v4');
  const poolId = (row: PoolSnapshot) => {
    const pool = built.find(entry => entry.row === row)!.pool;
    return lower(row.address ?? (row.protocol === 'v4' ? row.id : row.protocol === 'v2'
      ? pool.liquidityToken.address : sdk.v3.Pool.getAddress(pool.token0, pool.token1, pool.fee)));
  };
  const v3Key = (a: any, b: any, fee: number) => tokenPairKey(a, b)+'/'+fee;
  const v4Key = (a: any, b: any, fee: number, spacing: number, hooks: string) =>
    tokenPairKey(a, b)+'/'+fee+'/'+spacing+'/'+lower(hooks);
  const v2Index = new Map(v2Rows.map(({ pool, row }) => [tokenPairKey(pool.token0, pool.token1), { pool, row }]));
  const v3Index = new Map(v3Rows.map(({ pool, row }) => [v3Key(pool.token0, pool.token1, pool.fee), { pool, row }]));
  const v4Index = new Map(v4Rows.map(({ pool, row }) => [v4Key(pool.currency0, pool.currency1, pool.fee, pool.tickSpacing, pool.hooks), { pool, row }]));
  const requested = (name: string, pairs: any[]) => record(name, { requested: pairs.length });
  const v2PoolProvider = {
    getPoolAddress(a: any, b: any) {
      const entry = v2Index.get(tokenPairKey(a, b));
      const [token0, token1] = a.sortsBefore(b) ? [a, b] : [b, a];
      return { poolAddress: entry ? poolId(entry.row) : sdk.v2.Pair.getAddress(a, b), token0, token1 };
    },
    async getPools(pairs: any[]) {
      requested('v2.pool.getPools', pairs);
      const selected = pairs.map(([a, b]) => v2Index.get(tokenPairKey(a, b))).filter(Boolean);
      const byKey = new Map(selected.map((entry: any) => [tokenPairKey(entry.pool.token0, entry.pool.token1), entry.pool]));
      return {
        getPool: (a: any, b: any) => byKey.get(tokenPairKey(a, b)),
        getPoolByAddress: (address: string) => selected.find((entry: any) => poolId(entry.row) === lower(address))?.pool,
        getAllPools: () => [...new Set(selected.map((entry: any) => entry.pool))],
      };
    },
  };
  const v3PoolProvider = {
    getPoolAddress(a: any, b: any, fee: number) {
      const entry = v3Index.get(v3Key(a, b, fee));
      const [token0, token1] = a.sortsBefore(b) ? [a, b] : [b, a];
      return { poolAddress: entry ? poolId(entry.row) : sdk.v3.Pool.getAddress(a, b, fee), token0, token1 };
    },
    async getPools(pairs: any[]) {
      requested('v3.pool.getPools', pairs);
      const selected = pairs.map(([a, b, fee]) => v3Index.get(v3Key(a, b, fee))).filter(Boolean);
      const byKey = new Map(selected.map((entry: any) => [v3Key(entry.pool.token0, entry.pool.token1, entry.pool.fee), entry.pool]));
      // Gas helpers request individual getPool values. Routing consumes only
      // the supplied catalog projection; a zero-gas lookup reference must not
      // become a discovery candidate through upstream direct-pool fallback.
      const routing = selected.filter((entry: any) => routeRows.includes(entry.row));
      return {
        getPool: (a: any, b: any, fee: number) => byKey.get(v3Key(a, b, fee)),
        getPoolByAddress: (address: string) => routing.find((entry: any) => poolId(entry.row) === lower(address))?.pool,
        getAllPools: () => [...new Set(routing.map((entry: any) => entry.pool))],
      };
    },
  };
  const v4PoolProvider = {
    getPoolId(a: any, b: any, fee: number, spacing: number, hooks: string) {
      const entry = v4Index.get(v4Key(a, b, fee, spacing, hooks));
      const [currency0, currency1] = a.isNative || (!b.isNative && a.sortsBefore(b)) ? [a, b] : [b, a];
      return { poolId: entry ? lower(entry.row.id) : sdk.v4.Pool.getPoolId(a, b, fee, spacing, hooks), currency0, currency1 };
    },
    async getPools(pairs: any[]) {
      requested('v4.pool.getPools', pairs);
      const selected = pairs.map(([a, b, fee, spacing, hooks]) => v4Index.get(v4Key(a, b, fee, spacing, hooks))).filter(Boolean);
      const byKey = new Map(selected.map((entry: any) => [v4Key(entry.pool.currency0, entry.pool.currency1,
        entry.pool.fee, entry.pool.tickSpacing, entry.pool.hooks), entry.pool]));
      return {
        getPool: (a: any, b: any, fee: number, spacing: number, hooks: string) => byKey.get(v4Key(a, b, fee, spacing, hooks)),
        getPoolById: (id: string) => selected.find((entry: any) => lower(entry.row.id) === lower(id))?.pool,
        getAllPools: () => [...new Set(selected.map((entry: any) => entry.pool))],
      };
    },
  };
  const subgraphPools = (protocol: string) => routeRows.filter(row => row.protocol === protocol).map(row => {
    const a = currency(row.token0), b = currency(row.token1);
    const tokenRow = (value: any) => ({ id: currencyAddress(value), symbol: value.symbol, decimals: String(value.decimals) });
    if (protocol === 'v2') return { id: poolId(row), token0: tokenRow(a), token1: tokenRow(b),
      supply: 1, reserve: row.tvlETH ?? 1, reserveUSD: row.tvlUSD ?? 1 };
    return { id: protocol === 'v4' ? lower(row.id) : poolId(row), token0: tokenRow(a), token1: tokenRow(b),
      feeTier: String(protocol === 'v4' ? row.lpFee ?? row.feePips : row.feePips),
      tickSpacing: String(row.tickSpacing), hooks: row.hooks ?? ZERO, liquidity: row.liquidity,
      tvlETH: row.tvlETH ?? 1, tvlUSD: row.tvlUSD ?? 1 };
  });
  const subgraph = (protocol: string) => ({ async getPools() {
    record(protocol+'.subgraph.getPools'); return subgraphPools(protocol);
  } });
  const tokenProvider = { async getTokens(addresses: string[]) {
    record('token.getTokens', { addresses: addresses.map(lower) });
    const selected = addresses.map(address => tokens.get(lower(address))).filter(Boolean);
    return { getTokenByAddress: (address: string) => selected.find(token => lower(token.address) === lower(address)),
      getTokenBySymbol: (symbol: string) => selected.find(token => token.symbol === symbol), getAllTokens: () => selected };
  } };
  const tokenPropertiesProvider = { async getTokensProperties(currencies: any[]) {
    record('token.getTokensProperties', { addresses: currencies.map(currencyAddress) });
    return Object.fromEntries(currencies.map(value => [currencyAddress(value), {}]));
  } };
  const tokenValidatorProvider = { async validateTokens(values: any[]) {
    record('token.validateTokens', { addresses: values.map(currencyAddress) });
    return { getValidationByToken: () => undefined };
  } };
  // Upstream policy lists are not CyberGold pool/token admission rules.
  const blockedTokenListProvider = { hasTokenBySymbol: async () => false, getTokenBySymbol: async () => undefined,
    hasTokenByAddress: async () => false, getTokenByAddress: async () => undefined };
  const quoteMany = async (amounts: any[], routes: any[], mode: 'exactIn' | 'exactOut') => {
    record('quote.'+mode, { routes: routes.length, amounts: amounts.map(amount => amount.quotient.toString()) });
    options.nominateRoutes?.(routes);
    const poolRows = new Map<number, any[]>();
    const observations = await mapQuoteJobs(routes.length*amounts.length, async index => {
      const routeIndex = Math.floor(index/amounts.length), route = routes[routeIndex];
      const amount = amounts[index%amounts.length];
      if (!poolRows.has(routeIndex)) poolRows.set(routeIndex,
        (route.pools ?? route.pairs).map((pool: any) => snapshotBySdkPool.get(pool)));
      const pools = poolRows.get(routeIndex)!;
      const result = await options.quoteRoute({ route, amount, mode, pools, blockNumber });
      record('quote.amount', { protocol: route.protocol, mode, pools: pools.map((row: any) => row?.id),
        amount: amount.quotient.toString(), quote: result.quote });
      return { amount, quote: result.quote === null ? null : BigNumber.from(result.quote),
        sqrtPriceX96AfterList: result.sqrtPriceX96AfterList?.map((value: string) => BigNumber.from(value)) ?? [],
        initializedTicksCrossedList: result.initializedTicksCrossedList ?? [],
        gasEstimate: BigNumber.from(result.gasEstimate ?? 0), gasLimit: BigNumber.from(0) };
    }, options.quoteSignal);
    const routesWithQuotes = routes.map((route, index) => [route,
      observations.slice(index*amounts.length, (index+1)*amounts.length)]);
    return { routesWithQuotes, blockNumber: BigNumber.from(blockNumber) };
  };
  const onChainQuoteProvider = {
    getQuotesManyExactIn: (amounts: any[], routes: any[]) => quoteMany(amounts, routes, 'exactIn'),
    getQuotesManyExactOut: (amounts: any[], routes: any[]) => quoteMany(amounts, routes, 'exactOut'),
  };
  const gasModelFactory = { async buildGasModel(parameters: any) {
    record('gas.buildGasModel');
    const quoteToken = parameters.quoteToken ?? parameters.token;
    const usdToken = sor.usdGasTokensByChain[chainId]?.[0];
    return { estimateGasCost() { return { gasEstimate: BigNumber.from(0),
      gasCostInToken: CurrencyAmount.fromRawAmount(quoteToken, 0), gasCostInUSD: CurrencyAmount.fromRawAmount(usdToken, 0) }; } };
  } };
  class OfflineProvider extends (sorRequire('@ethersproject/providers').BaseProvider) {
    constructor() { super({ chainId, name: 'offline-snapshot-fixture' }); }
    async detectNetwork() { return { chainId, name: 'offline-snapshot-fixture' }; }
    async perform(method: string) { record('unexpected.provider.'+method); throw new Error('No transport in offline fixture: '+method); }
  }
  const AlphaRouterClass = sor.AlphaRouter;
  const router = new AlphaRouterClass({ chainId, provider: new OfflineProvider(),

    ...(chainId === 31338 ? { v2Supported: [chainId], v4Supported: [chainId], mixedSupported: [chainId] } : {}),
    v4PoolParams: routeRows.filter(row => row.protocol === 'v4').map(row => [row.lpFee ?? row.feePips, row.tickSpacing, row.hooks ?? ZERO]),
    v2SubgraphProvider: subgraph('v2'), v3SubgraphProvider: subgraph('v3'), v4SubgraphProvider: subgraph('v4'),
    v2PoolProvider, v3PoolProvider, v4PoolProvider, tokenProvider, tokenPropertiesProvider,
    tokenValidatorProvider, blockedTokenListProvider, onChainQuoteProvider, v2QuoteProvider: onChainQuoteProvider,
    gasPriceProvider: { async getGasPrice() { record('gas.getGasPrice'); return { gasPriceWei: BigNumber.from(0) }; } },
    v2GasModelFactory: gasModelFactory, v3GasModelFactory: gasModelFactory,
    v4GasModelFactory: gasModelFactory, mixedRouteGasModelFactory: gasModelFactory,
  });
  return { router, sdk, counts, currency, poolSnapshot: (pool: any) => snapshotBySdkPool.get(pool) };
}
