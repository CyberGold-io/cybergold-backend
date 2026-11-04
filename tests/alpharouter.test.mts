import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { setImmediate } from 'node:timers/promises';
import { createCalculationSession } from '../src/uniswap-sdk/calculation-session.ts';
import { routeRequest } from '../src/uniswap-sdk/alpha-worker.ts';
import { runRequest } from '../src/uniswap-sdk/engine.ts';
import { cases, BLOCK, gasSupportPools, WETH, USDC } from './alpha-fixtures.mts';

const ZERO = '0x0000000000000000000000000000000000000000';

test('terminal calculation errors retire pending callbacks and silence late work before reuse', async () => {
  const frames: any[] = [];
  let fail: (error: Error) => void;
  let lateQuote: (value: any) => Promise<any>;
  let latePublish: (value: any[]) => void;
  let pendingRetired = false;
  const session = createCalculationSession(async (request, quote, publish) => {
    if (request.id !== 'first') return [['next result']];
    lateQuote = quote;
    latePublish = publish;
    publish([['early candidate']]);
    const pending = quote({ amount: '100' });
    void pending.catch(() => { pendingRetired = true; });
    await Promise.all([pending, new Promise((_, reject) => { fail = reject; })]);
    return [];
  }, value => { frames.push(value); }, error => (error as Error).message);
  session.receive({ id: 'first' });
  const callback = frames.find(frame => frame.operation === 'quote');
  fail!(new Error('ordinary failure'));
  await setImmediate();
  assert.equal(pendingRetired, true);
  assert.deepEqual(frames.at(-1), { id: 'first', error: 'ordinary failure' });
  const terminalLength = frames.length;
  await assert.rejects(lateQuote!({ amount: '200' }), /retired/);
  latePublish!([['late candidate']]);
  assert.equal(session.receive({ id: 'first', operation: 'quoteResult', quoteId: callback.quoteId,
    result: { quote: '999' } }), true);
  await setImmediate();
  assert.equal(frames.length, terminalLength);
  session.receive({ id: 'next' });
  await setImmediate();
  assert.deepEqual(frames.at(-1), { id: 'next', candidates: [['next result']] });
  session.close();
});

test('closing a calculation session retires callbacks without publishing a terminal or late frame', async () => {
  const frames: any[] = [];
  let retired = false;
  let publishLate: (value: any[]) => void;
  const session = createCalculationSession(async (_request, quote, publish) => {
    publishLate = publish;
    try { await quote({ amount: '100' }); }
    catch { retired = true; }
    publish([['completed after input close']]);
    return [];
  }, value => { frames.push(value); }, () => 'ordinary failure');
  session.receive({ id: 'closing' });
  assert.equal(frames.length, 1);
  session.close();
  await setImmediate();
  assert.equal(retired, true);
  publishLate!([['late candidate']]);
  assert.equal(frames.length, 1);
});

test('active calculation callbacks resolve and retain the existing unknown-frame signal', async () => {
  const frames: any[] = [];
  const session = createCalculationSession(async (_request, quote, publish) => {
    const result = await quote({ amount: '100' });
    publish([[result.quote]]);
    return [[result.quote]];
  }, value => { frames.push(value); }, () => 'ordinary failure');
  session.receive({ id: 'active' });
  const callback = frames[0];
  assert.equal(session.receive({ id: 'unknown', operation: 'quoteResult', quoteId: callback.quoteId,
    result: { quote: 'bad' } }), false);
  assert.equal(session.receive({ id: 'active', operation: 'quoteResult', quoteId: callback.quoteId,
    result: { quote: '200' } }), true);
  await setImmediate();
  assert.deepEqual(frames.slice(1), [
    { id: 'active', operation: 'candidates', candidates: [['200']] },
    { id: 'active', candidates: [['200']] },
  ]);
  session.close();
});

test('ordered cancellation removes retired query records and acknowledges after late work is silenced', async () => {
  const frames: any[] = [];
  let publishLate: (value: any[]) => void;
  const session = createCalculationSession(async (request, quote, publish) => {
    publishLate = publish;
    await quote({ amount: request.amount });
    return [[request.id]];
  }, value => { frames.push(value); }, () => 'ordinary failure');
  for (let index = 0; index < 100; index++) {
    const id = String(index);
    session.receive({ id, amount: '100' });
    const callback = frames.at(-1);
    session.receive({ id, operation: 'quoteResult', quoteId: callback.quoteId, result: { quote: '200' } });
    await setImmediate();
    assert.deepEqual(frames.at(-1), { id, candidates: [[id]] });
    session.receive({ id, operation: 'cancel' });
    assert.deepEqual(frames.at(-1), { id, operation: 'cancelled' });
    const length = frames.length;
    publishLate!([['retired']]);
    assert.equal(frames.length, length);
    // A deleted owner cannot resolve a callback in a later calculation.
    assert.equal(session.receive({ id, operation: 'quoteResult', quoteId: callback.quoteId,
      result: { quote: 'late duplicate' } }), false);
  }
  session.close();
});

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
  await assert.rejects(routeRequest({ id: '31337', chainId: 31337, blockNumber: BLOCK,
    source: fixture.tokenIn.address, target: fixture.tokenOut.address, amount: fixture.amount,
    pools: fixture.pools.map(pool => ({ ...pool, token0: { ...pool.token0, chainId: 31337 },
      token1: { ...pool.token1, chainId: 31337 } })) }, async () => { throw new Error('unexpected callback'); }),
    /31337/);
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


test('explicit Sandbox fork dependencies retain 31338 through actual Alpha and SDK callbacks', async () => {
  const fixture = cases.find(value => !value.expectedNull && !value.nativeOutput)!;
  const pools = fixture.pools.map(pool => ({ ...pool,
    token0: { ...pool.token0, chainId: 31338 }, token1: { ...pool.token1, chainId: 31338 } }));
  let callbacks = 0;
  const selected = await routeRequest({ id: 'fork-real-id', chainId: 31338, blockNumber: BLOCK,
    source: fixture.tokenIn.address, target: fixture.tokenOut.address, amount: fixture.amount, pools }, async request => {
    callbacks++;
    assert.ok(request.branches.every((branch: any) => branch.hops.every((hop: any) =>
      !hop.pool || (hop.pool.token0.chainId === 31338 && hop.pool.token1.chainId === 31338))));
    const value = await runRequest({ id: 'fork-real-id', operation: 'simulateRoute', mode: request.mode,
      amount: request.amount, pools: pools as any[], route: { branches: request.branches.map((branch: any) => ({
        amountIn: branch.amountIn, hops: branch.hops.filter((hop: any) => hop.pool)
          .map((hop: any) => ({ poolId: hop.pool.id, zeroForOne: hop.zeroForOne })) })) } });
    return { quote: value.fullyFilled && ('settled' in value && value.settled)
      ? value[request.mode === 'exactIn' ? 'amountOut' : 'amountIn'] : null };
  });
  assert.ok(callbacks > 0);
  assert.ok(selected.length > 0);
  assert.ok(selected[0].every((branch: any) => branch.hops.every((hop: any) => !hop.pool || hop.pool.token0.chainId === 31338)));
});

test('Alpha publishes simultaneous sibling topologies in one ordered batch before its SDK price', async () => {
  const fixture = cases.find(value => value.id === 'split-exact-in')!;
  const published: any[] = [];
  const pricedPaths: string[] = [];
  let entered!: () => void, release!: () => void;
  const firstCallback = new Promise<void>(resolve => { entered = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  let completed = false;
  const calculation = routeRequest({ id: 'early-alpha', chainId: 1, blockNumber: BLOCK,
    source: fixture.tokenIn.address, target: fixture.tokenOut.address,
    amount: fixture.amount, pools: fixture.pools }, async request => {
    assert.equal(published.length, 1, 'one simultaneous route batch precedes the first deep price callback');
    assert.ok(published[0].length >= 2, 'the complete sibling path batch is already available');
    const identity = JSON.stringify(request.branches[0].hops.map((hop: any) => hop.pool.id));
    if (!pricedPaths.includes(identity)) pricedPaths.push(identity);
    entered();
    await held;
    return { quote: null };
  }, batch => { published.push(batch); });
  void calculation.then(() => { completed = true; });
  await firstCallback;
  assert.equal(published.length, 1);
  assert.ok(published[0].length >= 2);
  assert.equal(completed, false);
  release();
  const selected = await calculation;
  assert.ok(published.length > 0);
  assert.equal(published.length, 1);
  const identities = published[0].map((candidate: any[]) => candidate.map(branch => branch.hops
    .map((hop: any) => [hop.pool?.id, hop.zeroForOne, hop.kind, hop.currencyOut])));
  assert.equal(new Set(identities.map((identity: any) => JSON.stringify(identity))).size, published[0].length);
  assert.deepEqual(published[0].map((candidate: any[]) => JSON.stringify(candidate[0].hops
    .map((hop: any) => hop.pool.id))), pricedPaths);
  assert.deepEqual(selected, []);
  assert.ok(published.every(batch => batch.every((candidate: any[]) => candidate.every(branch => !('quote' in branch)))));
});

test('one cancelled calculation retires its callbacks without suppressing a sibling finder', async () => {
  const frames: any[] = [];
  let retired = false;
  const session = createCalculationSession(async (request, quote, publish) => {
    publish([[request.id]]);
    if (request.id === 'held') {
      try { await quote({ amount: '100' }); } catch { retired = true; }
    }
    return [[request.id]];
  }, frame => { frames.push(frame); }, () => 'ordinary failure');
  session.receive({ id: 'held' });
  session.receive({ id: 'sibling' });
  session.receive({ id: 'held', operation: 'cancel' });
  await setImmediate();
  assert.equal(retired, true);
  assert.ok(frames.some(frame => frame.id === 'sibling' && frame.operation === 'candidates'));
  assert.ok(frames.some(frame => frame.id === 'sibling' && !frame.operation && frame.candidates));
  assert.ok(!frames.some(frame => frame.id === 'held' && !frame.operation));
  session.close();
});


test('Sandbox native output uses the fork wrapper dependency without changing chain', async () => {
  const fixture = cases.find(value => value.nativeOutput)!;
  const pools = fixture.pools.map(pool => ({ ...pool,
    token0: { ...pool.token0, chainId: 31338 }, token1: { ...pool.token1, chainId: 31338 } }));
  let callbacks = 0;
  const selected = await routeRequest({ id: 'fork-native-output', chainId: 31338, blockNumber: BLOCK,
    source: fixture.tokenIn.address, target: ZERO, amount: fixture.amount, pools }, async () => {
    callbacks++; return { quote: '1000' };
  });
  assert.ok(callbacks > 0);
  assert.ok(selected.length > 0);
  assert.equal(selected[0][0].hops.at(-1).kind, 'unwrap');
  assert.ok(selected[0][0].hops.filter((hop: any) => hop.pool).every((hop: any) => hop.pool.token0.chainId === 31338));
});
