"""Concurrent immutable path reads retain ordered private SDK replay ownership."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.quoter.amm import price_path
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.route_work_slots import CandidateWork, run_candidate
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.uniswap_routes import pool_identity


A, B, C, D = ('0x'+format(index, '040x') for index in range(1, 5))
BLOCK = {'number': 101, 'hash': '0x'+'ab'*32}


def pool(a, b, number):
    return {'id': f'pool-{number}', 'protocol': 'v2', 'address': '0x'+format(number, '040x'),
            'token0': {'address': a, 'chainId': 31338, 'decimals': 18},
            'token1': {'address': b, 'chainId': 31338, 'decimals': 18}}


def state(pool):
    return {**deepcopy(pool), 'reserve0': '1000', 'reserve1': '1000', 'tick': pool.get('tick', 0),
            'ticks': [], 'bitmapWords': []}


def concentrated(a, b, number, protocol='v3', tick=0, spacing=60):
    return {**pool(a, b, number), 'protocol': protocol, 'tick': tick, 'tickSpacing': spacing,
            'feePips': 3000, 'hooks': '0x'+'00'*20, 'poolManager': D}


class Registry:
    def __init__(self, pools):
        self.inventory = {row['id']: deepcopy(row) for row in pools}
        self.pending = SharedReads()
        self.calls, self.started, self.release, self.drained, self.failures = [], {}, {}, {}, {}
        self.extended = []
        for row in pools:
            key = pool_identity(row)
            self.started[key], self.release[key], self.drained[key] = (asyncio.Event() for _ in range(3))

    async def snapshot(self, pool, block):
        key = pool_identity(pool)
        self.calls.append(pool['id'])
        self.started[key].set()
        try:
            await self.release[key].wait()
            if key in self.failures:
                raise self.failures[key]
            return state(pool)
        finally:
            self.drained[key].set()

    async def extend_ticks(self, snapshot, requests, block):
        self.extended.append(deepcopy(requests))
        ticks = {int(row['index']): row for row in snapshot.get('ticks', [])}
        words = {int(row['wordPosition']): row for row in snapshot.get('bitmapWords', [])}
        for request in requests:
            ticks.update({int(index): {'index': int(index)} for index in request.get('ticks', [])})
            words.update({int(word): {'wordPosition': int(word), 'bitmap': '1'}
                          for word in request.get('wordPositions', [])})
        return {**snapshot, 'ticks': list(ticks.values()), 'bitmapWords': list(words.values())}


class SDK:
    def __init__(self):
        self.calls, self.entered = [], asyncio.Event()
        self.zero = False
        self.missing = None

    async def request(self, payload, on_state=None):
        self.calls.append(deepcopy(payload))
        self.entered.set()
        if self.missing:
            await on_state(self.missing)
        current, amount = payload['pools'][0], int(payload['amount'])
        return {'amountIn': str(amount), 'amountOut': '0' if self.zero else str(2*amount),
                'fullyFilled': True, 'settled': True,
                'postState': [{'id': current['id'], 'reserve0': str(int(current['reserve0'])+amount)}]}

    async def close(self):
        pass


class OrderedPathSnapshots(unittest.IsolatedAsyncioTestCase):
    def setup_path(self, pools=None):
        pools = pools or [pool(A, B, 10), pool(B, C, 11)]
        registry, sdk = Registry(pools), SDK()
        engine = RouteQuoteEngine(SimpleNamespace(), registry, sdk=sdk)
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.pending.close)
        route = [{'pool': deepcopy(row), 'zeroForOne': True} for row in pools]
        return engine, registry, sdk, route

    async def started(self, registry):
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in registry.started.values())), 1)

    async def test_later_read_starts_before_first_replay_without_blocking_first_hop(self):
        engine, registry, sdk, route = self.setup_path()
        bank, canonical = {}, {}
        task = asyncio.create_task(price_path(engine, route, 10, BLOCK, bank, canonical))
        try:
            await self.started(registry)
            first, second = [pool_identity(hop['pool']) for hop in route]
            registry.release[first].set()
            await asyncio.wait_for(sdk.entered.wait(), 1)
            self.assertEqual(len(sdk.calls), 1)
            self.assertEqual(list(canonical), [route[0]['pool']['id']])
            self.assertFalse(registry.release[second].is_set())
            registry.release[second].set()
            self.assertEqual(await task, (10, 40))
            self.assertEqual([row['amount'] for row in sdk.calls], ['10', '20'])
            self.assertEqual(len(registry.calls), 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_initial_read_errors_are_consumed_in_route_order(self):
        engine, registry, sdk, route = self.setup_path()
        first, second = [pool_identity(hop['pool']) for hop in route]
        registry.failures = {first: RuntimeError('first route read'), second: RuntimeError('later route read')}
        task = asyncio.create_task(price_path(engine, route, 10, BLOCK, {}, {}))
        await self.started(registry)
        registry.release[second].set()
        await registry.drained[second].wait()
        self.assertFalse(task.done())
        registry.release[first].set()
        with self.assertRaisesRegex(RuntimeError, 'first route read'):
            await task
        self.assertEqual(sdk.calls, [])

    async def test_unused_failed_tail_does_not_reject_zero_output(self):
        engine, registry, sdk, route = self.setup_path()
        sdk.zero = True
        second = pool_identity(route[1]['pool'])
        registry.failures[second] = RuntimeError('unused tail')
        for event in registry.release.values():
            event.set()
        self.assertEqual(await price_path(engine, route, 10, BLOCK, {}, {}), (10, 0))
        self.assertEqual(len(sdk.calls), 1)

    async def test_unused_tail_disproof_outranks_zero_output(self):
        engine, registry, sdk, route = self.setup_path()
        sdk.zero = True
        registry.failures[pool_identity(route[1]['pool'])] = SnapshotChanged('unused tail disproof')
        for event in registry.release.values():
            event.set()
        with self.assertRaisesRegex(SnapshotChanged, 'unused tail disproof'):
            await price_path(engine, route, 10, BLOCK, {}, {})

    async def test_owned_cancellation_drains_all_snapshot_subscriptions(self):
        engine, registry, sdk, route = self.setup_path()
        task = asyncio.create_task(price_path(engine, route, 10, BLOCK, {}, {}))
        await self.started(registry)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(all(event.is_set() for event in registry.drained.values()))
        self.assertEqual(sdk.calls, [])

    async def test_waiting_initial_path_state_releases_parent_scheduler_capacity(self):
        engine, registry, sdk, route = self.setup_path()
        slots, changed = asyncio.Semaphore(1), asyncio.Event()
        await slots.acquire()
        lease = CandidateWork(slots, changed)
        async def evaluate(*_):
            return await price_path(engine, route, 10, BLOCK, {}, {})
        task = asyncio.create_task(run_candidate(lease, evaluate, 0, None))
        await self.started(registry)
        self.assertEqual(slots._value, 1)
        self.assertEqual(engine.semaphore._value, 8)
        for event in registry.release.values():
            event.set()
        self.assertEqual(await task, (10, 40))
        self.assertEqual(slots._value, 1)
        self.assertEqual(engine.semaphore._value, 8)

    async def test_cancelling_one_path_keeps_another_subscriber_on_shared_pool_read(self):
        engine, registry, sdk, route = self.setup_path()
        snapshot = registry.snapshot
        async def shared(pool, block):
            return await registry.pending.one(pool_identity(pool), lambda: snapshot(pool, block))
        registry.snapshot = shared
        whole = asyncio.create_task(price_path(engine, route, 10, BLOCK, {}, {}))
        prefix = asyncio.create_task(price_path(engine, route[:1], 10, BLOCK, {}, {}))
        await self.started(registry)
        first, second = [pool_identity(hop['pool']) for hop in route]
        whole.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await whole
        self.assertFalse(registry.drained[first].is_set())
        self.assertTrue(registry.drained[second].is_set())
        registry.release[first].set()
        self.assertEqual(await prefix, (10, 20))
        self.assertEqual(registry.calls.count(route[0]['pool']['id']), 1)

    async def test_later_owned_disproof_survives_cancellation_of_blocked_first_read(self):
        engine, registry, sdk, route = self.setup_path()
        second = pool_identity(route[1]['pool'])
        registry.failures[second] = SnapshotChanged('later owned context')
        task = asyncio.create_task(price_path(engine, route, 10, BLOCK, {}, {}))
        await self.started(registry)
        registry.release[second].set()
        await registry.drained[second].wait()
        task.cancel()
        with self.assertRaisesRegex(SnapshotChanged, 'later owned context'):
            await task
        self.assertTrue(all(event.is_set() for event in registry.drained.values()))

    async def test_aliases_repeated_pool_and_native_hops_keep_private_state_ordered(self):
        known = pool(A, B, 10)
        engine, registry, sdk, _ = self.setup_path([known])
        first, second = deepcopy(known), deepcopy(known)
        first['id'], second['id'] = 'first-alias', 'second-alias'
        route = [{'kind': 'wrap', 'currencyOut': A}, {'pool': first, 'zeroForOne': True},
                 {'pool': second, 'zeroForOne': False}, {'kind': 'unwrap', 'currencyOut': B}]
        private = {**state(known), 'id': 'private-alias', 'reserve0': '700'}
        bank, canonical = {'private-alias': private}, {}
        registry.release[pool_identity(known)].set()
        self.assertEqual(await price_path(engine, route, 10, BLOCK, bank, canonical), (10, 40))
        self.assertEqual(registry.calls, [known['id']])
        self.assertEqual([row['pools'][0]['reserve0'] for row in sdk.calls], ['700', '710'])
        self.assertEqual(canonical[known['id']]['reserve0'], '1000')
        self.assertEqual(list(bank), [known['id']])

    async def test_concurrent_canonical_coverage_is_not_replaced_by_prefetch(self):
        engine, registry, sdk, route = self.setup_path()
        first, second = [pool_identity(hop['pool']) for hop in route]
        canonical = {}
        task = asyncio.create_task(price_path(engine, route, 10, BLOCK, {}, canonical))
        await self.started(registry)
        registry.release[second].set()
        await registry.drained[second].wait()
        chosen = {**state(route[1]['pool']), 'reserve0': '2500',
                  'ticks': [{'index': 77}], 'bitmapWords': [{'wordPosition': 8, 'bitmap': '2'}]}
        canonical[chosen['id']] = deepcopy(chosen)
        registry.release[first].set()
        self.assertEqual(await task, (10, 40))
        self.assertEqual(sdk.calls[1]['pools'][0], chosen)
        self.assertEqual(canonical[chosen['id']], chosen)

    async def test_initial_fanout_does_not_predict_dynamic_tick_requests(self):
        engine, registry, sdk, route = self.setup_path([pool(A, B, 10)])
        sdk.missing = [{'poolId': route[0]['pool']['id'], 'wordPositions': [7], 'ticks': [120]}]
        registry.release[pool_identity(route[0]['pool'])].set()
        await price_path(engine, route, 10, BLOCK, {}, {})
        self.assertEqual(sdk.calls[0]['pools'][0]['ticks'], [])
        self.assertEqual(registry.extended, [sdk.missing])

    async def test_first_bitmap_words_follow_sdk_floor_and_direction_for_v3_and_v4(self):
        for protocol in ('v3', 'v4'):
            for tick, direction, expected in [(-1, True, -1), (-1, False, 0),
                                               (15300, True, 0), (15300, False, 1)]:
                with self.subTest(protocol=protocol, tick=tick, direction=direction):
                    current = concentrated(A, B, 10, protocol, tick)
                    engine, registry, sdk, route = self.setup_path([current])
                    route[0]['zeroForOne'] = direction
                    registry.release[pool_identity(current)].set()
                    await price_path(engine, route, 10, BLOCK, {}, {})
                    self.assertEqual(registry.extended, [[{
                        'poolId': current['id'], 'wordPositions': [expected], 'ticks': []}]])
                    self.assertEqual(sdk.calls[0]['pools'][0]['bitmapWords'],
                                     [{'wordPosition': expected, 'bitmap': '1'}])

    async def test_each_later_pool_first_word_starts_before_first_word_finishes(self):
        pools = [concentrated(A, B, 10), concentrated(B, C, 11, 'v4')]
        engine, registry, sdk, route = self.setup_path(pools)
        entered = {row['id']: asyncio.Event() for row in pools}
        release = {row['id']: asyncio.Event() for row in pools}
        extend = registry.extend_ticks
        async def blocked(snapshot, requests, block):
            entered[snapshot['id']].set()
            await release[snapshot['id']].wait()
            return await extend(snapshot, requests, block)
        registry.extend_ticks = blocked
        for event in registry.release.values():
            event.set()
        task = asyncio.create_task(price_path(engine, route, 10, BLOCK, {}, {}))
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered.values())), 1)
            self.assertEqual(sdk.calls, [])
            release[pools[0]['id']].set()
            await asyncio.wait_for(sdk.entered.wait(), 1)
            self.assertEqual(len(sdk.calls), 1)
            release[pools[1]['id']].set()
            self.assertEqual(await task, (10, 40))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_repeated_alias_preserves_private_tick_and_demands_later_word_exactly(self):
        current = concentrated(A, B, 10, tick=15300)
        engine, registry, sdk, _ = self.setup_path([current])
        alias = {**deepcopy(current), 'id': 'other-alias'}
        route = [{'pool': current, 'zeroForOne': True}, {'pool': alias, 'zeroForOne': False}]
        original = sdk.request
        async def request(payload, on_state=None):
            if sdk.calls:
                self.assertEqual(payload['pools'][0]['tick'], 15360)
                self.assertEqual(payload['pools'][0]['bitmapWords'], [{'wordPosition': 0, 'bitmap': '1'}])
                await on_state([{'poolId': current['id'], 'wordPositions': [1], 'ticks': [15420]}])
            value = await original(payload, on_state)
            value['postState'][0]['tick'] = 15360
            return value
        sdk.request = request
        registry.release[pool_identity(current)].set()
        bank, canonical = {}, {}
        self.assertEqual(await price_path(engine, route, 10, BLOCK, bank, canonical), (10, 40))
        self.assertEqual(registry.calls, [current['id']])
        self.assertEqual([rows[0]['wordPositions'] for rows in registry.extended], [[0], [1]])
        self.assertEqual(bank[current['id']]['tick'], 15360)
        self.assertEqual(canonical[current['id']]['tick'], 15300)

    async def test_prefetched_coverage_fills_existing_private_state_without_replacing_scalars(self):
        current = concentrated(A, B, 10, tick=0)
        engine, registry, sdk, route = self.setup_path([current])
        registry.release[pool_identity(current)].set()
        private = {**state(current), 'tick': 15360, 'reserve0': '700'}
        bank = {current['id']: private}
        await price_path(engine, route, 10, BLOCK, bank, {})
        self.assertEqual(sdk.calls[0]['pools'][0]['tick'], 15360)
        self.assertEqual(sdk.calls[0]['pools'][0]['reserve0'], '700')
        self.assertEqual(sdk.calls[0]['pools'][0]['bitmapWords'], [{'wordPosition': 0, 'bitmap': '1'}])

    async def test_ordinary_first_word_failure_keeps_sdk_demand_fallback(self):
        current = concentrated(A, B, 10)
        engine, registry, sdk, route = self.setup_path([current])
        extend = registry.extend_ticks
        attempts = []
        async def flaky(snapshot, requests, block):
            attempts.append(deepcopy(requests))
            if len(attempts) == 1:
                raise OSError('advisory read failed')
            return await extend(snapshot, requests, block)
        registry.extend_ticks = flaky
        sdk.missing = [{'poolId': current['id'], 'wordPositions': [0], 'ticks': []}]
        registry.release[pool_identity(current)].set()
        self.assertEqual(await price_path(engine, route, 10, BLOCK, {}, {}), (10, 20))
        self.assertEqual(attempts, [sdk.missing, sdk.missing])

    async def test_ordinary_first_word_failure_does_not_reject_unused_word(self):
        current = concentrated(A, B, 10)
        engine, registry, sdk, route = self.setup_path([current])
        sdk.zero = True
        async def unavailable(*_):
            raise OSError('unused first word unavailable')
        registry.extend_ticks = unavailable
        registry.release[pool_identity(current)].set()
        self.assertEqual(await price_path(engine, route, 10, BLOCK, {}, {}), (10, 0))

    async def test_cancellation_during_first_word_reads_drains_all_owned_subscriptions(self):
        pools = [concentrated(A, B, 10), concentrated(B, C, 11, 'v4')]
        engine, registry, sdk, route = self.setup_path(pools)
        entered = {row['id']: asyncio.Event() for row in pools}
        drained = {row['id']: asyncio.Event() for row in pools}
        async def blocked(snapshot, *_):
            entered[snapshot['id']].set()
            try:
                await asyncio.Event().wait()
            finally:
                drained[snapshot['id']].set()
        registry.extend_ticks = blocked
        for event in registry.release.values():
            event.set()
        task = asyncio.create_task(price_path(engine, route, 10, BLOCK, {}, {}))
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered.values())), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(all(event.is_set() for event in drained.values()))
        self.assertEqual(sdk.calls, [])

    async def test_bitmap_prefetch_preserves_concurrently_selected_canonical_coverage(self):
        current = concentrated(A, B, 10)
        engine, registry, sdk, route = self.setup_path([current])
        entered, release = asyncio.Event(), asyncio.Event()
        extend = registry.extend_ticks
        async def blocked(snapshot, requests, block):
            entered.set()
            await release.wait()
            return await extend(snapshot, requests, block)
        registry.extend_ticks = blocked
        registry.release[pool_identity(current)].set()
        canonical = {}
        task = asyncio.create_task(price_path(engine, route, 10, BLOCK, {}, canonical))
        await asyncio.wait_for(entered.wait(), 1)
        chosen = {**state(current), 'reserve0': '2500', 'ticks': [{'index': 77}],
                  'bitmapWords': [{'wordPosition': 0, 'bitmap': '2'}, {'wordPosition': 8, 'bitmap': '3'}]}
        canonical[current['id']] = deepcopy(chosen)
        release.set()
        self.assertEqual(await task, (10, 20))
        self.assertEqual(sdk.calls[0]['pools'][0], chosen)
        self.assertEqual(canonical[current['id']], chosen)

    async def test_unused_bitmap_disproof_survives_zero_output_and_owned_drain(self):
        pools = [pool(A, B, 10), concentrated(B, C, 11)]
        engine, registry, sdk, route = self.setup_path(pools)
        sdk.zero = True
        async def disproved(*_):
            raise SnapshotChanged('first bitmap disproved')
        registry.extend_ticks = disproved
        for event in registry.release.values():
            event.set()
        with self.assertRaisesRegex(SnapshotChanged, 'first bitmap disproved'):
            await price_path(engine, route, 10, BLOCK, {}, {})

    async def test_same_route_identity_with_different_observed_address_does_not_supply_state(self):
        wanted = {**pool(A, B, 10), 'protocol': 'v3', 'feePips': 500}
        engine, registry, sdk, route = self.setup_path([wanted])
        decoy = {**state(wanted), 'id': 'other-address', 'address': D, 'reserve0': '9999'}
        registry.release[pool_identity(wanted)].set()
        await price_path(engine, route, 10, BLOCK, {}, {'other-address': decoy})
        self.assertEqual(registry.calls, [wanted['id']])
        self.assertEqual(sdk.calls[0]['pools'][0]['reserve0'], '1000')

    async def test_zero_funding_starts_no_snapshot(self):
        engine, registry, sdk, route = self.setup_path()
        self.assertEqual(await price_path(engine, route, 0, BLOCK, {}, {}), (0, 0))
        self.assertEqual((registry.calls, sdk.calls), ([], []))


if __name__ == '__main__':
    unittest.main()
