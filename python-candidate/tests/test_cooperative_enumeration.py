"""Enumeration fairness without changing the full stream or no-route meaning."""
import asyncio
from types import SimpleNamespace
import unittest

from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.cooperative import async_finish, sort_steps
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.discovery import TopologyCache, path_steps, paths, topology_scope
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteTool
from cybergold_candidate.routing_encoding import weighted_routes, split_runtime, ZERO
from test_quoter_topology_reuse import A, B, C, D, BLOCK, pool
from cybergold_candidate.route_search import WETH


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
