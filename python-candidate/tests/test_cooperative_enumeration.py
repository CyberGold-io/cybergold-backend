"""Enumeration fairness without changing the full stream or no-route meaning."""
import asyncio
from copy import deepcopy
from itertools import combinations
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.pool_initialization import record_pool_initialization
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.cooperative import CHECKPOINT, async_finish, async_values, sort_steps
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter import discovery
from cybergold_candidate.quoter.discovery import (
    TopologyCache, path_steps, paths, route_candidates, route_candidate_steps, topology_scope)
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteTool
from cybergold_candidate.routing_encoding import weighted_routes, split_runtime, ZERO
from test_quoter_topology_reuse import A, B, C, D, BLOCK, pool
from cybergold_candidate.route_search import WETH
from cybergold_candidate.search_observations import search_observation_scope


def graph(width=8):
    rows = []
    for index in range(width):
        middle = '0x' + format(100 + index, '040x')
        for fee in (500, 3000, 10000):
            rows.extend((pool(A, middle, 1000+len(rows), 'v3', fee),
                         pool(middle, B, 1001+len(rows), 'v3', fee)))
    rows.extend((pool(B, C, 9998, 'v3'), pool(C, D, 9999, 'v2')))
    return rows


def adapter(rows):
    registry = SimpleNamespace(inventory={row['id']: row for row in rows}, seed=rows[-2])
    return registry, CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)


class CooperativeEnumerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_split_order_tiny_amount_duplicates_native_and_uint256_max(self):
        large = 2**256 - 1
        allocations = {0: [], 1: [], 2: [(1, 1), (1, 1)],
                       3: [(1, 2), (2, 1)], 4: [(1, 3), (2, 2), (3, 1)],
                       large: [(large//4, large-large//4),
                               (large//2, large-large//2),
                               (large*3//4, large-large*3//4)]}
        for source, target in ((A, B), (ZERO, B), (B, ZERO)):
            pools = [pool(A if source == A else WETH, B, index, 'v3', fee)
                     for index, fee in enumerate((100, 500, 3000), 1)]
            routes = paths(pools, source, target)
            self.assertEqual(len(routes), 3)
            original = deepcopy(routes)
            for amount, lots in allocations.items():
                with self.subTest(source=source, target=target, raw=amount):
                    expected = [[{'amountIn': str(amount), 'hops': route}] for route in routes]
                    expected.extend([{'amountIn': str(first), 'hops': left},
                                     {'amountIn': str(second), 'hops': right}]
                                    for left, right in combinations(routes, 2) for first, second in lots)
                    self.assertEqual(list(route_candidates(routes, amount)), expected)
                    self.assertEqual([row async for row in async_values(route_candidate_steps(routes, amount))],
                                     expected)
            self.assertEqual(routes, original)

    async def test_zero_and_one_raw_unit_finish_after_singles_without_pair_work(self):
        routes = paths([pool(A, B, index, 'v3', 100+index) for index in range(16)], A, B)
        for amount in (0, 1):
            with self.subTest(raw=amount), patch.object(discovery, 'route_available', return_value=True) as checks:
                iterator = route_candidates(routes, amount)
                for _ in routes:
                    self.assertEqual(next(iterator)[0]['amountIn'], str(amount))
                checks.reset_mock()
                with patch.object(discovery, 'combinations', side_effect=AssertionError('No split can be emitted')):
                    self.assertEqual(list(iterator), [])
                self.assertEqual(checks.call_count, 0)

    async def rejected_custom_feed(self):
        await self.enterAsyncContext(search_observation_scope())
        rows = [{**pool(A, B, index, 'v3', 100+index),
                 'address': '0x'+format(index, '040x')} for index in range(1, 41)]
        registry = SimpleNamespace(inventory={row['id']: row for row in rows},
                                   chain=1, generation='captured-owner')
        session = RouteBootstrap([CustomRoutes(registry)], catalog=registry, block=BLOCK)
        self.addAsyncCleanup(session.close)
        self.enterContext(bootstrap_scope(session))
        feed = iter(session.offer_feeds(A, B, 1000, BLOCK, cooperative=True)[0])
        self.addCleanup(feed.close)
        singles = 0
        while True:
            row = next(feed)
            if row is CHECKPOINT:
                continue
            if len(row['branches']) == 2:
                break
            singles += 1
        self.assertEqual(singles, 40)
        for row in rows:
            record_pool_initialization(registry, {**row, 'sqrtRatioX96': '0'},
                                       BLOCK, registry.generation)
        return feed

    async def test_actual_custom_feed_rejected_pair_tail_yields_to_ready_work(self):
        feed = await self.rejected_custom_feed()
        ready = []
        asyncio.get_running_loop().call_soon(lambda: ready.append(True))
        self.assertEqual([row async for row in async_values(feed)], [])
        self.assertEqual(ready, [True], 'A rejected-only inner scan must not hide cooperative work')

    async def test_cancel_actual_custom_rejected_tail_closes_suspended_steps(self):
        closed = False
        def tracked(*args, **kwargs):
            nonlocal closed
            try:
                yield from route_candidate_steps(*args, **kwargs)
            finally:
                closed = True
        with patch('cybergold_candidate.quoter.custom_routes.route_candidate_steps', tracked):
            feed = await self.rejected_custom_feed()
            async def drain():
                return [row async for row in async_values(feed)]
            pending = asyncio.create_task(drain())
            asyncio.get_running_loop().call_soon(pending.cancel)
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertTrue(closed)

    async def test_path_walk_order_native_transitions_and_cache_match_sync(self):
        rows = graph(3) + [pool(WETH, A, 9996, 'v3')]
        for source, target in ((A, C), (C, A), (A, D), (D, A), (ZERO, B), (B, ZERO)):
            with self.subTest(source=source, target=target):
                expected = paths(rows, source, target)
                cache = TopologyCache()
                with topology_scope(cache):
                    for _ in range(2):
                        self.assertEqual(await async_finish(path_steps(rows, source, target)), expected)

    async def test_complete_order_split_funding_and_origin_merges_equal_sync(self):
        rows = graph(3)
        registry, amm = adapter(rows)
        for options in ({}, {'first': True}, {'market': True},
                        {'market': True, 'first': True}, {'market': True, 'linear_only': True}):
            with self.subTest(options=options):
                session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
                try:
                    with bootstrap_scope(session):
                        expected = list(amm.nominations(A, C, 101, BLOCK, **options))
                        actual = [row async for row in amm.async_nominations(A, C, 101, BLOCK, **options)]
                        self.assertEqual(actual, expected)
                        for branches, _ in actual:
                            self.assertEqual(sum(split_runtime(101, weighted_routes(branches))), 101)
                finally:
                    await session.close()

    async def test_stable_family_groups_match_sync(self):
        registry, amm = adapter(graph(4))
        session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        try:
            with bootstrap_scope(session):
                expected = amm.family_offers(A, C, 101, BLOCK)
                self.assertEqual(await amm.async_family_offers(A, C, 101, BLOCK), expected)
        finally:
            await session.close()

    async def test_ready_callbacks_run_during_hidden_duplicate_scan(self):
        registry, amm = adapter([pool(A, B, 1), pool(B, C, 2)])
        candidate = [{'amountIn': '101', 'hops': [{'pool': registry.inventory[pool(A, B, 1)['id']],
                                                'zeroForOne': True}]}]
        state = {'reads': 0, 'closed': False}
        class Repeated(RouteTool):
            name = 'uniroute-api'
            def discover(self, query):
                def offers():
                    try:
                        for _ in range(4096):
                            state['reads'] += 1
                            yield candidate
                    finally:
                        state['closed'] = True
                return CandidateFeed(available=offers())
        session = RouteBootstrap([Repeated()])
        callbacks = []
        try:
            with bootstrap_scope(session):
                iterator = amm.async_nominations(A, B, 101, BLOCK)
                first = await anext(iterator)
                asyncio.get_running_loop().call_soon(lambda: callbacks.append(state['reads']))
                tail = [row async for row in iterator]
            self.assertEqual(first[0], candidate)
            self.assertEqual(tail, [])
            self.assertEqual(state['reads'], 4096)
            self.assertTrue(state['closed'])
            self.assertEqual(len(callbacks), 1)
            self.assertLess(callbacks[0], 4096)
            observed = session.metrics['providers']['uniroute-api']
            self.assertEqual((observed['feedReads'], observed['candidates']), (4096, 4096))
        finally:
            await session.close()

    async def test_cancellation_inside_hidden_scan_closes_owned_iterator(self):
        registry, amm = adapter([pool(A, B, 1), pool(B, C, 2)])
        candidate = [{'amountIn': '101', 'hops': [{'pool': registry.inventory[pool(A, B, 1)['id']],
                                                'zeroForOne': True}]}]
        state = {'reads': 0, 'closed': False}
        class Repeated(RouteTool):
            name = 'uniroute-api'
            def discover(self, query):
                def offers():
                    try:
                        for _ in range(10000):
                            state['reads'] += 1
                            yield candidate
                    finally:
                        state['closed'] = True
                return CandidateFeed(available=offers())
        session = RouteBootstrap([Repeated()])
        try:
            with bootstrap_scope(session):
                iterator = amm.async_nominations(A, B, 101, BLOCK)
                await anext(iterator)
                pending = asyncio.create_task(anext(iterator))
                asyncio.get_running_loop().call_soon(pending.cancel)
                with self.assertRaises(asyncio.CancelledError):
                    await pending
            self.assertTrue(state['closed'])
            self.assertLess(state['reads'], 10000)
            stopped = state['reads']
            await asyncio.sleep(0)
            self.assertEqual(state['reads'], stopped)
        finally:
            await session.close()

    async def test_walk_and_sort_allow_progress_before_exhaustion(self):
        registry, amm = adapter(graph(15))
        ready = []
        asyncio.get_running_loop().call_soon(lambda: ready.append(True))
        iterator = amm.async_nominations(A, C, 101, BLOCK, first=True)
        try:
            await anext(iterator)
            self.assertEqual(ready, [True])
        finally:
            await iterator.aclose()
        rows = [(index % 5, index) for index in range(400, -1, -1)]
        self.assertEqual(await async_finish(sort_steps(rows, key=lambda row: row[0])),
                         sorted(rows, key=lambda row: row[0]))

    async def test_disconnected_graph_still_has_valid_no_route_outcome(self):
        registry, amm = adapter([pool(A, B, 1), pool(C, D, 2)])
        self.assertEqual([row async for row in amm.async_nominations(A, D, 101, BLOCK)], [])
        async def price(*_):
            self.fail('A disconnected graph has no path to price')
        with self.assertRaises(QuoteFailure) as error:
            await amm.convert(A, D, 101, BLOCK, {}, {}, price_path=price)
        self.assertEqual(error.exception.code, 'quote-no-route')


if __name__ == '__main__':
    unittest.main()
