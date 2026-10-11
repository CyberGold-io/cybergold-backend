"""Actual Viem calldata/Web3 decoding, fresh signing context and failures."""
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
from cybergold_candidate.core_permit import CorePermit, CorePermitRpc

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, failure=False, reorg=False, blocked=False, chain='0x7a6a', malformed=False):
        super().__init__()
        self.calls, self.failure, self.reorg, self.blocked, self.chain, self.malformed = [], failure, reorg, blocked, chain, malformed
        self.started, self.cancelled = asyncio.Event(), 0

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'eth_getBlockByNumber':
            result = {'number':'0x65', 'timestamp':'0x6a000001',
                      'hash':'0x'+'b'*64 if self.reorg and params[0] != 'latest' else HASH}
        elif method == 'eth_call':
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            if self.failure:
                return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://secret:password@private.invalid'}}
            row = next(row for row in [REFERENCE['name'],*REFERENCE['rows']] if row['data'] == params[0]['data'])
            result = '0x' if self.malformed else row['result']
        else:
            raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    async def disconnect(self):
        pass


def service(provider):
    settings=SimpleNamespace(RPC_URL='http://synthetic.invalid',RPC_AUTHORIZATION='Bearer fixture-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE['core'],NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=REFERENCE['helpers'])
    return CorePermit(settings,CorePermitRpc(settings,AsyncWeb3(provider)))


class CorePermitTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_fixed_domain_and_lossless_nonce_at_one_hash(self):
        provider=Provider()
        value=await service(provider).get(REFERENCE['rows'][0]['owner'])
        self.assertEqual(value['domain'],{'name':REFERENCE['name']['value'],'version':'1','chainId':31338,'verifyingContract':REFERENCE['core']})
        self.assertEqual(value['spender'],REFERENCE['helpers'])
        self.assertEqual(value['nonce'],REFERENCE['rows'][0]['value'])
        self.assertEqual(value['context']['blockHash'],HASH)
        calls=[params for method,params in provider.calls if method=='eth_call']
        self.assertEqual(len(calls),2)
        self.assertEqual({params[0]['data'] for params in calls},{REFERENCE['name']['data'],REFERENCE['rows'][0]['data']})
        for params in calls:
            self.assertEqual(params[0]['to'],REFERENCE['core'])
            self.assertEqual(params[1],{'blockHash':HASH,'requireCanonical':True})

    async def test_concurrent_owners_and_repeated_reads_never_share_nonce(self):
        observer=service(Provider())
        values=await asyncio.gather(*(observer.get(row['owner']) for row in REFERENCE['rows']))
        self.assertEqual([value['nonce'] for value in values],[row['value'] for row in REFERENCE['rows']])
        await observer.get(REFERENCE['rows'][0]['owner'])
        self.assertEqual(sum(method=='eth_call' for method,_ in observer.rpc.w3.provider.calls),6)

    async def test_reorg_fails_whole_signing_context(self):
        with self.assertRaises(Exception):
            await service(Provider(reorg=True)).get(REFERENCE['rows'][0]['owner'])

    async def test_wrong_chain_reads_no_contract(self):
        provider=Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError,'chain mismatch'):
            await service(provider).get(REFERENCE['rows'][0]['owner'])
        self.assertFalse(any(method=='eth_call' for method,_ in provider.calls))

    async def test_failure_and_invalid_abi_never_supply_zero_or_cached_nonce(self):
        for provider in (Provider(failure=True),Provider(malformed=True)):
            with self.assertRaises(Exception):
                await service(provider).get(REFERENCE['rows'][0]['owner'])

    async def test_cancellation_cancels_both_reads(self):
        provider=Provider(blocked=True)
        task=asyncio.create_task(service(provider).get(REFERENCE['rows'][0]['owner']))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(provider.cancelled,2)

    async def test_http_fixed_operation_validation_and_redacted_outage(self):
        for provider,expected in ((Provider(),200),(Provider(failure=True),503)):
            app=create_app(core_permit=service(provider))
            async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                invalid=await client.get('/api/account/core-permit?owner=private-password')
                self.assertEqual(invalid.status_code,400)
                self.assertNotIn('private-password',invalid.text)
                result=await client.get('/api/account/core-permit',params={'owner':REFERENCE['rows'][0]['owner'],'provider':'http://untrusted.invalid','target':'0x0'})
                self.assertEqual(result.status_code,expected)
                self.assertEqual(result.headers['cache-control'],'no-store')
                self.assertNotIn('password',result.text)
                if expected==503:
                    self.assertNotIn('nonce',result.json())
                    self.assertIn('correlationId',result.json())


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
