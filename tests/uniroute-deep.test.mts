import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { execFileSync, spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { once } from 'node:events';
import { discoverDeepLocal, localPoolKey, quoteLocalSplits } from '../src/uniswap-sdk/uniroute-deep.ts';
import type { LocalCandidate, LocalQuote } from '../src/uniswap-sdk/uniroute-deep.ts';
import { discoverLocal } from '../src/uniswap-sdk/uniroute-local.ts';
import { runRequest } from '../src/uniswap-sdk/engine.ts';
import { v3, A, B, C, WETH, BLOCK, cases } from './alpha-fixtures.mts';

const ZERO = '0x'+'00'.repeat(20);
const token = (address: string, chainId = 1) => ({ address, chainId, decimals: 18 });
function asymmetric(amount = '100000000000000000007') {
  return { chainId: 1, source: A, target: C, amount, pools: [
    v3(token(A), token(C), 500, 0, 10n**20n),
    v3(token(A), token(C), 3000, 0, 2n*10n**20n),
  ] } as any;
}

function runtimeFunding(candidate: LocalCandidate, amount: string) {
  const total = candidate.reduce((sum, branch) => sum+BigInt(branch.amountIn), 0n);
  let allocated = 0n;
  return candidate.map((branch, index) => {
    const share = BigInt(branch.amountIn)*1_000_000n/total;
    const funded = index === candidate.length-1 ? BigInt(amount)-allocated : BigInt(amount)*share/1_000_000n;
    allocated += funded;
    return funded;
  });
}

async function replay(request: any, candidate: LocalCandidate) {
  const funding = runtimeFunding(candidate, request.amount);
  return runRequest({ id: 'final-replay', operation: 'simulateRoute', mode: 'exactIn', amount: request.amount,
    pools: request.pools, route: { branches: candidate.map((branch, index) => ({ amountIn: funding[index].toString(),
      hops: branch.hops.filter(hop => hop.pool).map(hop => ({ poolId: hop.pool.id, zeroForOne: hop.zeroForOne! })) })) } });
}

function canonical(request: any, observed: any[] = []): LocalQuote {
  return async callback => {
    observed.push(callback);
    const value = await runRequest({ id: 'canonical-percentage', operation: 'simulateRoute', mode: 'exactIn',
      amount: callback.amount, pools: request.pools, route: { branches: callback.branches.map(branch => ({
        amountIn: branch.amountIn, hops: branch.hops.filter(hop => hop.pool)
          .map(hop => ({ poolId: hop.pool.id, zeroForOne: hop.zeroForOne! })),
      })) } });
    return { quote: value.fullyFilled && 'settled' in value && value.settled ? value.amountOut : null };
  };
}

test('all published finder/quote/split sources and CommonJS maps match their pins', () => {
  const manifest = JSON.parse(readFileSync(new URL('../vendor/uniroute-public/VENDOR.json', import.meta.url), 'utf8'));
  assert.equal(manifest.components.length, 6);
  for (const row of manifest.components) {
    const source = readFileSync(new URL('../vendor/uniroute-public/upstream/'+row.component, import.meta.url));
    assert.equal(createHash('sha256').update(source).digest('hex'), row.sourceSha256);
    assert.equal(createHash('sha1').update('blob '+source.length+'\0').update(source).digest('hex'), row.gitBlob);
  }
  execFileSync(process.execPath, ['vendor/uniroute-public/build-runtime.cjs', '--check']);
});

test('actual published deep5 improves the canonical asymmetric split over deep25', async () => {
  const request = asymmetric(), original = JSON.stringify(request.pools);
  const raw: LocalCandidate[][] = [], calls: any[] = [];
  const fine = await discoverDeepLocal(request, canonical(request, calls), rows => { raw.push(rows); });
  const coarse = await quoteLocalSplits(request, raw[0], canonical(request), { percentageStep: 25 });
  assert.equal(raw.length, 1);
  assert.equal(raw[0].length, 2);
  assert.deepEqual(fine[0].map(branch => branch.amountIn), ['35', '65']);
  assert.deepEqual(coarse[0].map(branch => branch.amountIn), ['25', '75']);
  const fineReplay = await replay(request, fine[0]), coarseReplay = await replay(request, coarse[0]);
  assert(BigInt(fineReplay.amountOut) > BigInt(coarseReplay.amountOut));
  assert.equal(fineReplay.amountIn, request.amount);
  assert(fineReplay.fullyFilled && 'settled' in fineReplay && fineReplay.settled);
  assert.equal(calls.length, 40);
  assert(fine.length > 5, 'all split results survive instead of a full-route-first result quota');
  assert.equal(JSON.stringify(request.pools), original);
});

test('raw finder publishes before bounded percentage jobs and every ordered split survives', async () => {
  const request = asymmetric(), order: string[] = [];
  const linears = await discoverLocal(request);
  const expected = await quoteLocalSplits(request, linears, canonical(request));
  const callbacks: Parameters<LocalQuote>[0][] = [], published: LocalCandidate[][] = [];
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let entered!: () => void;
  const started = new Promise<void>(resolve => { entered = resolve; });
  const quote = canonical(request);
  let settled = false;
  const operation = discoverDeepLocal(request, async callback => {
    order.push('quote'); callbacks.push(callback); entered(); await gate; return quote(callback);
  }, rows => { order.push('finder'); published.push(rows); });
  void operation.then(() => { settled = true; }, () => { settled = true; });
  try {
    await started;
    assert.equal(order[0], 'finder');
    assert.deepEqual(published, [linears]);
    assert.equal(callbacks.length, 8, 'holding the first batch must not construct all 40 callback payloads');
    assert(order.slice(1).every(stage => stage === 'quote'));
    assert.equal(settled, false, 'optimized results cannot finish while their observations are held');
    release();
    assert.deepEqual(await operation, expected, 'bounded observations retain every ordered split result');
    assert.equal(callbacks.length, 40);
    for (const candidate of published[0]) {
      const path = candidate[0].hops;
      const amounts = callbacks.filter(callback => callback.branches[0].hops === path)
        .map(callback => callback.amount);
      assert.deepEqual(amounts, Array.from({ length: 20 }, (_, index) =>
        (BigInt(request.amount)*BigInt(100-index*5)/100n).toString()));
    }
  } finally {
    // An assertion failure must also release and drain every owned callback.
    release();
    await operation.catch(() => undefined);
  }
});

test('shared terminal pool is only an upstream split limitation; all finder paths survive', async () => {
  const request = { ...asymmetric(), pools: [v3(token(A), token(B), 500, 0, 10n**20n),
    v3(token(A), token(B), 3000, 0, 2n*10n**20n), v3(token(B), token(C), 3000)] };
  const raw: LocalCandidate[][] = [];
  const splits = await discoverDeepLocal(request, canonical(request), rows => { raw.push(rows); });
  assert.equal(raw[0].length, 2);
  assert(raw[0].every(candidate => candidate[0].hops.at(-1)!.pool === request.pools[2]));
  assert.deepEqual(splits, []);
  for (const candidate of raw[0]) assert(BigInt((await replay(request, candidate)).amountOut) > 0n);
});

test('physical alias keys prevent independently quoted copies from becoming a false split', async () => {
  const request = asymmetric();
  const first = request.pools[0];
  const alias = { ...first, id: 'unresolved-alias-without-address-shape', address: undefined };
  request.pools = [first, alias];
  assert.equal(localPoolKey(first), localPoolKey(alias));
  const raw: LocalCandidate[][] = [];
  assert.deepEqual(await discoverDeepLocal(request, canonical(request), rows => { raw.push(rows); }), []);
  assert.equal(raw[0].length, 2);
  assert(raw[0].some(candidate => candidate[0].hops[0].pool === alias));
});

test('true31338 native semantic hops and original pool references reach callbacks', async () => {
  const request = { chainId: 31338, source: A, target: ZERO, amount: '1000000000000000007',
    pools: [v3(token(A, 31338), token(WETH, 31338))] } as any;
  const raw: LocalCandidate[][] = [], calls: any[] = [];
  assert.deepEqual(await discoverDeepLocal(request, canonical(request, calls), rows => { raw.push(rows); }), []);
  assert.equal(raw[0][0][0].hops.at(-1)!.kind, 'unwrap');
  assert.equal(calls.length, 20);
  assert(calls.every(callback => callback.branches[0].hops.at(-1).kind === 'unwrap'));
  assert(calls.every(callback => callback.branches[0].hops[0].pool === request.pools[0]));
  assert.equal(request.pools[0].token0.chainId, 31338);
});

for (const id of ['v2-exact-in', 'v4-exact-in', 'mixed-exact-in']) test('published deep components use canonical callbacks for '+id, async () => {
  const fixture = cases.find(row => row.id === id)!;
  const request = { chainId: 1, source: fixture.tokenIn.address, target: fixture.tokenOut.address,
    amount: fixture.amount, pools: fixture.pools } as any;
  const raw: LocalCandidate[][] = [], calls: any[] = [];
  await discoverDeepLocal(request, canonical(request, calls), rows => { raw.push(rows); });
  assert(raw[0].length > 0);
  assert(calls.length >= 20);
  const executed = await replay(request, raw[0][0]);
  assert.equal(executed.amountIn, request.amount);
  assert(executed.fullyFilled && 'settled' in executed && executed.settled);
  assert(BigInt(executed.amountOut) > 0n);
});

test('hook and partial paths remain raw hints when canonical deep callbacks are unquotable', async () => {
  const fixture = cases.find(row => row.id === 'v4-exact-in')!;
  const pool = { ...fixture.pools[0], hooks: '0x'+'12'.repeat(20) };
  const request = { chainId: 1, source: fixture.tokenIn.address, target: fixture.tokenOut.address,
    amount: fixture.amount, pools: [pool] } as any;
  const raw: LocalCandidate[][] = [];
  let callbacks = 0;
  assert.deepEqual(await discoverDeepLocal(request, async callback => {
    callbacks++;
    assert.equal(callback.branches[0].hops[0].pool, pool);
    return { quote: null };
  }, rows => { raw.push(rows); }), []);
  assert.equal(raw[0].length, 1);
  assert.equal(raw[0][0][0].hops[0].pool, pool);
  assert.equal(callbacks, 20);
});

for (const amount of ['10001', '3']) test('percentage weights preserve runtime remainder for raw input '+amount, async () => {
  const request = asymmetric(amount);
  // A canonical callback can quote zero-funded percentages as zero. The
  // final adapter decides which actual funded split is useful, including dust.
  const split = await quoteLocalSplits(request, await discoverLocal(request), async callback => {
    const physical = callback.branches[0].hops[0].pool;
    const weight = physical.feePips === 500 ? 1n : 2n;
    return { quote: (BigInt(callback.amount)*weight).toString() };
  });
  const shape = split.find(candidate => candidate.map(branch => branch.amountIn).join(',') === '35,65')!;
  assert(shape);
  const funding = runtimeFunding(shape, amount);
  assert.deepEqual(funding, amount === '10001' ? [3500n, 6501n] : [1n, 2n]);
  assert.equal(funding.reduce((sum, value) => sum+value, 0n), BigInt(amount));
  assert(shape.every(branch => request.pools.includes(branch.hops[0].pool)));
  const executed = await replay(request, shape);
  assert.equal(executed.amountIn, amount);
  assert(executed.fullyFilled && 'settled' in executed && executed.settled);
});

test('ordinary callback failures retain early hints and other canonical percentages', async () => {
  const request = asymmetric();
  let calls = 0;
  const quote = canonical(request), raw: LocalCandidate[][] = [];
  const result = await discoverDeepLocal(request, async callback => {
    if (++calls === 1) throw new Error('ordinary callback unavailable');
    return quote(callback);
  }, rows => { raw.push(rows); });
  assert.equal(raw[0].length, 2);
  assert(result.length > 0);
  const partial: LocalCandidate[][] = [];
  assert.deepEqual(await discoverDeepLocal(request, async () => ({ quote: null }), rows => { partial.push(rows); }), []);
  assert.equal(partial[0].length, 2);
  const failed: LocalCandidate[][] = [];
  await assert.rejects(discoverDeepLocal(request, async () => { throw new Error('callback unavailable'); },
    rows => { failed.push(rows); }), /incomplete/);
  assert.equal(failed[0].length, 2);
});

test('finder-only comparison executes no canonical quote or split work', async () => {
  let callbacks = 0;
  const raw: LocalCandidate[][] = [];
  assert.deepEqual(await discoverDeepLocal(asymmetric(), async () => { callbacks++; throw new Error('unused'); },
    rows => { raw.push(rows); }, { finderOnly: true }), []);
  assert.equal(raw[0].length, 2);
  assert.equal(callbacks, 0);
});

test('actual JSONL worker sends early candidates and tracks canonical callback IDs', async () => {
  const request = asymmetric(), child = spawn(process.execPath,
    ['src/uniswap-sdk/uniroute-worker.ts', '--split-percentage=25'], { stdio: ['pipe', 'pipe', 'pipe'] });
  const lines = createInterface({ input: child.stdout });
  let early = false, terminal = false, callbacks = 0;
  const ids = new Set<string>();
  try {
    child.stdin.write(JSON.stringify({ ...request, id: 'worker-owned-query', blockNumber: BLOCK })+'\n');
    for await (const line of lines) {
      const frame = JSON.parse(line);
      assert.equal(frame.id, 'worker-owned-query');
      if (frame.operation === 'candidates') {
        assert.equal(callbacks, 0);
        assert.equal(frame.candidates.length, 2);
        early = true;
      } else if (frame.operation === 'quote') {
        assert(early);
        assert(!ids.has(frame.quoteId)); ids.add(frame.quoteId); callbacks++;
        const result = await canonical(request)(frame);
        child.stdin.write(JSON.stringify({ id: frame.id, operation: 'quoteResult', quoteId: frame.quoteId, result })+'\n');
      } else {
        assert(!frame.error);
        assert(frame.candidates.length > 0);
        terminal = true; break;
      }
    }
    assert(early && terminal);
    assert.equal(callbacks, 8);
  } finally {
    lines.close();
    const stopped = once(child, 'exit');
    child.kill();
    await stopped;
  }
});
