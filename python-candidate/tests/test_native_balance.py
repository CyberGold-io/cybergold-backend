"""Native balances: one holder read, lossless values and no token fan-out."""
import asyncio
import json
from types import SimpleNamespace
import unittest

import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.recovery_rpc import RecoveryApiError
from cybergold_candidate.wallet_balances import NativeBalance, WalletBalancesRpc

ADDRESS='0x'+'1'*40
HASH='0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, code=hex(2**200), failure=False, reorg=False, chain='0x7a6a', blocked=False):
        super().__init__()
        self.code,self.failure,self.reorg,self.chain,self.blocked=code,failure,reorg,chain,blocked
        self.calls,self.cancelled=[],False
        self.started=asyncio.Event()

    async def make_request(self, method, params):
        self.calls.append((method,params))
        if method=='eth_chainId':result=self.chain
        elif method=='eth_getBlockByNumber':
            result={'number':'0x65','timestamp':'0x6a000001',
                    'hash':'0x'+'b'*64 if self.reorg and params[0]!='latest' else HASH}
        elif method=='eth_getBalance':
            self.started.set()
            if self.blocked:
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled=True
                    raise
            if self.failure:return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://password@private.invalid'}}
            result=self.code
        else:raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    async def disconnect(self):pass


def service(provider):
    settings=SimpleNamespace(RPC_URL='http://synthetic.invalid',RPC_AUTHORIZATION='Bearer fixture-only',
        NEXT_PUBLIC_CHAIN_ID='31338',NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=ADDRESS,
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=None)
    return NativeBalance(settings,WalletBalancesRpc(settings,AsyncWeb3(provider)))


class NativeBalanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_and_wide_native_balances_without_erc20_reads(self):
        for code,expected in (('0x0','0'),('0x1','1'),(hex(2**200),str(2**200))):
            provider=Provider(code);value=await service(provider).get(ADDRESS,ordinary=True)
            self.assertEqual(value['balance'],expected)
            self.assertEqual(value['context']['blockNumber'],'101')
            self.assertEqual(provider.calls,[('eth_getBlockByNumber',('latest',False)),
                ('eth_getBalance',[ADDRESS,{'blockHash':HASH,'requireCanonical':True}])])

    async def test_address_binding_is_per_request_not_a_retained_guess(self):
        provider=Provider();reader=service(provider)
        addresses=[ADDRESS,'0x'+'2'*40]
        values=await asyncio.gather(*(reader.get(address,ordinary=True) for address in addresses))
        self.assertEqual([value['holder'] for value in values],addresses)
        self.assertEqual([params[0] for method,params in provider.calls if method=='eth_getBalance'],addresses)

    async def test_ordinary_native_balance_uses_pinned_read_without_surrounding_checks(self):
        provider=Provider(reorg=True)
        value=await service(provider).get(ADDRESS,ordinary=True)
        self.assertEqual(value['balance'],str(2**200))
        self.assertEqual(value['context']['blockHash'],HASH)
        self.assertEqual([method for method,_ in provider.calls],['eth_getBlockByNumber','eth_getBalance'])

    async def test_disconnect_cancels_native_balance_read(self):
        provider=Provider(blocked=True);task=asyncio.create_task(service(provider).get(ADDRESS,ordinary=True))
        await provider.started.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(provider.cancelled)

    async def test_http_failure_is_redacted_unavailable_not_zero(self):
        for reader in (None,service(Provider(failure=True)),service(Provider(code='invalid'))):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(native_balance=reader)),base_url='http://fixture') as client:
                response=await client.get('/api/account/native-balance',params={'holder':ADDRESS,'purpose':'display'})
                self.assertEqual(response.status_code,503)
                self.assertEqual(response.headers['cache-control'],'no-store')
                self.assertNotIn('password',response.text)
                self.assertNotIn('balance',response.json())
                self.assertIn('correlationId',response.json())

    async def test_get_head_shape_and_standard_operation_metrics(self):
        provider=Provider();app=create_app(native_balance=service(provider))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            for method in ('get','head'):
                response=await getattr(client,method)('/api/account/native-balance',params={'holder':ADDRESS,'purpose':'display','provider':'ignored'})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.headers['cache-control'],'no-store')
                if method=='get':self.assertEqual(response.json()['balance'],str(2**200))
            self.assertEqual((await client.get('/api/account/native-balance',params={'holder':'invalid'})).status_code,400)
            self.assertIn('operation="/api/account/native-balance"',(await client.get('/metrics')).text)
        self.assertNotIn('ignored',json.dumps(provider.calls))

    async def test_default_native_balance_retains_chain_and_final_block_checks(self):
        provider=Provider()
        await service(provider).get(ADDRESS)
        self.assertEqual([method for method,_ in provider.calls],
            ['eth_chainId','eth_getBlockByNumber','eth_getBalance','eth_getBlockByNumber'])
        for provider,error in ((Provider(chain='0x1'),ValueError),(Provider(reorg=True),RecoveryApiError)):
            with self.assertRaises(error):await service(provider).get(ADDRESS)

    async def test_http_only_display_opts_into_ordinary_native_balance(self):
        for purpose in (None,'ignored','swap-preflight','display'):
            for provider in (Provider(reorg=True),Provider(chain='0x1')):
                params={'holder':ADDRESS}
                if purpose is not None:params['purpose']=purpose
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(native_balance=service(provider))),base_url='http://fixture') as client:
                    response=await client.get('/api/account/native-balance',params=params)
                self.assertEqual(response.status_code,200 if purpose=='display' else 503)
                self.assertEqual(len(provider.calls),2 if purpose=='display' else (4 if provider.reorg else 1))


if __name__=='__main__':unittest.main()
