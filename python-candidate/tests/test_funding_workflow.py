"""Funding refinements use the serving search's publication and ownership path."""
import asyncio
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
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.plan_call import METHOD, compile_call
from cybergold_candidate.quoter.plan_simulation import HelpersPlanSimulation
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.route_work_slots import bootstrap_priority, engine_work
from test_universal_quote import Quotes, Engine, CORE, request


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
    def smaller(value):
        plan = deepcopy(value['plan'])
        plan['allocations'][0]['amountIn'] = plan['body']['branches'][0]['amountIn'] = '8000'
        return {'inputs': [{**value['inputs'][0], 'amount': '8000'}], 'plan': plan,
                'phase': 'core-consumption'}

    async def test_incumbent_publishes_before_one_owned_deduplicated_refinement(self):
        q, req, selected = self.fixture()
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

    async def test_captured_useful_funding_publishes_while_unrelated_priority_work_continues(self):
        # This is full serving/search integration with actual captured pool
        # states and the installed SDK. Helpers replies are recorded actual
        # contract bytes, bound to exact complete calldata/funding overrides;
        # the test does not claim fresh EVM execution or a timing guarantee.
        from test_core_funding import CoreFundingTests
        from test_economic_quote_api import SharedStore
        from test_quoter_plan_simulation import Rpc

        q, root, captured = CoreFundingTests.captured_actual_service(self)
        registry = q.engine.registry
        q.conversion = MethodType(Quoter.conversion, q)
        q.seed_routes = lambda *_: None  # This fixture owns four observed pools.
        q.discover = AsyncMock()  # No remote inventory/connector supplier.
        q.route_provider_factory = lambda: [CustomRoutes(registry)]
        assets = root['plan']['body']['branches'][0]['data']['basketAssets']
        q.basis_reader = AsyncMock(return_value=(deepcopy(assets), [600000, 400000]))
        self.addAsyncCleanup(q.close)

        def call_identity(params):
            return hashlib.sha256(json.dumps(params, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

        recorded = captured['pricingReducedRpc']
        contract = Web3().eth.contract(abi=ABI)
        original_call = compile_call(root['request'], root['plan'], chain=31338,
            helpers=q.helpers, core=q.core, contract=contract)
        actual_root_wire = Web3.to_hex(Web3().codec.encode([collapse_if_tuple(METHOD['outputs'][0])],
            [argument(root['pricingEvidence']['rawTradeResult'], METHOD['outputs'][0])]))
        replies = {call_identity(original_call.params): {'result': actual_root_wire},
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
        q.plan_simulator = HelpersPlanSimulation(q.settings, registry, helpers=q.helpers,
            adapter=q.adapter, core=q.core, now=lambda: root['context']['observedAt'],
            semaphore=q.engine.semaphore)
        store = SharedStore()
        store.memory_lookup = lambda *_args, **_kwargs: deepcopy(root)
        store.memory_neighbors = lambda *_args, **_kwargs: [
            {'family': root['routeFamily'], 'side': 'lower', 'quote': deepcopy(root)}]
        service = EconomicQuotes(q, store)
        self.addAsyncCleanup(service.close)

        release_unrelated_tail, smaller_ready = asyncio.Event(), asyncio.Event()
        completed_rounds = [0] * 64
        selected = []
        async def publish(frame):
            value = frame.get('value') or {}
            if (value and int(value['inputs'][0]['amount']) < int(root['inputs'][0]['amount'])
                    and int(value['quotedOutput']) >= int(root['quotedOutput'])):
                self.assertFalse(release_unrelated_tail.is_set())
                selected.append(deepcopy(value))
                smaller_ready.set()
        pool = deepcopy(captured['pools'][0])
        async def competitor(index):
            with bootstrap_priority():
                while not release_unrelated_tail.is_set():
                    async with engine_work(q.engine.semaphore):
                        await q.engine.sdk.request({'operation': 'quote', 'pools': [deepcopy(pool)],
                            'poolId': pool['id'], 'mode': 'exactIn', 'zeroForOne': False,
                            'amount': str(1_000_000+index*1000+completed_rounds[index])})
                    completed_rounds[index] += 1
                    await asyncio.sleep(0)

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
            self.assertTrue(all(completed_rounds), 'The competing priority work must actually run')
            self.assertIn(recorded['paramsSha256'], observed_calls)
            for key, expected in recorded['expected'].items():
                self.assertEqual(selected[-1][key], expected)
            self.assertEqual(selected[-1]['inputs'][0]['amount'], '33134152568')
            self.assertEqual(selected[-1]['quotedOutput'], '249741636318399242213')
        finally:
            release_unrelated_tail.set()
            for task in (operation, ready, *competitors):
                if not task.done():
                    task.cancel()
            await asyncio.gather(operation, ready, *competitors, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
