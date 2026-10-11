"""Configured router authority, native wire bytes and fresh Permit2 facts."""
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
from cybergold_candidate.permit2_context import Permit2Context, Permit2Rpc

REFERENCE=json.loads(Path(sys.argv[1]).read_text())
HASH='0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self,failure=None,reorg=False,blocked=False,code='0x6000'):
        super().__init__()
        self.calls,self.failure,self.reorg,self.blocked,self.code=[],failure,reorg,blocked,code
        self.started,self.cancelled=asyncio.Event(),0

    async def make_request(self,method,params):
        self.calls.append((method,params))
        if method=='eth_chainId':result='0x7a6a'
        elif method=='eth_getBlockByNumber':
            result={'number':'0x65','timestamp':'0x6a000001','hash':'0x'+'b'*64 if self.reorg and params[0]!='latest' else HASH}
        elif method in ('eth_call','eth_getCode'):
            if self.failure==method:
                return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://secret:password@private.invalid'}}
            if method=='eth_getCode':result=self.code
            else:
                row=next(row for row in [REFERENCE['router'],*REFERENCE['nonceRows'],*REFERENCE['allowanceRows']]
                    if row['data']==params[0]['data'] and
                       ('token' not in row or row['token']==params[0]['to']))
                if self.blocked and row is not REFERENCE['router']:
                    self.started.set()
                    try:await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        self.cancelled+=1
                        raise
                result=row['result']
        else:raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    async def disconnect(self):pass


def service(provider):
    settings=SimpleNamespace(RPC_URL='http://synthetic.invalid',RPC_AUTHORIZATION='Bearer fixture-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='0x'+'4'*40,NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=REFERENCE['helpers'])
    return Permit2Context(settings,Permit2Rpc(settings,AsyncWeb3(provider)))


class Permit2ContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_and_bytecode_use_same_canonical_hash(self):
        provider=Provider()
        value=await service(provider).get({'mode':'verify'})
        self.assertEqual(value['permit2'],REFERENCE['permit2'])
        self.assertEqual(value['result'],{'code':'0x6000'})
        for method,params in provider.calls:
            if method in ('eth_call','eth_getCode'):
                self.assertEqual(params[1],{'blockHash':HASH,'requireCanonical':True})
        self.assertEqual([params[0] for method,params in provider.calls if method=='eth_getCode'],[REFERENCE['permit2']])

    async def test_empty_bytecode_is_reported_for_existing_app_verification(self):
        value=await service(Provider(code='0x')).get({'mode':'verify'})
        self.assertEqual(value['result']['code'],'0x')

    async def test_full_word_advances_to_first_unused_nonce(self):
        provider=Provider()
        value=await service(provider).get({'mode':'nonce','owner':REFERENCE['owners'][0]})
        self.assertEqual(value['result']['nonce'],'257')
        rows=[params for method,params in provider.calls if method=='eth_call']
        self.assertEqual([params[0]['data'] for params in rows],[REFERENCE['router']['data'],REFERENCE['nonceRows'][0]['data'],REFERENCE['nonceRows'][1]['data']])
        self.assertTrue(all(params[0]['to']==REFERENCE['permit2'] for params in rows[1:]))

    async def test_two_owners_do_not_share_nonce_or_allowances(self):
        observer=service(Provider())
        values=await asyncio.gather(*(observer.get({'mode':'nonce','owner':owner}) for owner in REFERENCE['owners']))
        self.assertEqual([value['result']['nonce'] for value in values],['257','1'])
        values=await asyncio.gather(*(observer.get({'mode':'allowances','owner':owner,'tokens':REFERENCE['tokens']}) for owner in REFERENCE['owners']))
        for index,value in enumerate(values):
            self.assertEqual([row['value'] for row in value['result']['allowances']],[str(2**255+index+offset) for offset in range(2)])

    async def test_allowance_order_duplicates_and_full_integer_precision(self):
        provider=Provider()
        tokens=[REFERENCE['tokens'][1],REFERENCE['tokens'][0],REFERENCE['tokens'][1]]
        value=await service(provider).get({'mode':'allowances','owner':REFERENCE['owners'][0],'tokens':tokens})
        self.assertEqual([row['token'] for row in value['result']['allowances']],tokens)
        self.assertEqual([row['value'] for row in value['result']['allowances']],[str(2**255+1),str(2**255),str(2**255+1)])
        calls=[params for method,params in provider.calls if method=='eth_call']
        self.assertEqual([params[0]['to'] for params in calls],[REFERENCE['helpers'],*dict.fromkeys(tokens)])
        self.assertTrue(all(params[1]=={'blockHash':HASH,'requireCanonical':True} for params in calls))

    async def test_empty_permission_list_probes_no_token(self):
        provider=Provider()
        value=await service(provider).get({'mode':'allowances','owner':REFERENCE['owners'][0],'tokens':[]})
        self.assertEqual(value['result']['allowances'],[])
        self.assertEqual(sum(method=='eth_call' for method,_ in provider.calls),1)

    async def test_reorg_never_returns_mixed_permit_context(self):
        with self.assertRaises(Exception):await service(Provider(reorg=True)).get({'mode':'verify'})

    async def test_cancellation_stops_all_pending_allowance_reads(self):
        provider=Provider(blocked=True)
        task=asyncio.create_task(service(provider).get({'mode':'allowances','owner':REFERENCE['owners'][0],'tokens':REFERENCE['tokens']}))
        await provider.started.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(provider.cancelled,2)

    async def test_http_modes_bad_shapes_no_store_and_sanitized_provider_failures(self):
        for provider,expected in ((Provider(),200),(Provider(failure='eth_call'),503)):
            app=create_app(permit2_context=service(provider))
            async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                for body in ({'mode':'arbitrary-method'},{'mode':'nonce','owner':'private-password'},{'mode':'allowances','owner':REFERENCE['owners'][0],'tokens':['0x0']}):
                    invalid=await client.post('/api/account/permit2',json=body)
                    self.assertEqual(invalid.status_code,400);self.assertNotIn('private-password',invalid.text)
                result=await client.post('/api/account/permit2?provider=http://untrusted.invalid',json={'mode':'verify','target':'0x0'})
                self.assertEqual(result.status_code,expected)
                self.assertEqual(result.headers['cache-control'],'no-store');self.assertNotIn('password',result.text)
                if expected==503:self.assertIn('correlationId',result.json())


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
