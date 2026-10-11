"""Independent fixed-asset wallet responses, without cross-asset waiting."""
import asyncio
import json
from types import SimpleNamespace
import unittest

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.wallet_balances import TOKENS, TokenBalance, WalletBalancesRpc

WALLET = '0x' + '1' * 40
OTHER = '0x' + '2' * 40
CORE = '0x' + 'c' * 40
HASH = '0x' + 'a' * 64
ASSETS = {'cygld': CORE, **dict(TOKENS)}


class Provider(AsyncBaseProvider):
    def __init__(self, failure=None, blocked=None, reorg=False, value=2**255):
        super().__init__()
        self.calls = []
        self.failure, self.blocked, self.reorg, self.value = failure, blocked, reorg, value
        self.started, self.cancelled = asyncio.Event(), 0
        self.codec = Web3().codec

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = '0x7a6a'
        elif method == 'eth_getBlockByNumber':
            if self.failure == 'head':
                return self.error()
            result = {'number': '0x65', 'timestamp': '0x6a000001',
                      'hash': '0x' + 'b' * 64 if self.reorg and params[0] != 'latest' else HASH}
        elif method in ('eth_call', 'eth_getBalance'):
            asset = params[0]['to'].lower() if method == 'eth_call' else 'eth'
            holder = '0x' + params[0]['data'][-40:] if method == 'eth_call' else params[0]
            if asset == self.blocked:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            if asset == self.failure:
                return self.error()
            value = self.value + (0 if holder.lower() == WALLET else 1)
            result = '0x' + self.codec.encode(['uint256'], [value]).hex() if method == 'eth_call' else hex(value)
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    @staticmethod
    def error():
        return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'private provider password'}}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION=None,
        NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=None)
    return TokenBalance(settings, WalletBalancesRpc(settings, AsyncWeb3(provider)))


class TokenBalanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_fixed_asset_performs_one_lossless_hash_pinned_balance_read(self):
        for token_id in ('eth', *ASSETS):
            provider = Provider()
            value = await service(provider).get(WALLET, token_id)
            self.assertEqual(value['tokenId'], token_id)
            self.assertEqual(value['holder'], WALLET)
            self.assertEqual(value['balance'], {'status': 'success', 'value': str(2**255)})
            self.assertEqual(value['context']['blockNumber'], '101')
            reads = [(method, params) for method, params in provider.calls
                     if method in ('eth_call', 'eth_getBalance')]
            self.assertEqual(len(reads), 1)
            method, params = reads[0]
            self.assertEqual(params[1], {'blockHash': HASH, 'requireCanonical': True})
            if token_id == 'eth':
                self.assertEqual(method, 'eth_getBalance')
            else:
                self.assertEqual(method, 'eth_call')
                self.assertEqual(params[0]['to'].lower(), ASSETS[token_id].lower())

    async def test_slow_asset_does_not_hold_another_asset_and_cancellation_is_independent(self):
        provider = Provider(blocked=CORE)
        reader = service(provider)
        slow = asyncio.create_task(reader.get(WALLET, 'cygld'))
        await provider.started.wait()
        quick = await asyncio.wait_for(reader.get(WALLET, 'eth'), 0.5)
        self.assertEqual(quick['balance']['status'], 'success')
        self.assertFalse(slow.done())
        slow.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await slow
        self.assertEqual(provider.cancelled, 1)

    async def test_concurrent_holders_and_assets_do_not_share_values(self):
        reader = service(Provider())
        first, second = await asyncio.gather(reader.get(WALLET, 'paxg'), reader.get(OTHER, 'usdc'))
        self.assertEqual((first['holder'], first['tokenId'], first['balance']['value']),
                         (WALLET, 'paxg', str(2**255)))
        self.assertEqual((second['holder'], second['tokenId'], second['balance']['value']),
                         (OTHER, 'usdc', str(2**255 + 1)))

    async def test_real_zero_is_success_while_selected_read_failure_stays_explicit(self):
        for token_id in ('eth', 'paxg'):
            zero = await service(Provider(value=0)).get(WALLET, token_id)
            self.assertEqual(zero['balance'], {'status': 'success', 'value': '0'})
            target = 'eth' if token_id == 'eth' else ASSETS[token_id].lower()
            failed = await service(Provider(failure=target)).get(WALLET, token_id)
            self.assertEqual(failed['balance'], {'status': 'failure', 'error': 'contract-read-failed'})
            self.assertNotIn('password', json.dumps(failed))

    async def test_http_fast_response_arrives_while_another_request_is_blocked(self):
        provider = Provider(blocked=CORE)
        app = create_app(token_balance=service(provider))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            slow = asyncio.create_task(client.get('/api/account/token-balance', params={'holder': WALLET, 'tokenId': 'cygld'}))
            await provider.started.wait()
            quick = await asyncio.wait_for(client.get('/api/account/token-balance', params={'holder': WALLET, 'tokenId': 'usdc'}), 0.5)
            self.assertEqual(quick.status_code, 200)
            self.assertEqual(quick.json()['balance']['status'], 'success')
            self.assertEqual(quick.headers['cache-control'], 'no-store')
            self.assertFalse(slow.done())
            slow.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await slow
            self.assertEqual(provider.cancelled, 1)

    async def test_http_selector_validation_ignores_arbitrary_contract_or_provider_fields(self):
        provider = Provider()
        app = create_app(token_balance=service(provider))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            invalid_holder = await client.get('/api/account/token-balance', params={'holder': 'invalid', 'tokenId': 'paxg'})
            self.assertEqual(invalid_holder.status_code, 400)
            self.assertEqual(invalid_holder.json()['error'], 'A valid holder address is required.')
            for token_id in (None, 'unknown', '0x' + '9' * 40):
                query = {'holder': WALLET, **({'tokenId': token_id} if token_id else {})}
                invalid = await client.get('/api/account/token-balance', params=query)
                self.assertEqual(invalid.status_code, 400)
                self.assertIn('tokenId', invalid.json()['error'])
            for method in ('get', 'head'):
                response = await getattr(client, method)('/api/account/token-balance', params={
                    'holder': WALLET, 'tokenId': 'paxg', 'address': 'ignored', 'provider': 'http://untrusted.invalid'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                if method == 'get':
                    self.assertEqual(response.json()['tokenId'], 'paxg')
            self.assertNotIn('untrusted', json.dumps(provider.calls))
            self.assertIn('operation="/api/account/token-balance"', (await client.get('/metrics')).text)

    async def test_http_head_failure_or_reorg_is_unavailable_without_a_balance_guess(self):
        for provider in (Provider(failure='head'), Provider(reorg=True)):
            app = create_app(token_balance=service(provider))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                response = await client.get('/api/account/token-balance', params={'holder': WALLET, 'tokenId': 'paxg'})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertNotIn('balance', response.json())
            self.assertNotIn('password', response.text)


if __name__ == '__main__':
    unittest.main()
