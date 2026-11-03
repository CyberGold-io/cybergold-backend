"""Shared progress and progressive source scheduling retain semantic coverage."""
import asyncio
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter, adapt_candidates, prioritize_candidates, route_priority
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.candidate_hints import normalize_hints
from cybergold_candidate.quoter.cooperative import CHECKPOINT, async_values, finish, values
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter import discovery
from cybergold_candidate.quoter.discovery import TopologyCache, _enumerate_paths, route_candidates, route_identity
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteQuery, RouteTool, round_robin
from cybergold_candidate.route_search import WETH
from cybergold_candidate.routing_encoding import ZERO, weighted_routes, split_runtime
from cybergold_candidate.uniswap_routes import pool_identity
from test_quoter_topology_reuse import A, B, C, D, BLOCK, pool


def fixture():
    return [pool(A, B, 1, 'v3', 500), pool(A, B, 2, 'v3', 3000),
            pool(B, C, 3, 'v3', 500), pool(B, C, 4, 'v3', 3000), pool(C, D, 5)]


class SharedTopologyProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_interleaved_cold_consumers_share_one_build_and_independent_routes(self):
        rows, cache = fixture(), TopologyCache()
        first = cache.path_steps(rows, A, C, WETH, 3)
        second = cache.path_steps(rows, A, C, WETH, 3)
        self.assertIs(next(first), CHECKPOINT)
        self.assertIs(next(second), CHECKPOINT)
        expected = _enumerate_paths(rows, A, C)
        left, right = finish(first), finish(second)
        self.assertEqual((left, right), (expected, expected))
        self.assertEqual((cache.build_starts, cache.build_reuses, cache.graph_builds), (1, 1, 1))
        self.assertFalse(cache.pending_walks)
        left[0][0]['zeroForOne'] = not left[0][0]['zeroForOne']
        self.assertEqual(right, expected)

    async def test_closed_subscriber_keeps_sibling_progress_and_clear_closes_owner(self):
        rows, cache = fixture(), TopologyCache()
        first = cache.path_steps(rows, A, C, WETH, 3)
        second = cache.path_steps(rows, A, C, WETH, 3)
        next(first)
        next(second)
        first.close()
        self.assertEqual(len(cache.pending_walks), 1)
        self.assertEqual(finish(second), _enumerate_paths(rows, A, C))
        self.assertEqual(cache.graph_builds, 1)
        partial = cache.path_steps(rows, C, A, WETH, 3)
        next(partial)
        owned = next(iter(cache.pending_walks.values()))
        cache.clear()
        self.assertIsNone(owned.steps.gi_frame)
        self.assertFalse(cache.pending_walks)
        self.assertFalse(cache.walks)
        partial.close()

    async def test_completed_shared_walk_rebinds_current_aliases_without_cached_state(self):
        rows, cache = fixture(), TopologyCache()
        first = cache.path_steps(rows, A, C, WETH, 3)
        next(first)
        changed = deepcopy(rows)
        changed[0].update(id='current-alias', address='resolved', reserve0='private-like-value')
        changed[0]['token0']['symbol'] = 'current'
        second = cache.path_steps(changed, A, C, WETH, 3)
        next(second)
        first.close()
        actual = finish(second)
        self.assertEqual(actual, _enumerate_paths(changed, A, C))
        self.assertEqual(cache.graph_builds, 1)
        self.assertNotIn('private-like-value', repr(cache.walks))
        self.assertNotIn('current-alias', repr(cache.walks))

    async def test_different_amounts_share_progress_but_keep_their_actual_allocations(self):
        rows = fixture()
        registry = SimpleNamespace(inventory={row['id']: row for row in rows}, seed=rows[-1])
        session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        try:
            with bootstrap_scope(session):
                feeds = [iter(session.offer_feeds(A, C, amount, BLOCK, cooperative=True)[0])
                         for amount in (101, 999)]
                prefixes = [[], []]
                for index, field in enumerate(('build_starts', 'build_reuses')):
                    while not getattr(session.topology, field):
                        row = next(feeds[index])
                        if row is not CHECKPOINT:
                            prefixes[index].append(row)
                nominees = [prefix + list(values(feed)) for prefix, feed in zip(prefixes, feeds, strict=True)]
            self.assertEqual(session.topology.graph_builds, 1)
            self.assertEqual(session.topology.build_reuses, 1)
            self.assertEqual(len(nominees[0]), len(nominees[1]))
            for amount, offers in zip((101, 999), nominees, strict=True):
                self.assertTrue(all(sum(int(row['amountIn']) for row in offer['branches']) == amount
                                    for offer in offers))
        finally:
            await session.close()


def nomination_key(row):
    branches, origins = row
    return tuple((branch['amountIn'], route_identity(branch['hops'])) for branch in branches), tuple(origins)


def legacy_nominations(registry, source, target, amount, *, market=False, first=False):
    """The pre-progressive path/priority composition, as an independent reference."""
    anchor = pool_identity(registry.seed)
    routes = _enumerate_paths(list(registry.inventory.values()), source, target)
    if market:
        routes = [route for route in routes if pool_identity(next(hop for hop in
            (route if source.lower() == D.lower() else reversed(route)) if 'pool' in hop)['pool']) == anchor]
    if first:
        routes = sorted(routes, key=lambda route: route_priority(route, anchor))
    offers = ({'branches': candidate, 'origins': ['cybergold-custom']}
              for candidate in route_candidates(routes, amount))
    candidates = normalize_hints(offers, source, target)
    if first:
        candidates = prioritize_candidates(candidates, registry)
    return list(adapt_candidates(candidates, source, D, market=market, anchor=anchor if market else None))


class EarlyNominationTests(unittest.IsolatedAsyncioTestCase):
    def setup_adapter(self, rows):
        registry = SimpleNamespace(inventory={row['id']: row for row in rows}, seed=rows[-1])
        return registry, CyberGoldAmmAdapter(SimpleNamespace(registry=registry), D)

    async def test_full_multiset_and_original_split_tail_match_reference_at_amount_edges(self):
        rows = fixture() + [pool(A, C, 6, 'v3', 3000), pool(C, D, 7)]
        registry, adapter = self.setup_adapter(rows)
        for amount in (0, 1, 2, 101, 2**255+7):
            for source, target, market in ((A, C, False), (A, D, True), (D, A, True)):
                for first in (False, True):
                    with self.subTest(amount=amount, source=source, market=market, first=first):
                        expected = legacy_nominations(registry, source, target, amount, market=market, first=first)
                        actual = [row async for row in adapter.async_nominations(
                            source, target, amount, BLOCK, market=market, first=first)]
                        self.assertEqual(Counter(map(nomination_key, actual)), Counter(map(nomination_key, expected)))
                        self.assertEqual([nomination_key(row) for row in actual if len(row[0]) > 1],
                                         [nomination_key(row) for row in expected if len(row[0]) > 1])
                        self.assertTrue(all(sum(split_runtime(amount, weighted_routes(branches))) == amount
                                            for branches, _ in actual))

    async def test_anchored_early_route_passes_before_exhaustive_walk_and_keeps_native_source(self):
        rows = fixture() + [pool(WETH, C, 6, 'v3', 500), pool(WETH, C, 7, 'v3', 3000), pool(C, D, 8)]
        registry, adapter = self.setup_adapter(rows)
        session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        original, full_walks = discovery._enumerate_path_steps, []
        def observed(pools, *args, **kwargs):
            if len(pools) > 2:
                full_walks.append(True)
            return (yield from original(pools, *args, **kwargs))
        try:
            with patch.object(discovery, '_enumerate_path_steps', observed), bootstrap_scope(session):
                candidates = adapter.async_nominations(ZERO, D, 10001, BLOCK, market=True, first=True)
                try:
                    branches, origins = await anext(candidates)
                    self.assertEqual(full_walks, [])
                    # Normalization can cache the small early subgraph; it
                    # must not have started the exhaustive catalog walk.
                    self.assertTrue(all(len(key[-1]) <= 2 for key in session.topology.walks))
                    self.assertEqual(origins, ['cybergold-custom'])
                    self.assertEqual(branches[0]['amountIn'], '10001')
                    self.assertEqual(branches[0]['hops'][0], {'kind': 'wrap', 'currencyOut': WETH.lower()})
                    physical = [hop for hop in branches[0]['hops'] if 'pool' in hop]
                    self.assertEqual(physical[0]['pool']['feePips'], 3000)
                    self.assertEqual(pool_identity(physical[-1]['pool']), pool_identity(registry.seed))
                finally:
                    await candidates.aclose()
                self.assertFalse(session.topology.pending_walks)
        finally:
            await session.close()

    async def test_raw_progressive_stream_keeps_signed_amount_behavior_and_no_added_duplicates(self):
        rows = fixture() + [pool(A, C, 6, 'v3', 3000)]
        registry, _ = self.setup_adapter(rows)
        for amount in (-3, 0, 1, 101):
            feed = CustomRoutes(registry).discover(RouteQuery(A, C, amount, BLOCK))
            actual = list(feed.available)
            expected = list(route_candidates(_enumerate_paths(rows, A, C), amount))
            key = lambda branches: tuple((row['amountIn'], route_identity(row['hops'])) for row in branches)
            self.assertEqual(Counter(map(key, actual)), Counter(map(key, expected)))
        malformed = CustomRoutes(registry).discover(RouteQuery(A, C, None, BLOCK))
        with self.assertRaises(TypeError):
            list(malformed.available)


class FairSourceStepsTests(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_rotation_preserves_each_source_order_and_complete_coverage(self):
        def slow():
            yield CHECKPOINT
            yield CHECKPOINT
            yield 'slow-1'
            yield 'slow-2'
        def ready():
            yield 'ready-1'
            yield CHECKPOINT
            yield 'ready-2'
        expected = ['ready-1', 'slow-1', 'ready-2', 'slow-2']
        self.assertEqual(list(values(round_robin([slow(), ready()]))), expected)
        self.assertEqual([row async for row in async_values(round_robin([slow(), ready()]))], expected)

    async def test_closing_after_ready_peer_closes_suspended_sources(self):
        state = {'steps': 0, 'closed': []}
        def slow():
            try:
                for _ in range(1000):
                    state['steps'] += 1
                    yield CHECKPOINT
                yield 'slow'
            finally:
                state['closed'].append('slow')
        def ready():
            try:
                yield 'ready'
                yield 'later'
            finally:
                state['closed'].append('ready')
        stream = async_values(round_robin([slow(), ready()]))
        self.assertEqual(await anext(stream), 'ready')
        self.assertEqual(state['steps'], 1)
        await stream.aclose()
        self.assertCountEqual(state['closed'], ['slow', 'ready'])

    async def test_actual_adapter_reads_ready_peer_before_custom_first_nomination(self):
        rows = fixture()
        registry = SimpleNamespace(inventory={row['id']: row for row in rows}, seed=rows[-1])
        route = next(route for route in _enumerate_paths(rows, A, D)
                     if all(hop['pool']['feePips'] == 3000 for hop in route))
        class Ready(RouteTool):
            name = 'uniroute-api'
            def discover(self, query):
                return CandidateFeed(available=[[{'amountIn': str(query.amount), 'hops': route}]])
        session = RouteBootstrap([CustomRoutes(registry), Ready()], catalog=registry)
        adapter = CyberGoldAmmAdapter(SimpleNamespace(registry=registry), D)
        try:
            with bootstrap_scope(session):
                candidates = adapter.async_nominations(A, D, 101, BLOCK, market=True, first=True)
                try:
                    branches, origins = await anext(candidates)
                    self.assertEqual(origins, ['uniroute-api'])
                    self.assertEqual(branches[0]['hops'], route)
                    self.assertEqual(session.metrics['providers']['cybergold-custom']['feedReads'], 0)
                finally:
                    await candidates.aclose()
        finally:
            await session.close()


if __name__ == '__main__':
    unittest.main()
