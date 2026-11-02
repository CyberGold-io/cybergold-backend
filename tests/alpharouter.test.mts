import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { routeRequest } from '../src/uniswap-sdk/alpha-worker.ts';
import { runRequest } from '../src/uniswap-sdk/engine.ts';
import { cases, BLOCK, gasSupportPools, WETH, USDC } from './alpha-fixtures.mts';

const ZERO = '0x0000000000000000000000000000000000000000';
for (const fixture of cases) test('actual AlphaRouter canonical callback: '+fixture.id, async () => {
  const calls: any[] = [];
  const selected = await routeRequest({ id: fixture.id, chainId: 1, blockNumber: BLOCK,
    source: fixture.tokenIn.address, target: fixture.nativeOutput ? ZERO : fixture.tokenOut.address,
    amount: fixture.amount, mode: fixture.mode as 'exactIn' | 'exactOut', pools: fixture.pools }, async request => {
    calls.push(request);
    const value = await runRequest({ id: fixture.id, operation: 'simulateRoute', mode: request.mode,
      amount: request.amount, pools: fixture.pools as any[], route: { branches: request.branches.map((branch: any) => ({
        amountIn: branch.amountIn, hops: branch.hops.filter((hop: any) => hop.pool)
          .map((hop: any) => ({ poolId: hop.pool.id, zeroForOne: hop.zeroForOne })) })) } });
    return { quote: value.fullyFilled && ('settled' in value && value.settled) ? value[request.mode === 'exactIn' ? 'amountOut' : 'amountIn'] : null };
  });
  if (fixture.expectedNull) { assert.deepEqual(selected, []); return; }
  assert.equal(selected.length, 1);
  assert(calls.length > 0, 'every protocol including V2 uses canonical callbacks');
  assert(selected[0].length > 0);
  assert(selected[0].every((branch: any) => typeof branch.amountIn === 'string'));
  if (fixture.id === 'split-exact-in') {
    assert.equal(selected[0].length, 2);
    assert(BigInt(selected[0][0].amountIn) + BigInt(selected[0][1].amountIn) <= BigInt(fixture.amount));
  }
  if (fixture.nativeOutput) assert.equal(selected[0][0].hops.at(-1).kind, 'unwrap');
});

test('AlphaRouter keeps actual unsupported chain instead of relabelling it', async () => {
  const fixture = cases[0];
  await assert.rejects(routeRequest({ id: '31338', chainId: 31338, blockNumber: BLOCK,
    source: fixture.tokenIn.address, target: fixture.tokenOut.address, amount: fixture.amount,
    pools: fixture.pools.map(pool => ({ ...pool, token0: { ...pool.token0, chainId: 31338 },
      token1: { ...pool.token1, chainId: 31338 } })) }, async () => { throw new Error('unexpected callback'); }),
    /31338/);
});

// An existing canonical reference takes precedence over the gas lookup seed.
test('AlphaRouter preserves the supplied USD/WETH pool alias', async () => {
  const pool = { ...gasSupportPools[0], id: 'v3:known-usd-weth:500' };
  const candidates = await routeRequest({ id: 'gas-pool-alias', chainId: 1, blockNumber: BLOCK,
    source: WETH, target: USDC, amount: '1000000', pools: [pool] }, async () => ({ quote: '100' }));
  assert.equal(candidates[0][0].hops[0].pool.id, pool.id);
});

test('zero-gas lookup reference cannot bootstrap a USD/WETH route absent from catalog', async () => {
  const require = createRequire(import.meta.url);
  const usd = require('@uniswap/smart-order-router').usdGasTokensByChain[1][0].address;
  const callbacks: any[] = [];
  const candidates = await routeRequest({ id: 'no-gas-helper-route', chainId: 1, blockNumber: BLOCK,
    source: WETH, target: usd, amount: '1000000', pools: cases[0].pools }, async request => {
    callbacks.push(request);
    return { quote: '100' };
  });
  assert.deepEqual(candidates, []);
  assert.deepEqual(callbacks, []);
});
