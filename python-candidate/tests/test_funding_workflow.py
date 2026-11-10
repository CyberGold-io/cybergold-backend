"""Funding refinements use the serving search's publication and ownership path."""
import asyncio
from contextlib import aclosing
from copy import deepcopy
import hashlib
import json
from types import MethodType
import unittest
from unittest.mock import AsyncMock, patch

from eth_utils.abi import collapse_if_tuple
from web3 import Web3

from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.helpers_execution import ABI, argument
from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.core_funding import compose_remaining_budget
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.plan_call import METHOD, compile_call
from cybergold_candidate.quoter.plan_simulation import HelpersPlanSimulation
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.route_work_slots import bootstrap_priority, engine_work
from test_universal_quote import Quotes, Engine, CORE, PAXG, request


class FundingWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        q = Quotes(Engine())
        q.route_provider_factory = lambda: []
        q.amm.async_family_offers = AsyncMock(return_value=[])
        req = {key: value for key, value in request().items()
               if key in ('intent', 'inputs', 'outputCurrency')}
        selected_calls = []

        async def candidate(funded, *args, selected=None, **kwargs):
            amount = funded['inputs'][0]['amount']
            if selected is not None:
                selected_calls.append(amount)
            plan = deepcopy(selected) if selected else {
                'allocations': [{'kind': 0, 'amountIn': amount}], 'conversions': {},
                'body': {'branches': [{'kind': 0, 'amountIn': amount, 'data': {
                    'basketAssets': [], 'acquisitions': [], 'continuations': []}}]}}
            return {'request': deepcopy(funded), 'inputs': deepcopy(funded['inputs']),
                    'plan': plan, 'quotedOutput': '5000', 'routeFamily': 'core',
                    'estimatedRecipientOutputs': [{'kind': 0, 'token': CORE, 'id': '0', 'amount': '5000'}],
                    'estimatedRetainedInputCharges': [], 'conversionObservations': [],
                    'fees': {'coreProtocolFeeCygld': '0', 'coreHelpersFeeCygld': '0', 'marketFeeCygld': '0'},
                    'searchCoverage': {}, 'context': {'chainId': 1, 'blockTag': 'latest'}}
        q.candidate = candidate
        return q, req, selected_calls

    @staticmethod
    def smaller(value, amount='8000'):
        plan = deepcopy(value['plan'])
        plan['allocations'][0]['amountIn'] = plan['body']['branches'][0]['amountIn'] = amount
        return {'inputs': [{**value['inputs'][0], 'amount': amount}], 'plan': plan,
                'phase': 'core-consumption'}

    async def test_pending_useful_validation_does_not_block_independent_core_funding(self):
        # Control-flow observations only, not SDK or EVM economics acceptance.
        q, req, _ = self.fixture()
        original = q.candidate
        entered, release, drained, ready = (asyncio.Event() for _ in range(4))
        async def candidate(funded, *args, **kwargs):
            if funded['inputs'][0]['amount'] == '9000':
                entered.set()
                try:
                    await release.wait()
                finally:
                    drained.set()
            return await original(funded, *args, **kwargs)
        q.candidate = candidate
        async def alternatives(_q, value, *args, **kwargs):
            yield {**self.smaller(value, '9000'), 'phase': 'useful-core-residual'}
            yield self.smaller(value)
        async def publish(frame):
            if frame['type'] == 'qualified' and frame['value']['inputs'][0]['amount'] == '8000':
                self.assertFalse(release.is_set())
                ready.set()
        with patch('cybergold_candidate.quoter.search.core_funding_alternatives', alternatives):
            operation = asyncio.create_task(Quoter.get(q, req, on_update=publish))
            waiting = asyncio.create_task(ready.wait())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                await asyncio.wait((operation, waiting), timeout=1,
                                   return_when=asyncio.FIRST_COMPLETED)
                self.assertTrue(ready.is_set(), 'Pending C+U validation blocked independent pure-Core publication')
                self.assertFalse(drained.is_set())
            finally:
                operation.cancel(); waiting.cancel()
                await asyncio.gather(operation, waiting, return_exceptions=True)
                release.set()
        self.assertTrue(drained.is_set())

    async def test_pending_primary_composition_does_not_block_fresh_residual_funding(self):
        # Fixed nominations and observations isolate serving dependencies; no
        # synthetic Core result is claimed as real contract qualification.
        q, req, _ = self.fixture()
        primary, release, fresh, ready = (asyncio.Event() for _ in range(4))
        orders = {order: asyncio.Event() for order in (True, False)}
        started, drained = [], []
        measured = [{'branch': 0, 'index': 0, 'currency': PAXG, 'consumed': 100,
                     'acquired': 300, 'residual': 200}]
        async def sized(_q, value, _measured, residuals, *args):
            return self.smaller(value, '7000' if residuals else '8000')
        async def conversion(source, target, amount, *args, capture, **kwargs):
            if source.lower() == req['inputs'][0]['currency'].lower():
                primary.set()
                await release.wait()
                raise QuoteFailure('quote-no-route')
            fresh.set()
            route = {'inputCurrency': source, 'outputCurrency': target, 'routes': []}
            capture.update(inputCurrency=source, outputCurrency=target, branches=[], template=route,
                           _observation={'consumedInput': '50'})
            return route, 50, []
        q.conversion = conversion
        async def composition(_q, value, proposal, *args, core_first=None, **kwargs):
            identity = proposal['inputs'][0]['amount'], core_first
            started.append(identity)
            if identity[0] == '8000':
                orders[core_first].set()
            try:
                async with aclosing(compose_remaining_budget(_q, value, proposal, *args,
                        core_first=core_first, **kwargs)) as alternatives:
                    async for composed in alternatives:
                        yield composed
            finally:
                drained.append(identity)
        async def publish(frame):
            if frame['type'] == 'qualified' and frame['value']['inputs'][0]['amount'] == '7000':
                self.assertFalse(release.is_set())
                ready.set()
        with patch('cybergold_candidate.quoter.core_funding.project_core_inputs', return_value=measured), \
                patch('cybergold_candidate.quoter.core_funding._sized', sized), \
                patch('cybergold_candidate.quoter.search.compose_remaining_budget', composition):
            operation = asyncio.create_task(Quoter.get(q, req, on_update=publish))
            waiting = asyncio.create_task(ready.wait())
            try:
                await asyncio.wait_for(primary.wait(), 2)
                await asyncio.wait_for(asyncio.gather(*(event.wait() for event in orders.values())), 2)
                await asyncio.wait((operation, waiting), timeout=1,
                                   return_when=asyncio.FIRST_COMPLETED)
                self.assertTrue(fresh.is_set(), 'Pending primary-market composition blocked fresh residual discovery')
                self.assertTrue(ready.is_set(), 'Fresh residual funding never reached publication')
                self.assertFalse(drained, 'Both composition orders must still be pending')
            finally:
                operation.cancel(); waiting.cancel()
                await asyncio.gather(operation, waiting, return_exceptions=True)
                release.set()
        self.assertCountEqual(drained, started, 'Cancellation must drain every started composition owner')
        self.assertEqual(started.count(('8000', True)), 1)
        self.assertEqual(started.count(('8000', False)), 1)

    async def test_distinct_repaired_route_owns_one_measured_funding_pass(self):
        # A controlled failed/successful Helpers boundary tests lineage only;
        # these observations do not establish any real EVM economic outcome.
        q, req, _ = self.fixture()
        original, roots, repaired, ready = q.candidate, [], [], asyncio.Event()
        def continuation_fee(plan):
            rows = plan['body']['branches'][0]['data']['continuations']
            routes = rows[0]['route']['routes'] if rows else []
            return routes[0]['steps'][0]['fee'] if routes else None
        def route(fee):
            return {'inputCurrency': PAXG, 'outputCurrency': CORE, 'routes': [{'sharePpm': 0,
                'steps': [{'kind': 1, 'currencyOut': CORE, 'fee': fee, 'tickSpacing': 0}]}]}
        async def candidate(funded, *args, selected=None, **kwargs):
            fee = continuation_fee(selected) if selected else None
            if selected is not None and fee == 100:
                error = QuoteFailure('quote-contract-reverted')
                error.unsettled_intermediate = {'currency': PAXG, 'amount': 1}
                raise error
            if selected is not None and fee is None:
                raise QuoteFailure('quote-no-route')  # Unrelated retention fallback.
            value = await original(funded, *args, selected=selected, **kwargs)
            if fee == 3000 and funded['inputs'][0]['amount'] == '9000':
                value['estimatedRetainedInputCharges'] = [{'currency': PAXG, 'amount': '100', 'branch': 0, 'stage': 0}]
                repaired.append(value['inputs'][0]['amount'])
            return value
        q.candidate = candidate
        async def alternatives(_q, value, *args, **kwargs):
            fee = continuation_fee(value['plan'])
            roots.append((fee, value['inputs'][0]['amount']))
            if fee == 3000:
                yield self.smaller(value)
            else:
                proposal = self.smaller(value, '9000')
                data = proposal['plan']['body']['branches'][0]['data']
                data.update(basketAssets=[PAXG], continuations=[{'route': route(100), 'feeCygld': '0'}])
                proposal['plan']['conversions']['0:residual:0'] = {
                    'inputCurrency': PAXG, 'outputCurrency': CORE, 'branches': [], 'template': route(100)}
                yield {**proposal, 'phase': 'useful-core-residual'}
        async def repair(_q, funded, selected, block, *, unsettled, attempt):
            replacement = deepcopy(selected)
            replacement['body']['branches'][0]['data']['continuations'][0]['route'] = route(3000)
            replacement['conversions']['0:residual:0']['template'] = route(3000)
            return await attempt({'inputs': deepcopy(funded['inputs']), 'plan': replacement})
        async def publish(frame):
            if frame['type'] == 'qualified' and frame['value']['inputs'][0]['amount'] == '8000':
                ready.set()
        with patch('cybergold_candidate.quoter.search.core_funding_alternatives', alternatives), \
                patch('cybergold_candidate.quoter.core_market_recovery.compose_core_market', repair):
            async with asyncio.timeout(5):
                result = await Quoter.get(q, req, on_update=publish)
        self.assertEqual(repaired, ['9000'], 'The distinct repaired body must actually succeed with surplus')
        self.assertTrue(ready.is_set(), 'A distinct successful repaired route inherited funding-only suppression')
        self.assertEqual(result['inputs'][0]['amount'], '8000')
        self.assertEqual(roots, [(None, '10001'), (3000, '9000')],
                         'Each new root owns one pass; its resized child must not recursively restart it')

    async def test_incumbent_publishes_before_one_owned_deduplicated_refinement(self):
        q, req, selected = self.fixture()
        q.conversion = AsyncMock(side_effect=QuoteFailure('quote-no-route'))
        published, roots = [], []

        async def alternatives(_q, value, block, observations, **options):
            self.assertTrue(published, 'The incumbent must publish before optional inverse work')
            roots.append(value['inputs'][0]['amount'])
            proposal = self.smaller(value)
            yield proposal
            yield deepcopy(proposal)

        async def publish(frame):
            if frame['type'] == 'qualified':
                published.append(deepcopy(frame['value']))

        with patch('cybergold_candidate.quoter.search.core_funding_alternatives', alternatives):
            async with asyncio.timeout(5):
                result = await Quoter.get(q, req, on_update=publish)
        self.assertEqual(roots, ['10001'], 'Derived observations must not restart the same pass')
        self.assertEqual(selected, ['8000'], 'Equivalent proposals must share one complete evaluation')
        self.assertEqual(q.conversion.await_count, 2,
                         'Equivalent proposals must share the same two composition orders')
        self.assertEqual(result['inputs'][0]['amount'], '8000')
        self.assertEqual(result['request']['inputs'], req['inputs'])
        self.assertEqual(result['searchCoverage']['selectedPhase'], 'core-consumption')
        self.assertNotIn('inputLimitObserved', result['searchCoverage'])
        self.assertEqual(published[0]['inputs'], req['inputs'])

    async def test_cancellation_drains_pending_funding_producer(self):
        q, req, selected = self.fixture()
        entered, drained = asyncio.Event(), asyncio.Event()

        async def alternatives(*args, **options):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield {}
            finally:
                drained.set()

        with patch('cybergold_candidate.quoter.search.core_funding_alternatives', alternatives):
            task = asyncio.create_task(Quoter.get(q, req))
            try:
                async with asyncio.timeout(5):
                    await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(drained.is_set())
                self.assertEqual(selected, [])
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_changed_core_observation_reprices_same_derived_body(self):
        q, req, selected = self.fixture()
        original, count, roots = q.candidate, 0, []

        async def observed(*args, **kwargs):
            nonlocal count
            value = await original(*args, **kwargs)
            if kwargs.get('selected') is None:
                count += 1
                value['pricingEvidence'] = {'stages': [{'consumedInput': str(4000 if count == 1 else 4001)}]}
            return value

        async def alternatives(_q, value, *args, **options):
            roots.append(value['pricingEvidence']['stages'][0]['consumedInput'])
            yield self.smaller(value)
            yield self.smaller(value)

        q.candidate = observed
        with patch('cybergold_candidate.quoter.search.core_funding_alternatives', alternatives):
            async with asyncio.timeout(5):
                result = await Quoter.get(q, req)
        self.assertCountEqual(roots, ['4000', '4001'])
        self.assertEqual(selected, ['8000', '8000'])
        self.assertEqual(result['inputs'][0]['amount'], '8000')

    async def test_optional_funding_error_preserves_valid_incumbent(self):
        q, req, _ = self.fixture()

        async def alternatives(*args, **options):
            raise RuntimeError('Optional inverse pricing unavailable')
            yield {}

        with patch('cybergold_candidate.quoter.search.core_funding_alternatives', alternatives):
            async with asyncio.timeout(5):
                result = await Quoter.get(q, req)
        self.assertEqual(result['inputs'], req['inputs'])
        self.assertEqual(result['quotedOutput'], '5000')

    async def test_inverse_nomination_reuses_original_input_maxima(self):
        q, req, selected = self.fixture()

        async def alternatives(_q, value, *args, **options):
            proposal = self.smaller(value)
            proposal['inputs'][0]['amount'] = '20000'
            proposal['plan']['allocations'][0]['amountIn'] = '20000'
            proposal['plan']['body']['branches'][0]['amountIn'] = '20000'
            yield proposal

        with patch('cybergold_candidate.quoter.search.core_funding_alternatives', alternatives):
            async with asyncio.timeout(5):
                result = await Quoter.get(q, req)
        self.assertEqual(result['inputs'], req['inputs'])
        self.assertEqual(selected, [])

    async def test_oversized_base_does_not_exclude_its_fitting_recomposition(self):
        # Controlled observations preserve the existing per-complete-body budget
        # boundary; an advisory base is not eligibility for another composition.
        q, req, selected = self.fixture()
        req['inputs'][0]['currency'] = PAXG
        original, published = q.candidate, []
        async def candidate(funded, *args, selected=None, **kwargs):
            value = await original(funded, *args, selected=selected, **kwargs)
            if selected is not None:
                self.assertLessEqual(int(funded['inputs'][0]['amount']), int(req['inputs'][0]['amount']))
                value['quotedOutput'] = '6000'
                value['estimatedRecipientOutputs'][0]['amount'] = '6000'
            return value
        q.candidate = candidate
        async def sized(_q, value, *args):
            proposal = self.smaller(value)
            identity = {'inputCurrency': PAXG, 'outputCurrency': PAXG, 'routes': []}
            retained = {'inputCurrency': PAXG, 'outputCurrency': CORE, 'routes': []}
            proposal['plan']['body']['branches'][0]['data'].update(
                basketAssets=[PAXG], acquisitions=[{'amountIn': '8000', 'route': identity}],
                continuations=[{'route': retained, 'feeCygld': '0'}])
            proposal['plan']['conversions']['0:residual:0'] = {
                'inputCurrency': PAXG, 'outputCurrency': CORE, 'branches': [], 'template': retained}
            market = {'kind': 1, 'amountIn': '12000', 'data': {
                'route': {'inputCurrency': req['inputs'][0]['currency'],
                          'outputCurrency': CORE, 'routes': []}, 'feeCygld': '0'}}
            proposal['plan']['body']['branches'].append(market)
            proposal['plan']['allocations'].append({'kind': 1, 'amountIn': '12000'})
            proposal['inputs'][0]['amount'] = '20000'
            return proposal
        async def conversion(source, target, amount, *args, capture, **kwargs):
            self.assertEqual(amount, 2001)
            route = {'inputCurrency': source, 'outputCurrency': target, 'routes': []}
            capture.update(inputCurrency=source, outputCurrency=target, branches=[], template=route)
            return route, 1, []
        q.conversion = AsyncMock(side_effect=conversion)
        async def publish(frame):
            if frame['type'] == 'qualified':
                published.append(deepcopy(frame['value']))
        measured = [{'branch': 0, 'index': 0, 'currency': PAXG,
                     'consumed': 8000, 'acquired': 8000, 'residual': 0}]
        with patch('cybergold_candidate.quoter.core_funding.project_core_inputs', return_value=measured), \
                patch('cybergold_candidate.quoter.search.project_core_inputs', return_value=measured), \
                patch('cybergold_candidate.quoter.core_funding._sized', sized):
            async with asyncio.timeout(5):
                result = await Quoter.get(q, req, on_update=publish)
        self.assertEqual(result['quotedOutput'], '6000')
        self.assertEqual(result['inputs'], req['inputs'])
        self.assertNotIn('20000', selected)
        self.assertEqual(selected, ['10001', '10001'])
        self.assertEqual(q.conversion.await_count, 2)
        self.assertEqual(published[-1]['searchCoverage']['selectedPhase'], 'core-market-funding')

    async def test_captured_useful_funding_publishes_while_unrelated_priority_work_continues(self):
        for fixture, empty_history in (
                ('core-funding-usdt-100k-20261109.json', False),
                ('core-funding-eth-100-v3-20261110.json', True)):
            with self.subTest(fixture=fixture, empty_history=empty_history):
                await self.assert_captured_funding_publishes(fixture, empty_history=empty_history)

    async def assert_captured_funding_publishes(self, fixture, *, empty_history):
        # This is full serving/search integration with actual captured pool
        # states and the installed SDK. Helpers replies are recorded actual
        # contract bytes, bound to exact complete calldata/funding overrides;
        # the test does not claim fresh EVM execution or a timing guarantee.
        from test_core_funding import CoreFundingTests
        from test_economic_quote_api import SharedStore
        from test_quoter_plan_simulation import Rpc

        q, root, captured = CoreFundingTests.captured_actual_service(self, fixture)
        registry = q.engine.registry
        q.conversion = MethodType(Quoter.conversion, q)
        q.seed_routes = lambda *_: None  # Only this fixture's observed catalog.
        q.discover = AsyncMock()  # No remote inventory/connector supplier.
        q.route_provider_factory = lambda: [CustomRoutes(registry)]
        assets = root['plan']['body']['branches'][0]['data']['basketAssets']
        q.basis_reader = AsyncMock(return_value=(deepcopy(assets), [600000, 400000]))
        self.addAsyncCleanup(q.close)

        def call_identity(params):
            return hashlib.sha256(json.dumps(params, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

        recorded = captured['pricingReducedRpc']
        pinned = ({'number': int(captured['sourceAnchor']['blockNumber']),
                   'hash': captured['sourceAnchor']['blockHash']} if empty_history else None)
        contract = Web3().eth.contract(abi=ABI)
        original_call = compile_call(root['request'], root['plan'], chain=31338,
            helpers=q.helpers, core=q.core, contract=contract, block=pinned)
        actual_root_wire = Web3.to_hex(Web3().codec.encode([collapse_if_tuple(METHOD['outputs'][0])],
            [argument(root['pricingEvidence']['rawTradeResult'], METHOD['outputs'][0])]))
        if 'pricingRootRpc' in captured:
            self.assertEqual(call_identity(original_call.params), captured['pricingRootRpc']['paramsSha256'])
            root_response = captured['pricingRootRpc']['response']
        else:
            root_response = {'result': actual_root_wire}
        replies = {call_identity(original_call.params): root_response,
                   recorded['paramsSha256']: recorded['response']}
        observed_calls = []
        class RecordedProvider:
            async def make_request(self, method, params):
                identity = call_identity(params)
                observed_calls.append(identity)
                if method != 'eth_call' or identity not in replies:
                    # Other ordinary candidates lack a recorded observation.
                    raise QuoteFailure('quote-no-route')
                await asyncio.sleep(0)
                return deepcopy(replies[identity])
        registry.get_rpc = lambda: Rpc(RecordedProvider())
        simulator = HelpersPlanSimulation(q.settings, registry, helpers=q.helpers,
            adapter=q.adapter, core=q.core, now=lambda: root['context']['observedAt'],
            semaphore=q.engine.semaphore)
        async def simulate(funded, plan, **options):
            if pinned is not None:
                options['block'] = pinned
            return await simulator(funded, plan, **options)
        q.plan_simulator = simulate
        store = SharedStore()
        if empty_history:
            # A controlled initial complete nomination enters the real
            # candidate/Helpers path, with no stored, neighbor or route seed.
            # This tests serving ownership, not hosted catalog discovery.
            original_candidate = q.candidate
            async def candidate(funded, share, *args, selected=None, **options):
                if selected is None and share == 100 and funded['inputs'] == root['inputs']:
                    selected = deepcopy(root['plan'])
                return await original_candidate(funded, share, *args, selected=selected, **options)
            q.candidate = candidate
            q.exploration_block = AsyncMock(return_value=deepcopy(pinned))
            self.assertEqual(store.rows, {})
            self.assertEqual(store.family_rows, {})
        else:
            store.memory_lookup = lambda *_args, **_kwargs: deepcopy(root)
            store.memory_neighbors = lambda *_args, **_kwargs: [
                {'family': root['routeFamily'], 'side': 'lower', 'quote': deepcopy(root)}]
        service = EconomicQuotes(q, store)
        self.addAsyncCleanup(service.close)

        release_unrelated_tail, smaller_ready, root_ready, all_competed = (
            asyncio.Event() for _ in range(4))
        completed_rounds = [0] * 64
        selected, delivered, compositions = [], [], set()
        async def publish(frame):
            value = frame.get('value') or {}
            if frame['type'] == 'qualified':
                delivered.append(deepcopy(value))
                if value['inputs'] == root['inputs']:
                    root_ready.set()
            if (value and int(value['inputs'][0]['amount']) < int(root['inputs'][0]['amount'])
                    and int(value['quotedOutput']) >= int(root['quotedOutput'])):
                self.assertFalse(release_unrelated_tail.is_set())
                selected.append(deepcopy(value))
                smaller_ready.set()
        pool = deepcopy(captured['pools'][0])
        async def competitor(index):
            if empty_history:
                await root_ready.wait()
            with bootstrap_priority():
                while not release_unrelated_tail.is_set():
                    async with engine_work(q.engine.semaphore):
                        await q.engine.sdk.request({'operation': 'quote', 'pools': [deepcopy(pool)],
                            'poolId': pool['id'], 'mode': 'exactIn', 'zeroForOne': False,
                            'amount': str(1_000_000+index*1000+completed_rounds[index])})
                    completed_rounds[index] += 1
                    if all(completed_rounds):
                        all_competed.set()
                    await asyncio.sleep(0)

        async def parked_composition(*args, core_first=None, **kwargs):
            compositions.add(core_first)
            await release_unrelated_tail.wait()
            for _ in ():
                yield _

        composition_patch = patch('cybergold_candidate.quoter.search.compose_remaining_budget', parked_composition)
        composition_patch.start()
        competitors = [asyncio.create_task(competitor(index)) for index in range(64)]
        operation = asyncio.create_task(service.progressive(root['request'], publish))
        ready = asyncio.create_task(smaller_ready.wait())
        try:
            # A cleanup allowance for a frozen test, not a product selection
            # deadline: the unrelated priority tail stays ready until finally.
            async with asyncio.timeout(10):
                done, _ = await asyncio.wait((operation, ready), return_when=asyncio.FIRST_COMPLETED)
                if operation in done:
                    await operation
                self.assertTrue(smaller_ready.is_set())
                await all_competed.wait()
            self.assertTrue(all(completed_rounds), 'The competing priority work must actually run')
            self.assertIn(recorded['paramsSha256'], observed_calls)
            for key, expected in recorded['expected'].items():
                self.assertEqual(selected[-1][key], expected)
            self.assertEqual(selected[-1]['inputs'], recorded['expected']['inputs'])
            self.assertEqual(selected[-1]['quotedOutput'], recorded['expected']['quotedOutput'])
            self.assertEqual(compositions, {True, False})
            if empty_history:
                self.assertTrue(root_ready.is_set())
                self.assertEqual(delivered[0]['inputs'], root['inputs'])
                self.assertTrue(all(value.get('observation', {}).get('source') != 'stored' for value in delivered))
        finally:
            release_unrelated_tail.set()
            for task in (operation, ready, *competitors):
                if not task.done():
                    task.cancel()
            await asyncio.gather(operation, ready, *competitors, return_exceptions=True)
            composition_patch.stop()


if __name__ == '__main__':
    unittest.main()
