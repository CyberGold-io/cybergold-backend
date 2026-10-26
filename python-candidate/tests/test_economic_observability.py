"""Operation evidence is scoped, safe, and separate from cached economics."""
import asyncio
from copy import deepcopy
from contextvars import ContextVar
import io
import json
import logging
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from web3 import AsyncWeb3, AsyncHTTPProvider, Web3

from cybergold_candidate.app import create_app
from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.rpc_transport import rpc_provider
from cybergold_candidate.telemetry import configure_logging, operation_work, rpc_exchange
from cybergold_candidate.trade_observation import economic_evidence
from cybergold_candidate.tx_preparation import TransactionPreparation
from cybergold_candidate.uniswap_state import UniswapRpc
from test_economic_quote_api import SharedStore, service
from test_universal_quote import request, USER, PAXG


class EconomicObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = logging.getLogger('cybergold.candidate')
        previous = (list(self.logger.handlers), self.logger.level, self.logger.propagate)
        def restore():
            self.logger.handlers, self.logger.level, self.logger.propagate = previous
        self.addCleanup(restore)
        self.stream = io.StringIO()
        configure_logging(self.stream)

    def outcomes(self):
        return [row for row in map(json.loads, self.stream.getvalue().splitlines())
                if row.get('event') == 'quote_outcome']

    async def test_search_lookup_refresh_and_preparation_have_distinct_safe_evidence(self):
        store = SharedStore()
        quoter, quotes = service(store)
        app = create_app(economic_quotes=quotes,
                         transaction_preparation=TransactionPreparation(quoter, now=lambda: 2000))
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://one') as client:
            initial = await client.post('/api/economic-quotes', json=value)
            cached = await client.post('/api/economic-quotes', json=value)
            refreshed = await client.post('/api/economic-quotes', json={**value, 'refresh': True})
            prepared = await client.post('/api/tx-preparations', json={'quote': initial.json(),
                'sender': USER, 'recipient': USER, 'slippageBps': 100})
        self.assertEqual([initial.status_code, cached.status_code, refreshed.status_code, prepared.status_code], [200]*4)
        rows = self.outcomes()
        self.assertEqual([row['resultSource'] for row in rows],
                         ['search', 'stored-quote', 'refresh', 'prepared-transaction'])
        self.assertEqual([row['operationKind'] for row in rows],
                         ['quoter', 'quoter', 'quoter', 'transaction-preparation'])
        self.assertTrue(all('requestId' in row for row in rows))
        self.assertEqual(rows[0]['requestId'], initial.headers['x-cybergold-request-id'])
        self.assertEqual(rows[0]['quotedOutput'], initial.json()['quotedOutput'])
        self.assertEqual(rows[0]['funding'], initial.json()['inputs'])
        self.assertEqual(rows[0]['inputBudget'], value['inputs'])
        self.assertIn('producerMetrics', rows[0])
        self.assertIn('observedQuoteMetrics', rows[1])
        self.assertNotIn('producerMetrics', rows[1])
        self.assertNotIn('firstExecutableMs', rows[0])
        self.assertNotIn('firstExecutableMs', rows[1])
        # Neither current subscription IDs nor transport counters enter storage.
        self.assertFalse(any('requestId' in quote or 'rpc' in quote for quote in store.rows.values()))
        for text in ('calldata', 'signature', 'planDescription', 'sender', 'recipient'):
            self.assertNotIn('"'+text+'"', self.stream.getvalue())
        rendered = app.state.metrics.render().decode()
        self.assertIn('operation="/api/economic-quotes"', rendered)
        self.assertIn('operation="/api/tx-preparations"', rendered)
        samples = [sample for family in app.state.metrics.quoter_first_plan.collect()
                   for sample in family.samples if sample.name.endswith('_count')]
        self.assertEqual(sum(sample.value for sample in samples), 2)

    async def test_timeout_and_no_route_keep_error_codes_ids_and_private_producer_clocks(self):
        quoter, quotes = service(SharedStore())
        app = create_app(economic_quotes=quotes)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        errors = [QuoteFailure('quote-no-route'), TimeoutError('https://secret.invalid password=secret')]
        errors[0].quoter_metrics = {'totalMs': 15100, 'searchMs': 15000, 'selectionReason': 'timeout'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://one') as client:
            for error in errors:
                quoter.quote = AsyncMock(side_effect=error)
                response = await client.post('/api/economic-quotes', json={**value, 'refresh': True})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['requestId'], response.headers['x-cybergold-request-id'])
                self.assertIn('correlationId', response.json())
        rows = self.outcomes()
        self.assertEqual([row['code'] for row in rows], ['quote-no-route', 'quote-timeout'])
        self.assertEqual(rows[0]['producerMetrics']['selectionReason'], 'timeout')
        self.assertEqual(rows[0]['producerMetrics']['totalMs'], 15100)
        self.assertEqual(rows[0]['inputBudget'], value['inputs'])
        self.assertNotIn('secret', self.stream.getvalue())

    async def test_fast_estimator_is_observed_without_becoming_an_executable_result(self):
        estimator = SimpleNamespace(get_model=AsyncMock(return_value={
            'namespace': 'trade', 'estimate': {'strategy': 'market', 'amount': '123'}}))
        app = create_app(trade_quotes=estimator)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://one') as client:
            response = await client.post('/api/economic-estimates', json={'side': 'buy', 'mode': 'exact-in',
                'counterToken': PAXG, 'amount': '1000'})
        self.assertEqual(response.status_code, 200, response.text)
        row, = self.outcomes()
        self.assertEqual(row['operationKind'], 'fast-estimator')
        self.assertEqual(row['resultSource'], 'fast-estimate')
        self.assertEqual(row['estimatedAmount'], '123')
        self.assertNotIn('firstExecutableMs', row)

    async def test_fast_estimator_preserves_existing_supplier_failure_status(self):
        estimator = SimpleNamespace(get_model=AsyncMock(side_effect=InvalidPreview('supplier failure')))
        app = create_app(trade_quotes=estimator)
        value = {'side': 'buy', 'mode': 'exact-in', 'counterToken': PAXG, 'amount': '1000'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://one') as client:
            canonical = await client.post('/api/economic-estimates', json=value)
            legacy = await client.post('/api/quotes/trade/model', json=value)
        self.assertEqual(canonical.status_code, legacy.status_code)
        self.assertEqual(canonical.status_code, 503)
        self.assertEqual(canonical.json()['code'], legacy.json()['code'])

    async def test_telemetry_sink_failure_preserves_product_success_and_failure(self):
        quoter, quotes = service(SharedStore())
        app = create_app(economic_quotes=quotes)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        def broken(*_args, **_kwargs):
            raise RuntimeError('telemetry sink unavailable')
        with patch.object(self.logger, 'info', broken), patch.object(self.logger, 'error', broken), \
                patch.object(app.state.metrics.economic_results, 'labels', broken):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://one') as client:
                success = await client.post('/api/economic-quotes', json=value)
                self.assertEqual(success.status_code, 200, success.text)
                quoter.quote = AsyncMock(side_effect=QuoteFailure('quote-no-route'))
                failure = await client.post('/api/economic-quotes', json={**value, 'refresh': True})
                self.assertEqual(failure.status_code, 503)
                self.assertEqual(failure.json()['code'], 'quote-no-route')

    async def test_caller_cancellation_is_observed_and_still_propagates(self):
        started = asyncio.Event()
        async def pending(_value, **_kwargs):
            started.set()
            await asyncio.Event().wait()
        quotes = SimpleNamespace(get=pending)
        app = create_app(economic_quotes=quotes)
        value = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://one') as client:
            operation = asyncio.create_task(client.post('/api/economic-quotes', json=value))
            await started.wait()
            operation.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await operation
        row, = self.outcomes()
        self.assertEqual(row['outcome'], 'cancelled')
        self.assertNotIn('code', row)

    def test_projection_excludes_wallet_material_and_untrusted_metric_fields(self):
        value = {'quotedOutput': '123', 'inputs': [{'currency': PAXG, 'amount': '1000'}],
            'metrics': {'totalMs': 20, 'requestBody': 'private', 'searchMs': float('nan')},
            'context': {'chainId': 1, 'blockNumber': '10', 'blockHash': '0x'+'a'*64},
            'calldata': 'private', 'signature': 'private', 'plan': {'body': 'private'}}
        evidence = {'operationKind': 'quoter', 'resultSource': 'search',
            'rpc': {'transport': {'started': 1, 'completed': 1, 'url': 'private', 'summedExchangeMs': 8}}}
        safe = economic_evidence(value, evidence)
        self.assertNotIn('private', json.dumps(safe))
        self.assertEqual(safe['producerMetrics'], {'totalMs': 20})
        self.assertEqual(safe['rpc']['transport']['summedExchangeMs'], 8)


class OperationCounterTests(unittest.IsolatedAsyncioTestCase):
    async def test_simultaneous_scopes_keep_own_getter_demand_and_one_owned_shared_exchange(self):
        provider = rpc_provider('http://synthetic.invalid', None)
        self.addAsyncCleanup(provider.disconnect)
        rpc = UniswapRpc(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1'), AsyncWeb3(provider))
        started, release, second_joined = (asyncio.Event() for _ in range(3))
        label = ContextVar('test_counter_caller')
        async def wire(_provider, method, params):
            self.assertEqual(method, 'eth_call')
            started.set()
            await release.wait()
            return {'jsonrpc': '2.0', 'id': 1, 'result': Web3.to_hex(Web3().codec.encode(['uint256'], [123]))}
        many = rpc.reads.many
        async def subscription(*args, **kwargs):
            if label.get() == 'second':
                second_joined.set()
            return await many(*args, **kwargs)
        rpc.reads.many = subscription
        block = {'number': 10, 'hash': '0x'+'a'*64}
        async def operation(name):
            label.set(name)
            with operation_work() as work:
                for _ in range(2):
                    value = await rpc.read_function(PAXG, 'value()', [], [], ['uint256'], block)
                    self.assertEqual(value, (123,))
                return work.snapshot()
        with patch.object(AsyncHTTPProvider, 'make_request', wire):
            first = asyncio.create_task(operation('first'))
            await started.wait()
            second = asyncio.create_task(operation('second'))
            await second_joined.wait()
            release.set()
            a, b = await asyncio.gather(first, second)
        self.assertEqual(a['getterReads'], {'scope': 'hash-pinned-getter-bank',
            'requested': 2, 'issued': 1, 'coalesced': 0, 'reused': 1})
        self.assertEqual(b['getterReads'], {'scope': 'hash-pinned-getter-bank',
            'requested': 2, 'issued': 0, 'coalesced': 1, 'reused': 1})
        self.assertEqual(a['transport']['started'], 1)
        self.assertEqual(a['transport']['completed'], 1)
        self.assertEqual(b['transport']['started'], 0)
        self.assertGreaterEqual(a['transport']['summedExchangeMs'], 0)

    async def test_summed_exchange_time_has_its_own_coordinate_and_scope_resets(self):
        with operation_work() as work, patch('cybergold_candidate.telemetry.time.perf_counter',
                                             side_effect=[0, 0, 1, 1]):
            with rpc_exchange(), rpc_exchange():
                pass
            snapshot = work.snapshot()
        self.assertEqual(snapshot['transport']['summedExchangeMs'], 2000)
        self.assertNotIn('durationMs', snapshot)
        with operation_work() as fresh:
            self.assertEqual(fresh.snapshot()['transport']['started'], 0)


if __name__ == '__main__':
    unittest.main()
