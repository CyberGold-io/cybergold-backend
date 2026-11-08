/** Actual published UniRoute RouteFinder, with explicit CyberGold model wiring. */
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { RouteFinder } = require('../../vendor/uniroute-public/runtime/core/route/RouteFinder.js');
const { configureWrappedCurrency } = require('../../vendor/uniroute-public/runtime/lib/poolUtils.js');

const ZERO = '0x0000000000000000000000000000000000000000';
const WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2';
export const LOCAL_CONFIG = { RouteFinder: {
  MaxHops: 3, MaxHopsExtended: 3, MinRoutesThreshold: 0, MaxExtendedRoutes: 0,
} };

type Pool = { id: string; protocol: 'v2' | 'v3' | 'v4'; token0: { address: string };
  token1: { address: string }; tickSpacing?: number };
export type LocalRequest = { chainId: number; source: string; target: string; amount: string; pools: Pool[] };

function endpointVariants(currency: string) {
  return currency === ZERO ? [ZERO, WETH] : currency === WETH ? [WETH, ZERO] : [currency];
}

export async function discoverLocal(request: LocalRequest): Promise<{ amountIn: string; hops: any[] }[][]> {
  configureWrappedCurrency(WETH);
  const pools = request.pools.map(physical => ({ physical, protocol: physical.protocol,
    token0: { lowerCased: physical.token0.address.toLowerCase() },
    token1: { lowerCased: physical.token1.address.toLowerCase() }, tickSpacing: physical.tickSpacing }));
  const poolIndexes = new Map(request.pools.map((pool, index) => [pool, index]));
  const source = request.source.toLowerCase(), target = request.target.toLowerCase();
  const finder = new RouteFinder(LOCAL_CONFIG);
  const candidates: { amountIn: string; hops: any[] }[][] = [];
  const seen = new Set<string>();
  // The public finder grants its extra hop only after a fake edge is already
  // inside the path. Project both native endpoints so a terminal transition
  // after three physical pools needs no change to its algorithm or hop bound.
  for (const graphSource of endpointVariants(source)) for (const graphTarget of endpointVariants(target)) {
    const routes = await finder.generateRoutes(request.chainId, pools,
      { lowerCased: graphSource }, { lowerCased: graphTarget }, true);
    for (const route of routes) {
      let current = source;
      const hops: any[] = [];
      const transition = (following: string) => {
        if (current === following) return;
        const kind = current === ZERO ? 'wrap' : 'unwrap';
        const previous = hops.at(-1);
        if (previous?.kind && previous.kind !== kind) hops.pop();
        else hops.push({ kind, currencyOut: following });
        current = following;
      };
      transition(graphSource);
      for (const pool of route.path) {
        const zeroForOne = current === pool.token0.lowerCased;
        const following = (zeroForOne ? pool.token1 : pool.token0).lowerCased;
        if (pool.nativeTransition) transition(following);
        else {
          hops.push({ pool: pool.physical, zeroForOne });
          current = following;
        }
      }
      transition(target);
      const identity = JSON.stringify(hops.map(hop => hop.pool
        ? [poolIndexes.get(hop.pool), hop.zeroForOne] : [hop.kind, hop.currencyOut]));
      if (!seen.has(identity)) {
        seen.add(identity);
        candidates.push([{ amountIn: request.amount, hops }]);
      }
    }
  }
  return candidates;
}
