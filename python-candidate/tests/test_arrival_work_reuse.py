"""Arrival scheduling controls; contract leaves are explicit fixture responses."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from collections import Counter
from unittest.mock import AsyncMock, patch

from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter import search as search_module
from cybergold_candidate.quoter.contracts import SearchSession
from cybergold_candidate.quoter.exploration import explore
from cybergold_candidate.quoter.route_tools import RouteQuery
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.quoter.plan_transport import simulation_scope
from cybergold_candidate.quoter.route_tools import PendingRouteTool
from test_quoter_plan_simulation import BLOCK, CORE, WETH, fixture, market
from test_universal_quote import Quotes, Engine, PAXG, OTHER
from quoter_fixture import synthetic_pool


class ArrivalWorkTests(unittest.IsolatedAsyncioTestCase):
    async def until(self, predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0)

    async def test_origin_only_arrival_does_not_restart_failed_helpers_work(self):
        request, plan = market()
        branches = [{'amountIn': '10000', 'hops': deepcopy(plan['conversions']['0:market']['branches'][0]['hops'])}]
        duplicate, first_done = asyncio.Event(), asyncio.Event()
        class First:
            name = 'first-provider'
            async def discover(self, *_):
                return [deepcopy(branches)]
        class Duplicate:
            name = 'later-provider'
            async def discover(self, *_):
                await duplicate.wait()
                return [deepcopy(branches)]
        session = RouteBootstrap([PendingRouteTool(First()), PendingRouteTool(Duplicate())])
        simulation, _, _, provider = fixture(*[{'error': {'code': 3, 'message': 'execution reverted'}}] * 4)
        attempts = []
        async def ordinary():
            list(session.offers(WETH, CORE, 10000, BLOCK))
        async def reprice():
            attempts.append(session.revision)
            try:
                await simulation(request, plan)
            except QuoteFailure:
                pass
            first_done.set()
        async with simulation_scope():
            task = asyncio.create_task(session.run(ordinary(), reprice))
            try:
                await asyncio.wait_for(first_done.wait(), 1)
                duplicate.set()
                await asyncio.wait_for(task, 1)
            finally:
                duplicate.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(len(provider.calls), 1, 'A new diagnostic origin is not another executable input')
        self.assertEqual(attempts, [1])
        self.assertEqual(session.revision, 1)
        self.assertEqual({name: value['candidates'] for name, value in session.metrics['providers'].items()},
                         {'first-provider': 1, 'later-provider': 1})
        self.assertEqual([row['origins'] for row in session.offers(WETH, CORE, 10000, BLOCK)], [])

    async def test_real_search_arrivals_only_restart_query_consumers_and_merge_duplicate_origins(self):
        """Real Quoter owners/selection, explicit fixed contract-result leaf."""
        first, duplicate, core, finish = (asyncio.Event() for _ in range(4))
        duplicate_published, ordinary_done = asyncio.Event(), asyncio.Event()
        _, plan = market()
        market_hops = deepcopy(plan['conversions']['0:market']['branches'][0]['hops'])
        gold_pool = synthetic_pool(WETH, PAXG, 955, 'v2')
        gold_hops = [{'pool': gold_pool, 'zeroForOne': gold_pool['token0']['address'].lower() == WETH.lower()}]
        class Provider:
            name = 'controlled-arrival'
            async def discover_batches(self, source, target, amount, block):
                if target.lower() == CORE.lower():
                    await first.wait()
                    yield [[{'amountIn': str(amount), 'hops': market_hops}]]
                    await duplicate.wait()
                    yield [[{'amountIn': str(amount), 'hops': deepcopy(market_hops)}]]
                    duplicate_published.set()
                    await finish.wait()
                elif target.lower() == PAXG.lower():
                    await core.wait()
                    yield [[{'amountIn': str(amount), 'hops': gold_hops}]]
        class Controlled(Quotes):
            def __init__(self):
                super().__init__(Engine())
                self.calls = Counter()
            async def candidate(self, request, share, order, block, assets, weights, *, first=False, **options):
                self.calls[share, order, first] += 1
                bootstrap = search_module.current_bootstrap()
                targets = [CORE] if share == 0 else [PAXG] if share == 100 else [CORE, PAXG] if share == 50 else [OTHER]
                available = sum(len(list(bootstrap.offers(WETH, target, 10000, block))) for target in targets)
                await asyncio.sleep(0)
                return {'request': deepcopy(request), 'inputs': deepcopy(request['inputs']),
                    'quotedOutput': str(100 + available), 'searchCoverage': {},
                    'plan': {'allocations': [], 'conversions': {}, 'body': {
                        'branches': [{'kind': int(share == 0), 'amountIn': '10000', 'data': {}}]}}}
        async def empty_alternatives(*args, **kwargs):
            if False:
                yield None
        original_run = RouteBootstrap.run
        async def run(session, ordinary, *args, **kwargs):
            async def observed():
                result = await ordinary
                ordinary_done.set()
                return result
            return await original_run(session, observed(), *args, **kwargs)
        q = Controlled()
        q.route_provider_factory = lambda: [PendingRouteTool(Provider())]
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        grid = [(share, order) for share in (0, 25, 50, 75, 100)
                for order in (('core-first', 'market-first') if 0 < share < 100 else ('core-first',))]
        with patch.object(RouteBootstrap, 'run', run), \
                patch.object(search_module, 'explore', AsyncMock()), \
                patch.object(search_module, 'core_funding_alternatives', empty_alternatives), \
                patch.object(search_module, 'measured_funding_proposal', return_value=None), \
                patch.object(search_module, 'observe_market_segments', return_value=False):
            task = asyncio.create_task(q.quote(request))
            try:
                await self.until(lambda: task.done() or ordinary_done.is_set())
                if task.done():
                    await task
                self.assertTrue(all(q.calls[share, order, first] for share, order in grid for first in (False, True)))
                before = q.calls.copy()
                first.set()
                await self.until(lambda: sum(q.calls.values()) >= sum(before.values()) + 6)
                await asyncio.sleep(0)
                market_round = q.calls.copy()
                restarted = {key for key, count in market_round.items() if count != before[key]}
                self.assertEqual(restarted, {(share, order, fast) for share, order in grid if share in (0, 50)
                                             for fast in (False, True)})
                duplicate.set()
                await asyncio.wait_for(duplicate_published.wait(), 1)
                await asyncio.sleep(0)
                self.assertEqual(q.calls, market_round)
                core.set()
                await self.until(lambda: sum(q.calls.values()) >= sum(market_round.values()) + 6)
                after_core = q.calls.copy()
                restarted = {key for key, count in after_core.items() if count != market_round[key]}
                self.assertEqual(restarted, {(share, order, fast) for share, order in grid if share in (50, 100)
                                             for fast in (False, True)})
                finish.set()
                value = await asyncio.wait_for(task, 1)
                self.assertGreater(int(value['quotedOutput']), 100)
            finally:
                first.set(); duplicate.set(); core.set(); finish.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_child_queries_remain_parent_dependencies_after_parent_scope_exits(self):
        session = RouteBootstrap({})
        parent, unrelated = set(), set()
        release = asyncio.Event()
        async def child():
            await release.wait()
            session.offers(WETH, PAXG, 50, BLOCK)
        with session.consuming(parent):
            session.offers(WETH, CORE, 100, BLOCK)
            task = asyncio.create_task(child())
        with session.consuming(unrelated):
            session.offers(WETH, OTHER, 100, BLOCK)
        release.set()
        await task
        async def check():
            self.assertTrue(session.affected(parent))
            self.assertFalse(session.affected(unrelated))
            self.assertFalse(session.affected(set()))
            self.assertTrue(session.affected(None), 'Unknown coalesced owners remain eligible')
        await session._arrival_pass(check, {(WETH.lower(), PAXG.lower(), 50)})
        await session.close()

    async def test_shared_registry_graph_change_wakes_unrelated_query_at_batch_publication(self):
        engine = Engine()
        release, ordinary_done = asyncio.Event(), asyncio.Event()
        _, plan = market()
        branches = [{'amountIn': '100', 'hops': plan['conversions']['0:market']['branches'][0]['hops']}]
        class Provider:
            name = 'graph-arrival'
            async def discover(self, *_):
                await release.wait()
                return [branches]
        session = RouteBootstrap([PendingRouteTool(Provider())], catalog=engine.registry)
        related, unrelated, seen = set(), set(), []
        async def ordinary():
            with session.consuming(related):
                list(session.offers(WETH, CORE, 100, BLOCK))
            with session.consuming(unrelated):
                list(session.offers(WETH, OTHER, 101, BLOCK))
            ordinary_done.set()
        async def arrival():
            seen.append((session.affected(related), session.affected(unrelated)))
        task = asyncio.create_task(session.run(ordinary(), arrival))
        try:
            await ordinary_done.wait()
            # PoolProducer/other connector owners share this real inventory;
            # no registry load callback belongs to this particular mutation.
            pool = synthetic_pool(OTHER, CORE, 956, 'v2')
            engine.registry.inventory[pool['id']] = pool
            release.set()
            await asyncio.wait_for(task, 1)
            self.assertEqual(seen, [(True, True)])
            self.assertEqual(session.catalog_revision, 1)
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_supply_normalized_failed_shared_follower_remains_unknown_on_arrival(self):
        """Actual cached supply aliases coalesce; the follower did not read hints."""
        arrival, finish, ordinary_done = (asyncio.Event() for _ in range(3))
        hop = {'pool': synthetic_pool(CORE, WETH, 957, 'v2'), 'zeroForOne': CORE.lower() < WETH.lower()}
        class Provider:
            name = 'supply-arrival'
            async def discover_batches(self, *_):
                await arrival.wait()
                yield [[{'amountIn': '50', 'hops': [hop]}]]
                await finish.wait()
        class Controlled(Quotes):
            def __init__(self):
                super().__init__(Engine())
                self.core_state_cache.value['supply'] = 50
                self.calls = Counter()
            async def candidate(self, request, share, order, block, *args, first=False, **options):
                self.calls[first] += 1
                self_outer.assertEqual(request['inputs'][0]['amount'], '50')
                list(search_module.current_bootstrap().offers(CORE, WETH, 50, block))
                await asyncio.sleep(0)
                raise QuoteFailure('quote-contract-reverted')
        self_outer = self
        q = Controlled()
        q.route_provider_factory = lambda: [PendingRouteTool(Provider())]
        request = {'intent': 3, 'inputs': [{'currency': CORE, 'amount': '100'}], 'outputCurrency': WETH}
        original_run = RouteBootstrap.run
        async def run(session, ordinary, *args, **kwargs):
            async def observed():
                await ordinary
                ordinary_done.set()
            return await original_run(session, observed(), *args, **kwargs)
        with patch.object(RouteBootstrap, 'run', run), patch.object(search_module, 'explore', AsyncMock()):
            task = asyncio.create_task(q.quote(request))
            try:
                await asyncio.wait_for(ordinary_done.wait(), 1)
                self.assertEqual(q.calls, {True: 1, False: 1}, 'The two funded owners actually coalesced')
                arrival.set()
                await self.until(lambda: q.calls[True] == 2 and q.calls[False] == 2)
                finish.set()
                with self.assertRaises(QuoteFailure):
                    await asyncio.wait_for(task, 1)
            finally:
                arrival.set(); finish.set()
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_native_duplicate_origins_merge_without_repricing_and_maps_clear(self):
        request, plan = market(native=True)
        chosen = plan['conversions']['0:market']
        branches = [{'amountIn': '10000', 'hops': [{'kind': 'wrap', 'currencyOut': WETH},
                    *deepcopy(chosen['branches'][0]['hops'])]}]
        async def supplier(*_):
            return [deepcopy(branches)]
        session = RouteBootstrap({'first': supplier, 'other': supplier})
        value = {'plan': deepcopy(plan)}
        async def ordinary():
            list(session.offers(request['inputs'][0]['currency'], CORE, 10000, BLOCK))
        async def noop():
            pass
        await session.run(ordinary(), noop, origins=lambda: session.merge_quote_origins(value))
        self.assertTrue({'first', 'other'} <= set(value['routeOrigins']['discoveryProviders']))
        self.assertNotIn('first', chosen['discoveryOrigins'])
        self.assertFalse(session._known_offers)
        self.assertFalse(session._offer_origins)
        self.assertFalse(session._query_revisions)

    async def test_completed_prefix_duplicate_merges_origin_without_another_revision(self):
        _, plan = market()
        session = RouteBootstrap({})
        session.offers(WETH, CORE, 10000, BLOCK)
        query = RouteQuery(WETH.lower(), CORE.lower(), 10000, BLOCK)
        hops = plan['conversions']['0:market']['branches'][0]['hops']
        self.assertTrue(session.publish_completed(query, hops, ['first-prefix']))
        revision = session.revision
        self.assertFalse(session.publish_completed(query, hops, ['later-prefix']))
        self.assertEqual(session.revision, revision)
        value = {'plan': deepcopy(plan)}
        session.merge_quote_origins(value)
        self.assertTrue({'first-prefix', 'later-prefix'} <= set(value['routeOrigins']['discoveryProviders']))
        await session.close()

    async def test_catalog_arrival_and_explicit_retry_keep_failed_route_retryable(self):
        route = [{'kind': 'wrap', 'currencyOut': CORE}]
        session = RouteBootstrap({})
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '100'}], 'outputCurrency': CORE}
        tracker = SearchSession(1)
        tracker.discovery_done.set()
        async def families(*_):
            return [('one', [(route, ['fixture'])])]
        q = SimpleNamespace(amm=SimpleNamespace(async_family_offers=families))
        attempts = []
        async def evaluate(*args, **kwargs):
            attempts.append(True)
            raise QuoteFailure('quote-contract-reverted')
        async def run():
            await explore(q, request, BLOCK, tracker, evaluate, lambda: {}, observations={})
        with patch('cybergold_candidate.quoter.exploration.recover_selected', AsyncMock(return_value=[])):
            with budget_context(QuoteBudget()), bootstrap_scope(session):
                await run()
                await session._arrival_pass(run, {(WETH.lower(), CORE.lower(), 100)})
                self.assertEqual(len(attempts), 1, 'Unchanged path is not a newly arrived nomination')
                await session._arrival_pass(run, None)  # Catalog/state invalidation remains broad.
                await run()  # Ordinary explicit retry is not a failure-cache lookup.
        self.assertEqual(len(attempts), 3)
        await session.close()

    async def test_failed_family_recovery_retries_when_its_consumed_child_query_changes(self):
        route = [{'kind': 'wrap', 'currencyOut': CORE}]
        session = RouteBootstrap({})
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '100'}], 'outputCurrency': CORE}
        tracker = SearchSession(1)
        tracker.discovery_done.set()
        async def families(*_): return [('one', [(route, ['fixture'])])]
        q = SimpleNamespace(amm=SimpleNamespace(async_family_offers=families))
        attempts, repairs = [], []
        async def evaluate(*args, **kwargs):
            attempts.append(True)
            raise QuoteFailure('quote-contract-reverted')
        async def recovery(*args, **kwargs):
            repairs.append(True)
            list(session.offers(WETH, PAXG, 17, BLOCK))
            return []
        async def run():
            await explore(q, request, BLOCK, tracker, evaluate, lambda: {}, observations={})
        with patch('cybergold_candidate.quoter.exploration.recover_selected', recovery):
            with budget_context(QuoteBudget()), bootstrap_scope(session):
                await run()
                await session._arrival_pass(run, {(WETH.lower(), CORE.lower(), 100)})
                self.assertEqual(len(attempts), 1)
                await session._arrival_pass(run, {(WETH.lower(), PAXG.lower(), 17)})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(repairs), 2)
        await session.close()
        self.assertFalse(session._family_queries)

    def test_offer_identity_preserves_lots_native_direction_and_authority(self):
        _, plan = market()
        a = [{'amountIn': '100', 'hops': deepcopy(plan['conversions']['0:market']['branches'][0]['hops'])}]
        original = RouteBootstrap._nomination_identity(a)
        for kind in ('lot', 'direction', 'authority', 'spacing', 'native', 'precision', 'chain'):
            b = deepcopy(a)
            if kind == 'lot': b[0]['amountIn'] = '101'
            if kind == 'direction': b[0]['hops'][0]['zeroForOne'] = not b[0]['hops'][0]['zeroForOne']
            if kind == 'authority': b[0]['hops'][0]['pool']['address'] = OTHER
            if kind == 'spacing': b[0]['hops'][0]['pool']['tickSpacing'] = 60
            if kind == 'native': b[0]['hops'].insert(0, {'kind': 'wrap', 'currencyOut': WETH})
            if kind == 'precision': b[0]['hops'][0]['pool']['token0']['decimals'] = 6
            if kind == 'chain': b[0]['hops'][0]['pool']['token0']['chainId'] = 10
            self.assertNotEqual(RouteBootstrap._nomination_identity(b), original, kind)
        b = deepcopy(a)
        b[0]['hops'][0]['pool'].update(symbol='display only', liquidity='old supplier hint')
        self.assertEqual(RouteBootstrap._nomination_identity(b), original)


if __name__ == '__main__':
    unittest.main()
