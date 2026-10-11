"""Exact recovery redemption simulations versus the canonical Viem ABI."""
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
from cybergold_candidate.recovery_redemption import RedemptionRequest, RecoveryRedemption, RecoveryRedemptionRpc

REFERENCE=json.loads(Path(sys.argv[1]).read_text()); HASH='0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, failure=False, blocked=False, reorg=False, chain='0x7a6a'):
        super().__init__()
        self.calls=[];self.failure,self.blocked,self.reorg,self.chain=failure,blocked,reorg,chain
        self.started,self.cancelled=asyncio.Event(),False

    async def make_request(self,method,params):
        self.calls.append((method,params))
        if method=='eth_chainId':result=self.chain
        elif method=='eth_getBlockByNumber':result={'number':'0x65','timestamp':'0x6a000001','hash':'0x'+'b'*64 if self.reorg and params[0]!='latest' else HASH}
        elif method=='eth_call':
            self.started.set()
            if self.blocked:
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:self.cancelled=True;raise
            if self.failure:return {'jsonrpc':'2.0','id':1,'error':{'code':3,'message':'execution reverted https://password@private.invalid'}}
            row=next(row for row in REFERENCE if row['call']==params[0]);result=row['result']
        else:raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    async def disconnect(self):pass


def service(provider):
    settings=SimpleNamespace(RPC_URL='http://synthetic.invalid',RPC_AUTHORIZATION='Bearer fixture',NEXT_PUBLIC_CHAIN_ID='31338',NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE[0]['core'])
    return RecoveryRedemption(settings,RecoveryRedemptionRpc(settings,AsyncWeb3(provider)))


class RedemptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_calldata_sender_recipient_minimum_and_wide_values(self):
        provider=Provider();observer=service(provider)
        for row in REFERENCE:
            result=await observer.get(RedemptionRequest.model_validate(row['payload']))
            self.assertEqual(result['rawOut'],row['rawOut'])
            for key,value in row['payload'].items():self.assertEqual(result[key].lower(),value.lower())
        reads=[params for method,params in provider.calls if method=='eth_call']
        self.assertEqual([read[0] for read in reads],[row['call'] for row in REFERENCE])
        self.assertTrue(all(read[1]=={'blockHash':HASH,'requireCanonical':True} for read in reads))

    async def test_concurrent_holders_and_intents_are_not_cached_or_modified(self):
        provider=Provider();observer=service(provider)
        result=await asyncio.gather(*(observer.get(RedemptionRequest.model_validate(row['payload'])) for row in REFERENCE))
        self.assertEqual([row['rawOut'] for row in result],[row['rawOut'] for row in REFERENCE])
        await observer.get(RedemptionRequest.model_validate(REFERENCE[0]['payload']))
        self.assertEqual(sum(method=='eth_call' for method,_ in provider.calls),4)

    async def test_canonicality_and_configured_chain_failures(self):
        for provider,message in ((Provider(reorg=True),'head changed'),(Provider(chain='0x1'),'chain mismatch')):
            with self.assertRaisesRegex(ValueError,message):await service(provider).get(RedemptionRequest.model_validate(REFERENCE[0]['payload']))

    async def test_caller_cancellation_stops_simulation(self):
        provider=Provider(blocked=True);task=asyncio.create_task(service(provider).get(RedemptionRequest.model_validate(REFERENCE[0]['payload'])))
        await provider.started.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(provider.cancelled)

    async def test_native_revert_is_redacted_and_never_a_successful_preview(self):
        app=create_app(recovery_redemption=service(Provider(failure=True)))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            result=await client.post('/api/transaction/recovery-redemption',json=REFERENCE[0]['payload'])
            self.assertEqual(result.status_code,503);self.assertEqual(result.headers['cache-control'],'no-store')
            self.assertNotIn('password',result.text);self.assertNotIn('rawOut',result.json())

    async def test_fixed_request_and_ordinary_native_uint_range_error(self):
        provider=Provider();app=create_app(recovery_redemption=service(provider))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            for payload in ({},{**REFERENCE[0]['payload'],'shares':'-1'},{**REFERENCE[0]['payload'],'holder':'bad'}):
                self.assertEqual((await client.post('/api/transaction/recovery-redemption',json=payload)).status_code,400)
            result=await client.post('/api/transaction/recovery-redemption',json={**REFERENCE[1]['payload'],'provider':'http://unused.invalid','recipient':REFERENCE[0]['payload']['holder']})
            self.assertEqual(result.status_code,200);self.assertEqual(result.json()['holder'].lower(),REFERENCE[1]['payload']['holder'])
            self.assertEqual((await client.post('/api/transaction/recovery-redemption',json={**REFERENCE[0]['payload'],'shares':str(2**256)})).status_code,503)
        self.assertTrue(all(method in ('eth_chainId','eth_getBlockByNumber','eth_call') for method,_ in provider.calls))


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
