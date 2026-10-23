import json
from types import SimpleNamespace
import unittest

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.basket_preview import BasketPreview, BasketPreviewRpc
from cybergold_candidate.preview_errors import KnownPreviewError, preview_error
from cybergold_candidate.quote_errors import public_quote_error


SHORTAGES = (
    ('InsufficientCygldSupply', 'redemption-supply-exceeded'),
    ('InsufficientReserveBalance', 'insufficient-reserve-balance'),
    ('InsufficientRecoveryShares', 'insufficient-recovery-shares'),
)


def selector(name):
    return Web3.to_hex(Web3.keccak(text=name+'()'))[:10]


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

    def test_explicit_shortages_keep_their_resource_without_guessing_amounts(self):
        for name, code in SHORTAGES:
            for mode in (None, 'redeem-exact-in', 'redeem-exact-out'):
                with self.subTest(name=name, mode=mode):
                    error = preview_error({'data': selector(name), 'message': 'private provider text'}, mode=mode)
                    payload = public_quote_error(error)
                    self.assertEqual(payload['code'], code)
                    if code == 'redemption-supply-exceeded':
                        self.assertEqual(payload['constraint'], {'kind': 'redemption-supply', 'quantity': 'gross-cygld-input'})
                    else:
                        self.assertNotIn('constraint', payload)
                    self.assertNotIn('private', json.dumps(payload))
        for arguments in ({'grossCygldIn': 123}, {'params': {'grossCygldIn': 123}}):
            error = preview_error({'data': selector('InsufficientCygldSupply')},
                mode='redeem-exact-in', arguments=arguments)
            self.assertEqual(error.constraint['requestedRaw'], '123')

    def test_unknown_transport_and_malformed_replies_are_not_business_errors(self):
        for data in (None, {}, '0x12345678', '0xnothex',
                *(selector(name)+'zz' for name, _ in SHORTAGES)):
            self.assertIsNone(preview_error({'data': data, 'message': 'private upstream text'}))
        selector = Web3.to_hex(Web3.keccak(text='MaxTotalSupplyExceeded(uint256,uint256,uint256)'))[:10]
        self.assertIsNone(preview_error({'data': selector}))

    async def test_focused_api_preserves_failure_status_specific_code_and_no_extra_calls(self):
        for data, expected in (('0x33aa101c', 'redemption-supply-exceeded'),
                *((selector(name), code) for name, code in SHORTAGES), ('0x12345678', 'quote-contract-reverted')):
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
                if expected == 'redemption-supply-exceeded':
                    self.assertEqual(response.json()['constraint'], {'kind': 'redemption-supply',
                        'quantity': 'gross-cygld-input', 'requestedRaw': '100'})

    def test_cap_error_retains_its_two_distinct_limits_without_new_reads(self):
        for name, limit in (('MaxTotalSupplyExceeded', 'maximum-total-supply'),
                            ('CygldSupplyCapExceeded', 'effective-supply-cap')):
            for current, requested, capacity in ((90, 20, 100), (101, 1, 100), (2**255, 2**255-1, 2**256-2)):
                selector = Web3.to_hex(Web3.keccak(text=name+'(uint256,uint256,uint256)'))[:10]
                data = selector + Web3().codec.encode(['uint256']*3, [current, requested, capacity]).hex()
                payload = public_quote_error(preview_error({'data': data, 'message': 'private provider text'}))
                self.assertEqual(payload['code'], 'issuance-cap-exceeded')
                self.assertEqual(payload['constraint'], {'kind': 'issuance-cap', 'quantity': 'gross-cygld-mint',
                    'limitKind': limit, 'currentSupplyRaw': str(current), 'requestedRaw': str(requested),
                    'availableRaw': str(max(0, capacity-current)), 'limitRaw': str(capacity)})
                self.assertNotIn('private', json.dumps(payload))

    def test_identical_supply_selector_does_not_invent_an_exact_output_reserve_cause(self):
        error = preview_error({'data': '0x33aa101c'}, mode='redeem-exact-out')
        self.assertEqual(error.code, 'redemption-capacity-exceeded')
        self.assertEqual(error.constraint, {'kind': 'redemption-capacity', 'quantity': 'core-output-minima'})
        self.assertIn('reserves or', str(error))
        self.assertNotIn('availableRaw', public_quote_error(error)['constraint'])
        unknown_context = preview_error({'data': '0x33aa101c'})
        self.assertEqual(unknown_context.code, 'insufficient-protocol-supply')
        self.assertIn('supply or redemption capacity', str(unknown_context))

    async def test_token_and_native_previews_preserve_shortage_codes(self):
        from cybergold_candidate.token_preview import TokenPreview, TokenPreviewRpc
        for data, code in (('0x33aa101c', 'redemption-supply-exceeded'),
                *((selector(name), code) for name, code in SHORTAGES)):
            for mode in ('redeem-token-exact-in', 'redeem-native-exact-in'):
                with self.subTest(mode=mode, code=code):
                    provider = Provider(data)
                    cfg = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID=1, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS='0x'+'1'*40)
                    preview = TokenPreview(cfg, TokenPreviewRpc(cfg, AsyncWeb3(provider)))
                    app = create_app(token_preview=preview)
                    value = {'mode': mode, 'grossCygldIn': '123456789012345678901234567890', 'quotes': []}
                    if mode == 'redeem-token-exact-in':
                        value['outputToken'] = '0x'+'2'*40
                    async with app.router.lifespan_context(app), httpx.AsyncClient(
                            transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                        response = await client.post('/api/quotes/token-preview', json=value)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()['code'], code)
                    if code == 'redemption-supply-exceeded':
                        self.assertEqual(response.json()['constraint']['requestedRaw'], value['grossCygldIn'])
                    else:
                        self.assertNotIn('constraint', response.json())
                    self.assertEqual(provider.calls.count('eth_call'), 1)

    async def test_authoritative_cap_and_input_supply_errors_precede_all_route_search(self):
        from test_quote_intent import service, request
        for mode, name in (('issue-exact-out', 'MaxTotalSupplyExceeded'), ('redeem-exact-in', None)):
            intent, provider, routes, wire = service()
            original = provider.make_request
            async def invoke(method, params):
                if method == 'eth_call':
                    function, _ = provider.contract.decode_function_input(params[0]['data'])
                    expected = 'previewIssueFromBasketExactOut' if mode == 'issue-exact-out' else 'previewRedeemToBasketExactIn'
                    if function.fn_name == expected:
                        data = ('0x33aa101c' if name is None else
                            Web3.to_hex(Web3.keccak(text=name+'(uint256,uint256,uint256)'))[:10] +
                            Web3().codec.encode(['uint256']*3, [90, 20, 100]).hex())
                        return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'data': data}}
                return await original(method, params)
            provider.make_request = invoke
            frames = []
            async def publish(frame):
                frames.append(frame)
            try:
                with self.assertRaises(KnownPreviewError) as failure:
                    await intent.get(request(mode), publish)
                self.assertEqual(failure.exception.code, 'issuance-cap-exceeded' if name else 'redemption-supply-exceeded')
                self.assertFalse(wire.batches, 'No inverse or forward route discovery should precede the paid preview rejection')
                self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
            finally:
                await routes.close()

    async def test_unavailable_core_capacity_keeps_market_candidate_and_constraint(self):
        from test_trade_quote import Engines, request
        engines = Engines()
        engines.core_error = preview_error({'data': '0x33aa101c'}, mode='redeem-exact-in',
            arguments={'grossCygldIn': 100})
        frames = []
        async def publish(frame):
            frames.append(frame)
        try:
            result = await engines.quotes.get(request('sell'), publish)
            self.assertEqual(result['strategy'], 'market')
            assessment = result['providerAssessments']['core']
            self.assertEqual(assessment['code'], 'redemption-supply-exceeded')
            self.assertEqual(assessment['constraint']['requestedRaw'], '100')
            frame = next(frame for frame in frames if frame['type'] == 'provider-error')
            self.assertEqual(frame['constraint'], assessment['constraint'])
        finally:
            await engines.quotes.close()

    async def test_stream_exposes_known_error_without_provider_text(self):
        from cybergold_candidate.quote_intent import handle_quote_intent
        class Request:
            async def json(self):
                return {'mode':'redeem-exact-in','token':'0x'+'1'*40,'quoteToken':'0x'+'1'*40,
                        'native':False,'amount':'100','adapter':'0x'+'2'*40,'deadline':'1000','orderedAssets':[]}
        for data, code in (('0x33aa101c', 'insufficient-protocol-supply'),
                *((selector(name), code) for name, code in SHORTAGES)):
            class Service:
                async def get(self, request, update):
                    raise preview_error({'data': data, 'message': 'private provider text'})
            response = await handle_quote_intent(Request(), Service())
            events = [json.loads(row) async for row in response.body_iterator]
            self.assertEqual(events[-1]['code'], code)
            self.assertEqual(events[-1]['type'], 'error')
            self.assertNotIn('private provider text', json.dumps(events))


if __name__ == '__main__':
    unittest.main()
