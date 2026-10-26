"""Two API clients share observations; Refresh is distinct from lookup."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import unittest

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quoter.store import EconomicQuoteStore
from cybergold_candidate.tx_preparation import TransactionPreparation
from test_universal_quote import Engine, Quotes, request


class SharedStore:
    def __init__(self):
        self.rows = {}

    def capture_scope(self, value):
        return str(value)

    async def lookup(self, value, *, scope):
        return deepcopy(self.rows.get(scope))

    async def save(self, value, quote, *, scope):
        self.rows[scope] = deepcopy(quote)
        return True


def service(store):
    quoter = Quotes(Engine())
    quoter.engine.registry.ensure_loaded = AsyncMock()
    return quoter, EconomicQuotes(quoter, store)


class EconomicQuoteApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_fork_generation_observer_runs_before_cache_lookup(self):
        quoter, _ = service(SharedStore())
        registry = quoter.engine.registry
        registry.chain = 31338
        registry.store = SimpleNamespace(scope='generation:unobserved:')
        generation = {'value': 'one'}
        async def observe():
            registry.generation = generation['value']
            registry.store.scope = 'generation:' + generation['value'] + ':'
        class MemoryScopeStore(EconomicQuoteStore):
            rows = {}
            async def lookup(self, value, *, scope):
                return deepcopy(self.rows.get(scope))
            async def save(self, value, quote, *, scope):
                self.rows[scope] = deepcopy(quote)
                return True
        store = MemoryScopeStore(quoter.settings, registry)
        quotes = EconomicQuotes(quoter, store, observe_scope=observe)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        first = await quotes.get(value)
        self.assertEqual((await quotes.get(value))['observation']['source'], 'stored')
        before = len(quoter.evaluated)
        generation['value'] = 'two'
        replacement = await quotes.get(value)
        self.assertEqual(replacement['observation']['source'], 'search')
        self.assertGreater(len(quoter.evaluated), before)
        self.assertEqual({key.namespace for key in store.rows},
                         {'generation:one:economic-quotes', 'generation:two:economic-quotes'})
        self.assertEqual(first['request'], replacement['request'])

    async def test_second_api_client_uses_original_saved_quote_without_head_read(self):
        store = SharedStore()
        first, a = service(store)
        second, b = service(store)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        app_a, app_b = create_app(economic_quotes=a), create_app(economic_quotes=b)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app_a), base_url='http://one') as client_a, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app_b), base_url='http://two') as client_b:
            initial = await client_a.post('/api/economic-quotes', json=value)
            self.assertEqual(initial.status_code, 200, initial.text)
            second.engine.block = AsyncMock(side_effect=AssertionError('lookup must not acquire a new head'))
            cached = await client_b.post('/api/economic-quotes', json={**value, 'deadline': 'ignored', 'recipient': 'ignored'})
            self.assertEqual(cached.status_code, 200, cached.text)
        measured, reused = initial.json(), cached.json()
        self.assertEqual(reused['context'], measured['context'])
        self.assertEqual(reused['plan'], measured['plan'])
        self.assertEqual(reused['quotedOutput'], measured['quotedOutput'])
        self.assertEqual(reused['observation']['source'], 'stored')
        second.engine.block.assert_not_called()
        self.assertTrue(first.evaluated)
        self.assertFalse(second.evaluated)

    async def test_refresh_replays_seed_and_failed_refresh_keeps_saved_success(self):
        store = SharedStore()
        quoter, quotes = service(store)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        observed = await quotes.get(value)
        recorded = deepcopy(store.rows)
        quote = quoter.quote
        seeds = []
        async def measured(req, **kwargs):
            seeds.append(kwargs.get('seed'))
            return await quote(req, **kwargs)
        quoter.quote = measured
        refreshed = await quotes.get(value, refresh=True)
        self.assertEqual(refreshed['observation'], {'source': 'search', 'refresh': True})
        self.assertEqual(seeds[0]['plan'], observed['plan'])
        saved = deepcopy(store.rows)
        quoter.quote = AsyncMock(side_effect=QuoteFailure('quote-no-route'))
        with self.assertRaises(QuoteFailure):
            await quotes.get(value, refresh=True)
        self.assertEqual(store.rows, saved)
        retained = await quotes.get(value)
        self.assertEqual(retained['quotedOutput'], observed['quotedOutput'])
        self.assertEqual(len(recorded), 1)

    async def test_economic_api_does_not_require_or_emit_execution_terms(self):
        _, quotes = service(SharedStore())
        app = create_app(economic_quotes=quotes)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://one') as client:
            response = await client.post('/api/economic-quotes', json=value)
            invalid = await client.post('/api/economic-quotes', json={**value, 'refresh': 'yes'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(invalid.status_code, 400)
        def check(node):
            if isinstance(node, dict):
                self.assertFalse({'deadline', 'recipient', 'outputMinimum', 'minimumOutput', 'minimumAmount', 'calldata'} & node.keys())
                for item in node.values():
                    check(item)
            elif isinstance(node, list):
                for item in node:
                    check(item)
        check(response.json())

    async def test_unusable_saved_routes_leave_ordinary_candidates_available(self):
        quoter, _ = service(SharedStore())
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        previous = await quoter.quote(value)
        unusable = deepcopy(previous)
        unusable['plan']['conversions'] = {}
        result = await quoter.quote(value, seed=unusable)
        self.assertGreater(int(result['quotedOutput']), 0)
        self.assertNotEqual(result['searchCoverage']['selectedPhase'], 'saved-plan')

    async def test_different_sized_seed_is_not_mislabeled_as_requested_funding(self):
        quoter, _ = service(SharedStore())
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        previous = await quoter.quote(value)
        changed = {**value, 'inputs': [{**value['inputs'][0], 'amount': '20002'}]}
        result = await quoter.quote(changed, seed=previous)
        self.assertEqual(sum(int(row['amountIn']) for row in result['plan']['allocations']), 20002)
        self.assertEqual(result['inputs'][0]['amount'], '20002')
        self.assertNotEqual(result['searchCoverage']['selectedPhase'], 'saved-plan')


if __name__ == '__main__':
    unittest.main()
