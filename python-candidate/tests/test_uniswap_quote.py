"""Compare actual Viem tuple layouts, opaque legs, wide results and cancellation."""
import asyncio
import json
import sys
from types import SimpleNamespace
import unittest

import httpx
from web3 import AsyncWeb3

from test_basket_preview import HASH, Provider, REFERENCE
from cybergold_candidate.app import create_app
from cybergold_candidate.uniswap_quote import UniswapQuote, UniswapQuoteRpc


def service(provider):
    settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS=REFERENCE['helpers'],
                               RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture-only')
    return UniswapQuote(settings, UniswapQuoteRpc(settings, AsyncWeb3(provider)), lambda: '2026-10-01T00:00:00.000Z')


class UniswapQuoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_and_multihop_viem_layouts_and_lossless_ordered_results(self):
        for row in REFERENCE['rows']:
            with self.subTest(mode=row['mode']):
                provider = Provider()
                result = await service(provider).get(row['request'])
                self.assertEqual(json.dumps(result['result']).lower(), json.dumps(row['value']).lower())
                self.assertEqual(result['context']['blockHash'], HASH)
                calls = [params for method, params in provider.calls if method == 'eth_call']
                self.assertEqual(calls, [[{'to': service(provider).rpc.quoter, 'data': row['data']},
                                         {'blockHash': HASH, 'requireCanonical': True}]])

    async def test_invalid_input_and_abi_values_fail_before_rpc(self):
        original = REFERENCE['rows'][0]['request']
        invalid = [{}, {'mode': 'eth_sendTransaction'}, {**original, 'amount': '-1'},
                   {**original, 'amount': str(2**256)}, {**original, 'path': '0x1'}]
        provider = Provider()
        app = create_app(uniswap_quote=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for request in invalid:
                response = await client.post('/api/quotes/uniswap', json=request)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(provider.calls, [])

    async def test_fixed_target_no_store_and_redacted_supplier_failure(self):
        provider = Provider()
        app = create_app(uniswap_quote=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/quotes/uniswap?target=0x0&provider=http://untrusted.invalid',
                                         json={**REFERENCE['rows'][0]['request'], 'method': 'eth_sendTransaction'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            provider.failure = True
            response = await client.post('/api/quotes/uniswap', json=REFERENCE['rows'][0]['request'])
            self.assertEqual(response.status_code, 503)
            self.assertIn('correlationId', response.json())
            self.assertNotIn('password', response.text)

    async def test_reorg_wrong_chain_and_caller_cancellation(self):
        for provider in (Provider(reorg=True), Provider(chain='0x1')):
            with self.assertRaises(Exception):
                await service(provider).get(REFERENCE['rows'][0]['request'])
        provider = Provider(blocked=True)
        operation = asyncio.create_task(service(provider).get(REFERENCE['rows'][0]['request']))
        await provider.started.wait()
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertEqual(provider.cancelled, 1)

    async def test_concurrent_modes_do_not_share_quote_calldata(self):
        provider = Provider()
        preview = service(provider)
        rows = REFERENCE['rows']
        results = await asyncio.gather(*(preview.get(row['request']) for row in rows))
        self.assertEqual([row['mode'] for row in results], [row['mode'] for row in rows])
        self.assertEqual(sorted(params[0]['data'] for method, params in provider.calls if method == 'eth_call'),
                         sorted(row['data'] for row in rows))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
