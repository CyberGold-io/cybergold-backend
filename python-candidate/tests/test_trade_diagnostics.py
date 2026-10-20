"""Subscriber correlation, semantic failures and safe additive instrumentation."""
import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.diagnostics import project
from cybergold_candidate.quote_errors import QuoteFailure
from test_trade_quote import Engines, request
from test_quote_intent import request as intent_request, service as intent_service
from cybergold_candidate.quote_cache import IntentSharing
from cybergold_candidate.shared_reads import SharedReads

ATTEMPTS = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222']


def samples(metric):
    return [row for family in metric.collect() for row in family.samples if not row.name.endswith('_created')]


class TradeDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_qualified_quotes_measure_first_result_but_indicative_models_do_not(self):
        class Quotes:
            async def get(self, value):
                return {'mode':value['mode'], 'context':{'chainId':1,'blockNumber':'123'},'result':{}}
            async def get_model(self, value):
                return {'namespace':'market','routes':[]}
            async def close(self):
                pass
        app = create_app(basket_preview=Quotes(),market_quotes=Quotes())
        async with app.router.lifespan_context(app),httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate',level='INFO') as captured:
                basket = await client.post('/api/quotes/basket-preview',json={'mode':'issue-exact-in','maximumAmountsIn':['10']})
                market = await client.post('/api/quotes/market',json={**request(),'adapter':'0x'+'5'*40})
                model = await client.post('/api/quotes/market/model',json={**request(),'adapter':'0x'+'5'*40})
        self.assertEqual([basket.status_code,market.status_code,model.status_code],[200,200,200])
        first = samples(app.state.metrics.quote_first_executable)
        self.assertEqual({row.labels['operation'] for row in first}, {'/api/quotes/basket-preview','/api/quotes/market'})
        provider = samples(app.state.metrics.quote_provider_outcomes)
        self.assertEqual({(row.labels['strategy'],row.labels['outcome'],row.value) for row in provider},
                         {('core','succeeded',1),('market','succeeded',1)})
        records = [json.loads(row.getMessage()) for row in captured.records]
        outcome = next(row for row in records if row.get('operation')=='/api/quotes/basket-preview' and row.get('event')=='quote_outcome')
        self.assertEqual(outcome['mode'],'issue-exact-in')
        self.assertEqual(outcome['direction'],'issue')
        self.assertEqual(outcome['inputMode'],'exact-in')

    async def test_intent_market_and_model_errors_keep_the_same_safe_error_contract(self):
        class Unavailable:
            async def get(self, *args):
                raise QuoteFailure('rpc-timeout', diagnostics={'rpcMethod':'eth_call', 'stage':'contract-read'})
            async def get_model(self, *args):
                return await self.get()
            async def close(self):
                pass
        cases = [('quote_intent', '/api/quotes/intent/stream', intent_request('issue-exact-out'), 200),
                 ('market_quotes', '/api/quotes/market/stream', {**request(), 'adapter':'0x'+'5'*40}, 200),
                 ('trade_quotes', '/api/quotes/trade/model', request(), 503)]
        for slot, path, body, status in cases:
            with self.subTest(path=path):
                app = create_app(**{slot:Unavailable()})
                async with app.router.lifespan_context(app), httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                    with self.assertLogs('cybergold.candidate', level='ERROR') as captured:
                        response = await client.post(path, json=body)
                self.assertEqual(response.status_code,status)
                payload = json.loads(response.text.splitlines()[-1])
                record = json.loads(captured.records[-1].getMessage())
                self.assertEqual(payload['correlationId'],record['correlationId'])
                self.assertEqual(payload['requestId'],response.headers['X-CyberGold-Request-Id'])
                self.assertEqual(payload['diagnostics'],record['diagnostics'])
                self.assertEqual(payload['code'],'rpc-timeout')

    async def test_http_200_terminal_failure_is_correlated_and_semantically_failed(self):
        engines = Engines()
        engines.core_error = engines.market_error = QuoteFailure('rpc-rate-limit',
            diagnostics={'rpcMethod': 'eth_call', 'stage': 'quote-read', 'upstreamErrorCode': -32005})
        app = create_app(trade_quotes=engines.quotes)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate', level='ERROR') as captured:
                response = await client.post('/api/quotes/trade/stream', json=request(),
                    headers={'X-CyberGold-Attempt-Id': ATTEMPTS[0]})
        frames = [json.loads(row) for row in response.text.splitlines()]
        terminal = frames[-1]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(terminal['type'], 'error')
        self.assertEqual(terminal['code'], 'rpc-rate-limit')
        self.assertEqual(terminal['attemptId'], ATTEMPTS[0])
        self.assertEqual(terminal['requestId'], response.headers['X-CyberGold-Request-Id'])
        failures = [json.loads(row.getMessage()) for row in captured.records]
        self.assertEqual(len(failures), 3)
        self.assertEqual(failures[-1]['correlationId'], terminal['correlationId'])
        self.assertEqual(failures[-1]['diagnostics'], terminal['diagnostics'])
        self.assertEqual({row['workId'] for row in failures}, {terminal['workId']})
        self.assertEqual([(row.labels['outcome'], row.value) for row in samples(app.state.metrics.quote_outcomes)], [('failed', 1)])
        self.assertFalse(samples(app.state.metrics.quote_first_executable))

    async def test_losing_provider_is_logged_even_when_another_provider_succeeds(self):
        engines = Engines()
        engines.market_error = QuoteFailure('quote-no-route')
        app = create_app(trade_quotes=engines.quotes)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate', level='INFO') as captured:
                response = await client.post('/api/quotes/trade/stream', json=request())
        frames = [json.loads(row) for row in response.text.splitlines()]
        self.assertEqual(frames[-1]['type'], 'complete')
        provider = next(row for row in frames if row['type'] == 'provider-error')
        failure = next(json.loads(row.getMessage()) for row in captured.records if row.levelname == 'ERROR')
        self.assertEqual(failure['correlationId'], provider['correlationId'])
        self.assertEqual(failure['strategy'], 'market')
        self.assertEqual(failure['requestId'], frames[-1]['requestId'])
        metric = app.state.metrics.render().decode()
        self.assertIn('cybergold_backend_quote_first_executable_seconds_count', metric)
        self.assertIn('outcome="succeeded",strategy="core"', metric)
        self.assertNotIn(frames[-1]['requestId'], metric)
        self.assertNotIn(provider['correlationId'], metric)

    async def test_optional_quote_work_survives_provider_error_log_projection(self):
        engines = Engines()
        error = QuoteFailure('quote-timeout', diagnostics={'rpcMethod': 'eth_call', 'elapsedMs': 8})
        error.quote_diagnostics = {'phase': 'initial-search', 'elapsedMs': 15000, 'qualified': False,
            'inversionIteration': 0, 'private': 'private-wallet',
            'routeWave': {'mode': 'exact-in', 'subphase': 'typed-reserve', 'elapsedMs': 15000,
                          'typedEnumerated': 32, 'typedCompleted': 24, 'typedPending': 8,
                          'sdkLockWaitMs': 42000, 'calldata': 'private-calldata'}}
        engines.core_error = error
        app = create_app(trade_quotes=engines.quotes)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate', level='INFO') as captured:
                response = await client.post('/api/quotes/trade/stream', json=request())
        frames = [json.loads(row) for row in response.text.splitlines()]
        self.assertEqual(frames[-1]['type'], 'complete')
        provider = next(row for row in frames if row['type'] == 'provider-error')
        failure = next(json.loads(row.getMessage()) for row in captured.records if row.levelname == 'ERROR')
        self.assertEqual(failure['event'], 'quote_failure')
        self.assertEqual(failure['quoteDiagnostics'], provider['quoteDiagnostics'])
        self.assertEqual(failure['diagnostics'], {'rpcMethod': 'eth_call', 'elapsedMs': 8})
        self.assertEqual(failure['quoteDiagnostics']['routeWave']['sdkLockWaitMs'], 42000)
        for secret in ('private-wallet', 'private-calldata'):
            self.assertNotIn(secret, response.text + json.dumps(failure))

    def test_malformed_optional_quote_work_cannot_replace_the_original_error(self):
        from cybergold_candidate.quote_errors import public_quote_error
        error = QuoteFailure('quote-timeout')
        for source in (None, 'private-data', {'phase': [], 'elapsedMs': float('nan')},
                       {'phase': 'private-seed', 'qualified': 'private-key', 'elapsedMs': -1}):
            error.quote_diagnostics = source
            self.assertEqual(public_quote_error(error), {'code': 'quote-timeout', 'error': str(error)})
        error.quote_diagnostics = {'phase': 'initial-search', 'elapsedMs': 1}
        with patch('cybergold_candidate.rpc_diagnostics.math.isfinite', side_effect=ValueError('collector unavailable')):
            self.assertEqual(public_quote_error(error), {'code': 'quote-timeout', 'error': str(error)})

    async def test_shared_physical_failure_keeps_two_intent_owners_and_subscribers_distinct(self):
        intent, _provider, routes, _wire = intent_service()
        bank = SharedReads()
        self.addAsyncCleanup(bank.close)
        self.addAsyncCleanup(routes.close)
        started, release = asyncio.Event(), asyncio.Event()
        physical = QuoteFailure('rpc-timeout', diagnostics={'rpcMethod': 'eth_call',
            'stage': 'contract-read', 'elapsedMs': 8, 'failureType': 'provider-timeout'})
        produced, raised_errors = [], []
        async def produce():
            produced.append(True)
            started.set()
            await release.wait()
            raise physical
        async def eligibility(*_args, **_kwargs):
            try:
                return await bank.one('same-pool-eligibility-read', produce)
            except Exception as error:
                raised_errors.append(error)
                raise
        routes.engine.search_routes = eligibility
        sharing = IntentSharing(intent)
        app = create_app(quote_intent=sharing)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate', level='ERROR') as captured:
                first = asyncio.create_task(client.post('/api/quotes/intent/stream',
                    json=intent_request('issue-exact-in')))
                await asyncio.wait_for(started.wait(), 2)
                await asyncio.sleep(.02)
                other = asyncio.create_task(client.post('/api/quotes/intent/stream',
                    json=intent_request('issue-exact-out')))
                async with asyncio.timeout(2):
                    while bank.pending['same-pool-eligibility-read'].users != 2:
                        await asyncio.sleep(0)
                release.set()
                responses = await asyncio.gather(first, other)
        self.assertEqual(len(produced), 1)
        self.assertEqual(sharing.started, 2)
        self.assertEqual(len(raised_errors), 2)
        self.assertTrue(all(error is physical for error in raised_errors))
        payloads = [json.loads(response.text.splitlines()[-1]) for response in responses]
        self.assertEqual([payload['code'] for payload in payloads], ['rpc-timeout'] * 2)
        self.assertEqual([payload['diagnostics'] for payload in payloads], [physical.rpc_diagnostics] * 2)
        logical = [payload['quoteDiagnostics'] for payload in payloads]
        self.assertEqual([value['phase'] for value in logical], ['initial-search', 'execution-search'])
        self.assertEqual([value['routeWave']['mode'] for value in logical], ['exact-in', 'exact-out'])
        self.assertGreater(logical[0]['elapsedMs'], logical[1]['elapsedMs'] + 10)
        records = [json.loads(row.getMessage()) for row in captured.records]
        for payload in payloads:
            record = next(row for row in records if row['correlationId'] == payload['correlationId'])
            self.assertEqual(record['quoteDiagnostics'], payload['quoteDiagnostics'])

    async def test_actual_core_snapshot_survives_outer_trade_and_shared_terminal_rethrows(self):
        intent, _provider, routes, _wire = intent_service()
        self.addAsyncCleanup(routes.close)
        physical = QuoteFailure('rpc-timeout', diagnostics={'rpcMethod': 'eth_call', 'elapsedMs': 8})
        async def failed(*_args, **_kwargs):
            raise physical
        routes.engine.search_routes = failed
        engines = Engines()
        engines.quotes.core = intent
        app = create_app(trade_quotes=engines.quotes)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate', level='ERROR') as captured:
                response = await client.post('/api/quotes/trade/stream',
                    # Native execution remains Core-only; ordinary ERC20
                    # counterparts can now retain a qualified Market fallback.
                    json=request(native=True, counterToken=intent_request('issue-exact-in')['quoteToken']))
        frames = [json.loads(row) for row in response.text.splitlines()]
        provider = next(frame for frame in frames if frame['type'] == 'provider-error')
        terminal = frames[-1]
        self.assertEqual(terminal['type'], 'error')
        self.assertEqual(terminal['code'], 'rpc-timeout')
        self.assertEqual(provider['quoteDiagnostics']['phase'], 'initial-search')
        self.assertEqual(terminal['quoteDiagnostics'], provider['quoteDiagnostics'])
        self.assertEqual(terminal['diagnostics'], physical.rpc_diagnostics)
        records = [json.loads(row.getMessage()) for row in captured.records]
        self.assertTrue(all(record['quoteDiagnostics'] == provider['quoteDiagnostics'] for record in records))

    async def test_coalesced_requests_keep_distinct_subscriber_ids_and_one_work_id(self):
        engines = Engines()
        engines.hold_core, engines.hold_market = asyncio.Event(), asyncio.Event()
        app = create_app(trade_quotes=engines.quotes)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            calls = [asyncio.create_task(client.post('/api/quotes/trade/stream', json=request(),
                     headers={'X-CyberGold-Attempt-Id': attempt})) for attempt in ATTEMPTS]
            await asyncio.wait_for(engines.core_started.wait(), 5)
            async with asyncio.timeout(5):
                while engines.quotes.sharing.joined != 1:
                    await asyncio.sleep(0)
            engines.hold_core.set(); engines.hold_market.set()
            responses = await asyncio.gather(*calls)
        frames = [[json.loads(row) for row in response.text.splitlines()] for response in responses]
        self.assertEqual(len(engines.core_calls), 1)
        self.assertEqual(len(engines.market_calls), 1)
        self.assertNotEqual(frames[0][-1]['requestId'], frames[1][-1]['requestId'])
        self.assertEqual(frames[0][-1]['workId'], frames[1][-1]['workId'])
        for attempt, response, subscriber in zip(ATTEMPTS, responses, frames, strict=True):
            self.assertTrue(all(row['attemptId'] == attempt for row in subscriber))
            self.assertTrue(all(row['requestId'] == response.headers['X-CyberGold-Request-Id'] for row in subscriber))

    async def test_invalid_optional_metadata_and_instrumentation_failure_do_not_fail_product(self):
        engines = Engines()
        engines.market_error = QuoteFailure('quote-no-route')
        app = create_app(trade_quotes=engines.quotes)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with (patch('cybergold_candidate.trade_observation.logging.getLogger') as get_logger,
                  patch.object(app.state.metrics.quote_outcomes, 'labels', side_effect=ValueError('collector unavailable'))):
                get_logger.return_value.error.side_effect = ValueError('logging unavailable')
                get_logger.return_value.info.side_effect = ValueError('logging unavailable')
                response = await client.post('/api/quotes/trade/stream', json=request(),
                    headers={'X-CyberGold-Attempt-Id': 'Bearer fixture-secret'})
        frames = [json.loads(row) for row in response.text.splitlines()]
        self.assertEqual(frames[-1]['type'], 'complete')
        self.assertTrue(all('attemptId' not in row for row in frames))
        self.assertNotIn('fixture-secret', response.text)

    async def test_current_quote_and_execution_paths_have_fixed_http_labels(self):
        paths = ['/api/quotes/intent/stream', '/api/quotes/market', '/api/quotes/market/stream',
                 '/api/quotes/market/model', '/api/transaction/token-approval-gas']
        app = create_app()
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            for path in paths:
                response = await client.post(path, json={})
                self.assertEqual(response.status_code, 400)
                self.assertIn('X-CyberGold-Request-Id', response.headers)
        self.assertEqual({row.labels['operation'] for row in samples(app.state.metrics.http_requests)}, set(paths))

    def test_diagnostic_projection_bounds_reproduction_fields_and_keeps_no_signed_material(self):
        valid = {'requestId': ATTEMPTS[0], 'correlationId': ATTEMPTS[1], 'workId': ATTEMPTS[0],
                 'strategy': 'market', 'stage': 'simulation', 'side': 'sell', 'amount': str(2**256-1),
                 'inputMaximum': '100', 'outputMinimum': '99', 'tokenIn': '0x'+'a'*40,
                 'tokenOut': '0x'+'0'*40, 'blockNumber': '123', 'blockHash': '0x'+'b'*64,
                 'errorClassification': 'quote-contract-reverted'}
        self.assertEqual(project({**valid, 'signature': 'private', 'raw': 'private', 'wallet': 'private'}), valid)
        self.assertEqual(project({'requestId': 'private', 'strategy': 'private', 'stage': 'private',
            'amount': str(2**256), 'inputMaximum': '-1', 'outputMinimum': '1.1', 'tokenIn': 'private',
            'blockHash': '0x'+'b'*65, 'blockNumber': '1\n', 'errorClassification': 'private'}), {})

    async def test_client_diagnostic_links_failed_request_without_replacing_its_ingress_id(self):
        app = create_app()
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate',level='INFO') as captured:
                response = await client.post('/api/diagnostics',json={'operation':'swap','outcome':'failed',
                    'requestId':ATTEMPTS[0],'correlationId':ATTEMPTS[1],'stage':'simulation'})
        record = next(json.loads(row.getMessage()) for row in captured.records
                      if json.loads(row.getMessage()).get('event')=='client_diagnostic')
        self.assertEqual(record['requestId'],ATTEMPTS[0])
        self.assertEqual(record['diagnosticRequestId'],response.headers['X-CyberGold-Request-Id'])
        self.assertEqual(record['correlationId'],ATTEMPTS[1])


if __name__ == '__main__':
    unittest.main()
