"""Current browser ABI wire/results, partial reads, canonicality and cancellation."""
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
from cybergold_candidate.protocol_facts import ProtocolFacts, ProtocolFactsRpc

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH='0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, failures=(), helpers=True, reorg=False, blocked=False):
        super().__init__(); self.calls=[]; self.failures=failures; self.reorg=reorg; self.blocked=blocked
        self.started=asyncio.Event(); self.cancelled=0
        self.rows={row['data']: row for row in REFERENCE['rows']}
    async def make_request(self, method, params):
        self.calls.append((method,params))
        if method=='eth_chainId': result='0x7a6a'
        elif method=='eth_getBlockByNumber':
            result={'number':'0x65','timestamp':'0x6a000001','hash': '0x'+'b'*64 if self.reorg and params[0]!='latest' else HASH}
        elif method=='eth_call':
            self.started.set()
            if self.blocked:
                try: await asyncio.Event().wait()
                except asyncio.CancelledError: self.cancelled+=1;raise
            row=self.rows[params[0]['data']]
            if row['name'] in self.failures:
                return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://secret:password@private.invalid'}}
            result=row['result']
        else: raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}
    async def disconnect(self): pass


def service(provider, helpers=True):
    settings=SimpleNamespace(RPC_URL='http://synthetic.invalid',RPC_AUTHORIZATION='Bearer test-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE['core'],NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=REFERENCE['helpers'] if helpers else None)
    return ProtocolFacts(settings,ProtocolFactsRpc(settings,AsyncWeb3(provider)),lambda:'2026-10-01T00:00:00.000Z')


class FactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_reset_retires_only_the_old_facts_observation(self):
        from cybergold_candidate.quote_history import QuoteHistory
        provider = Provider()
        warm = service(provider)
        history = QuoteHistory(warm.settings)
        await history.observe_generation('old')
        warm.history = history
        warm.on_observation = history.facts_observed
        original = warm.rpc.assert_canonical
        async def reset_during_read(block):
            await original(block)
            await history.observe_generation('new')
        warm.rpc.assert_canonical = reset_during_read
        result = await warm.get()
        self.assertEqual(result['context']['blockHash'], HASH)
        self.assertIsNone(result['basketModel'])
        self.assertFalse(history.facts)
        warm.rpc.assert_canonical = original
        fresh = await warm.get()
        self.assertEqual(fresh, result)
        self.assertIn(HASH, history.facts)
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 34)

    async def test_cold_facts_expose_current_capacity_without_model_acquisition(self):
        from cybergold_candidate.quote_history import QuoteHistory
        provider = Provider()
        cold = service(provider)
        history = QuoteHistory(cold.settings)
        cold.history = history
        result = await cold.get()
        self.assertIsNone(result['basketModel'])
        self.assertFalse(history.states)
        self.assertFalse(history.tasks)
        self.assertEqual(result['issuanceCapacity'], {
            'totalSupply': {'status': 'success', 'value': str(200 * 10**18)},
            'maxTotalSupply': {'status': 'success', 'value': str(250 * 10**18)},
            'effectiveCygldSupplyCap': {'status': 'success', 'value': str(240 * 10**18)}})
        self.assertTrue(all(params[1] == {'blockHash': HASH, 'requireCanonical': True}
                            for method, params in provider.calls if method == 'eth_call'))

    async def test_one_capacity_failure_preserves_other_capacity_and_basket_facts(self):
        result = await service(Provider(failures=('effectiveCygldSupplyCap',))).get()
        self.assertEqual(result['issuanceCapacity']['effectiveCygldSupplyCap'],
                         {'status': 'failure', 'error': 'contract-read-failed'})
        self.assertEqual(result['issuanceCapacity']['totalSupply']['value'], str(200 * 10**18))
        self.assertEqual(result['issuanceCapacity']['maxTotalSupply']['value'], str(250 * 10**18))
        self.assertEqual(result['basket']['assets']['status'], 'success')
        self.assertEqual(result['fees']['issuancePpm']['status'], 'success')

    async def test_existing_model_is_delivered_without_new_state_acquisition(self):
        from cybergold_candidate.quote_history import QuoteHistory
        first, second = Provider(), Provider()
        plain = await service(first).get()
        warm = service(second)
        history = QuoteHistory(warm.settings)
        history.states['prior'] = {'context':{'chainId':31338,'blockNumber':'99','blockHash':'prior'},
                                   'state':{'assets':['public-asset']},'_acquiredAt':0}
        warm.history = history
        result = await warm.get()
        self.assertEqual(result.pop('basketModel')['context']['blockHash'], 'prior')
        self.assertEqual(result, plain)
        self.assertEqual(first.calls, second.calls)
        self.assertFalse(history.tasks)

    async def test_browser_calldata_values_and_hash_pinning(self):
        provider=Provider(); result=await service(provider).get()
        self.assertEqual(result['context'],{'chainId':31338,'blockNumber':'101','blockHash':HASH,'blockTimestamp':str(0x6a000001),'observedAt':'2026-10-01T00:00:00.000Z'})
        self.assertEqual(result['reference']['value'],str(2**180))
        self.assertEqual(result['basket']['goldRefGramsFp18']['value'][0],str(2**200))
        self.assertEqual(result['fees']['issuancePpm']['value'],'0')
        self.assertIs(result['pause']['value'],False)
        self.assertEqual([row['name']['value'] for row in result['basket']['metadata']],['Gold €']*2)
        for method,params in provider.calls:
            if method=='eth_call':
                self.assertIn(params[0]['to'],[REFERENCE['core'],REFERENCE['helpers'],*REFERENCE['assets']])
                self.assertIn(params[0]['data'],provider.rows)
                self.assertEqual(params[1],{'blockHash':HASH,'requireCanonical':True})
        self.assertEqual(sum(method=='eth_call' for method,_ in provider.calls),17)
    async def test_partial_fields_and_metadata_are_not_invented(self):
        result=await service(Provider(failures=('basketTargetsPpm','name'))).get()
        self.assertEqual(result['basket']['targetsPpm'],{'status':'failure','error':'contract-read-failed'})
        self.assertEqual(result['basket']['metadata'][0]['name']['status'],'failure')
        self.assertEqual(result['fees']['helpersPpm']['value'],'15')
        self.assertNotIn('password',json.dumps(result))
    async def test_optional_helpers_do_not_block_core(self):
        provider=Provider();result=await service(provider,False).get()
        self.assertIsNone(result['helpers'])
        self.assertEqual(result['fees']['helpersPpm'],{'status':'failure','error':'not-configured'})
        self.assertFalse(any(method=='eth_call' and params[0]['to']==REFERENCE['helpers'] for method,params in provider.calls))
    async def test_reorg_cannot_publish_successful_mixed_facts(self):
        with self.assertRaises(Exception):await service(Provider(reorg=True)).get()
    async def test_cancelled_caller_cancels_private_reads(self):
        provider=Provider(blocked=True);task=asyncio.create_task(service(provider).get())
        await provider.started.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(provider.cancelled,11)
    async def test_fixed_http_operation_no_caller_target_and_no_store(self):
        provider=Provider();app=create_app(protocol_facts=service(provider))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.get('/api/protocol/facts?provider=http://untrusted.invalid&address=0x0&method=eth_sendTransaction')
            self.assertEqual(response.status_code,200);self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(response.json()['core'],REFERENCE['core'])
    async def test_fatal_http_error_redacted_and_correlated(self):
        app=create_app(protocol_facts=service(Provider(reorg=True)))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.get('/api/protocol/facts')
            self.assertEqual(response.status_code,503);self.assertIn('correlationId',response.json())
            self.assertNotIn('password',response.text)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
