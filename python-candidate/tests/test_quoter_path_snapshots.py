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
    return {**deepcopy(pool), 'reserve0': '1000', 'reserve1': '1000', 'ticks': [], 'bitmapWords': []}


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
        return {**snapshot, 'ticks': [{'index': 120}], 'bitmapWords': [{'wordPosition': 7, 'bitmap': '1'}]}


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
