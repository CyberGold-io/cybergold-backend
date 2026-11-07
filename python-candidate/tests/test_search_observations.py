"""Search-owned reuse saves completed reads without retaining canonical facts."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock
import unittest

from cybergold_candidate.search_observations import search_observation_scope, current_search_observations
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
import test_latest_uniswap_state as fixtures
from test_latest_uniswap_state import pool, A, B


class SearchObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_getters_share_across_callbacks_but_not_searches(self):
        rpc, provider = fixtures.LatestGetterTests.rpc(self)
        async with search_observation_scope():
            self.assertEqual(await rpc.read_function(A, 'value()', [], [], ['uint256'], LATEST_BLOCK), (1,))
            provider.value = 2
            value = await asyncio.create_task(rpc.read_function(A, 'value()', [], [], ['uint256'], LATEST_BLOCK))
            self.assertEqual(value, (1,))
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(rpc.reads.completed, {})
        self.assertIsNone(current_search_observations())
        async with search_observation_scope():
            self.assertEqual(await rpc.read_function(A, 'value()', [], [], ['uint256'], LATEST_BLOCK), (2,))
        self.assertEqual(len(provider.calls), 2)

    async def test_decoded_success_is_owned_and_failure_does_not_replace_it(self):
        produce = AsyncMock(side_effect=[ValueError('ordinary failure'), {'rows': [1]}])
        async with search_observation_scope() as observations:
            with self.assertRaises(ValueError):
                await observations.read('same', produce)
            first = await observations.read('same', produce)
            first['rows'].append(2)
            self.assertEqual(await observations.read('same', produce), {'rows': [1]})
            self.assertEqual(produce.await_count, 2)

    async def test_one_cancelled_subscriber_does_not_cancel_another(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def produce():
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return 7
        async with search_observation_scope() as observations:
            first = asyncio.create_task(observations.read('same', produce))
            await entered.wait()
            second = asyncio.create_task(observations.read('same', produce))
            await asyncio.sleep(0)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            release.set()
            self.assertEqual(await second, 7)
            self.assertEqual(calls, 1)
        self.assertEqual(observations.reads.pending, {})

    async def test_snapshot_aliases_reuse_baseline_and_ticks_without_private_scalar_leak(self):
        registry, rpc, store = fixtures.LatestStateTests.registry(self)
        identity = pool()
        async with search_observation_scope() as observations:
            initial = await registry.snapshot(identity, LATEST_BLOCK)
            rpc.value = 200
            alias = {**deepcopy(identity), 'id': 'different-alias'}
            current = await registry.snapshot(alias, LATEST_BLOCK)
            self.assertEqual(current['id'], 'different-alias')
            self.assertEqual(current['liquidity'], '100')
            self.assertEqual(len(rpc.calls), 2)
            requested = [{'poolId': identity['id'], 'wordPositions': [1], 'ticks': [120]}]
            filled = await registry.extend_ticks(initial, requested, LATEST_BLOCK)
            count = len(rpc.calls)
            private = {**deepcopy(initial), 'liquidity': '999', 'tick': 200}
            replay = await registry.extend_ticks(private, requested, LATEST_BLOCK)
            self.assertEqual(len(rpc.calls), count)
            self.assertEqual((replay['liquidity'], replay['tick']), ('999', 200))
            baseline = next(iter(observations.pool_states.values()))
            self.assertEqual((baseline['liquidity'], baseline['tick']), ('100', 0))
            self.assertEqual(replay['ticks'], filled['ticks'])
            self.assertEqual(initial['ticks'], [])
        next_search = await registry.snapshot(identity, LATEST_BLOCK)
        self.assertEqual(next_search['liquidity'], '200')
        self.assertEqual(registry.observed, {})
        store.save.assert_not_called()

    async def test_latest_coverage_replacement_keeps_baseline_scalars_metadata_and_rows_independent(self):
        for prior_coverage in (False, True):
            with self.subTest(prior_coverage=prior_coverage):
                registry, rpc, store = fixtures.LatestStateTests.registry(self)
                async with search_observation_scope() as observations:
                    initial = await registry.snapshot(pool(), LATEST_BLOCK)
                    key, = observations.pool_states
                    baseline = deepcopy(initial)
                    baseline['nestedUnknown'] = {'rows':[{'value':'baseline metadata'}]}
                    if prior_coverage:
                        baseline['ticks'] = [{'index':0,'liquidityGross':'7','liquidityNet':'3','extraScalar':True}]
                        baseline['bitmapWords'] = [{'wordPosition':0,'bitmap':'1','extraScalar':None}]
                    else:
                        baseline.pop('ticks', None)
                        baseline.pop('bitmapWords', None)
                    observations.pool_states[key] = baseline
                    private = deepcopy(baseline)
                    private.update(liquidity='999', tick=200)
                    private['nestedUnknown']['rows'][0]['value'] = 'private metadata'
                    private.setdefault('ticks', []).append(
                        {'index':120,'liquidityGross':'9','liquidityNet':'-2','extraScalar':'keep tick'})
                    private.setdefault('bitmapWords', []).append(
                        {'wordPosition':1,'bitmap':'2','extraScalar':'keep word'})
                    before = deepcopy(baseline)
                    calls = len(rpc.calls)
                    result = await registry.extend_ticks(private, [], LATEST_BLOCK)
                    retained = observations.pool_states[key]
                    self.assertEqual(len(rpc.calls), calls)
                    self.assertEqual((result['liquidity'],result['tick']), ('999',200))
                    self.assertEqual((retained['liquidity'],retained['tick']),
                                     (baseline['liquidity'],baseline['tick']))
                    self.assertEqual(baseline, before)
                    self.assertEqual(list(retained), list({**baseline,'bitmapWords':[],'ticks':[]}))
                    for field in ('ticks','bitmapWords'):
                        self.assertEqual(retained[field], result[field])
                        self.assertEqual(result[field], private[field])
                    self.assertEqual(retained['nestedUnknown'], before['nestedUnknown'])
                    records = [private, result, retained]
                    for index, record in enumerate(records):
                        record['nestedUnknown']['rows'][0]['value'] = str(index)
                        record['ticks'][-1]['extraScalar'] = index
                        record['bitmapWords'][-1]['extraScalar'] = index
                    self.assertEqual([row['nestedUnknown']['rows'][0]['value'] for row in records], ['0','1','2'])
                    self.assertEqual([row['ticks'][-1]['extraScalar'] for row in records], [0,1,2])
                    self.assertEqual([row['bitmapWords'][-1]['extraScalar'] for row in records], [0,1,2])
                    self.assertEqual(baseline, before)
                store.save.assert_not_called()

    async def test_concurrent_disjoint_coverage_is_reused_together(self):
        registry, rpc, _ = fixtures.LatestStateTests.registry(self)
        ordinary = rpc.read_function
        entered, release = set(), asyncio.Event()
        async def read(address, signature, types, args, outputs, block):
            if signature.startswith('tickBitmap('):
                entered.add(args[0])
                if len(entered) == 2:
                    release.set()
                await release.wait()
            return await ordinary(address, signature, types, args, outputs, block)
        rpc.read_function = read
        async with search_observation_scope():
            initial = await registry.snapshot(pool(), LATEST_BLOCK)
            await asyncio.wait_for(asyncio.gather(*(registry.extend_ticks(initial,
                [{'poolId': initial['id'], 'wordPositions': [word], 'ticks': []}], LATEST_BLOCK)
                for word in (1, 2))), 1)
            count = len(rpc.calls)
            both = await registry.extend_ticks(initial,
                [{'poolId': initial['id'], 'wordPositions': [1, 2], 'ticks': []}], LATEST_BLOCK)
            self.assertEqual({row['wordPosition'] for row in both['bitmapWords']}, {1, 2})
            self.assertEqual(len(rpc.calls), count)

    async def test_scalar_reads_finish_without_awaiting_display_metadata(self):
        registry, rpc, _ = fixtures.LatestStateTests.registry(self)
        release, scalars = asyncio.Event(), asyncio.Event()
        ordinary = rpc.read_function
        async def read(*args):
            if args[1] == 'liquidity()':
                scalars.set()
            return await ordinary(*args)
        rpc.read_function = read
        async def metadata(address, block):
            await release.wait()
            return registry.token(address, 18)
        registry.token_metadata = AsyncMock(side_effect=metadata)
        identity = pool()
        for token in (identity['token0'], identity['token1']):
            token['decimals'] = None
        task = asyncio.create_task(registry.snapshot(identity, LATEST_BLOCK))
        try:
            await asyncio.wait_for(scalars.wait(), 1)
            self.assertEqual((await asyncio.wait_for(asyncio.shield(task), 1))['liquidity'], '100')
            registry.token_metadata.assert_not_awaited()
        finally:
            release.set()
            result = await task
        self.assertEqual(result['liquidity'], '100')

    async def test_unresolved_v2_identity_resolves_only_on_snapshot(self):
        registry, rpc, _ = fixtures.LatestStateTests.registry(self)
        rpc.v2_factory = A
        ordinary = rpc.read_function
        async def read(address, signature, types, args, outputs, block):
            if signature == 'getPair(address,address)':
                rpc.calls.append((signature, args, block))
                return (B,)
            return await ordinary(address, signature, types, args, outputs, block)
        rpc.read_function = read
        identity = pool('v2')
        del identity['address']
        self.assertEqual(rpc.calls, [])
        async with search_observation_scope():
            first = await registry.snapshot(identity, LATEST_BLOCK)
            resolved = await registry.snapshot(pool('v2'), LATEST_BLOCK)
            self.assertEqual(first['address'], B)
            self.assertEqual(resolved['reserve0'], first['reserve0'])
            self.assertEqual([row[0] for row in rpc.calls], ['getPair(address,address)', 'getReserves()'])

    async def test_distinct_physical_addresses_do_not_share_scalar_snapshots(self):
        registry, rpc, _ = fixtures.LatestStateTests.registry(self)
        first_pool = pool()
        other_pool = {**deepcopy(first_pool), 'address': A}
        async with search_observation_scope():
            first = await registry.snapshot(first_pool, LATEST_BLOCK)
            rpc.value = 200
            other = await registry.snapshot(other_pool, LATEST_BLOCK)
            self.assertEqual((first['liquidity'], other['liquidity']), ('100', '200'))
            self.assertEqual((await registry.snapshot(first_pool, LATEST_BLOCK))['liquidity'], '100')
            self.assertEqual(len(rpc.calls), 4)


if __name__ == '__main__':
    unittest.main()
