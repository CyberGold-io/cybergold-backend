"""Late provider topology competes through the actual whole-plan SDK replay."""
import asyncio
from copy import deepcopy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter import search as quoter_search
from cybergold_candidate.quoter.bootstrap import current_bootstrap
from cybergold_candidate.quoter.candidate_hints import normalize_hints
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.route_tools import PendingRouteTool
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.quoter.uniroute_routes import UnirouteLocal
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.tx_preparation import TransactionPreparation
from quoter_fixture import service, synthetic_pool
from test_universal_quote import WETH, PAXG, CORE, OTHER, BLOCK, Quotes, Engine, USER, request as fixture_request


class Provider:
    name = 'controlled-topology'

    def __init__(self, route, *, failure=None):
        self.route, self.failure = route, failure
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.closed, self.cancelled, self.queries = False, 0, []

    async def discover(self, source, target, amount, block):
        self.queries.append((source, target, amount))
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        if self.failure:
            raise self.failure
        if source.lower() != WETH.lower() or target.lower() != CORE.lower():
            return []
        return [[{'amountIn': str(amount), 'hops': deepcopy(self.route)}]]

    async def close(self):
        self.closed = True


def hops(pools, source):
    result = []
    for pool in pools:
        direction = source.lower() == pool['token0']['address'].lower()
        result.append({'pool': deepcopy(pool), 'zeroForOne': direction})
        source = pool['token1' if direction else 'token0']['address']
    return result


class ParallelQuoterTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_finder_prefix_qualifies_while_deep_callback_is_blocked(self):
        connector = synthetic_pool(WETH, PAXG, 1601, 'v2')
        connector.update(reserve0=str(10**12), reserve1=str(10**12))
        anchor = synthetic_pool(PAXG, CORE, 1602, 'v3', liquidity=10**6)
        q = service(self, [connector, anchor])
        q.seed_routes = lambda *_: None
        async def discover(*_):
            pass
        q.discover = discover
        entered, release, qualified = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Local(UnirouteLocal):
            async def _quote(self, *args):
                entered.set()
                await release.wait()
                return await super()._quote(*args)
        local = Local(q.engine)
        q.route_provider_factory = lambda: [PendingRouteTool(local)]
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        budget = QuoteBudget()
        async def publish(frame):
            value = frame['value']
            if value['searchCoverage']['selectedPhase'] == 'backward-prefix':
                self.assertFalse(release.is_set())
                qualified.set()
                budget.finish_selection('best-initial')
        with budget_context(budget):
            async with asyncio.timeout(10):
                task = asyncio.create_task(q.get(request, publish))
                await entered.wait()
                await qualified.wait()
                value = await task
        self.assertEqual(value['inputs'][0]['amount'], '3025')
        self.assertEqual(value['routeOrigins']['discoveryProviders'], ['uniroute-local'])
        self.assertGreater(local.diagnostics['quoteCallbacks'], 0)
        self.assertEqual(value['metrics']['routeDiscovery']['providers']['uniroute-local']['quoteCallbacks'],
                         local.diagnostics['quoteCallbacks'])
        self.assertIsNone(local.process)
        self.assertTrue(local.closed)
        queries = local.sequence
        prepared = await TransactionPreparation(q).prepare({'quote': value, 'sender': USER, 'recipient': USER})
        self.assertEqual(prepared['economicQuote']['quotedOutput'], value['quotedOutput'])
        self.assertEqual(local.sequence, queries)

    def fine_split_fixture(self):
        narrow = synthetic_pool(WETH, PAXG, 1603, 'v3', liquidity=6*10**6)
        broad = synthetic_pool(WETH, PAXG, 1604, 'v2')
        broad.update(reserve0='80000', reserve1='80000')
        anchor = synthetic_pool(PAXG, CORE, 1605, 'v4', liquidity=10**12)
        q = service(self, [narrow, broad, anchor])
        async def basis(_):
            return [PAXG], [1000000]
        async def preview(_mode, value, _block):
            acquired = value['maximumAmountsIn'][0]
            return {'netCygldOut': str(int(acquired)*2), 'amountsInExact': [acquired],
                    'orderedCoreAssets': [PAXG],
                    'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
        q.basis_reader, q.preview = basis, preview
        q.seed_routes = lambda *_: None
        async def discover(*_):
            pass
        q.discover = discover
        entered, release, linear_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Local(UnirouteLocal):
            async def _quote(self, *args):
                entered.set()
                await release.wait()
                return await super()._quote(*args)
        local = Local(q.engine)
        q.route_provider_factory = lambda: [PendingRouteTool(local)]
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '25000'}], 'outputCurrency': CORE}
        return q, local, request, entered, release, linear_ready

    async def test_actual_later_five_percent_split_beats_early_finder_candidates(self):
        q, local, request, entered, release, linear_ready = self.fine_split_fixture()
        budget, updates = QuoteBudget(), []
        async def publish(frame):
            value = frame['value']
            updates.append(deepcopy(value))
            split = any(len(row.get('branches', [])) > 1 for row in value['plan']['conversions'].values())
            if split:
                budget.finish_selection('best-initial')
            else:
                linear_ready.set()
        with budget_context(budget):
            async with asyncio.timeout(10):
                # Isolate actual percentage-split optimization on the existing
                # Core-only grid. Full-grid serving availability is exercised
                # independently; other allocations share this same budget.
                task = asyncio.create_task(q.get(request, publish, core_only=True))
                await entered.wait()
                await linear_ready.wait()
                release.set()
                value = await task
        linear_best = max(int(item['quotedOutput']) for item in updates if not any(
            len(row.get('branches', [])) > 1 for row in item['plan']['conversions'].values()))
        self.assertGreater(int(value['quotedOutput']), linear_best)
        self.assertTrue(any(len(row.get('branches', [])) > 1 for row in value['plan']['conversions'].values()))
        self.assertEqual(value['routeOrigins']['discoveryProviders'], ['uniroute-local'])
        self.assertGreater(local.diagnostics['quoteCallbacks'], 0)
        for name, count in local.diagnostics.items():
            self.assertEqual(value['metrics']['routeDiscovery']['providers']['uniroute-local'][name], count)
        self.assertIsNone(local.process)
        replay = await q.evaluate_selected({**request, 'inputs': value['inputs']}, value['plan'])
        self.assertEqual(replay['quotedOutput'], value['quotedOutput'])

    async def test_full_grid_fine_split_retains_normal_clock_economic_floor(self):
        q, local, request, entered, release, linear_ready = self.fine_split_fixture()
        async def publish(frame):
            if not any(len(row.get('branches', [])) > 1
                       for row in frame['value']['plan']['conversions'].values()):
                linear_ready.set()
        # Unlike the isolated capability proof, no update stops this normal
        # producer clock. The matched pre-change full grid yields 48,468 at
        # funding 25,000; completed hints must preserve that economic floor.
        with budget_context(QuoteBudget()):
            async with asyncio.timeout(10):
                task = asyncio.create_task(q.get(request, publish))
                try:
                    await entered.wait()
                    await linear_ready.wait()
                    release.set()
                    value = await task
                finally:
                    release.set()
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertGreaterEqual(int(value['quotedOutput']), 48468)
        self.assertEqual(value['inputs'][0]['currency'].lower(), WETH.lower())
        self.assertLessEqual(int(value['inputs'][0]['amount']), 25000)
        self.assertGreater(local.diagnostics['quoteCallbacks'], 0)
        self.assertIsNone(local.process)
        self.assertTrue(local.closed)
        replay = await q.evaluate_selected({**request, 'inputs': value['inputs']}, value['plan'])
        self.assertEqual(replay['quotedOutput'], value['quotedOutput'])

    async def test_actual_deep_callback_failures_preserve_executable_finder_hints(self):
        connector = synthetic_pool(WETH, PAXG, 1606, 'v3', liquidity=10**9)
        anchor = synthetic_pool(PAXG, CORE, 1607, 'v4', liquidity=10**9)
        q = service(self, [connector, anchor])
        q.seed_routes = lambda *_: None
        async def discover(*_):
            pass
        q.discover = discover
        async def unavailable(*_args, **_kwargs):
            raise OSError('ordinary callback state unavailable')
        callback_engine = SimpleNamespace(registry=q.engine.registry, semaphore=q.engine.semaphore,
                                         quote_sdk_branches=unavailable)
        local = UnirouteLocal(callback_engine)
        q.route_provider_factory = lambda: [PendingRouteTool(local)]
        value = await q.get({'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE})
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(value['routeOrigins']['discoveryProviders'], ['uniroute-local'])
        self.assertGreater(local.diagnostics['quoteCallbackFailures'], 0)
        self.assertEqual(local.diagnostics['quoteCallbacks'], local.diagnostics['quoteCallbackFailures'])
        self.assertIsNone(local.process)

    async def test_actual_uniroute_refreshes_same_query_after_late_catalog_discovery(self):
        connector = synthetic_pool(WETH, PAXG, 1501, 'v3', liquidity=10**9)
        anchor = synthetic_pool(PAXG, CORE, 1502, 'v4', liquidity=10**9)
        q = service(self, [anchor])
        q.engine.registry.observed[connector['id']] = deepcopy(connector)
        q.seed_routes = lambda *_: None
        old_finished = asyncio.Event()
        pair_calls = []
        class Local(UnirouteLocal):
            async def discover_batches(self, source, target, amount, block):
                result = []
                async for batch in super().discover_batches(source, target, amount, block):
                    result.extend(batch)
                    yield batch
                if (source.lower(), target.lower(), amount) == (WETH.lower(), CORE.lower(), 10000):
                    pair_calls.append(len(result))
                    old_finished.set()
        local = Local(q.engine)
        async def delayed_discovery(*_):
            await old_finished.wait()
            q.engine.registry.inventory[connector['id']] = deepcopy(connector)
        q.discover = delayed_discovery
        q.route_provider_factory = lambda: [CustomRoutes(q.engine.registry), PendingRouteTool(local)]
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        value = await q.get(request)
        self.assertEqual(pair_calls, [0, 1])
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertIn('uniroute-local', value['routeOrigins']['discoveryProviders'])
        self.assertTrue(local.closed)
        self.assertIsNone(local.process)

    async def test_new_persisted_load_is_observed_before_connector_discovery_finishes(self):
        from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
        connector = synthetic_pool(WETH, PAXG, 1503, 'v3', liquidity=10**9)
        anchor = synthetic_pool(PAXG, CORE, 1504, 'v4', liquidity=10**9)
        q = service(self, [anchor])
        registry = q.engine.registry
        entered, release_load, release_connectors = (asyncio.Event() for _ in range(3))
        registry.load_task = None
        async def load():
            await release_load.wait()
            registry.inventory[connector['id']] = deepcopy(connector)
        async def ensure_loaded():
            registry.load_task = asyncio.create_task(load())
        async def connectors(*_):
            entered.set()
            await release_connectors.wait()
        registry.ensure_loaded = ensure_loaded
        q.engine.connector_inventory = connectors
        registry.token = lambda address, decimals: {'address': address, 'decimals': decimals, 'chainId': 1}
        async def metadata(address, _):
            return registry.token(address, 18)
        registry.token_metadata = metadata
        session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        with bootstrap_scope(session):
            task = asyncio.create_task(Quoter.discover(q, request, [PAXG, OTHER], BLOCK))
            await entered.wait()
            self.assertIs(session._catalog_load, registry.load_task)
            release_load.set()
            await registry.load_task
            await asyncio.sleep(0)
            self.assertEqual(session.revision, 1)
            self.assertFalse(task.done())
            release_connectors.set()
            await task
        await session.close()

    async def test_late_only_provider_gets_shared_partial_prefix_repair_and_keeps_its_origin(self):
        connector = synthetic_pool(WETH, PAXG, 401, 'v2', liquidity=10**12)
        anchor = synthetic_pool(PAXG, CORE, 402, 'v3', liquidity=10**6)
        q = service(self, [anchor])
        q.engine.registry.observed[connector['id']] = deepcopy(connector)
        q.seed_routes = lambda *_: None
        async def no_catalog_change(*_):
            pass
        q.discover = no_catalog_change
        provider = Provider(hops([connector, anchor], WETH))
        provider.name = 'uniroute-local'
        q.route_provider_factory = lambda: [PendingRouteTool(provider)]
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        first_exploration_done = asyncio.Event()
        original_explore = quoter_search.explore
        rounds = []
        async def observed_explore(*args, **kwargs):
            index = len(rounds)
            rounds.append(index)
            try:
                return await original_explore(*args, **kwargs)
            finally:
                if index == 0:
                    first_exploration_done.set()
        with patch.object(quoter_search, 'explore', observed_explore):
            task = asyncio.create_task(q.get(request))
            await provider.started.wait()
            await first_exploration_done.wait()
            self.assertFalse(task.done())
            # Both initial/catalog optional snapshots have exhausted before
            # this sole supplier offers a path. Its intermediate concentrated
            # pool cannot settle the original full-budget forward execution.
            provider.release.set()
            value = await task
        self.assertGreater(len(rounds), 1)
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertIn(int(value['inputs'][0]['amount']), (3025, 3035))
        self.assertEqual(value['searchCoverage']['selectedPhase'], 'backward-prefix')
        self.assertEqual(value['routeOrigins']['discoveryProviders'], ['uniroute-local'])
        optional = value['metrics']['optionalSearch']
        self.assertGreaterEqual(optional['repairs'], 1)
        self.assertLessEqual(optional['starts'], 16)
        self.assertEqual(set(value['metrics']['routeDiscovery']['providers']), {'uniroute-local'})
        self.assertEqual(set(q.engine.registry.inventory), {anchor['id']})
        self.assertTrue(provider.closed)
        queries = len(provider.queries)
        prepared = await TransactionPreparation(q).prepare({'quote': value, 'sender': USER, 'recipient': USER})
        self.assertEqual(prepared['plan']['inputs'], value['inputs'])
        self.assertEqual(prepared['economicQuote']['quotedOutput'], value['quotedOutput'])
        self.assertEqual(len(provider.queries), queries)

    async def test_sole_local_tool_has_no_hidden_custom_exploration_lane(self):
        q, request, _ = self.fixture()
        local = UnirouteLocal(q.engine)
        q.route_provider_factory = lambda: [PendingRouteTool(local)]
        value = await q.get(request)
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(value['routeOrigins']['discoveryProviders'], ['uniroute-local'])
        self.assertEqual(set(value['metrics']['routeDiscovery']['providers']), {'uniroute-local'})
        self.assertIsNone(local.process)
        class Empty:
            name = 'uniroute-local'
            async def discover(self, *_):
                return []
        q.route_provider_factory = lambda: [PendingRouteTool(Empty())]
        with self.assertRaises(QuoteFailure):
            await q.get(request)

    async def test_direct_core_basket_has_no_amm_nominator(self):
        q = Quotes(Engine())
        request = fixture_request(3)
        value = await Quoter.get(q, request)
        self.assertEqual(value['routeOrigins']['economicEvaluator'], 'cybergold-quoter')
        self.assertEqual(value['routeOrigins']['discoveryProviders'], [])
        self.assertEqual(value['metrics']['routeDiscovery']['queries'], 0)

    async def test_same_amm_tool_api_serves_market_and_market_plus_core_segments(self):
        from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
        for share in (0, 50):
            q = Quotes(Engine())
            query_rows = []
            class Spy:
                name = 'uniroute-api'
                async def discover(self, source, target, amount, block):
                    query_rows.append((source, target, amount, deepcopy(block)))
                    return []
            session = RouteBootstrap([CustomRoutes(q.engine.registry), PendingRouteTool(Spy())])
            request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10001'}],
                       'outputCurrency': CORE}
            async def no_arrival():
                pass
            with bootstrap_scope(session):
                result = await session.run(q.candidate(request, share, 'core-first', BLOCK,
                                                      [PAXG, OTHER], [500000, 500000]), no_arrival)
            kinds = {row['kind'] for row in result['plan']['allocations']}
            self.assertEqual(kinds, {1} if share == 0 else {0, 1})
            self.assertEqual(bool(q.previews), share != 0)
            self.assertTrue(query_rows)
            self.assertTrue(all(isinstance(a, str) and isinstance(b, str) and isinstance(amount, int)
                                and context == BLOCK for a, b, amount, context in query_rows))
            if share:
                pairs = {(a.lower(), b.lower()) for a, b, _, _ in query_rows}
                self.assertIn((WETH.lower(), PAXG.lower()), pairs)
                self.assertIn((WETH.lower(), OTHER.lower()), pairs)

    def fixture(self, *, better=True, failure=None):
        old = synthetic_pool(WETH, PAXG, 201, 'v3', liquidity=10**9)
        anchor = synthetic_pool(PAXG, CORE, 202, 'v4', liquidity=10**9)
        external = synthetic_pool(WETH, PAXG, 203, 'v2')
        source = 'reserve0' if WETH.lower() == external['token0']['address'].lower() else 'reserve1'
        target = 'reserve1' if source == 'reserve0' else 'reserve0'
        external[source], external[target] = str(10**9), str((3 if better else 1) * 10**9 // (1 if better else 3))
        q = service(self, [old, anchor])
        # The producer can read this physical pool; ordinary inventory has not
        # discovered it. Its supplied topology never publishes a fake price.
        q.engine.registry.observed[external['id']] = deepcopy(external)
        q.seed_routes = lambda *_: None
        async def discover(*_):
            pass
        q.discover = discover
        provider = Provider(hops([external, anchor], WETH), failure=failure)
        q.route_provider_factory = lambda: [CustomRoutes(q.engine.registry), PendingRouteTool(provider)]
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        return q, request, provider

    async def test_late_better_topology_wins_after_custom_quote_without_waiting(self):
        q, request, provider = self.fixture()
        updates, local = [], asyncio.Event()
        async def publish(frame):
            updates.append(deepcopy(frame['value']))
            local.set()
        task = asyncio.create_task(q.get(request, publish))
        await provider.started.wait()
        await local.wait()
        self.assertFalse(provider.release.is_set())
        first = int(updates[-1]['quotedOutput'])
        self.assertGreater(first, 0)
        provider.release.set()
        value = await task
        self.assertGreater(int(value['quotedOutput']), first)
        self.assertIn(value['searchCoverage']['selectedPhase'],
                      ('provider-arrival', 'provider-arrival-quick', 'route-family'))
        self.assertGreater(value['metrics']['routeDiscovery']['reevaluations'], 0)
        self.assertTrue(provider.closed)
        self.assertEqual(q.engine.semaphore._value, 8)
        # Preparation can replay the winning semantic plan without any new
        # provider discovery, despite its pool being absent from the catalog.
        queries = len(provider.queries)
        prepared = await q.evaluate_selected(request, value['plan'])
        self.assertEqual(prepared['quotedOutput'], value['quotedOutput'])
        self.assertEqual(len(provider.queries), queries)

    async def test_late_worse_topology_and_supplier_failure_preserve_local_winner(self):
        for failure in (None, OSError('private supplier diagnostic')):
            q, request, provider = self.fixture(better=False, failure=failure)
            updates, local = [], asyncio.Event()
            async def publish(frame):
                updates.append(deepcopy(frame['value']))
                local.set()
            task = asyncio.create_task(q.get(request, publish))
            await local.wait()
            first = int(updates[-1]['quotedOutput'])
            provider.release.set()
            result = await task
            self.assertGreaterEqual(int(result['quotedOutput']), first)
            self.assertNotIn('private supplier diagnostic', repr(result['metrics']))
            self.assertTrue(provider.closed)

    async def test_unrelated_hint_pool_cannot_relabel_output_as_requested_currency(self):
        q, request, provider = self.fixture()
        q.route_provider_factory = None
        baseline = await q.get(request)
        unrelated = synthetic_pool(OTHER, PAXG, 204, 'v2')
        unrelated['reserve0'], unrelated['reserve1'] = '1000000000000', '1000000000000'
        q.engine.registry.observed[unrelated['id']] = deepcopy(unrelated)
        provider.route = hops([unrelated, q.engine.registry.seed], OTHER)
        provider.release.set()
        q.route_provider_factory = lambda: [CustomRoutes(q.engine.registry), PendingRouteTool(provider)]
        result = await q.get(request)
        self.assertEqual(result['quotedOutput'], baseline['quotedOutput'])
        self.assertTrue(provider.closed)

    async def test_malformed_and_empty_optional_hints_leave_later_valid_topology(self):
        q, _, provider = self.fixture()
        malformed = [[{'amountIn': '1', 'hops': [{'pool': {'protocol': 'v2', 'id': 'bad',
            'token0': {'address': None}, 'token1': {'address': PAXG}}}]}], []]
        good = [{'amountIn': '100', 'hops': provider.route}]
        candidates = list(normalize_hints([{'branches': row, 'origins': ['test-provider']}
                                          for row in [*malformed, good]], WETH, CORE))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0][0]['amountIn'], '100')
        self.assertEqual(candidates[0][1], ['test-provider'])

    async def test_equivalent_later_nominator_enriches_origin_without_economic_replacement(self):
        q, request, provider = self.fixture()
        provider.name = 'uniswap-alpharouter'
        provider.route = hops(list(q.engine.registry.inventory.values()), WETH)
        updates, ready = [], asyncio.Event()
        async def publish(frame):
            updates.append(deepcopy(frame['value']))
            ready.set()
        task = asyncio.create_task(q.get(request, publish))
        await ready.wait()
        original = updates[-1]
        provider.release.set()
        result = await task
        self.assertEqual(result['quotedOutput'], original['quotedOutput'])
        self.assertEqual(result['searchCoverage']['selectedPhase'], original['searchCoverage']['selectedPhase'])
        self.assertEqual(result['routeOrigins']['discoveryProviders'],
                         ['cybergold-custom', 'uniswap-alpharouter'])
        chosen = deepcopy(result['plan'])
        for conversion in chosen['conversions'].values():
            conversion['discoveryOrigins'] = [{'nonsensical': 'optional'}, 123]
        # Optional provenance cannot become a replay/eligibility requirement.
        replay = await q.evaluate_selected(request, chosen)
        self.assertEqual(replay['quotedOutput'], result['quotedOutput'])

    async def test_existing_clock_keeps_completed_detailed_custom_improvement(self):
        q, request, provider = self.fixture()
        candidate = q.candidate
        detailed = asyncio.Event()
        async def controlled(*args, **kwargs):
            value = await candidate(*args, **kwargs)
            value['quotedOutput'] = '100' if kwargs.get('first') else '110'
            if not kwargs.get('first'):
                detailed.set()
            return value
        q.candidate = controlled
        updates, published_detailed = [], asyncio.Event()
        async def publish(frame):
            updates.append(int(frame['value']['quotedOutput']))
            if updates[-1] == 110:
                published_detailed.set()
        # Signal the existing selection stop only after the observed detailed
        # result. Cold child startup is not a wall-clock test condition.
        budget = QuoteBudget(initial=30, extension=0)
        with budget_context(budget):
            task = asyncio.create_task(q.get(request, publish))
            await published_detailed.wait()
            budget.finish_selection('best-initial')
            result = await task
        self.assertTrue(detailed.is_set())
        self.assertIn(110, updates)
        self.assertEqual(result['quotedOutput'], '110')
        self.assertFalse(provider.release.is_set())
        self.assertGreater(provider.cancelled, 0)
        self.assertTrue(provider.closed)

    async def test_disproof_and_caller_cancellation_drain_provider_work(self):
        for disproof in (False, True):
            q, request, provider = self.fixture(failure=SnapshotChanged('selected state changed') if disproof else None)
            task = asyncio.create_task(q.get(request))
            await provider.started.wait()
            if disproof:
                provider.release.set()
            else:
                task.cancel()
            with self.assertRaises(SnapshotChanged if disproof else asyncio.CancelledError) as raised:
                await task
            discovery = raised.exception.quoter_metrics['routeDiscovery']
            self.assertIn('controlled-topology', discovery['providers'])
            self.assertIn('physicalRpc', discovery)
            self.assertTrue(provider.closed)
            self.assertEqual(q.engine.semaphore._value, 8)
            self.assertIsNone(current_bootstrap())

    async def test_sdk_startup_cancel_acquires_and_reaps_the_created_child(self):
        entered, release = asyncio.Event(), asyncio.Event()
        create = asyncio.create_subprocess_exec
        child = None
        async def created_before_return(*args, **kwargs):
            nonlocal child
            child = await create(*args, **kwargs)
            entered.set()
            await release.wait()
            return child
        worker = SdkWorker(command=[sys.executable, '-c', 'import sys; sys.stdin.buffer.read()'])
        self.addAsyncCleanup(worker.close)
        with patch('asyncio.create_subprocess_exec', side_effect=created_before_return):
            task = asyncio.create_task(worker.request({'operation': 'fixture'}))
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(child.returncode)
        self.assertIsNone(worker.process)


if __name__ == '__main__':
    unittest.main()
