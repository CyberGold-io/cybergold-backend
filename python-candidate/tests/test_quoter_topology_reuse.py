"""Request-local topology reuse preserves current nominations and metadata."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.discovery import (
    TopologyCache, current_topology, paths, _enumerate_paths, topology_scope)
from cybergold_candidate.quoter.route_tools import PendingRouteTool
from cybergold_candidate.routing_encoding import ZERO, weighted_routes, split_runtime
from cybergold_candidate.route_search import WETH

A, B, C, D = ('0x'+str(value)*40 for value in (1, 2, 3, 4))
BLOCK = {'number': 1, 'hash': '0x'+'ab'*32}


def pool(a, b, number, protocol='v2', fee=3000):
    a, b = sorted((a, b))
    return {'id': '0x'+format(number, '040x'), 'protocol': protocol,
            'token0': {'address': a, 'decimals': 18},
            'token1': {'address': b, 'decimals': 18}, 'feePips': fee,
            'tickSpacing': 60, 'hooks': ZERO}


class TopologyReuseTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        rows = [pool(A, B, index+10, 'v3', 100+index) for index in range(4)]
        registry = SimpleNamespace(inventory={row['id']: row for row in rows}, seed=rows[-1])
        return registry, CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)

    async def test_walks_bind_current_pools_and_keep_returned_routes_independent(self):
        rows = [pool(A, B, 10), pool(B, C, 11), pool(A, C, 12)]
        cache = TopologyCache()
        with topology_scope(cache):
            first = paths(rows, A, C)
            self.assertEqual(first, _enumerate_paths(rows, A, C))
            first[0][0]['zeroForOne'] = not first[0][0]['zeroForOne']
            first.append([])
            rows[0] = {**rows[0], 'id': 'changed-alias', 'address': 'resolved',
                       'token0': {**rows[0]['token0'], 'symbol': 'current'},
                       'reserve0': 'fresh-current-state'}
            second = paths(rows, A, C)
            self.assertEqual(second, _enumerate_paths(rows, A, C))
            self.assertIs(second[1][0]['pool'], rows[0])
            self.assertEqual(cache.graph_builds, 1)
            self.assertEqual(cache.path_hits, 1)
            self.assertNotIn('fresh-current-state', repr(cache.walks))
            self.assertNotIn('current', repr(cache.walks))

    async def test_direction_alias_native_hops_limit_and_hook_changes_match_enumeration(self):
        rows = [pool(WETH, A, 10, 'v3'), pool(A, B, 11), pool(B, C, 12), pool(C, D, 13)]
        cache = TopologyCache()
        with topology_scope(cache):
            for source, target, limit in ((ZERO, C, 3), (C, ZERO, 3), (ZERO, D, 3), (ZERO, D, 4)):
                for _ in range(2):
                    self.assertEqual(paths(rows, source, target, max_hops=limit),
                                     _enumerate_paths(rows, source, target, max_hops=limit))
            resolved = {**deepcopy(rows[0]), 'address': 'resolved', 'id': 'resolved-alias'}
            self.assertEqual(paths([*rows, resolved], ZERO, C), _enumerate_paths([*rows, resolved], ZERO, C))
            rows[1]['hooks'] = '0x'+'99'*20
            self.assertEqual(paths(rows, ZERO, C), [])

    async def test_session_catalog_and_metadata_remain_current_without_arrival_rounds(self):
        registry = SimpleNamespace(inventory={'ab': pool(A, B, 10)})
        session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        with bootstrap_scope(session):
            self.assertEqual(session.candidates(A, C, 101, BLOCK), [])
            registry.inventory['bc'] = pool(B, C, 11)
            offered = session.candidates(A, C, 101, BLOCK)
            self.assertEqual(len(offered), 1)
            registry.inventory['bc']['token1']['symbol'] = 'new metadata'
            current = session.candidates(A, C, 101, BLOCK)
            self.assertEqual(current[0][0]['hops'][-1]['pool']['token1']['symbol'], 'new metadata')
            self.assertEqual(session.revision, 0)
            self.assertEqual(session.topology.graph_builds, 2)
        await session.close()
        self.assertEqual(session.topology.walks, {})
        self.assertEqual(session.topology.validated, {})
        self.assertIsNone(current_topology())

    async def test_complete_split_nominations_equal_uncached_order_and_funding(self):
        registry, adapter = self.fixture()
        with topology_scope(None):
            baseline = list(adapter.nominations(A, B, 101, BLOCK))
        session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        with bootstrap_scope(session):
            for _ in range(3):
                actual = list(adapter.nominations(A, B, 101, BLOCK))
                self.assertEqual(actual, baseline)
                self.assertTrue(all(sum(split_runtime(101, weighted_routes(rows))) == 101 for rows, _ in actual))
            self.assertEqual(session.topology.route_validations, 4)
            self.assertGreater(session.topology.validation_hits, 4)
            self.assertGreater(session.topology.path_hits, session.topology.graph_builds)
        await session.close()

    async def test_late_duplicate_supplier_retains_its_origin_after_cache_warmup(self):
        registry, adapter = self.fixture()
        release, started = asyncio.Event(), asyncio.Event()
        row = list(adapter.nominations(A, B, 101, BLOCK))[0][0]
        class Supplier:
            name = 'uniswap-alpharouter'
            async def discover(self, *_):
                started.set()
                await release.wait()
                return [deepcopy(row)]
        session = RouteBootstrap([CustomRoutes(registry), PendingRouteTool(Supplier())], catalog=registry)
        try:
            with bootstrap_scope(session):
                before = list(adapter.nominations(A, B, 101, BLOCK))
                await started.wait()
                self.assertTrue(all(origins == ['cybergold-custom'] for _, origins in before))
                release.set()
                await asyncio.gather(*session._tasks)
                after = list(adapter.nominations(A, B, 101, BLOCK))
                matching = [origins for branches, origins in after if branches == row]
                self.assertEqual(matching, [['cybergold-custom', 'uniswap-alpharouter']])
                self.assertEqual(len(after), len(before))
        finally:
            await session.close()

    async def test_rendering_metadata_is_revalidated_and_requests_do_not_share_cache(self):
        registry, adapter = self.fixture()
        first = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        with bootstrap_scope(first):
            old = list(adapter.nominations(A, B, 101, BLOCK))
            registry.inventory[next(iter(registry.inventory))]['token0']['symbol'] = 'current'
            self.assertEqual(len(list(adapter.nominations(A, B, 101, BLOCK))), len(old))
            bad = registry.inventory[next(iter(registry.inventory))]
            del bad['feePips']
            # Removing a required field must not reuse prior encoding validation.
            registry.inventory.pop(bad['id'])
            bad['protocol'] = 'v2'
            registry.inventory[bad['id']] = bad
            actual = list(adapter.nominations(A, B, 101, BLOCK))
            with topology_scope(None):
                expected = list(adapter.nominations(A, B, 101, BLOCK))
            self.assertEqual(actual, expected)
        second = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        self.assertIsNot(first.topology, second.topology)
        self.assertEqual(second.topology.walks, {})
        await first.close()
        await second.close()


if __name__ == '__main__':
    unittest.main()
