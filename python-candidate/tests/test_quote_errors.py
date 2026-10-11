"""Actual RPC/HTTP errors retain their cause without provider secrets or retries."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
import httpx
from web3 import AsyncWeb3

from cybergold_candidate.app import create_app
from cybergold_candidate.rpc_transport import rpc_provider
from cybergold_candidate.quote_cache import IntentSharing


class QuoteErrorDelivery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status, self.delay, self.error = 200, 0, None
        self.calls = []

        async def rpc(request):
            self.calls.append(await request.json())
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.status != 200:
                return web.Response(status=self.status, text='private-provider-credential')
            return web.json_response({'jsonrpc': '2.0', 'id': 1,
                **({'error': self.error} if self.error else {'result': '0x1'})})

        app = web.Application()
        app.router.add_post('/', rpc)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/'

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def test_rpc_limits_access_transport_and_timeout_are_specific_in_stream_and_facts(self):
        cases = [(429, None, 0, 'rpc-rate-limit'), (403, None, 0, 'rpc-access-denied'),
                 (504, None, 0, 'rpc-timeout'),
                 (503, None, 0, 'rpc-unavailable'), (200, {'code': -32005,
                  'message': 'private-provider-credential'}, 0, 'rpc-rate-limit'),
                 (200, None, .1, 'rpc-timeout')]
        for status, error, delay, expected in cases:
            for path in ('/api/quotes/intent/stream', '/api/protocol/facts'):
                with self.subTest(status=status, delay=delay, path=path):
                    self.status, self.error, self.delay = status, error, delay
                    provider = rpc_provider(self.url, timeout_seconds=.03)

                    class Service:
                        async def get(self, *args):
                            return await AsyncWeb3(provider).eth.chain_id

                        async def close(self):
                            await provider.disconnect()

                    service = Service()
                    app = create_app(quote_intent=service, protocol_facts=service)
                    before = len(self.calls)
                    async with app.router.lifespan_context(app), httpx.AsyncClient(
                            transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                        response = await client.post(path, json={'mode': 'issue-exact-in',
                            'token': '0x'+'1'*40, 'quoteToken': '0x'+'1'*40, 'native': False,
                            'amount': '1', 'adapter': '0x'+'2'*40, 'deadline': '1000', 'orderedAssets': []}) \
                            if path.endswith('stream') else await client.get(path)
                    self.assertEqual(response.status_code, 200 if path.endswith('stream') else 503)
                    payload = json.loads(response.text.splitlines()[-1])
                    self.assertEqual(payload['code'], expected)
                    self.assertIn('RPC', payload['error'])
                    self.assertNotIn('private-provider-credential', response.text)
                    self.assertEqual(len(self.calls)-before, 1)
                    self.assertNotIn('"type":"complete"', response.text)

    async def test_shared_intent_head_deadline_is_an_rpc_timeout_without_starting_routes(self):
        reads = []
        class Rpc:
            async def block(self, _block):
                reads.append('head')
                await asyncio.Event().wait()
        class Service:
            routes = SimpleNamespace(rpc=Rpc())
            async def get(self, *args, **kwargs):
                raise AssertionError('A timed-out head cannot start a quote producer')
        service = IntentSharing(Service())
        app = create_app(quote_intent=service)
        deadline = asyncio.timeout
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with patch('cybergold_candidate.quote_cache.asyncio.timeout', side_effect=lambda _: deadline(.01)):
                response = await client.post('/api/quotes/intent/stream', json={'mode':'issue-exact-in',
                    'token':'0x'+'1'*40, 'quoteToken':'0x'+'1'*40, 'native':False,
                    'amount':'100000', 'adapter':'0x'+'2'*40, 'deadline':'1000', 'orderedAssets':[]})
        payload = json.loads(response.text.splitlines()[-1])
        self.assertEqual(payload['code'], 'rpc-timeout')
        self.assertEqual(reads, ['head'])
        self.assertEqual(service.started, 0)

    async def test_market_failure_diagnostic_does_not_change_payload_cache_policy_or_expose_text(self):
        calls = []

        def supplier(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(403, text='private-provider-credential')
            return httpx.Response(200, json={'amount': 1, 'base': 'USD', 'date': '2026-10-06',
                                           'rates': {'EUR': .9, 'CHF': .8, 'RUB': 80}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as upstream:
            app = create_app(client=upstream)
            async with app.router.lifespan_context(app), httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                failed = await client.get('/api/fx')
                fresh = await client.get('/api/fx')
                reused = await client.get('/api/fx')
        self.assertEqual(failed.headers['x-cybergold-market-fallback'], 'provider-http-403')
        self.assertEqual(failed.headers['cache-control'], 'no-store')
        self.assertEqual(set(failed.json()), {'base', 'rates', 'fetchedAt', 'stale'})
        self.assertTrue(failed.json()['stale'])
        self.assertNotIn('private-provider-credential', failed.text)
        self.assertFalse(fresh.json()['stale'])
        self.assertNotIn('x-cybergold-market-fallback', fresh.headers)
        self.assertEqual(fresh.json(), reused.json())
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
