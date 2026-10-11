"""Compare retained Safe wire bytes and preserve EOA/partial/reorg/isolation facts."""
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
from cybergold_candidate.governance_safe_principal import GovernanceSafePrincipal, SafePrincipalRpc

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, failure=None, reorg=False, blocked=False):
        super().__init__()
        self.calls, self.failure, self.reorg, self.blocked = [], failure, reorg, blocked
        self.started, self.cancelled = asyncio.Event(), 0

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = '0x7a6a'
        elif method == 'eth_getBlockByNumber':
            result = {'number':'0x65', 'timestamp':'0x6a000001',
                      'hash':'0x'+'b'*64 if self.reorg and params[0] != 'latest' else HASH}
        elif method in ('eth_call','eth_getCode'):
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            address = params[0]['to'] if method == 'eth_call' else params[0]
            if self.failure == method or (method == 'eth_call' and self.failure == params[0]['data']):
                return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://secret:password@private.invalid'}}
            if address.lower() == REFERENCE['eoa']:
                result = '0x'
            else:
                row = next(row for row in REFERENCE['rows'] if row['address'].lower() == address.lower())
                result = row['code'] if method == 'eth_getCode' else next(call['result'] for call in row['calls'] if call['data'] == params[0]['data'])
        else:
            raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE['core'], NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=None)
    return GovernanceSafePrincipal(settings, SafePrincipalRpc(settings, AsyncWeb3(provider)))


class SafePrincipalTests(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_safe_bytes_lossless_threshold_and_concurrent_principals(self):
        provider = Provider(); reader = service(provider)
        values = await asyncio.gather(*(reader.get(row['address']) for row in REFERENCE['rows']))
        for value,row in zip(values,REFERENCE['rows'],strict=True):
            self.assertEqual(value['address'].lower(),row['address'])
            self.assertEqual(value['owners'],{'status':'success','value':row['owners']})
            self.assertEqual(value['threshold'],{'status':'success','value':row['threshold']})
            self.assertEqual(value['code'],{'status':'success','value':row['code']})
        reads = [(method,params) for method,params in provider.calls if method in ('eth_call','eth_getCode')]
        self.assertEqual(len(reads),6)
        self.assertTrue(all(params[1] == {'blockHash':HASH,'requireCanonical':True} for _,params in reads))

    async def test_partial_probe_does_not_fabricate_a_threshold_or_hide_bytecode(self):
        value = await service(Provider(failure='0xe75235b8')).get(REFERENCE['core'])
        self.assertEqual(value['threshold'],{'status':'failure','error':'contract-read-failed'})
        self.assertEqual(value['code']['value'],'0x6001')
        self.assertEqual(value['owners']['value'],[REFERENCE['rows'][1]['address']])
        self.assertNotIn('password',json.dumps(value))

    async def test_failed_bytecode_does_not_classify_a_safe_as_an_eoa(self):
        value = await service(Provider(failure='eth_getCode')).get(REFERENCE['core'])
        self.assertEqual(value['code'],{'status':'failure','error':'contract-read-failed'})
        self.assertEqual(value['threshold']['value'],'1')

    async def test_known_empty_code_and_incompatible_safe_reads_remain_distinct(self):
        value = await service(Provider()).get(REFERENCE['eoa'])
        self.assertEqual(value['code'],{'status':'success','value':'0x'})
        self.assertEqual(value['owners']['status'],'failure')
        self.assertEqual(value['threshold']['status'],'failure')

    async def test_reorg_fails_whole_observation(self):
        with self.assertRaises(Exception):
            await service(Provider(reorg=True)).get(REFERENCE['core'])

    async def test_disconnect_cancellation_stops_all_three_reads(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get(REFERENCE['core']))
        await provider.started.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(provider.cancelled,3)

    async def test_fixed_http_address_validation_partial_and_redacted_outage(self):
        for provider,status in ((Provider(),200),(Provider(reorg=True),503)):
            app = create_app(governance_safe_principal=service(provider))
            async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.get('/api/governance/safe-principal',params={'address':REFERENCE['core'],'provider':'http://untrusted.invalid'})
                invalid=await client.get('/api/governance/safe-principal',params={'address':'not-an-address'})
            self.assertEqual(response.status_code,status)
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(invalid.status_code,400)
            self.assertNotIn('password',response.text)
            if status==503:self.assertIn('correlationId',response.json())


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
