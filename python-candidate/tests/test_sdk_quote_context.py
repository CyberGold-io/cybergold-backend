"""Serving SDK facades need chain context, never an onchain Quoter setting."""
import asyncio
from types import SimpleNamespace
import unittest

from web3 import AsyncWeb3

from cybergold_candidate.environment import load_environment
from cybergold_candidate.uniswap_quote import QuoteContextRpc, UniswapQuote
from cybergold_candidate.route_search import RouteSearchRpc
from test_route_search import Provider


class SdkEngine:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(8)
        self.calls = []

    async def quote_branches(self, branches, mode, amount, block):
        self.calls.append((branches, mode, amount, block))
        return {'amountIn': str(amount), 'amountOut': str(amount*2)}


class SdkQuoteContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_quote_succeeds_without_native_quoter_configuration_or_call(self):
        provider = Provider(chain='0x7a6a')
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', RPC_URL='http://synthetic.invalid',
                                   RPC_AUTHORIZATION=None)
        engine = SdkEngine()
        rpc = QuoteContextRpc(settings, AsyncWeb3(provider))
        service = UniswapQuote(settings, rpc=rpc, engine=engine)
        self.addAsyncCleanup(service.close)
        request = {'mode': 'exact-in', 'amount': '100',
                   'path': '0x'+'1'*40+'000bb8'+'2'*40}
        value = await service.get(request)
        self.assertEqual(value['result']['amount'], str(int(request['amount'])*2))
        self.assertEqual(value['qualification'], 'sdk')
        self.assertNotIn('quoter', value)
        self.assertEqual(len(engine.calls), 1)
        self.assertFalse(any(method == 'eth_call' for method, _ in provider.calls))

    async def test_route_transport_does_not_require_or_validate_native_quoter(self):
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', RPC_URL='http://synthetic.invalid',
                                   RPC_AUTHORIZATION=None)
        rpc = RouteSearchRpc(settings, AsyncWeb3(Provider(chain='0x7a6a')))
        self.addAsyncCleanup(rpc.close)
        self.assertEqual((await rpc.block(None))['number'], 101)
        self.assertFalse(hasattr(rpc, 'quoter'))

    def test_retired_setting_is_ignored_by_runtime_environment(self):
        settings = load_environment({'NEXT_PUBLIC_CHAIN_ID': '1',
            'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': '0x'+'1'*40,
            'NEXT_PUBLIC_RPC_URL': 'http://synthetic.invalid',
            'NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS': 'retired irrelevant input'})
        self.assertFalse(hasattr(settings, 'NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS'))


if __name__ == '__main__':
    unittest.main()
