"""Real worker pipes, shared computation and exhaustive ordered controls."""
import asyncio
from copy import deepcopy
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cybergold_candidate.quoter.cpu import CpuWorkers
from cybergold_candidate.quoter.cooperative import CHECKPOINT, async_finish, async_values, finish
from cybergold_candidate.quoter.discovery import TopologyCache, paths, path_steps, topology_scope
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope, _quick_offers
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteTool, round_robin, lazy_round_robin
from cybergold_candidate.quoter import amm_adapter
from cybergold_candidate.routing_encoding import ZERO
from cybergold_candidate.route_search import WETH
from test_quoter_topology_reuse import A, B, C, BLOCK, pool


def exhaustive(pools, source, target, limit):
    """Independent small-graph oracle, including zero-cost native transitions."""
    found = []
    def visit(current, visited, route, hops):
        if current == target:
            if route:
                found.append(route)
            return
        if hops < limit:
            for row in pools:
                if row.get('hooks', ZERO) != ZERO:
                    continue
                a, b = row['token0']['address'].lower(), row['token1']['address'].lower()
                if current not in (a, b):
                    continue
                other = b if current == a else a
                if other not in visited:
                    visit(other, visited | {other}, route + [{'pool': row,
                          'zeroForOne': current == a}], hops + 1)
        if current in (ZERO, WETH.lower()):
            other = WETH.lower() if current == ZERO else ZERO
            if other not in visited:
                visit(other, visited | {other}, route + [{'kind': 'wrap' if current == ZERO
                      else 'unwrap', 'currencyOut': other}], hops)
    source, target = source.lower(), target.lower()
    visit(source, {source}, [], 0)
    return sorted(found, key=lambda route: (len(route), repr(route)))


class DiscoveryCpuTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cpu = CpuWorkers()
        self.addAsyncCleanup(self.cpu.close)
        await self.cpu.start()

    async def test_reverse_distance_preserves_exhaustive_order_native_and_hop_limits(self):
        rng = random.Random(20261114)
        tokens = [ZERO, WETH, A, B, C]
        edges = [(a, b) for i, a in enumerate(tokens) for b in tokens[i+1:]]
        for case in range(40):
            rows = [pool(a, b, index+10, 'v3', 100+index)
                    for index, (a, b) in enumerate(rng.sample(edges, rng.randrange(len(edges))))]
            if rows and case % 3 == 0:
                rows[0]['hooks'] = '0x'+'99'*20
            source, target = rng.sample(tokens, 2)
            cache = TopologyCache(cpu=self.cpu)
            self.addAsyncCleanup(cache.close)
            with topology_scope(cache):
                for limit in (0, 1, 2, 3):
                    expected = exhaustive(rows, source, target, limit)
                    self.assertEqual(paths(rows, source, target, max_hops=limit), expected)
                    cache.walks.clear()
                    cache.pending.clear()
                    self.assertEqual(await async_finish(path_steps(rows, source, target,
                                                                  max_hops=limit)), expected)

    async def test_concurrent_misses_share_one_build_and_rebind_current_metadata(self):
        rows = [pool(A, B, index+10, 'v3', 100+index) for index in range(8)]
        cache = TopologyCache(cpu=self.cpu)
        self.addAsyncCleanup(cache.close)
        with topology_scope(cache):
            results = await asyncio.gather(*(async_finish(path_steps(rows, A, B)) for _ in range(12)))
            self.assertEqual(cache.graph_builds, 1)
            self.assertTrue(all(result == exhaustive(rows, A, B, 3) for result in results))
            results[0][0][0]['zeroForOne'] = False
            rows[0]['token0']['symbol'] = 'new metadata'
            rebound = await async_finish(path_steps(rows, A, B))
            self.assertEqual(rebound, exhaustive(rows, A, B, 3))
            self.assertIs(rebound[0][0]['pool'], rows[0])
            self.assertNotIn('new metadata', repr(cache.walks))

    async def test_full_pipeline_matches_sync_with_projection_splits_and_private_bodies(self):
        rows = [pool(A, B, index+10, 'v3', 100+index) for index in range(3)]
        registry = SimpleNamespace(inventory={row['id']: row for row in rows}, seed=rows[-1])
        amm = CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)
        for options in ({}, {'first': True}, {'market': True}, {'linear_only': True}):
            expected = list(amm.nominations(A, B, 101, BLOCK, **options))
            session = RouteBootstrap([CustomRoutes(registry)], catalog=registry, cpu=self.cpu)
            try:
                with bootstrap_scope(session):
                    outputs = await asyncio.gather(*(
                        self.collect(amm.async_nominations(A, B, 101, BLOCK, **options)) for _ in range(3)))
                    self.assertTrue(all(output == expected for output in outputs))
                    saved = deepcopy(outputs[1])
                    if outputs[0]:
                        outputs[0][0][0][0]['hops'][0]['zeroForOne'] = 'private mutation'
                    self.assertEqual(outputs[1], saved)
            finally:
                await session.close()

    @staticmethod
    async def collect(iterator):
        return [row async for row in iterator]

    async def test_reader_cancellation_keeps_shared_job_and_owner_close_stops_it(self):
        # Acquire both real processes so submitted graph jobs remain pending.
        workers = [await self.cpu.available.get() for _ in range(2)]
        cache = TopologyCache(cpu=self.cpu)
        rows = [pool(A, B, 10, 'v3')]
        with topology_scope(cache):
            first = asyncio.create_task(async_finish(path_steps(rows, A, B)))
            second = asyncio.create_task(async_finish(path_steps(rows, A, B)))
            await asyncio.sleep(0)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            self.assertFalse(second.done())
            for worker in workers:
                self.cpu.available.put_nowait(worker)
            self.assertEqual(await second, exhaustive(rows, A, B, 3))
        await cache.close()
        self.assertFalse(cache.tasks)
        self.assertFalse(cache.walks)
        self.assertFalse(self.cpu.jobs)

    async def test_processes_are_reused_and_close_reaps_them(self):
        processes = [worker.process for worker in self.cpu.workers]
        for _ in range(2):
            await self.cpu.paths([pool(A, B, 10, 'v3')], A, B, WETH, 3)
        self.assertEqual([worker.process for worker in self.cpu.workers], processes)
        await self.cpu.close()
        self.assertTrue(all(process.returncode is not None for process in processes))

    async def test_owner_cancellation_reaps_active_worker_and_pool_recovers(self):
        processes = [worker.process for worker in self.cpu.workers]
        rows = [pool(A, B, 10, 'v3')]
        cache = TopologyCache(cpu=self.cpu)
        with topology_scope(cache):
            reader = asyncio.create_task(async_finish(path_steps(rows, A, B)))
            while not self.cpu.jobs:
                await asyncio.sleep(0)
            reader.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await reader
            await cache.close()
        self.assertTrue(any(process.returncode is not None for process in processes))
        self.assertFalse(self.cpu.jobs)
        self.assertTrue(await self.cpu.paths(rows, A, B, WETH, 3))

    async def test_child_error_is_reported_reaped_and_does_not_poison_next_job(self):
        row = pool(A, B, 10, 'v3')
        del row['id']
        processes = [worker.process for worker in self.cpu.workers]
        with self.assertRaises(ValueError):
            await self.cpu.paths([row], A, B, WETH, 3)
        self.assertTrue(any(process.returncode is not None for process in processes))
        self.assertTrue(await self.cpu.paths([pool(A, B, 10, 'v3')], A, B, WETH, 3))

    async def test_pool_close_cancels_active_and_queued_jobs(self):
        rows = [pool(A, B, 10, 'v3')]
        workers = [await self.cpu.available.get() for _ in range(2)]
        tasks = [asyncio.create_task(self.cpu.paths(rows, A, B, WETH, 3)) for _ in range(3)]
        await asyncio.sleep(0)
        await self.cpu.close()
        self.assertTrue(all(task.cancelled() for task in tasks))
        self.assertFalse(self.cpu.jobs)
        for worker in workers:
            self.cpu.available.put_nowait(worker)

    async def test_failed_shared_computation_can_be_retried_without_catalog_change(self):
        real, calls = self.cpu, []
        class OnceUnavailable:
            async def paths(self, *args):
                calls.append(True)
                if len(calls) == 1:
                    raise ValueError('temporary worker failure')
                return await real.paths(*args)
        rows = [pool(A, B, 10, 'v3')]
        cache = TopologyCache(cpu=OnceUnavailable())
        self.addAsyncCleanup(cache.close)
        with topology_scope(cache):
            with self.assertRaises(ValueError):
                await async_finish(path_steps(rows, A, B))
            self.assertEqual(await async_finish(path_steps(rows, A, B)), exhaustive(rows, A, B, 3))
        self.assertEqual(len(calls), 2)

    async def test_failed_optional_cpu_feed_does_not_discard_valid_sibling(self):
        real, calls = self.cpu, []
        class OnceUnavailable:
            async def paths(self, *args):
                calls.append(True)
                if len(calls) == 1:
                    raise ValueError('temporary worker failure')
                return await real.paths(*args)
        row = pool(A, B, 10, 'v3')
        class Ready(RouteTool):
            name = 'ready-sibling'
            def discover(self, query):
                return CandidateFeed(available=[[{'amountIn': str(query.amount),
                    'hops': [{'pool': deepcopy(row), 'zeroForOne': True}]}]])
        registry = SimpleNamespace(inventory={row['id']: row}, seed=row)
        session = RouteBootstrap([CustomRoutes(registry), Ready()], catalog=registry, cpu=OnceUnavailable())
        amm = CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)
        try:
            with bootstrap_scope(session):
                actual = await self.collect(amm.async_nominations(A, B, 101, BLOCK))
            self.assertEqual(len(actual), 1)
            self.assertEqual(actual[0][1], ['ready-sibling'])
            self.assertEqual(session.metrics['providers']['cybergold-custom']['feedErrors'], 1)
        finally:
            await session.close()

    async def test_large_ready_prefix_constructs_only_consumed_normalizers(self):
        row = pool(A, B, 10, 'v3')
        registry = SimpleNamespace(inventory={row['id']: row}, seed=row)
        offer = {'branches': [{'amountIn': '101', 'hops': [{'pool': row, 'zeroForOne': True}]}],
                 'origins': ['ready']}
        session = RouteBootstrap([], catalog=registry)
        amm = CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)
        token = _quick_offers.set((session, {(A.lower(), B.lower(), 101): [offer]*100000}))
        try:
            with bootstrap_scope(session), patch.object(amm_adapter, 'normalize_steps',
                    wraps=amm_adapter.normalize_steps) as normalized:
                iterator = amm.async_nominations(A, B, 101, BLOCK)
                try:
                    self.assertEqual((await anext(iterator))[1], ['ready'])
                    self.assertEqual(normalized.call_count, 1)
                finally:
                    await iterator.aclose()
                self.assertEqual(normalized.call_count, 1)
        finally:
            _quick_offers.reset(token)
            await session.close()


class LazyRoundRobinTests(unittest.TestCase):
    def test_full_rounds_and_private_markers_equal_existing_order(self):
        feeds = [[CHECKPOINT, 'a', CHECKPOINT, 'b'], [], ['c', 'd', 'e']]
        expected = list(round_robin(feeds))
        actual = list(lazy_round_robin((lambda rows=rows: iter(rows)) for rows in feeds))
        self.assertEqual(actual, expected)

    def test_close_releases_started_iterator_without_constructing_unused_tail(self):
        created, closed = [], []
        def factory(index):
            created.append(index)
            def rows():
                try:
                    yield index
                    yield index
                finally:
                    closed.append(index)
            return rows()
        iterator = lazy_round_robin((lambda index=index: factory(index)) for index in range(100000))
        self.assertEqual(next(iterator), 0)
        iterator.close()
        self.assertEqual(created, [0])
        self.assertEqual(closed, [0])


if __name__ == '__main__':
    unittest.main()
