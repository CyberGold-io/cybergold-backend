"""Compare the four actual Viem call/result layouts, failures and cancellation."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.basket_preview import BasketPreview, BasketPreviewRpc

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x' + 'a' * 64


class Provider(AsyncBaseProvider):
    def __init__(self, failure=False, reorg=False, chain='0x7a6a', blocked=False):
        super().__init__()
        self.calls, self.failure, self.reorg, self.chain, self.blocked = [], failure, reorg, chain, blocked
        self.started, self.cancelled = asyncio.Event(), 0
        self.rows = {row['data']: row for row in REFERENCE['rows']}

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'eth_getBlockByNumber':
            result = {'number': '0x65', 'hash': '0x' + 'b' * 64 if self.reorg and params[0] != 'latest' else HASH}
        elif method == 'eth_call':
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            if self.failure:
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'https://secret:password@private.invalid'}}
            result = self.rows[params[0]['data']]['result']
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=REFERENCE['helpers'],
                               RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture-only')
    return BasketPreview(settings, BasketPreviewRpc(settings, AsyncWeb3(provider)), lambda: '2026-10-01T00:00:00.000Z')


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_model_delivery_adds_no_rpc_and_preserves_observed_context(self):
        from cybergold_candidate.quote_history import QuoteHistory
        from copy import deepcopy
        row = REFERENCE['rows'][0]
        plain_provider, warm_provider = Provider(), Provider()
        plain = await service(plain_provider).get(row['request'])
        warm = service(warm_provider)
        history = QuoteHistory(warm.settings)
        snapshot = {'context': {'chainId':31338,'blockNumber':'99','blockHash':'prior'},
                    'state': {'assets':['public-asset']}, '_acquiredAt': 0}
        history.states['prior'] = deepcopy(snapshot)
        warm.history = history
        result = await warm.get(row['request'])
        model = result.pop('basketModel')
        self.assertEqual(result, plain)
        self.assertEqual(warm_provider.calls, plain_provider.calls)
        self.assertEqual(model['context'], snapshot['context'])
        self.assertNotIn('_acquiredAt', model)
        history.states.clear()
        self.assertIsNone((await warm.get(row['request']))['basketModel'])

    async def test_all_four_canonical_viem_calls_and_lossless_ordered_results(self):
        for row in REFERENCE['rows']:
            with self.subTest(mode=row['mode']):
                provider = Provider()
                result = await service(provider).get(row['request'])
                # Web3 checksum formatting is the only address-text difference.
                self.assertEqual(json.dumps(result['result']).lower(), json.dumps(row['value']).lower())
                self.assertEqual(result['context'], {'chainId': 31338, 'blockNumber': '101', 'blockHash': HASH,
                                                    'observedAt': '2026-10-01T00:00:00.000Z'})
                calls = [params for method, params in provider.calls if method == 'eth_call']
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0]['data'], row['data'])
                self.assertEqual(calls[0][0]['to'].lower(), REFERENCE['helpers'])
                self.assertEqual(calls[0][1], {'blockHash': HASH, 'requireCanonical': True})

    async def test_http_input_abi_errors_are_400_without_rpc(self):
        provider = Provider()
        app = create_app(basket_preview=service(provider))
        invalid = [{}, {'mode': 'eth_sendTransaction'}, {'mode': 'issue-exact-out', 'netCygldOut': '-1'},
                   {'mode': 'issue-exact-out', 'netCygldOut': str(2**256)},
                   {'mode': 'issue-exact-out', 'netCygldOut': '1.5'},
                   {'mode': 'redeem-exact-out', 'minimumOutputs': [{'kind': 256, 'token': REFERENCE['helpers'],
                                                                 'id': '0', 'minimumAmount': '1'}]}]
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for request in invalid:
                response = await client.post('/api/quotes/basket-preview', json=request)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(provider.calls, [])

    async def test_fixed_target_no_store_and_correlation_without_private_details(self):
        provider = Provider()
        app = create_app(basket_preview=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/quotes/basket-preview?target=0x0&provider=http://untrusted.invalid',
                                         json={**REFERENCE['rows'][0]['request'], 'method': 'eth_sendTransaction'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            provider.failure = True
            response = await client.post('/api/quotes/basket-preview', json=REFERENCE['rows'][0]['request'])
            self.assertEqual(response.status_code, 503)
            self.assertIn('correlationId', response.json())
            self.assertNotIn('password', response.text)

    async def test_reorg_and_wrong_chain_do_not_publish_preview(self):
        for provider in (Provider(reorg=True), Provider(chain='0x1')):
            with self.assertRaises(Exception):
                await service(provider).get(REFERENCE['rows'][0]['request'])
        self.assertFalse(any(method == 'eth_call' for method, _ in provider.calls))

    async def test_caller_cancellation_reaches_private_read(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get(REFERENCE['rows'][0]['request']))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(provider.cancelled, 1)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
