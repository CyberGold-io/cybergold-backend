"""Canonical Viem/Web3 balance wire bytes, wallet isolation and ordinary failures."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.recovery_rpc import RecoveryApiError
from cybergold_candidate.wallet_balances import TOKENS, WalletBalances, WalletBalancesRpc

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, failure=None, reorg=False, blocked=False, malformed=None, count=None, malformed_outer=False, chain='0x7a6a'):
        super().__init__()
        self.calls, self.failure, self.reorg, self.blocked = [], failure, reorg, blocked
        self.started, self.cancelled = asyncio.Event(), 0
        self.codec, self.malformed, self.count = Web3().codec, malformed, count
        self.malformed_outer = malformed_outer
        self.chain = chain

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'eth_getBlockByNumber':
            if self.failure == method:
                return {'jsonrpc':'2.0', 'id':1, 'error':{'code':-32000, 'message':'private-password'}}
            result = {'number':'0x65', 'timestamp':'0x6a000001',
                      'hash': '0x'+'b'*64 if self.reorg and params[0] != 'latest' else HASH}
        elif method == 'eth_call':
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            if self.failure == method:
                return {'jsonrpc':'2.0', 'id':1, 'error':{'code':-32000, 'message':'https://secret:password@private.invalid'}}
            row = next(row for row in REFERENCE['rows'] if row['data'] == params[0]['data'])
            members = [(member['success'], bytes.fromhex(member['returnData'][2:])) for member in row['members']]
            for index, call in enumerate(row['calls']):
                if call['target'].lower() == self.failure or (self.failure == 'native' and index == 6):
                    members[index] = (False, b'private provider password')
                if self.malformed == index:
                    members[index] = (True, b'')
            if self.count is not None:
                members = members[:self.count] if self.count <= 7 else members + [members[-1]]
            result = '0x1234' if self.malformed_outer else '0x' + self.codec.encode(['(bool,bytes)[]'], [members]).hex()
        else:
            raise AssertionError(method)
        return {'jsonrpc':'2.0', 'id':1, 'result':result}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE['core'], NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=None)
    return WalletBalances(settings, WalletBalancesRpc(settings, AsyncWeb3(provider)))


class WalletBalancesTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_token_balances_lossless_values_and_hash_pinning(self):
        provider = Provider()
        value = await service(provider).get(REFERENCE['rows'][0]['holder'], ordinary=True)
        self.assertEqual(value['native'], {'status':'success', 'value':str(2**200)})
        self.assertEqual([row['id'] for row in value['tokens']], ['cygld', 'xaut', 'paxg', 'usdt', 'usdc', 'weth'])
        self.assertTrue(all(row['balance'] == {'status':'success', 'value':str(2**255)} for row in value['tokens']))
        self.assertEqual(value['context']['chainId'], 31338)
        self.assertEqual(value['context']['blockHash'], HASH)
        self.assertEqual([method for method, _ in provider.calls], ['eth_getBlockByNumber', 'eth_call'])
        self.assertEqual(provider.calls[0][1], ('latest', False))
        calls = [params for method, params in provider.calls if method == 'eth_call']
        self.assertEqual(len(calls), 1)
        self.assertFalse(any(method == 'eth_getBalance' for method, _ in provider.calls))
        self.assertEqual(calls[0][1], {'blockHash':HASH, 'requireCanonical':True})
        self.assertEqual(calls[0][0]['to'].lower(), REFERENCE['multicall'])
        # Compare actual aggregate calldata against independently encoded Viem.
        self.assertEqual(calls[0][0]['data'], REFERENCE['rows'][0]['data'])
        inner = provider.codec.decode(['(address,bool,bytes)[]'], bytes.fromhex(calls[0][0]['data'][10:]))[0]
        self.assertEqual([target.lower() for target, _, _ in inner],
                         [REFERENCE['core'].lower(), *(address.lower() for _, address in TOKENS), REFERENCE['multicall']])
        self.assertTrue(all(allow for _, allow, _ in inner))
        self.assertEqual(inner[-1][2][:4], Web3.keccak(text='getEthBalance(address)')[:4])
        self.assertEqual(provider.codec.decode(['address'], inner[-1][2][4:])[0], REFERENCE['rows'][0]['holder'])

    async def test_two_concurrent_wallets_do_not_share_holder_or_amount(self):
        observer = service(Provider())
        values = await asyncio.gather(*(observer.get(row['holder'], ordinary=True) for row in REFERENCE['rows']))
        for index, value in enumerate(values):
            self.assertEqual(value['holder'], REFERENCE['rows'][index]['holder'])
            self.assertEqual(value['tokens'][0]['balance']['value'], str(2**255+index))
            self.assertEqual(value['native']['value'], str(2**200+index))

    async def test_partial_token_and_native_failures_are_not_zero(self):
        for ordinary in (False, True):
            token_failure = await service(Provider(failure=TOKENS[0][1].lower())).get(
                REFERENCE['rows'][0]['holder'], ordinary=ordinary)
            self.assertEqual(token_failure['tokens'][1]['balance'], {'status':'failure', 'error':'contract-read-failed'})
            self.assertEqual(token_failure['tokens'][0]['balance']['status'], 'success')
            native_failure = await service(Provider(failure='native')).get(
                REFERENCE['rows'][0]['holder'], ordinary=ordinary)
            self.assertEqual(native_failure['native']['status'], 'failure')
            self.assertNotIn('password', json.dumps(native_failure))

    async def test_successful_but_malformed_member_is_failure_not_zero(self):
        for ordinary in (False, True):
            for index in (1, 6):
                value = await service(Provider(malformed=index)).get(REFERENCE['rows'][0]['holder'], ordinary=ordinary)
                selected = value['native'] if index == 6 else value['tokens'][index]['balance']
                self.assertEqual(selected, {'status':'failure', 'error':'contract-read-failed'})
                self.assertEqual(value['tokens'][0]['balance']['status'], 'success')

    async def test_missing_or_extra_aggregate_members_are_unavailable_without_fallback(self):
        for count in (0, 6, 8):
            provider = Provider(count=count)
            app = create_app(wallet_balances=service(provider))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.get('/api/account/wallet-balances', params={'holder':REFERENCE['rows'][0]['holder']})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('tokens', response.json())
            self.assertEqual(len([method for method, _ in provider.calls if method == 'eth_call']), 1)

    async def test_malformed_aggregate_result_is_unavailable_without_fallback(self):
        provider = Provider(malformed_outer=True)
        app = create_app(wallet_balances=service(provider))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/api/account/wallet-balances', params={'holder':REFERENCE['rows'][0]['holder']})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('tokens', response.json())
        self.assertEqual(len([method for method, _ in provider.calls if method == 'eth_call']), 1)
        self.assertFalse(any(method == 'eth_getBalance' for method, _ in provider.calls))

    async def test_display_keeps_successful_pinned_reads_without_final_reorg_check(self):
        provider = Provider(reorg=True, chain='0x1')
        value = await service(provider).get(REFERENCE['rows'][0]['holder'], ordinary=True)
        self.assertEqual(value['native']['status'], 'success')
        self.assertEqual(value['context']['blockHash'], HASH)
        self.assertEqual([method for method, _ in provider.calls], ['eth_getBlockByNumber', 'eth_call'])

    async def test_swap_preflight_retains_chain_check_and_final_block_reread(self):
        provider = Provider()
        await service(provider).get(REFERENCE['rows'][0]['holder'])
        self.assertEqual([method for method, _ in provider.calls],
                         ['eth_chainId', 'eth_getBlockByNumber', 'eth_call', 'eth_getBlockByNumber'])
        self.assertEqual(provider.calls[-1][1], ('0x65', False))
        self.assertEqual(provider.calls[2][1][0]['data'], REFERENCE['rows'][0]['data'])
        self.assertEqual(provider.calls[2][1][1], {'blockHash':HASH, 'requireCanonical':True})
        for provider, error in ((Provider(chain='0x1'), ValueError), (Provider(reorg=True), RecoveryApiError)):
            with self.assertRaises(error):
                await service(provider).get(REFERENCE['rows'][0]['holder'])

    async def test_caller_cancellation_stops_the_single_aggregate_call(self):
        for ordinary in (False, True):
            provider = Provider(blocked=True)
            task = asyncio.create_task(service(provider).get(REFERENCE['rows'][0]['holder'], ordinary=ordinary))
            await provider.started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(provider.cancelled, 1)

    async def test_http_invalid_holder_and_outage_redacted_no_store(self):
        for provider, expected in ((Provider(), 200), (Provider(failure='eth_getBlockByNumber'), 503), (Provider(failure='eth_call'), 503)):
            app = create_app(wallet_balances=service(provider))
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                invalid = await client.get('/api/account/wallet-balances?holder=private-password')
                self.assertEqual(invalid.status_code, 400)
                self.assertEqual(invalid.headers['cache-control'], 'no-store')
                self.assertNotIn('private-password', invalid.text)
                value = await client.get('/api/account/wallet-balances', params={'holder':REFERENCE['rows'][0]['holder'], 'purpose':'display', 'token':'0x0', 'provider':'http://untrusted.invalid'})
            self.assertEqual(value.status_code, expected)
            self.assertEqual(value.headers['cache-control'], 'no-store')
            self.assertNotIn('password', value.text)
            if expected == 503:
                self.assertIn('correlationId', value.json())


    async def test_http_purpose_preserves_existing_swap_preflight_checks(self):
        for purpose in (None, 'ignored', 'swap-preflight', 'display'):
            for provider in (Provider(reorg=True), Provider(chain='0x1')):
                app = create_app(wallet_balances=service(provider))
                params = {'holder':REFERENCE['rows'][0]['holder']}
                if purpose is not None:
                    params['purpose'] = purpose
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                    value = await client.get('/api/account/wallet-balances', params=params)
                self.assertEqual(value.status_code, 200 if purpose == 'display' else 503)
                self.assertEqual([method for method, _ in provider.calls],
                    ['eth_getBlockByNumber', 'eth_call'] if purpose == 'display' else
                    ['eth_chainId', 'eth_getBlockByNumber', 'eth_call', 'eth_getBlockByNumber'] if provider.reorg else
                    ['eth_chainId'])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
