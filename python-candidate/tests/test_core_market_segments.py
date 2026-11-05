"""Amount-sensitive tools must optimize the market lots actually produced by Core.

The complete-plan test oracle uses real SDK pool arithmetic and an explicit
synthetic Core preview. Hosted responses supply only structured topology;
actual local tools run their real child algorithms.
"""
import asyncio
from copy import deepcopy
import json
import unittest
from types import SimpleNamespace

import httpx

from cybergold_candidate.quoter.alpha_routes import AlphaRoutes
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.hosted_routes import UniRouteApiProvider, UniswapApiProvider
from cybergold_candidate.quoter.market_segments import (
    market_segment_scope, observe_market_segments, observed_market_amount, observed_market_revision)
from cybergold_candidate.quoter.uniroute_routes import UnirouteLocal
from cybergold_candidate.quoter.route_tools import RouteTool, CandidateFeed, PendingRouteTool
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from quoter_fixture import service, synthetic_pool
from test_universal_quote import CORE, PAXG, OTHER, WETH, BLOCK


REQUEST = {'intent': 1, 'inputs': [{'currency': CORE, 'amount': '10000'}], 'outputCurrency': WETH}


class MarketAmountObservationTests(unittest.TestCase):
    def quote(self, amount):
        return {'plan': {'conversions': {'0:redeem:0': {'inputCurrency': PAXG, 'outputCurrency': WETH}}},
                'conversionObservations': [{'operation': '0:redeem:0', 'fundedInput': str(amount)}]}

    def test_actual_lots_replace_nominal_queries_without_repeat_feedback_or_slot_leaks(self):
        args = (REQUEST, 100, 'core-first', '0:redeem:0', PAXG, WETH, 1)
        with market_segment_scope():
            baseline = observed_market_revision(REQUEST, 100, 'core-first')
            self.assertEqual(observed_market_amount(*args), 1)
            self.assertTrue(observe_market_segments(self.quote(5000), REQUEST, 100, 'core-first'))
            measured = observed_market_revision(REQUEST, 100, 'core-first')
            self.assertNotEqual(measured, baseline)
            self.assertEqual(observed_market_amount(*args), 5000)
            self.assertFalse(observe_market_segments(self.quote(5000), REQUEST, 100, 'core-first'))
            self.assertEqual(observed_market_revision(REQUEST, 100, 'core-first'), measured)
            # Different allocation/funding owns its own Core-produced lot.
            self.assertEqual(observed_market_amount(REQUEST, 25, 'core-first', *args[3:]), 1)
            changed = {**REQUEST, 'inputs': [{'currency': CORE, 'amount': '20000'}]}
            self.assertEqual(observed_market_amount(changed, *args[1:]), 1)
            self.assertTrue(observe_market_segments(self.quote(6000), REQUEST, 100, 'core-first'))
            self.assertFalse(observe_market_segments(self.quote(5000), REQUEST, 100, 'core-first'))
            self.assertEqual(observed_market_amount(*args), 5000)
            self.assertEqual(observed_market_revision(REQUEST, 100, 'core-first'), measured)
        with market_segment_scope():
            self.assertEqual(observed_market_amount(*args), 1)


def fixture(test, *, remote_pools=False):
    direct = synthetic_pool(PAXG, WETH, 7901, 'v2')
    first = synthetic_pool(PAXG, OTHER, 7902, 'v2')
    first['reserve0' if first['token0']['address'].lower() == OTHER.lower() else 'reserve1'] = str(3*10**9)
    second = synthetic_pool(OTHER, WETH, 7903, 'v2')
    seed = synthetic_pool(PAXG, CORE, 7904, 'v4', liquidity=10**12)
    q = service(test, [direct, seed] if remote_pools else [direct, first, second, seed])
    registry = q.engine.registry
    registry.chain = 31338
    for pool in (direct, first, second, seed):
        for token in ('token0', 'token1'):
            pool[token]['chainId'] = 31338
        registry.observed[pool['id']] = deepcopy(pool)
    for pool in registry.inventory.values():
        for token in ('token0', 'token1'):
            pool[token]['chainId'] = 31338
    async def basis(_):
        return [PAXG], [1_000_000]
    async def outputs(_):
        return [{'kind': 0, 'token': PAXG, 'id': '0', 'amount': '1'}]
    async def preview(mode, value, _):
        assert mode == 'redeem-exact-in'
        return {'projectedCoreOutputs': [{'kind': 0, 'token': PAXG, 'id': '0',
                                         'amount': str(int(value['grossCygldIn'])//2)}],
                'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
    async def discover(*_):
        pass
    q.basis_reader, q.core_outputs, q.preview = basis, outputs, preview
    q.seed_routes, q.discover = lambda *_: None, discover
    return q, direct, first, second


def structured_pool(source, target):
    return {'type': 'v2-pool', 'tokenIn': {'address': source}, 'tokenOut': {'address': target},
            'amountIn': str(2**255), 'amountOut': str(2**256-1)}


def unsettled_fixture(test):
    """A genuine SDK partial fill in a Core-produced currency, then a funded fallback."""
    q, direct, first, second = fixture(test)
    thin = synthetic_pool(PAXG, WETH, 7901, 'v3', liquidity=10**5)
    medium = synthetic_pool(PAXG, WETH, 7905, 'v2')
    for pool in (thin, medium):
        for token in ('token0', 'token1'):
            pool[token]['chainId'] = 31338
        q.engine.registry.inventory[pool['id']] = deepcopy(pool)
        q.engine.registry.observed[pool['id']] = deepcopy(pool)
    def route(pools):
        source, hops = PAXG.lower(), []
        for pool in pools:
            direction = source == pool['token0']['address'].lower()
            hops.append({'pool': deepcopy(pool), 'zeroForOne': direction})
            source = pool['token1' if direction else 'token0']['address'].lower()
        return hops
    control = SimpleNamespace(bad=route((thin,)), medium=route((medium,)), good=route((first, second)),
        calls=[], errors=[], attempts=[], closed=False, pending_done=asyncio.Event())
    leaf = q.plan_simulator
    async def simulate(request, selected, **options):
        control.attempts.append(deepcopy(selected))
        value = await leaf(request, selected, **options)
        unmet = next((row for row in value['estimatedRetainedInputCharges']
                      if row['currency'].lower() == PAXG.lower()), None)
        if unmet is not None:
            error = QuoteFailure('quote-contract-reverted')
            error.unsettled_intermediate = {'currency': PAXG, 'amount': int(unmet['amount'])}
            control.errors.append(error)
            raise error
        return value
    q.plan_simulator = simulate
    return q, control, leaf


class CoreMarketFailureBootstrapTests(unittest.IsolatedAsyncioTestCase):
    def tool(self, q, control, paths, *, pending=None):
        class Ready(RouteTool):
            name = 'controlled-ready-alternatives'
            def discover(self, query):
                control.calls.append(query.amount)
                return CandidateFeed(available=[[{'amountIn': str(query.amount), 'hops': deepcopy(path)}]
                    for path in paths(query.amount)], pending=pending(query) if pending else None)
            async def close(self):
                control.closed = True
        q.route_provider_factory = lambda: [Ready()]

    async def test_failed_first_core_leg_bootstraps_full_funding_then_explores_actual_lot(self):
        q, control, _ = unsettled_fixture(self)
        self.tool(q, control, lambda amount: (control.bad, control.medium) if amount == 1 else
                  (control.bad, control.medium, control.good))
        updates = []
        async def publish(frame):
            if frame['type'] == 'qualified':
                updates.append(deepcopy(frame['value']))
        async with asyncio.timeout(5):
            value = await q.get(REQUEST, publish, core_only=True)
        self.assertEqual(control.calls, [1, 5000])
        self.assertEqual(value['inputs'], REQUEST['inputs'])
        self.assertEqual(updates[0]['searchCoverage']['selectedPhase'], 'core-market-bootstrap')
        self.assertGreater(int(value['quotedOutput']), int(updates[0]['quotedOutput']))
        self.assertEqual(len(value['plan']['conversions']['0:redeem:0']['branches'][0]['hops']), 2)
        self.assertEqual(value['conversionObservations'][0]['fundedInput'], '5000')
        self.assertEqual(value['plan']['conversions']['0:redeem:0']['discoveryOrigins'],
                         ['controlled-ready-alternatives'])
        self.assertTrue(control.errors)
        self.assertTrue(control.closed)
        # The recovery replaces only a market leg. Core allocation/descriptors
        # and full request funding remain the complete Helpers call's inputs.
        initial = control.attempts[0]
        repaired = next(plan for plan in control.attempts
                        if plan['conversions']['0:redeem:0']['branches'][0]['hops'] == control.medium)
        self.assertEqual(initial['allocations'], repaired['allocations'])
        self.assertEqual(initial['body']['branches'][0]['amountIn'], repaired['body']['branches'][0]['amountIn'])
        self.assertEqual(initial['body']['branches'][0]['data']['expectedOutputs'],
                         repaired['body']['branches'][0]['data']['expectedOutputs'])

    async def test_late_ready_topology_is_not_masked_by_failed_plan_repair_dedup(self):
        q, control, _ = unsettled_fixture(self)
        failed = asyncio.Event()
        leaf = q.plan_simulator
        async def simulate(*args, **options):
            try:
                return await leaf(*args, **options)
            except QuoteFailure:
                failed.set()
                raise
        q.plan_simulator = simulate
        async def late(query):
            try:
                await failed.wait()
                await asyncio.sleep(0)
                return [[{'amountIn': str(query.amount), 'hops': deepcopy(control.good)}]]
            finally:
                control.pending_done.set()
        self.tool(q, control, lambda amount: (control.bad,), pending=late)
        async with asyncio.timeout(5):
            value = await q.get(REQUEST, core_only=True)
        self.assertEqual(control.calls, [1, 5000])
        self.assertEqual(value['inputs'], REQUEST['inputs'])
        self.assertGreater(int(value['quotedOutput']), 10_000)
        self.assertTrue(control.pending_done.is_set())
        self.assertTrue(control.closed)

    async def test_downstream_remainder_replaces_whole_unknown_core_funded_leg(self):
        from cybergold_candidate.quoter.amm import PartialPath
        from cybergold_candidate.quoter.contracts import capture_paths
        q, control, leaf = unsettled_fixture(self)
        thin = synthetic_pool(OTHER, WETH, 7907, 'v3', liquidity=10**5)
        for token in ('token0', 'token1'):
            thin[token]['chainId'] = 31338
        q.engine.registry.observed[thin['id']] = deepcopy(thin)
        bad = [deepcopy(control.good[0]),
               {'pool': thin, 'zeroForOne': thin['token0']['address'].lower() == OTHER.lower()}]
        remainders = []
        async def simulate(request, selected, **options):
            with capture_paths():
                try:
                    return await leaf(request, selected, **options)
                except PartialPath as partial:
                    last = partial.trace.hops[-1]
                    source = last.hop['pool']['token0' if last.hop['zeroForOne'] else 'token1']['address']
                    error = QuoteFailure('quote-contract-reverted')
                    error.unsettled_intermediate = {'currency': source, 'amount': last.funded-last.consumed}
                    remainders.append(deepcopy(error.unsettled_intermediate))
                    raise error from None
        q.plan_simulator = simulate
        class Ready(RouteTool):
            def __init__(self, name, path):
                self.name, self.path = name, path
            def discover(self, query):
                control.calls.append(query.amount)
                return CandidateFeed(available=[[{'amountIn': str(query.amount), 'hops': deepcopy(self.path)}]])
        q.route_provider_factory = lambda: [Ready('thin-downstream', bad), Ready('full-funding', control.medium)]
        async with asyncio.timeout(5):
            value = await q.get(REQUEST, core_only=True)
        self.assertTrue(remainders)
        self.assertTrue(all(row['currency'].lower() == OTHER.lower() for row in remainders))
        self.assertEqual(set(control.calls), {1, 5000})
        self.assertEqual(value['inputs'], REQUEST['inputs'])
        self.assertEqual(value['conversionObservations'][0]['fundedInput'], '5000')
        self.assertEqual(value['plan']['conversions']['0:redeem:0']['discoveryOrigins'], ['full-funding'])

    async def test_scalar_issuance_residual_recovers_without_resizing_acquisitions(self):
        paxg = synthetic_pool(WETH, PAXG, 7921, 'v2')
        other = synthetic_pool(WETH, OTHER, 7922, 'v2')
        thin = synthetic_pool(OTHER, PAXG, 7923, 'v3', liquidity=10**5)
        seed = synthetic_pool(PAXG, CORE, 7924, 'v4', liquidity=10**12)
        q = service(self, [paxg, other, thin, seed])
        def route(pools, source):
            result = []
            for pool in pools:
                direction = source.lower() == pool['token0']['address'].lower()
                result.append({'pool': deepcopy(pool), 'zeroForOne': direction})
                source = pool['token1' if direction else 'token0']['address']
            return result
        bad, good = route((thin, seed), OTHER), route((other, paxg, seed), OTHER)
        async def preview(mode, value, _):
            self.assertEqual(mode, 'issue-exact-in')
            return {'netCygldOut': '16000', 'amountsInExact': ['8000', '8000'],
                'orderedCoreAssets': [PAXG, OTHER],
                'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
        async def discover(*_):
            pass
        q.preview, q.discover, q.seed_routes = preview, discover, lambda *_: None
        leaf, attempts, queries = q.plan_simulator, [], []
        async def simulate(request, selected, **options):
            attempts.append(deepcopy(selected))
            value = await leaf(request, selected, **options)
            unmet = next((row for row in value['estimatedRetainedInputCharges']
                          if row['currency'].lower() == OTHER.lower()), None)
            if unmet is not None:
                error = QuoteFailure('quote-contract-reverted')
                error.unsettled_intermediate = {'currency': OTHER, 'amount': int(unmet['amount'])}
                raise error
            return value
        q.plan_simulator = simulate
        class Ready(RouteTool):
            name = 'issuance-ready-market-legs'
            def discover(self, query):
                queries.append((query.source, query.target, query.amount))
                key = query.source.lower(), query.target.lower()
                paths = {
                    (WETH.lower(), PAXG.lower()): [route((paxg,), WETH)],
                    (WETH.lower(), OTHER.lower()): [route((other,), WETH)],
                    (PAXG.lower(), CORE.lower()): [route((seed,), PAXG)],
                    (OTHER.lower(), CORE.lower()): [bad, good],
                }.get(key, [])
                return CandidateFeed(available=[[{'amountIn': str(query.amount), 'hops': path}] for path in paths])
        q.route_provider_factory = lambda: [Ready()]
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '20000'}], 'outputCurrency': CORE}
        async with asyncio.timeout(5):
            value = await q.get(request, core_only=True)
        self.assertEqual(value['inputs'], request['inputs'])
        self.assertGreater(int(value['quotedOutput']), 18000)
        residual = next(row for row in value['conversionObservations'] if row['operation'] == '0:residual:1')
        self.assertGreater(int(residual['fundedInput']), 1000)
        self.assertIn((OTHER.lower(), CORE.lower(), int(residual['fundedInput'])), queries)
        self.assertEqual(len(value['plan']['conversions']['0:residual:1']['branches'][0]['hops']), 3)
        repaired = next(plan for plan in attempts
                        if plan['conversions']['0:residual:1']['branches']
                        and len(plan['conversions']['0:residual:1']['branches'][0]['hops']) == 3)
        self.assertEqual(attempts[0]['body']['branches'][0]['data']['acquisitions'],
                         repaired['body']['branches'][0]['data']['acquisitions'])

    async def test_all_alternatives_fail_preserves_original_error_and_drains_provider(self):
        q, control, _ = unsettled_fixture(self)
        thin = synthetic_pool(PAXG, OTHER, 7906, 'v3', liquidity=10**5)
        for token in ('token0', 'token1'):
            thin[token]['chainId'] = 31338
        q.engine.registry.observed[thin['id']] = deepcopy(thin)
        other = [{'pool': thin, 'zeroForOne': thin['token0']['address'].lower() == PAXG.lower()},
                 deepcopy(control.good[1])]
        async def empty(_):
            try:
                await asyncio.sleep(0)
                return []
            finally:
                control.pending_done.set()
        self.tool(q, control, lambda amount: (control.bad, other), pending=empty)
        async with asyncio.timeout(5):
            with self.assertRaises(QuoteFailure) as raised:
                await q.get(REQUEST, core_only=True)
        self.assertIs(raised.exception, control.errors[0])
        self.assertEqual(control.calls, [1])
        self.assertEqual(sum(plan['conversions']['0:redeem:0']['branches'][0]['hops'] == other
                             for plan in control.attempts), 1)
        self.assertTrue(control.pending_done.is_set())
        self.assertTrue(control.closed)

    async def test_caller_cancellation_propagates_and_drains_bootstrap_and_provider(self):
        q, control, _ = unsettled_fixture(self)
        entered, cancelled = asyncio.Event(), asyncio.Event()
        leaf = q.plan_simulator
        async def simulate(request, selected, **options):
            hops = selected['conversions']['0:redeem:0']['branches'][0]['hops']
            if hops == control.medium:
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await leaf(request, selected, **options)
        q.plan_simulator = simulate
        async def pending(_):
            try:
                await asyncio.Event().wait()
            finally:
                control.pending_done.set()
        self.tool(q, control, lambda amount: (control.bad, control.medium), pending=pending)
        task = asyncio.create_task(q.get(REQUEST, core_only=True))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(cancelled.is_set())
        self.assertTrue(control.pending_done.is_set())
        self.assertTrue(control.closed)


class CoreMarketToolIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_measured_lot_ranks_all_nominees_after_a_detailed_baseline_was_coalesced(self):
        q, direct, first, second = fixture(self, remote_pools=True)
        # A complete leaf oracle with no AMM SDK callbacks cannot accidentally
        # invalidate construction through a completed-prefix Bootstrap revision.
        baseline = await q.candidate(REQUEST, 100, 'core-first', BLOCK, [PAXG], [1_000_000], first=True)
        explored = []
        def output(route, amount):
            current = amount
            for hop in route:
                state = q.engine.registry.observation(hop['pool'])
                left, right = ('reserve0', 'reserve1') if hop['zeroForOne'] else ('reserve1', 'reserve0')
                current = current*997*int(state[right])//(int(state[left])*1000+current*997)
            return current
        async def price_path(route, amount, *_):
            explored.append((len(route), amount))
            return amount, output(route, amount)
        q.price_path = price_path
        async def simulate(request, selected, **_):
            value = deepcopy(baseline)
            value['plan'] = deepcopy(selected)
            value['plan']['body']['branches'][0]['data']['expectedOutputs'][0]['amount'] = '5000'
            current = output(selected['conversions']['0:redeem:0']['branches'][0]['hops'], 5000)
            value['quotedOutput'] = str(current)
            value['conversionObservations'][0]['output'] = str(current)
            value['estimatedRecipientOutputs'][0]['amount'] = str(current)
            return value
        q.plan_simulator = simulate
        original = q.candidate
        async def detailed_only(request, *args, first=False, **options):
            if first:
                raise QuoteFailure('quote-no-route')
            return await original(request, *args, first=False, **options)
        q.candidate = detailed_only
        calls = []
        class Immediate(RouteTool):
            name = 'controlled-immediate'
            def discover(self, query):
                calls.append(query.amount)
                candidates = []
                for rows in ((direct,), (first, second)):
                    source, hops = query.source.lower(), []
                    for pool in rows:
                        direction = source == pool['token0']['address'].lower()
                        hops.append({'pool': deepcopy(pool), 'zeroForOne': direction})
                        source = pool['token1' if direction else 'token0']['address'].lower()
                    candidates.append([{'amountIn': str(query.amount), 'hops': hops}])
                return CandidateFeed(available=candidates)
        q.route_provider_factory = lambda: [Immediate()]
        async with asyncio.timeout(5):
            value = await q.get(REQUEST, core_only=True)
        self.assertEqual(calls, [1, 5000])
        self.assertEqual(value['metrics']['routeDiscovery']['revision'], 0)
        self.assertEqual(set(explored), {(1, 5000), (2, 5000)})
        self.assertGreater(int(value['quotedOutput']), 10_000)

    async def test_pending_hosted_prefix_exploration_does_not_hold_complete_quote_publication(self):
        q, direct, first, second = fixture(self)
        q.settings.CYBERGOLD_UNISWAP_API_KEY = 'fixture-only'
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def blocked_prefix(*_args, **_options):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        provider_engine = SimpleNamespace(registry=q.engine.registry, semaphore=q.engine.semaphore,
            quote_sdk_branches=blocked_prefix, uniswap_api_queue=q.engine.uniswap_api_queue)
        provider = UniRouteApiProvider(provider_engine, q.settings, client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'quote': {'route': []}}))))
        q.route_provider_factory = lambda: [CustomRoutes(q.engine.registry), PendingRouteTool(provider)]
        budget, qualified = QuoteBudget(), []
        async def publish(frame):
            if frame['type'] == 'qualified':
                await asyncio.wait_for(entered.wait(), 1)
                self.assertFalse(cancelled.is_set())
                qualified.append(deepcopy(frame['value']))
                budget.finish_selection('best-initial')
        async with asyncio.timeout(8):
            with budget_context(budget):
                value = await q.get(REQUEST, publish)
        self.assertTrue(qualified)
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(provider.client)

    async def test_actual_core_output_amount_drives_both_hosted_routes_and_complete_repricing(self):
        for guidestar in (False, True):
            with self.subTest(guidestar=guidestar):
                q, direct, first, second = fixture(self, remote_pools=True)
                q.settings.CYBERGOLD_UNISWAP_API_KEY = 'fixture-only'
                payloads = []
                async def respond(request):
                    payload = json.loads(request.content)
                    payloads.append(payload)
                    path = [PAXG, OTHER, WETH] if int(payload['amount']) > 1 else [PAXG, WETH]
                    if guidestar:
                        document = {'quote': {'route': [], 'swapSteps': [{'type': 'V2_SWAP_EXACT_IN',
                            'path': path, 'amountIn': payload['amount']}]}}
                    else:
                        document = {'quote': {'route': [[structured_pool(a, b) for a, b in zip(path, path[1:])]],
                                              'routeCandidates': [{}]}}
                    return httpx.Response(200, json=document)
                cls = UniswapApiProvider if guidestar else UniRouteApiProvider
                provider = cls(q.engine, q.settings, **({'guidestar': True} if guidestar else {}),
                    client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
                q.route_provider_factory = lambda: [CustomRoutes(q.engine.registry), PendingRouteTool(provider)]
                updates = []
                async def publish(frame):
                    if frame['type'] == 'qualified':
                        updates.append(deepcopy(frame['value']))
                async with asyncio.timeout(12):
                    value = await q.get(REQUEST, publish, core_only=True)
                self.assertEqual({row['amount'] for row in payloads}, {'1', '5000'})
                self.assertEqual(len(payloads), 2, 'the measured lot must not produce a requery cycle')
                self.assertTrue(all(row['tokenIn'].lower() == PAXG.lower() and row['tokenOut'].lower() == WETH.lower()
                                    and row['tokenInChainId'] == row['tokenOutChainId'] == 1 for row in payloads))
                self.assertGreater(int(value['quotedOutput']), min(int(row['quotedOutput']) for row in updates))
                self.assertGreater(int(value['quotedOutput']), 10_000)
                self.assertLess(int(value['quotedOutput']), 20_000, 'remote advertised scalar prices are ignored')
                chosen = value['plan']['conversions']['0:redeem:0']
                self.assertEqual(len(chosen['branches'][0]['hops']), 2)
                self.assertEqual(chosen['discoveryOrigins'], [provider.name])
                self.assertEqual([row['kind'] for row in value['plan']['allocations']], [0])
                self.assertTrue(provider.client is None)

    async def test_actual_issuance_residual_routes_use_hosted_market_segment_then_local_seed(self):
        for guidestar in (False, True):
            with self.subTest(guidestar=guidestar):
                direct = synthetic_pool(OTHER, PAXG, 7911, 'v2')
                first = synthetic_pool(OTHER, WETH, 7912, 'v2')
                first['reserve0' if first['token0']['address'].lower() == WETH.lower() else 'reserve1'] = str(3*10**9)
                second = synthetic_pool(WETH, PAXG, 7913, 'v2')
                seed = synthetic_pool(PAXG, CORE, 7914, 'v4', liquidity=10**12)
                q = service(self, [direct, seed])
                q.engine.registry.chain = 31338
                for pool in (direct, first, second, seed):
                    for token in ('token0', 'token1'):
                        pool[token]['chainId'] = 31338
                    q.engine.registry.observed[pool['id']] = deepcopy(pool)
                for pool in q.engine.registry.inventory.values():
                    for token in ('token0', 'token1'):
                        pool[token]['chainId'] = 31338
                q.settings.CYBERGOLD_UNISWAP_API_KEY = 'fixture-only'
                async def basis(_):
                    return [PAXG, OTHER], [500000, 500000]
                async def preview(mode, value, _):
                    assert mode == 'issue-exact-in'
                    return {'netCygldOut': '16000', 'amountsInExact': ['8000', '8000'],
                        'orderedCoreAssets': [PAXG, OTHER],
                        'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
                q.basis_reader, q.preview = basis, preview
                q.seed_routes = lambda *_: None
                async def discover(*_):
                    pass
                q.discover = discover
                payloads = []
                async def respond(request):
                    payload = json.loads(request.content); payloads.append(payload)
                    path = [OTHER, WETH, PAXG] if int(payload['amount']) > 1 else [OTHER, PAXG]
                    if guidestar:
                        document = {'quote': {'route': [], 'swapSteps': [{'type': 'V2_SWAP_EXACT_IN',
                            'path': path, 'amountIn': payload['amount']}]}}
                    else:
                        document = {'quote': {'route': [[structured_pool(a, b) for a, b in zip(path, path[1:])]]}}
                    return httpx.Response(200, json=document)
                cls = UniswapApiProvider if guidestar else UniRouteApiProvider
                provider = cls(q.engine, q.settings, **({'guidestar': True} if guidestar else {}),
                    client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
                q.route_provider_factory = lambda: [CustomRoutes(q.engine.registry), PendingRouteTool(provider)]
                request = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '8000'},
                    {'currency': OTHER, 'amount': '10000'}], 'outputCurrency': CORE}
                async with asyncio.timeout(12):
                    value = await q.get(request)
                self.assertEqual({row['amount'] for row in payloads}, {'1', '2000'})
                self.assertEqual(len(payloads), 2)
                self.assertTrue(all(row['tokenIn'].lower() == OTHER.lower() and row['tokenOut'].lower() == PAXG.lower()
                                    and row['tokenInChainId'] == 1 for row in payloads))
                self.assertGreater(int(value['quotedOutput']), 20_000)
                chosen = value['plan']['conversions']['0:residual:1']
                self.assertEqual(len(chosen['branches'][0]['hops']), 3)
                self.assertEqual(chosen['branches'][0]['hops'][-1]['pool']['id'], seed['id'])
                self.assertEqual(chosen['discoveryOrigins'], [provider.name])
                self.assertEqual(value['inputs'], request['inputs'])

    async def test_actual_local_routers_price_the_core_produced_market_leg(self):
        for tool in (AlphaRoutes, UnirouteLocal):
            with self.subTest(tool=tool.__name__):
                q, direct, first, second = fixture(self)
                queries = []
                class Recording(tool):
                    async def discover_batches(self, source, target, amount, block):
                        queries.append((source.lower(), target.lower(), amount))
                        async for batch in super().discover_batches(source, target, amount, block):
                            yield batch
                provider = Recording(q.engine)
                q.route_provider_factory = lambda: [PendingRouteTool(provider)]
                async with asyncio.timeout(15):
                    value = await q.get(REQUEST, core_only=True)
                self.assertEqual(set(queries), {(PAXG.lower(), WETH.lower(), 1), (PAXG.lower(), WETH.lower(), 5000)})
                self.assertEqual(len(queries), 2)
                self.assertGreater(provider.diagnostics['quoteCallbacks'], 0)
                self.assertGreater(int(value['quotedOutput']), 10_000)
                self.assertEqual(value['routeOrigins']['discoveryProviders'], [provider.name])
                self.assertEqual(value['plan']['conversions']['0:redeem:0']['branches'][0]['hops'][0]['pool']['token0']['chainId'], 31338)
                self.assertIsNone(provider.process)


if __name__ == '__main__':
    unittest.main()
