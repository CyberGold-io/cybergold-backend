"""Preserve Safe destination classification without an EOA guess on RPC failure."""
import asyncio
import json
from types import SimpleNamespace
import unittest

import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.governance_safe_principal import SafePrincipalRpc
from cybergold_candidate.governance_target_code import GovernanceTargetCode
from cybergold_candidate.recovery_rpc import RecoveryApiError

ADDRESS='0x'+'1'*40
HASH='0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, code='0x6000', failure=False, reorg=False, chain='0x7a6a', blocked=False):
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
        elif method=='eth_getCode':
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
    return GovernanceTargetCode(settings,SafePrincipalRpc(settings,AsyncWeb3(provider)))


class TargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_code_is_false_but_zero_instruction_has_code(self):
        for code,expected in (('0x',False),('0x00',True),('0x6000',True)):
            provider=Provider(code);value=await service(provider).get(ADDRESS)
            self.assertEqual(value['hasCode'],expected)
            self.assertEqual(value['context']['blockNumber'],'101')
            self.assertEqual(provider.calls[2],('eth_getCode',[ADDRESS,{'blockHash':HASH,'requireCanonical':True}]))
            self.assertFalse(any(method=='eth_call' for method,_ in provider.calls))

    async def test_address_binding_is_per_request_not_a_retained_guess(self):
        provider=Provider();reader=service(provider)
        addresses=[ADDRESS,'0x'+'2'*40]
        values=await asyncio.gather(*(reader.get(address) for address in addresses))
        self.assertEqual([value['address'] for value in values],addresses)
        self.assertEqual([params[0] for method,params in provider.calls if method=='eth_getCode'],addresses)

    async def test_wrong_chain_and_reorg_fail_without_classifying(self):
        for provider in (Provider(chain='0x1'),Provider(reorg=True)):
            with self.assertRaises((ValueError,RecoveryApiError)):await service(provider).get(ADDRESS)

    async def test_disconnect_cancels_native_code_read(self):
        provider=Provider(blocked=True);task=asyncio.create_task(service(provider).get(ADDRESS))
        await provider.started.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(provider.cancelled)

    async def test_http_failure_is_redacted_unavailable_not_empty_code(self):
        for reader in (None,service(Provider(failure=True)),service(Provider(code='invalid'))):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(governance_target_code=reader)),base_url='http://fixture') as client:
                response=await client.get('/api/governance/target-code',params={'address':ADDRESS})
                self.assertEqual(response.status_code,503)
                self.assertEqual(response.headers['cache-control'],'no-store')
                self.assertNotIn('password',response.text)
                self.assertNotIn('hasCode',response.json())
                self.assertIn('correlationId',response.json())

    async def test_get_head_shape_and_standard_operation_metrics(self):
        provider=Provider();app=create_app(governance_target_code=service(provider))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            for method in ('get','head'):
                response=await getattr(client,method)('/api/governance/target-code',params={'address':ADDRESS,'provider':'ignored'})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.headers['cache-control'],'no-store')
                if method=='get':self.assertTrue(response.json()['hasCode'])
            self.assertEqual((await client.get('/api/governance/target-code',params={'address':'invalid'})).status_code,400)
            self.assertIn('operation="/api/governance/target-code"',(await client.get('/metrics')).text)
        self.assertNotIn('ignored',json.dumps(provider.calls))


if __name__=='__main__':unittest.main()
