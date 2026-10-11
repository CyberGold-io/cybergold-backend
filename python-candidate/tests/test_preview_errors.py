import json
from types import SimpleNamespace
import unittest

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.basket_preview import BasketPreview, BasketPreviewRpc
from cybergold_candidate.preview_errors import KnownPreviewError, preview_error


class Provider(AsyncBaseProvider):
    def __init__(self, data):
        super().__init__()
        self.data, self.calls = data, []

    async def make_request(self, method, params):
        self.calls.append(method)
        if method == 'eth_call':
            return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'data': self.data,
                'message': 'https://private:password@example.invalid'}}
        result = '0x1' if method == 'eth_chainId' else {'number': '0x64', 'hash': '0x' + 'a' * 64}
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


class PreviewErrors(unittest.IsolatedAsyncioTestCase):
    def test_known_abi_supply_and_cap_errors(self):
        self.assertEqual(preview_error({'data': '0x33aa101c'}).code, 'insufficient-protocol-supply')
        for name in ('MaxTotalSupplyExceeded', 'CygldSupplyCapExceeded'):
            raw = Web3.to_hex(Web3.keccak(text=name+'(uint256,uint256,uint256)'))[:10]
            raw += Web3().codec.encode(['uint256']*3, [1, 2, 3]).hex()
            self.assertEqual(preview_error({'data': raw}).code, 'issuance-cap-exceeded')

    def test_unknown_transport_and_malformed_replies_are_not_business_errors(self):
        for data in (None, {}, '0x12345678', '0xnothex'):
            self.assertIsNone(preview_error({'data': data, 'message': 'private upstream text'}))
        selector = Web3.to_hex(Web3.keccak(text='MaxTotalSupplyExceeded(uint256,uint256,uint256)'))[:10]
        self.assertIsNone(preview_error({'data': selector}))

    async def test_focused_api_preserves_failure_status_specific_code_and_no_extra_calls(self):
        for data, expected in (('0x33aa101c', 'insufficient-protocol-supply'), ('0x12345678', 'quote-contract-reverted')):
            provider = Provider(data)
            cfg = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID=1, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS='0x'+'1'*40)
            preview = BasketPreview(cfg, BasketPreviewRpc(cfg, AsyncWeb3(provider)))
            app = create_app(basket_preview=preview)
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.post('/api/quotes/basket-preview', json={'mode':'redeem-exact-in','grossCygldIn':'100'})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json().get('code'), expected)
                self.assertNotIn('password', response.text)
                self.assertEqual(provider.calls.count('eth_call'), 1)

    async def test_stream_exposes_known_error_without_provider_text(self):
        from cybergold_candidate.quote_intent import handle_quote_intent
        class Request:
            async def json(self):
                return {'mode':'redeem-exact-in','token':'0x'+'1'*40,'quoteToken':'0x'+'1'*40,
                        'native':False,'amount':'100','adapter':'0x'+'2'*40,'deadline':'1000','orderedAssets':[]}
        class Service:
            async def get(self, request, update):
                raise KnownPreviewError('insufficient-protocol-supply', 'The redemption amount exceeds available CYGLD supply.')
        response = await handle_quote_intent(Request(), Service())
        events = [json.loads(row) async for row in response.body_iterator]
        self.assertEqual(events[-1]['code'], 'insufficient-protocol-supply')
        self.assertEqual(events[-1]['type'], 'error')


if __name__ == '__main__':
    unittest.main()
