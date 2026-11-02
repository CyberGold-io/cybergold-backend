"""Completed topology can bootstrap other plans without sharing prices/state."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.route_observations import project_route_discovery
from cybergold_candidate.route_work_slots import PricingSlots
from cybergold_candidate.routing_encoding import ZERO, split_runtime, weighted_routes
from cybergold_candidate.route_search import WETH
from cybergold_candidate.quoter.amm import price_path
from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.contracts import current_nomination, path_nomination
from cybergold_candidate.quoter.evaluate import replay_conversion
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteQuery, RouteTool


A, B, C = ('0x'+str(index)*40 for index in (1, 2, 3))
BLOCK = {'number': 123, 'hash': '0x'+'ab'*32}


def hop(source, target, index=4, protocol='v2'):
    a, b = sorted((source, target), key=str.lower)
    return {'zeroForOne': source.lower() == a.lower(), 'pool': {
        'id': '0x'+format(index, '040x'), 'protocol': protocol, 'feePips': 3000,
        'tickSpacing': 60, 'hooks': ZERO,
        'token0': {'address': a, 'decimals': 18, 'chainId': 31338},
        'token1': {'address': b, 'decimals': 18, 'chainId': 31338},
        'reserve0': 'canonical-only', 'sqrtRatioX96': 'canonical-only',
        'ticks': [{'index': 0, 'liquidityGross': '1', 'liquidityNet': '1'}], 'context': BLOCK, 'lpFee': 3000}}


class Engine:
    def __init__(self):
        self.semaphore = PricingSlots(8)
        self.calls, self.values, self.holds, self.errors = [], {}, {}, {}
        async def snapshot(pool, _block):
            return {**deepcopy(pool), 'reserve0': 'canonical-read'}
        self.registry = SimpleNamespace(inventory={}, snapshot=snapshot)

    async def quote_sdk_branches(self, branches, mode, amount, block, *, candidate, canonical):
        pool = branches[0]['hops'][0]['pool']
        identity = pool['id']
        self.calls.append((deepcopy(branches), amount, deepcopy(candidate)))
        if identity in self.holds:
            await self.holds[identity].wait()
        if identity in self.errors:
            raise self.errors[identity]
        canonical[identity] = {**deepcopy(pool), 'reserve0': 'canonical-read'}
        candidate[identity] = {**deepcopy(pool), 'reserve0': 'private-post-state'}
        used, output = self.values.get(identity, (amount, amount*2))
        return {'amountIn': str(used), 'amountOut': str(output)}


class CompletedRouteHints(unittest.IsolatedAsyncioTestCase):
    async def test_sink_is_topology_only_deduplicated_and_starts_no_query(self):
        calls = []
        class Immediate(RouteTool):
            name = 'any-source'
            def discover(_self, query):
                calls.append(query)
                return CandidateFeed(available=[[{'amountIn': '100', 'hops': [hop(A, C)]}]])
        session = RouteBootstrap([Immediate()])
        self.addAsyncCleanup(session.close)
        route = [hop(A, B)]
        query = RouteQuery(A, B, 100, BLOCK)
        self.assertTrue(session.publish_completed(query, route, ['first']))
        route[0]['pool']['reserve0'] = 'different-private-value'
        route[0]['pool']['token0']['symbol'] = 'optional-display'
        self.assertFalse(session.publish_completed(query, route, ['second']))
        self.assertEqual((calls, session.metrics['queries'], session.revision), ([], 0, 0))
        offered = list(session.offers(A, B, 100, BLOCK))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(offered), 2)  # The ordinary feed remains present.
        self.assertEqual(offered[0]['origins'], ['first', 'second'])
        self.assertEqual(offered[0]['branches'][0]['amountIn'], '100')
        pool = offered[0]['branches'][0]['hops'][0]['pool']
        for field in ('reserve0', 'sqrtRatioX96', 'ticks', 'context', 'lpFee'):
            self.assertNotIn(field, pool)
        self.assertNotIn('symbol', pool['token0'])
        offered[0]['origins'].append('mutated-copy')
        ready = session._ready_offers()[(A, B, 100)]
        self.assertEqual(ready[0]['origins'], ['first', 'second'])
        self.assertEqual(project_route_discovery(session.metrics)['completedOffers'], 1)

    async def test_unused_funding_prefixes_are_ready_without_starting_work_or_revision(self):
        session = RouteBootstrap([])
        self.addAsyncCleanup(session.close)
        session.candidates(A, B, 100, BLOCK)  # A consumed query even with no suppliers.
        for amount in (25, 50, 75):
            self.assertTrue(session.publish_completed(RouteQuery(A, B, amount, BLOCK), [hop(A, B)]))
        self.assertEqual(session.revision, 0)
        self.assertFalse(session._changed.is_set())
        self.assertEqual(session.metrics['queries'], 1)
        self.assertEqual(session.metrics['completedOffers'], 3)
        offered = list(session.offers(A, B, 25, BLOCK))
        self.assertEqual(offered[0]['branches'][0]['amountIn'], '25')
        self.assertEqual(session.revision, 0)
        # A later shape for that now-consumed query does wake the existing
        # driver; no pending supplier or other liveness property is needed.
        self.assertTrue(session.publish_completed(RouteQuery(A, B, 25, BLOCK), [hop(A, B, protocol='v3')]))
        self.assertEqual(session.revision, 1)
        self.assertTrue(session._changed.is_set())

    async def test_completed_prefix_wakes_quick_while_later_hop_is_still_pending(self):
        engine, session = Engine(), RouteBootstrap([])
        release, ready = asyncio.Event(), asyncio.Event()
        route = [hop(A, B), hop(B, C, 5)]
        engine.holds[route[1]['pool']['id']] = release
        engine.errors[route[1]['pool']['id']] = OSError('ordinary later-hop failure')
        async def ordinary():
            session.candidates(A, B, 100, BLOCK)
            with path_nomination(A, ['original-source']):
                try:
                    await price_path(engine, route, 100, BLOCK, {}, {})
                except OSError:
                    pass
            return 'ordinary-result'
        async def detailed():
            await release.wait()
        async def quick():
            first = next(iter(session.offers(A, B, 100, BLOCK)))
            self.assertEqual(first['origins'], ['original-source'])
            # Replay starts with a different private bank and publishes the
            # same semantic hint, so it must not create a feedback revision.
            with path_nomination(A, first['origins']):
                await price_path(engine, first['branches'][0]['hops'], 100, BLOCK, {}, {})
            self.assertEqual(session.revision, 1)
            ready.set()
        with bootstrap_scope(session):
            task = asyncio.create_task(session.run(ordinary(), detailed, quick=quick))
        try:
            await asyncio.wait_for(ready.wait(), 1)
            self.assertFalse(task.done())
            self.assertEqual(session.metrics['completedOffers'], 1)
            self.assertNotIn((A, C, 100), session._ready_offers())
        finally:
            release.set()
            self.assertEqual(await asyncio.wait_for(task, 1), 'ordinary-result')
        self.assertEqual(session.metrics['quickReevaluations'], 1)
        self.assertEqual(engine.semaphore._value, 8)

    async def test_partial_first_hop_keeps_original_funding_but_partial_intermediate_is_not_published(self):
        engine, session = Engine(), RouteBootstrap([])
        self.addAsyncCleanup(session.close)
        route = [hop(A, B), hop(B, C, 5)]
        engine.values[route[0]['pool']['id']] = 60, 80
        engine.values[route[1]['pool']['id']] = 79, 120
        with bootstrap_scope(session), path_nomination(A):
            with self.assertRaises(InvalidPreview):
                await price_path(engine, route, 100, BLOCK, {}, {})
        ready = session._ready_offers()
        self.assertEqual(set(ready), {(A, B, 100)})
        self.assertEqual(ready[(A, B, 100)][0]['branches'][0]['amountIn'], '100')
        self.assertEqual(ready[(A, B, 100)][0]['origins'], [])

    async def test_adapter_restores_native_source_and_preserves_split_branch_funding(self):
        engine, session = Engine(), RouteBootstrap([])
        self.addAsyncCleanup(session.close)
        physical = hop(WETH, B)
        candidate = [{'amountIn': '1', 'hops': [{'kind': 'wrap', 'currencyOut': WETH}, physical]},
                     {'amountIn': '2', 'hops': [{'kind': 'wrap', 'currencyOut': WETH}, physical]}]
        adapter = CyberGoldAmmAdapter(engine, C)
        adapter.nominations = lambda *_args, **_kwargs: iter([(candidate, ['original-source'])])
        async def replay(*args):
            return await price_path(engine, *args)
        with bootstrap_scope(session):
            await adapter.convert(ZERO, B, 100, BLOCK, {}, {}, price_path=replay)
        amounts = split_runtime(100, weighted_routes(candidate))
        ready = session._ready_offers()
        self.assertEqual(set(ready), {(ZERO, B, amount) for amount in amounts})
        self.assertNotIn((ZERO, B, 100), ready)
        for amount in amounts:
            offered = ready[(ZERO, B, amount)][0]
            self.assertEqual(offered['branches'][0]['hops'][0], {'kind': 'wrap', 'currencyOut': WETH.lower()})
            self.assertEqual(offered['origins'], ['original-source'])
        self.assertEqual(current_nomination(), (None, ()))
        # A caller retaining its native hop must not receive a second wrap.
        with bootstrap_scope(session), path_nomination(ZERO):
            await price_path(engine, [{'kind': 'wrap', 'currencyOut': WETH}, physical],
                             101, BLOCK, {}, {})
        hops = session._ready_offers()[(ZERO, B, 101)][0]['branches'][0]['hops']
        self.assertEqual(sum('kind' in item for item in hops), 1)

    async def test_selected_replay_restores_unwrap_and_all_v4_native_source_origins(self):
        for source, physical_source in ((WETH, ZERO), (ZERO, ZERO)):
            with self.subTest(source=source):
                engine, session = Engine(), RouteBootstrap([])
                self.addAsyncCleanup(session.close)
                route = [hop(physical_source, B, protocol='v4')]
                chosen = {'inputCurrency': source, 'outputCurrency': B,
                    'branches': [{'hops': route}], 'discoveryOrigins': ['selected-origin'],
                    'template': {'inputCurrency': physical_source, 'outputCurrency': B,
                                 'routes': weighted_routes([{'amountIn': '100', 'hops': route}])}}
                async def replay(*args):
                    return await price_path(engine, *args)
                quoter = SimpleNamespace(price_path=replay)
                with bootstrap_scope(session):
                    await replay_conversion(quoter, chosen, source, B, 100, BLOCK, {}, {})
                offered = session._ready_offers()[(source.lower(), B, 100)][0]
                self.assertEqual(offered['origins'], ['selected-origin'])
                hops = offered['branches'][0]['hops']
                if source == WETH:
                    self.assertEqual(hops[0], {'kind': 'unwrap', 'currencyOut': ZERO})
                else:
                    self.assertEqual(len(hops), 1)
                self.assertEqual(hops[-1]['pool']['protocol'], 'v4')
                self.assertEqual(current_nomination(), (None, ()))

    async def test_later_context_disproof_still_drains_early_quick_work(self):
        engine, session = Engine(), RouteBootstrap([])
        release, ready, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
        route = [hop(A, B), hop(B, C, 5)]
        engine.holds[route[1]['pool']['id']] = release
        engine.errors[route[1]['pool']['id']] = SnapshotChanged('later state disproved')
        async def ordinary():
            session.candidates(A, B, 100, BLOCK)
            return await price_path(engine, route, 100, BLOCK, {}, {})
        async def detailed():
            await release.wait()
        async def quick():
            try:
                ready.set()
                await asyncio.Event().wait()
            finally:
                drained.set()
        with bootstrap_scope(session):
            task = asyncio.create_task(session.run(ordinary(), detailed, quick=quick))
        await asyncio.wait_for(ready.wait(), 1)
        release.set()
        with self.assertRaises(SnapshotChanged):
            await asyncio.wait_for(task, 1)
        self.assertTrue(drained.is_set())
        self.assertEqual(engine.semaphore._value, 8)

    async def test_stop_close_and_replay_without_search_create_no_more_hints(self):
        budget = QuoteBudget()
        with budget_context(budget):
            session = RouteBootstrap([])
        query = RouteQuery(A, B, 100, BLOCK)
        budget.finish_selection('best-initial')
        self.assertFalse(session.publish_completed(query, [hop(A, B)]))
        await session.close()
        self.assertFalse(session.publish_completed(query, [hop(A, B)]))
        engine = Engine()
        with patch('cybergold_candidate.quoter.amm.paths', side_effect=AssertionError('replay discovered paths')):
            await price_path(engine, [hop(A, B)], 100, BLOCK, {}, {})
        self.assertEqual(session.metrics['completedOffers'], 0)
        self.assertEqual(session.metrics['queries'], 0)


if __name__ == '__main__':
    unittest.main()
