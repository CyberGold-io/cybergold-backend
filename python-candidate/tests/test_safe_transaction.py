"""Actual Viem Safe wire calls versus Web3; unsigned payload isolation."""
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
from cybergold_candidate.safe_transaction import SafeHashRequest, SafeTransaction, SafeTransactionRpc

REFERENCE=json.loads(Path(sys.argv[1]).read_text())
HASH='0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, failure=False, blocked=False, reorg=False, chain='0x7a6a'):
        super().__init__()
        self.calls=[]
        self.failure,self.blocked,self.reorg,self.chain=failure,blocked,reorg,chain
        self.started,self.cancelled=asyncio.Event(),False

    async def make_request(self,method,params):
        self.calls.append((method,params))
        if method=='eth_chainId':
            result=self.chain
        elif method=='eth_getBlockByNumber':
            result={'number':'0x65','timestamp':'0x6a000001',
                'hash':'0x'+'b'*64 if self.reorg and params[0]!='latest' else HASH}
        elif method=='eth_call':
            self.started.set()
            if self.blocked:
                try: await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled=True
                    raise
            if self.failure:
                return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://password@private.invalid'}}
            call=params[0]
            row=next(row for row in REFERENCE if row['payload']['address'].lower()==call['to'].lower())
            if call['data']==row['calls'][0]['params'][0]['data']:
                result='0x'+int(row['nonce']).to_bytes(32).hex()
            else:
                if call['data']!=row['calls'][1]['params'][0]['data']:
                    raise AssertionError('unsigned Safe payload changed')
                result=row['safeTxHash']
        else:
            raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    async def disconnect(self): pass


def service(provider):
    # No unrelated Core/Helpers/roster/version or code startup requirement.
    settings=SimpleNamespace(RPC_URL='http://synthetic.invalid',RPC_AUTHORIZATION='Bearer fixture',NEXT_PUBLIC_CHAIN_ID='31338')
    return SafeTransaction(settings,SafeTransactionRpc(settings,AsyncWeb3(provider)))


class SafeTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_viem_wire_and_wide_nonce_payload_hash(self):
        for row in REFERENCE:
            provider=Provider();observer=service(provider)
            nonce=await observer.get(row['payload']['address'])
            hashed=await observer.get(row['payload']['address'],SafeHashRequest.model_validate(row['payload']))
            self.assertEqual(nonce['nonce'],row['nonce'])
            self.assertEqual(hashed['safeTxHash'],row['safeTxHash'])
            calls=[{'method':method,'params':list(params)} for method,params in provider.calls if method=='eth_call']
            for actual,expected in zip(calls,row['calls'],strict=True):
                self.assertEqual(actual['params'][0],expected['params'][0])
                self.assertEqual(actual['params'][1],{'blockHash':HASH,'requireCanonical':True})

    async def test_concurrent_safe_addresses_and_exact_unsigned_payloads_are_isolated(self):
        provider=Provider();observer=service(provider)
        results=await asyncio.gather(*(observer.get(row['payload']['address'],SafeHashRequest.model_validate(row['payload'])) for row in REFERENCE))
        self.assertEqual([result['safeTxHash'] for result in results],[row['safeTxHash'] for row in REFERENCE])
        for _ in range(2): await observer.get(REFERENCE[0]['payload']['address'])
        self.assertEqual(sum(method=='eth_call' for method,_ in provider.calls),5)

    async def test_canonical_context_is_not_returned_after_reorg(self):
        with self.assertRaisesRegex(ValueError,'head changed'):
            await service(Provider(reorg=True)).get(REFERENCE[0]['payload']['address'])

    async def test_wrong_chain_does_not_read_safe(self):
        provider=Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError,'chain mismatch'):
            await service(provider).get(REFERENCE[0]['payload']['address'])
        self.assertEqual([method for method,_ in provider.calls],['eth_chainId'])

    async def test_cancellation_stops_provider_call(self):
        provider=Provider(blocked=True)
        task=asyncio.create_task(service(provider).get(REFERENCE[0]['payload']['address']))
        await provider.started.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(provider.cancelled)

    async def test_http_outage_is_redacted_not_a_default_nonce_or_hash(self):
        app=create_app(safe_transaction=service(Provider(failure=True)))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            for result in (await client.get('/api/governance/safe-nonce',params={'address':REFERENCE[0]['payload']['address']}),
                           await client.post('/api/governance/safe-transaction-hash',json=REFERENCE[0]['payload'])):
                self.assertEqual(result.status_code,503)
                self.assertEqual(result.headers['cache-control'],'no-store')
                self.assertNotIn('password',result.text)
                self.assertNotIn('nonce',result.json());self.assertNotIn('safeTxHash',result.json())

    async def test_fixed_http_shapes_head_and_native_abi_range_error(self):
        provider=Provider();app=create_app(safe_transaction=service(provider))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            self.assertEqual((await client.get('/api/governance/safe-nonce?address=bad')).status_code,400)
            self.assertEqual((await client.post('/api/governance/safe-transaction-hash',content='{')).status_code,400)
            result=await client.post('/api/governance/safe-transaction-hash',json={**REFERENCE[0]['payload'],'provider':'http://untrusted.invalid'})
            self.assertEqual(result.status_code,200);self.assertEqual(result.json()['safeTxHash'],REFERENCE[0]['safeTxHash'])
            head=await client.head('/api/governance/safe-nonce',params={'address':REFERENCE[0]['payload']['address']})
            self.assertEqual(head.status_code,200);self.assertEqual(head.content,b'')
            result=await client.post('/api/governance/safe-transaction-hash',json={**REFERENCE[0]['payload'],'operation':256})
            self.assertEqual(result.status_code,503)
            self.assertNotIn('safeTxHash',result.json())
        self.assertTrue(all(method in ('eth_call','eth_chainId','eth_getBlockByNumber') for method,_ in provider.calls))


if __name__=='__main__': unittest.main(argv=[sys.argv[0]])
