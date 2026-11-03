"""Shared progress and progressive source scheduling retain semantic coverage."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.cooperative import CHECKPOINT, finish, values
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.discovery import TopologyCache, _enumerate_paths
from cybergold_candidate.route_search import WETH
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
                self.assertIs(next(feeds[0]), CHECKPOINT)
                self.assertIs(next(feeds[1]), CHECKPOINT)
                nominees = [list(values(feed)) for feed in feeds]
            self.assertEqual(session.topology.graph_builds, 1)
            self.assertEqual(session.topology.build_reuses, 1)
            self.assertEqual(len(nominees[0]), len(nominees[1]))
            for amount, offers in zip((101, 999), nominees, strict=True):
                self.assertTrue(all(sum(int(row['amountIn']) for row in offer['branches']) == amount
                                    for offer in offers))
        finally:
            await session.close()


if __name__ == '__main__':
    unittest.main()
