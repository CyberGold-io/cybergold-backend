"""Funding refinements use the serving search's publication and ownership path."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, patch

from cybergold_candidate.quoter import Quoter
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


if __name__ == '__main__':
    unittest.main()
