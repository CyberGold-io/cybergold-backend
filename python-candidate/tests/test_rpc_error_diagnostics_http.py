"""RPC diagnostics follow API correlation without leaking across requests."""
import asyncio
import json
from types import SimpleNamespace
import unittest

from aiohttp import web
import httpx
from web3 import AsyncWeb3

from cybergold_candidate.app import create_app
from cybergold_candidate.route_search import reduce_results
from legacy_quote_wire_fixture import ReferenceRouteSearchRpc as RouteSearchRpc
from cybergold_candidate.rpc_transport import rpc_provider


ADDRESS = '0x' + '1' * 40
HASH = '0x' + 'a' * 64
INTENT = {'mode': 'issue-exact-in', 'token': ADDRESS, 'quoteToken': ADDRESS,
          'native': False, 'amount': '1', 'adapter': ADDRESS, 'deadline': '1000', 'orderedAssets': []}
ROUTES = {'mode': 'exact-in', 'targets': [{'inputAsset': ADDRESS, 'outputAsset': '0x' + '2' * 40, 'amount': '1'}]}
BASKET = {'mode': 'issue-exact-in', 'maximumAmountsIn': []}
POOL = {'tokenA': ADDRESS, 'tokenB': '0x' + '2' * 40, 'fee': 100}


class RpcRead:
    def __init__(self, url, *, timeout=.03, deadline=None):
        self.provider = rpc_provider(url, 'Bearer fixture-authorization', timeout_seconds=timeout)
        self.w3 = AsyncWeb3(self.provider)
        self.deadline = deadline

    async def get(self, *_args, **_kwargs):
        if self.deadline is not None:
            async with asyncio.timeout(self.deadline):
                block = await self.w3.eth.get_block('latest')
        else:
            block = await self.w3.eth.get_block('latest')
        return {'blockNumber': block['number']}

    async def close(self):
        await self.provider.disconnect()


class RpcErrorDiagnosticsHttp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status, self.error, self.delay = 200, None, 0
        self.errors_by_method = {}
        self.started = asyncio.Event()
        self.release = None
        self.calls = []

        async def rpc(request):
            payload = await request.json()
            self.calls.append(payload)
            self.started.set()
            if self.release is not None and (isinstance(payload, list) or payload['method'] == 'eth_getBlockByNumber'):
                await self.release.wait()
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.status != 200:
                return web.Response(status=self.status, text='fixture-private-body')

            def response(call):
                error = self.errors_by_method.get(call['method'], self.error)
                return {'jsonrpc': '2.0', 'id': call['id'], **(
                    {'error': error} if error else
                    {'result': '0x7a6a' if call['method'] == 'eth_chainId' else
                     {'number': '0x65', 'hash': HASH, 'timestamp': '0x1',
                      'baseFeePerGas': '0x1', 'transactions': []}})}

            return web.json_response([response(call) for call in payload] if isinstance(payload, list) else response(payload))

        upstream = web.Application()
        upstream.router.add_post('/rpc/fixture-key', rpc)
        self.runner = web.AppRunner(upstream)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/rpc/fixture-key?api_key=fixture-query-key'

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def request(self, service, slot, path, body=None):
        app = create_app(**{slot: service})
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate', level='ERROR') as logs:
                response = await client.get(path) if body is None else await client.post(path, json=body)
        payload = json.loads(response.text.splitlines()[-1])
        record = json.loads(logs.records[-1].getMessage())
        self.assertEqual(record['correlationId'], payload['correlationId'])
        self.assertEqual(record['diagnostics'], payload['diagnostics'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('fixture-authorization', response.text + record.__repr__())
        self.assertNotIn('fixture-query-key', response.text + record.__repr__())
        self.assertNotIn('fixture-key', response.text + record.__repr__())
        self.assertNotIn('fixture-private-body', response.text + record.__repr__())
        self.assertNotIn(self.url, response.text + record.__repr__())
        return response, payload, record

    async def test_json_and_ndjson_errors_include_same_diagnostics_in_correlated_log(self):
        paths = [
            ('transaction_fees', '/api/transaction/fees', None),
            ('protocol_facts', '/api/protocol/facts', None),
            ('basket_preview', '/api/quotes/basket-preview', BASKET),
            ('quote_intent', '/api/quotes/intent/stream', INTENT),
            ('route_search', '/api/quotes/routes/stream', ROUTES),
            ('pool_producer', '/api/pools/snapshot', POOL),
        ]
        self.error = {'code': -32005, 'message': 'Request quota reached; retry shortly.'}
        for slot, path, body in paths:
            with self.subTest(path=path):
                before = len(self.calls)
                response, payload, record = await self.request(RpcRead(self.url), slot, path, body)
                self.assertEqual(response.status_code, 200 if path.endswith('stream') else 503)
                self.assertEqual(payload['code'], 'rpc-rate-limit')
                self.assertEqual(record['errorClassification'], 'rpc-rate-limit')
                self.assertEqual(payload['diagnostics']['rpcMethod'], 'eth_getBlockByNumber')
                self.assertEqual(payload['diagnostics']['failureType'], 'rpc-error')
                self.assertEqual(payload['diagnostics']['upstreamErrorCode'], -32005)
                self.assertEqual(payload['diagnostics']['providerMessage'], self.error['message'])
                self.assertGreaterEqual(payload['diagnostics']['elapsedMs'], 0)
                self.assertTrue(payload['diagnostics']['stage'])
                self.assertEqual(len(self.calls) - before, 1)
                if slot == 'route_search':
                    self.assertEqual(payload['error'], 'Route search is temporarily unavailable.')
                elif slot == 'pool_producer':
                    self.assertEqual(payload['error'], 'Pool observations are temporarily unavailable.')

    async def test_http_status_and_provider_timeout_keep_existing_error_categories(self):
        for status, delay, code, failure in [
                (403, 0, 'rpc-access-denied', 'http-error'),
                (504, 0, 'rpc-timeout', 'http-error'),
                (200, .08, 'rpc-timeout', 'provider-timeout')]:
            with self.subTest(status=status, delay=delay):
                self.status, self.delay = status, delay
                _, payload, _ = await self.request(RpcRead(self.url), 'transaction_fees', '/api/transaction/fees')
                self.assertEqual(payload['code'], code)
                self.assertEqual(payload['diagnostics']['failureType'], failure)
                self.assertEqual(payload['diagnostics']['rpcMethod'], 'eth_getBlockByNumber')
                if status != 200:
                    self.assertEqual(payload['diagnostics']['httpStatus'], status)
                else:
                    self.assertNotIn('httpStatus', payload['diagnostics'])

    async def test_provider_message_is_useful_but_credentials_never_reach_api_or_log(self):
        self.error = {'code': -32005, 'message':
                      f'Request quota reached for fixture-query-key at {self.url}; '
                      'Authorization: Bearer fixture-authorization; account fixture-key'}
        _, payload, record = await self.request(RpcRead(self.url), 'quote_intent',
                                                '/api/quotes/intent/stream', INTENT)
        self.assertIn('Request quota reached', payload['diagnostics']['providerMessage'])
        self.assertIn('[redacted', payload['diagnostics']['providerMessage'])
        self.assertEqual(record['diagnostics'], payload['diagnostics'])
        self.assertEqual(payload['diagnostics']['upstreamErrorCode'], -32005)

    async def test_outer_deadline_preserves_cancelled_rpc_method_without_claiming_remote_error(self):
        self.delay = .08
        _, payload, _ = await self.request(RpcRead(self.url, timeout=1, deadline=.01),
                                           'transaction_fees', '/api/transaction/fees')
        diagnostics = payload['diagnostics']
        self.assertEqual(payload['code'], 'rpc-timeout')
        self.assertEqual(diagnostics['rpcMethod'], 'eth_getBlockByNumber')
        self.assertEqual(diagnostics['failureType'], 'backend-deadline')
        self.assertNotIn('upstreamErrorCode', diagnostics)
        self.assertNotIn('providerMessage', diagnostics)

    async def test_success_and_independent_failure_do_not_inherit_another_requests_diagnostics(self):
        failed = RpcRead(self.url)

        class PlainFailure:
            async def get(self):
                raise ValueError('Unrelated ordinary failure')

            async def close(self):
                pass

        app = create_app(transaction_fees=failed, protocol_facts=PlainFailure())
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            self.error = {'code': -32005, 'message': 'Request quota reached.'}
            with self.assertLogs('cybergold.candidate', level='ERROR') as logs:
                first = await client.get('/api/transaction/fees')
                self.error = None
                success = await client.get('/api/transaction/fees')
                unrelated = await client.get('/api/protocol/facts')
        self.assertIn('diagnostics', first.json())
        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.json(), {'blockNumber': 101})
        self.assertNotIn('diagnostics', unrelated.json())
        self.assertNotIn('diagnostics', json.loads(logs.records[-1].getMessage()))
        self.assertNotEqual(first.json()['correlationId'], unrelated.json()['correlationId'])

    async def test_httpx_batch_errors_retain_per_member_diagnostics_through_route_results(self):
        self.error = {'code': -32005, 'message': 'Request quota reached.'}
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS=ADDRESS,
                                   RPC_URL=self.url, RPC_AUTHORIZATION='Bearer fixture-authorization')
        rpc = RouteSearchRpc(settings)

        class Routes:
            async def get(self, request):
                values = await rpc.quote_batch('exact-in', ['0x01'], {'hash': HASH})
                plans = [[{'path': '0x01', 'route': 'direct', 'feeInfo': '100', 'totalFee': 100, 'callIndex': 0}]]
                return {'results': reduce_results(request, plans, dict(enumerate(values)))}

            async def close(self):
                await rpc.close()

        app = create_app(route_search=Routes())
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            response = await client.post('/api/quotes/routes', json=ROUTES)
        self.assertEqual(response.status_code, 200)
        failure = response.json()['results'][0]['failures'][0]
        self.assertEqual(failure['rpcCode'], -32005)
        self.assertEqual(failure['diagnostics']['rpcMethod'], 'eth_call')
        self.assertEqual(failure['diagnostics']['stage'], 'route-search')
        self.assertEqual(failure['diagnostics']['failureType'], 'rpc-error')
        self.assertEqual(failure['diagnostics']['upstreamErrorCode'], -32005)
        self.assertEqual(failure['diagnostics']['providerMessage'], self.error['message'])
        self.assertNotIn('fixture-authorization', response.text)
        self.assertNotIn('fixture-query-key', response.text)
        self.assertNotIn('fixture-key', response.text)

    async def test_concurrent_stream_success_and_plain_error_cannot_take_pending_rpc_failure_context(self):
        self.errors_by_method['eth_getBlockByNumber'] = {'code': -32005, 'message': 'Request quota reached.'}
        self.release = asyncio.Event()
        reader = RpcRead(self.url, timeout=1)

        class Concurrent:
            async def get(self, request, _publish):
                if request['amount'] == '3':
                    raise ValueError('Unrelated ordinary failure')
                if request['amount'] == '2':
                    return {'chainId': await reader.w3.eth.chain_id}
                return await reader.get()

            async def close(self):
                await reader.close()

        app = create_app(quote_intent=Concurrent())
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate', level='ERROR') as logs:
                pending = asyncio.create_task(client.post('/api/quotes/intent/stream', json=INTENT))
                try:
                    await self.started.wait()
                    success = await client.post('/api/quotes/intent/stream', json={**INTENT, 'amount': '2'})
                    unrelated = await client.post('/api/quotes/intent/stream', json={**INTENT, 'amount': '3'})
                    self.release.set()
                    failed = await pending
                finally:
                    self.release.set()
                    await asyncio.gather(pending, return_exceptions=True)
        success_event = json.loads(success.text.splitlines()[-1])
        unrelated_event = json.loads(unrelated.text.splitlines()[-1])
        failed_event = json.loads(failed.text.splitlines()[-1])
        self.assertEqual(success_event.pop('requestId'), success.headers['X-CyberGold-Request-Id'])
        self.assertEqual(success_event, {'type': 'complete', 'value': {'chainId': 31338}})
        self.assertNotIn('diagnostics', unrelated_event)
        self.assertEqual(failed_event['diagnostics']['rpcMethod'], 'eth_getBlockByNumber')
        records = {record['correlationId']: record for record in
                   (json.loads(item.getMessage()) for item in logs.records)}
        self.assertNotIn('diagnostics', records[unrelated_event['correlationId']])
        self.assertEqual(records[failed_event['correlationId']]['diagnostics'], failed_event['diagnostics'])


if __name__ == '__main__':
    unittest.main()
