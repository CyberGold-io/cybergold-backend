import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { discoverLocal, LOCAL_CONFIG } from '../src/uniswap-sdk/uniroute-local.ts';

const require = createRequire(import.meta.url);
const { RouteFinder } = require('../vendor/uniroute-public/runtime/core/route/RouteFinder.js');
const A = '0x'+'1'.repeat(40), B = '0x'+'2'.repeat(40), C = '0x'+'3'.repeat(40), D = '0x'+'4'.repeat(40);
const ZERO = '0x'+'0'.repeat(40), WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2';
function pool(a: string, b: string, protocol: 'v2' | 'v3' | 'v4', chainId = 1) {
  const [left, right] = [a, b].sort();
  return { id: `${protocol}:${left}:${right}`, protocol, token0: { address: left, chainId },
    token1: { address: right, chainId }, feePips: 3000, tickSpacing: 60 };
}
function ids(candidate: any[]) { return candidate[0].hops.filter((hop: any) => hop.pool).map((hop: any) => hop.pool.id); }

test('local UniRoute executes the pinned unchanged source and reproducible compiler artifact', () => {
  const source = readFileSync(new URL('../vendor/uniroute-public/upstream/src/core/route/RouteFinder.ts', import.meta.url));
  assert.equal(createHash('sha256').update(source).digest('hex'), 'efe814f8d9b9f7040c154cb847698cb5df4ff194c122877cab0c71d9d7c1d744');
  execFileSync(process.execPath, ['vendor/uniroute-public/build-runtime.cjs', '--check']);
  assert.equal(LOCAL_CONFIG.RouteFinder.MaxHops, 3);
});

test('actual UniRoute finds mixed paths, preserves input references, and avoids cycles', async () => {
  const pools = [pool(A, B, 'v2'), pool(B, C, 'v3'), pool(C, A, 'v4')];
  const before = JSON.stringify(pools);
  const candidates = await discoverLocal({ chainId: 1, source: A, target: C, amount: '9007199254740993007', pools });
  assert(candidates.some(candidate => ids(candidate).join(',') === [pools[0].id, pools[1].id].join(',')));
  assert(candidates.some(candidate => ids(candidate).join(',') === pools[2].id));
  assert(candidates.every(candidate => new Set(ids(candidate)).size === ids(candidate).length));
  assert(candidates.every(candidate => candidate[0].amountIn === '9007199254740993007'));
  assert.equal(JSON.stringify(pools), before);
});

test('the published mixed-protocol switch and extended-hop pass remain executable', async () => {
  const pools = [pool(A, B, 'v2'), pool(B, C, 'v3'), pool(C, D, 'v3')].map(physical => ({
    protocol: physical.protocol, token0: { lowerCased: physical.token0.address }, token1: { lowerCased: physical.token1.address } }));
  const config = { RouteFinder: { MaxHops: 1, MaxHopsExtended: 3, MinRoutesThreshold: 2, MaxExtendedRoutes: 1 } };
  const finder = new RouteFinder(config);
  assert.deepEqual(await finder.generateRoutes(1, pools, { lowerCased: A }, { lowerCased: D }, false), []);
  const routes = await finder.generateRoutes(1, pools, { lowerCased: A }, { lowerCased: D }, true);
  assert.equal(routes.length, 1);
  assert.equal(routes[0].path.length, 3);
  assert.equal(routes[0].protocol, 'mixed');
});

test('three physical hops retain the existing bound and disconnected graphs stay empty', async () => {
  const pools = [pool(A, B, 'v3'), pool(B, C, 'v3'), pool(C, D, 'v3')];
  const requests = { chainId: 1, source: A, target: D, amount: '100', pools };
  assert.equal((await discoverLocal(requests)).length, 1);
  assert.deepEqual(await discoverLocal({ ...requests, target: '0x'+'5'.repeat(40) }), []);
});

for (const chainId of [1, 31338]) test(`actual-chain ${chainId} native transitions use no pool price or chain alias`, async () => {
  const request = { chainId, source: ZERO, target: C, amount: '123', pools: [pool(WETH, C, 'v3', chainId)] };
  const wrapped = await discoverLocal(request);
  assert.equal(wrapped[0][0].hops[0].kind, 'wrap');
  assert.equal(wrapped[0][0].hops[1].pool.token0.chainId, chainId);
  const reverse = await discoverLocal({ ...request, source: C, target: ZERO });
  assert.equal(reverse[0][0].hops.at(-1).kind, 'unwrap');
  const native = await discoverLocal({ ...request, pools: [pool(ZERO, A, 'v4', chainId), pool(WETH, C, 'v3', chainId)] });
  assert(native.some(candidate => candidate[0].hops.some((hop: any) => hop.kind === 'wrap')));
  assert(native.every(candidate => candidate[0].hops.filter((hop: any) => hop.pool).length <= 3));
});

for (const protocol of ['v3', 'v4'] as const) test(`native terminal projection keeps three ${protocol} pools with unrelated V4`, async () => {
  const unrelated = pool(D, '0x'+'5'.repeat(40), 'v4');
  const pools = [pool(A, B, protocol), pool(B, C, protocol), pool(C, WETH, protocol), unrelated];
  const candidates = await discoverLocal({ chainId: 31338, source: A, target: ZERO, amount: '123', pools });
  const selected = candidates.find(candidate => ids(candidate).join(',') === pools.slice(0, 3).map(value => value.id).join(','));
  assert(selected);
  assert.equal(selected[0].hops.at(-1).kind, 'unwrap');
  assert(candidates.every(candidate => ids(candidate).length <= 3));
  const signatures = candidates.map(candidate => JSON.stringify(candidate));
  assert.equal(new Set(signatures).size, signatures.length);
});

test('wrapped terminal projection restores native-to-WETH transition after three V4 pools', async () => {
  const pools = [pool(A, B, 'v4'), pool(B, C, 'v4'), pool(C, ZERO, 'v4')];
  const candidates = await discoverLocal({ chainId: 1, source: A, target: WETH, amount: '123', pools });
  const selected = candidates.find(candidate => ids(candidate).length === 3);
  assert(selected);
  assert.equal(selected[0].hops.at(-1).kind, 'wrap');
  assert(candidates.every(candidate => ids(candidate).length <= 3));
});

test('endpoint variants do not allow a fourth physical pool or adjacent identity wrapping', async () => {
  const E = '0x'+'5'.repeat(40);
  const pools = [pool(A, B, 'v4'), pool(B, C, 'v4'), pool(C, D, 'v4'), pool(D, WETH, 'v4')];
  assert.deepEqual(await discoverLocal({ chainId: 1, source: A, target: ZERO, amount: '123', pools }), []);
  const candidates = await discoverLocal({ chainId: 1, source: ZERO, target: E, amount: '123',
    pools: [pool(WETH, E, 'v3'), pool(ZERO, D, 'v4')] });
  assert.equal(candidates.length, 1);
  const hops = candidates[0][0].hops;
  assert.equal(hops[0].kind, 'wrap');
  assert(hops.every((hop: any, index: number) => !hop.kind || !hops[index + 1]?.kind));
});
