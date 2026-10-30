"""Cached arithmetic and actual HTTP/TradeQuotes boundaries, without RPC."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.quoter.reuse_estimate import (CachedEconomicEstimates, arithmetic_estimate,
                                                       attach_reuse_sample, sample_for_quote)
from cybergold_candidate.routing_encoding import ZERO
from cybergold_candidate.route_search import WETH
from test_trade_quote import Engines, request as trade_request
from test_economic_quote_store import fixture, CORE, USDT


def quote_sample(**changes):
    _, _, request, quote = fixture()
    request['inputs'][0]['amount'] = '1000'
    return {**quote, 'request': request, 'inputs': deepcopy(request['inputs']),
        'quotedOutput': '999', 'routeFamily': 'mixed',
        'fees': {'coreProtocolFeeCygld': '3', 'coreHelpersFeeCygld': '1', 'marketFeeCygld': '7'},
        'estimatedRetainedInputCharges': [{'branch': 0, 'stage': 0, 'currency': USDT, 'amount': '400'}],
        'context': {'chainId': 31338, 'blockNumber': '10', 'blockHash': '0x'+'ab'*32,
                    'observedAt': '2026-10-30T00:00:00Z'}, **changes}


class SampleTests(unittest.TestCase):
    def test_shared_python_typescript_integer_vectors(self):
        vectors = json.loads((Path(__file__).resolve().parents[2]/'tests/fixtures/nearby-amount-estimates.json').read_text())
        for vector in vectors:
            with self.subTest(vector['name']):
                observed = arithmetic_estimate(vector['sample'], vector['budget'])
                if vector['expected'] is None:
                    self.assertIsNone(observed)
                else:
                    self.assertEqual({key: observed[key] for key in vector['expected']}, vector['expected'])
                    self.assertEqual(observed['basis'], vector['sample']['basis'])

    def test_reference_is_consumed_not_entered_or_funded_budget(self):
        quote = quote_sample()
        sample = sample_for_quote(quote)
        self.assertEqual(sample['referenceInput'], '600')
        self.assertEqual(arithmetic_estimate(sample, 900)['amount'], '999')
        self.assertEqual(arithmetic_estimate(sample, 300)['amount'], '499')
        reduced = quote_sample(inputs=[{'currency': USDT, 'amount': '600'}], estimatedRetainedInputCharges=[])
        self.assertEqual(sample_for_quote(reduced)['referenceInput'], '600')
        self.assertEqual(reduced['request']['inputs'][0]['amount'], '1000')

    def test_output_fees_are_not_subtracted_again(self):
        sample = sample_for_quote(quote_sample())
        estimate = arithmetic_estimate(sample, 600)
        self.assertEqual(estimate['amount'], '999')
        self.assertEqual(estimate['fees'], sample['fees'])

    def test_sale_uses_consumed_principal_and_its_input_fee(self):
        quote = quote_sample(routeFamily='market')
        quote['request'] = {'intent': 1, 'inputs': [{'currency': CORE, 'amount': '1000'}], 'outputCurrency': USDT}
        quote['inputs'] = deepcopy(quote['request']['inputs'])
        quote['fees']['marketFeeCygld'] = '100'
        quote['estimatedRetainedInputCharges'] = [{'currency': CORE, 'amount': '300'}]
        quote['conversionObservations'] = [{'operation': '0:market', 'inputCurrency': CORE, 'consumedInput': '600'}]
        sample = sample_for_quote(quote)
        self.assertEqual(sample['referenceInput'], '601')
        self.assertEqual(sample['fees']['marketFeeCygld'], '1')
        self.assertEqual(sample['basis'], 'market-sale-consumed')
        del quote['context']['chainId']
        fallback = sample_for_quote(quote)
        self.assertEqual(fallback['referenceInput'], '700')
        self.assertEqual(fallback['fees']['marketFeeCygld'], '100')

    def test_intermediate_units_never_become_source_consumption(self):
        quote = quote_sample()
        quote['estimatedRetainedInputCharges'].append({'currency': CORE, 'amount': '1000000'})
        quote['conversionObservations'] = [{'inputCurrency': CORE, 'consumedInput': '2000000000'}]
        self.assertEqual(sample_for_quote(quote)['referenceInput'], '600')

    def test_explicit_native_wrap_maps_units_but_does_not_alias_request_family(self):
        quote = quote_sample()
        quote['request']['inputs'][0]['currency'] = ZERO
        quote['inputs'][0]['currency'] = ZERO
        quote['estimatedRetainedInputCharges'] = [{'currency': WETH, 'amount': '400'}]
        quote['plan'] = {'conversions': {'0:market': {'inputCurrency': ZERO,
                                                    'template': {'inputCurrency': WETH}}}}
        self.assertEqual(sample_for_quote(quote)['referenceInput'], '600')
        quote['plan']['conversions'] = {}
        self.assertEqual(sample_for_quote(quote)['referenceInput'], '1000')

    def test_legacy_funding_approximation_and_zero_reference(self):
        legacy = quote_sample()
        del legacy['estimatedRetainedInputCharges']
        self.assertEqual(sample_for_quote(legacy)['basis'], 'funded-input-approximation')
        self.assertEqual(sample_for_quote(legacy)['referenceInput'], '1000')
        legacy['estimatedRetainedInputCharges'] = [{'currency': USDT}]
        self.assertEqual(sample_for_quote(legacy)['referenceInput'], '1000')
        self.assertEqual(sample_for_quote(legacy)['basis'], 'funded-input-approximation')
        zero = quote_sample(estimatedRetainedInputCharges=[{'currency': USDT, 'amount': '1000'}])
        self.assertIsNone(sample_for_quote(zero))

    def test_metadata_does_not_mutate_economics_or_recursively_anchor_hint(self):
        original = quote_sample()
        observed = attach_reuse_sample(original)
        self.assertNotIn('reuseSample', original)
        self.assertEqual({key: value for key, value in observed.items() if key != 'reuseSample'}, original)
        observed['reuseSample']['netOutput'] = '999999999999999'
        self.assertEqual(attach_reuse_sample(observed)['reuseSample']['netOutput'], '999')


class CachedApiTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, *, upper=True):
        engines = Engines()
        quote = quote_sample()
        store = SimpleNamespace(capture_scope=lambda _request: 'existing-scope',
            neighbors=AsyncMock(return_value={'lower': None, 'upper': {'identity': 'one', 'quote': quote} if upper else None}))
        observe = AsyncMock()
        engines.quotes.cached_estimates = CachedEconomicEstimates(store, CORE, observe_scope=observe)
        engines.quotes.resolve = AsyncMock(side_effect=AssertionError('no live model/adapter acquisition'))
        engines.market.registry = SimpleNamespace(ensure_loaded=AsyncMock(side_effect=AssertionError('no registry wait')))
        engines.market.head = AsyncMock(side_effect=AssertionError('no head'))
        engines.quotes.acquire_models = AsyncMock(side_effect=AssertionError('no SDK/model acquisition'))
        return engines, store, observe, quote

    async def test_actual_api_hit_miss_and_failure_are_always_rpc_free(self):
        for scenario in ('hit', 'miss', 'store-error', 'scope-error', 'invalid-accounting'):
            with self.subTest(scenario):
                engines, store, observe, quote = self.fixture(upper=scenario != 'miss')
                if scenario == 'store-error':
                    store.neighbors.side_effect = RuntimeError('unavailable private SQL')
                if scenario == 'scope-error':
                    observe.side_effect = RuntimeError('unavailable generation SQL')
                if scenario == 'invalid-accounting':
                    quote['inputs'][0]['amount'] = 'invalid'
                app = create_app(trade_quotes=engines.quotes)
                value = {key: trade_request(amount='900')[key] for key in
                         ('side', 'mode', 'counterToken', 'native', 'amount', 'slippageBps')}
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
                    response = await client.post('/api/economic-estimates', json=value)
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(result['models'], [])
                self.assertEqual('estimate' in result, scenario == 'hit')
                if scenario == 'hit':
                    self.assertEqual(result['estimate']['amount'], '999')
                    self.assertEqual(result['estimate']['context'], quote['context'])
                    self.assertEqual(result['estimate']['sourceIdentity'], 'one')
                    self.assertEqual(result['estimate']['sourceRequestedInput'], '1000')
                observe.assert_awaited_once()
                engines.quotes.resolve.assert_not_called()
                engines.market.registry.ensure_loaded.assert_not_called()
                engines.market.head.assert_not_called()
                engines.quotes.acquire_models.assert_not_called()
                self.assertEqual((engines.heads, engines.models, engines.core_calls, engines.market_calls), (0, 0, [], []))

    async def test_native_and_sell_adapter_match_economic_request(self):
        engines, store, _, _ = self.fixture(upper=False)
        await engines.quotes.get_model(trade_request(native=True, amount='900'))
        request = store.neighbors.call_args.args[0]
        self.assertEqual(request['inputs'], [{'currency': ZERO, 'amount': '900'}])
        self.assertEqual(request['outputCurrency'], CORE)
        await engines.quotes.get_model(trade_request(side='sell', native=True, amount='900'))
        request = store.neighbors.call_args.args[0]
        self.assertEqual(request['intent'], 1)
        self.assertEqual(request['inputs'], [{'currency': CORE, 'amount': '900'}])
        self.assertEqual(request['outputCurrency'], ZERO)

    async def test_cancellation_propagates(self):
        engines, store, _, _ = self.fixture()
        store.neighbors.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await engines.quotes.get_model(trade_request())

    async def test_exact_output_preserves_existing_model_path(self):
        engines = Engines()
        engines.quotes.cached_estimates = SimpleNamespace(get_model=AsyncMock(side_effect=AssertionError('exact-in only')))
        result = await engines.quotes.get_model(trade_request(mode='exact-out'))
        self.assertEqual(result['namespace'], 'trade')
        self.assertEqual(engines.heads, 1)
        engines.quotes.cached_estimates.get_model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
