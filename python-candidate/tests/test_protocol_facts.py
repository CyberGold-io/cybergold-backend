"""Current browser ABI wire/results, partial reads, canonicality and cancellation."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.protocol_facts import ProtocolFacts, ProtocolFactsRpc
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.shared_reads import SharedReads

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH='0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, failures=(), helpers=True, reorg=False, blocked=False, chain=31338):
        super().__init__(); self.calls=[]; self.failures=failures; self.reorg=reorg; self.blocked=blocked
        self.started=asyncio.Event(); self.cancelled=0
        self.chain, self.hash, self.number = chain, HASH, 101
        self.release = None
        self.results = {}
        self.rows={row['data']: row for row in REFERENCE['rows']}
    async def make_request(self, method, params):
        self.calls.append((method,params))
        if method=='eth_chainId': result=hex(self.chain)
        elif method=='eth_getBlockByNumber':
            result={'number':hex(self.number),'timestamp':'0x6a000001','hash': '0x'+'b'*64 if self.reorg and params[0]!='latest' else self.hash}
        elif method=='eth_call':
            self.started.set()
            if self.blocked:
                try: await asyncio.Event().wait()
                except asyncio.CancelledError: self.cancelled+=1;raise
            if self.release is not None:
                try: await self.release.wait()
                except asyncio.CancelledError: self.cancelled+=1;raise
            row=self.rows[params[0]['data']]
            if row['name'] in self.failures:
                return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://secret:password@private.invalid'}}
            result=self.results.get(row['name'], row['result'])
        else: raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}
    async def disconnect(self): pass


def service(provider, helpers=True, pool_reads=None):
    settings=SimpleNamespace(RPC_URL='http://synthetic.invalid',RPC_AUTHORIZATION='Bearer test-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE['core'],NEXT_PUBLIC_CHAIN_ID=str(provider.chain),
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=REFERENCE['helpers'] if helpers else None)
    return ProtocolFacts(settings,ProtocolFactsRpc(settings,AsyncWeb3(provider),pool_reads=pool_reads),lambda:'2026-10-01T00:00:00.000Z')


class FactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_mainnet_concurrent_and_warm_facts_share_getters_but_recheck_each_header(self):
        bank, provider = SharedReads(), Provider(chain=1)
        self.addAsyncCleanup(bank.close)
        first, second = service(provider, pool_reads=bank), service(provider, pool_reads=bank)
        self.addAsyncCleanup(first.close); self.addAsyncCleanup(second.close)
        results = await asyncio.gather(first.get(), second.get())
        self.assertEqual(results[0], results[1])
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 17)
        self.assertEqual(len(bank.completed), 17)
        self.assertEqual(await first.get(), results[0])
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 17)
        # Only getter observations are retained. Every operation still selects
        # its current head and verifies that exact header after decoding.
        blocks = [params[0] for method, params in provider.calls if method == 'eth_getBlockByNumber']
        self.assertEqual(blocks.count('latest'), 3)
        self.assertEqual(blocks.count('0x65'), 3)

    async def test_changed_hash_at_same_height_reads_fresh_and_warm_canonical_disproof_still_fails(self):
        provider = Provider(chain=1)
        facts = service(provider)
        self.addAsyncCleanup(facts.close)
        original = await facts.get()
        provider.reorg = True
        with self.assertRaises(SnapshotChanged):
            await facts.get()
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 17)
        provider.reorg = False
        provider.hash = '0x'+'c'*64
        provider.results['cygldRefGramsFp18'] = '0x'+(77).to_bytes(32).hex()
        changed = await facts.get()
        self.assertEqual(changed['context']['blockNumber'], original['context']['blockNumber'])
        self.assertEqual(changed['context']['blockHash'], provider.hash)
        self.assertEqual(changed['reference']['value'], '77')
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 34)

    async def test_raw_getter_identity_separates_chain_hash_address_and_calldata(self):
        bank, provider = SharedReads(), Provider(chain=1)
        self.addAsyncCleanup(bank.close)
        main = service(provider, pool_reads=bank)
        self.addAsyncCleanup(main.close)
        rpc, block = main.rpc, {'hash': HASH, 'number': 101}
        address = REFERENCE['core']
        await rpc.read('core', address, 'paused', block)
        await rpc.read('core', address.lower(), 'paused', {**block, 'hash': HASH.upper()})
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 1)
        await rpc.read('core', address, 'totalSupply', block)
        await rpc.read('core', REFERENCE['assets'][0], 'paused', block)
        await rpc.read('core', address, 'paused', {**block, 'hash': '0x'+'b'*64})
        sandbox_provider = Provider()
        sandbox = service(sandbox_provider, pool_reads=bank)
        self.addAsyncCleanup(sandbox.close)
        await sandbox.rpc.read('core', address, 'paused', block)
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 4)
        self.assertEqual(sum(method == 'eth_call' for method, _ in sandbox_provider.calls), 1)
        self.assertEqual(len(bank.completed), 4)

    async def test_partial_rpc_failures_retry_only_the_failed_getter(self):
        provider = Provider(chain=1, failures=('totalSupply',))
        facts = service(provider)
        self.addAsyncCleanup(facts.close)
        partial = await facts.get()
        self.assertEqual(partial['issuanceCapacity']['totalSupply']['status'], 'failure')
        self.assertEqual(partial['basket']['assets']['status'], 'success')
        self.assertEqual(len(facts.rpc.pool_reads.completed), 16)
        provider.failures = ()
        recovered = await facts.get()
        self.assertEqual(recovered['issuanceCapacity']['totalSupply']['status'], 'success')
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 18)
        self.assertEqual(len(facts.rpc.pool_reads.completed), 17)

    async def test_facts_and_typed_core_reader_share_the_same_raw_getter(self):
        from cybergold_candidate.uniswap_state import UniswapRpc
        provider, bank = Provider(chain=1), SharedReads()
        self.addAsyncCleanup(bank.close)
        facts = service(provider, pool_reads=bank)
        self.addAsyncCleanup(facts.close)
        typed_provider = Provider(chain=1)
        typed = UniswapRpc(facts.settings, AsyncWeb3(typed_provider), pool_reads=bank)
        self.addAsyncCleanup(typed.close)
        block = {'number': 101, 'hash': HASH}
        self.assertEqual(await typed.read_function(REFERENCE['core'], 'paused()', [], [], ['bool'], block), (False,))
        result = await facts.get()
        self.assertEqual(result['pause']['value'], False)
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 16)
        self.assertEqual(sum(method == 'eth_call' for method, _ in typed_provider.calls), 1)
        self.assertEqual(await typed.read_function(REFERENCE['core'], 'totalSupply()', [], [], ['uint256'], block),
                         (200 * 10**18,))
        self.assertEqual(sum(method == 'eth_call' for method, _ in typed_provider.calls), 1)

    async def test_malformed_typed_reply_evicts_only_its_exact_key_and_recovers(self):
        provider = Provider(chain=1)
        provider.results['cygldRefGramsFp18'] = '0x'
        facts = service(provider)
        self.addAsyncCleanup(facts.close)
        partial = await facts.get()
        self.assertEqual(partial['reference']['status'], 'failure')
        self.assertEqual(partial['fees']['helpersPpm']['status'], 'success')
        self.assertEqual(len(facts.rpc.pool_reads.completed), 16)
        provider.results.clear()
        recovered = await facts.get()
        self.assertEqual(recovered['reference']['value'], str(2**180))
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 18)
        self.assertEqual(len(facts.rpc.pool_reads.completed), 17)

    async def test_sandbox_overlap_shares_but_same_hash_override_is_not_retained(self):
        provider, bank = Provider(), SharedReads()
        self.addAsyncCleanup(bank.close)
        first, second = service(provider, pool_reads=bank), service(provider, pool_reads=bank)
        self.addAsyncCleanup(first.close); self.addAsyncCleanup(second.close)
        provider.release = asyncio.Event()
        a, b = asyncio.create_task(first.get()), asyncio.create_task(second.get())
        async def joined():
            while len(bank.pending) != 11 or any(entry.users != 2 for entry in bank.pending.values()):
                await asyncio.sleep(0)
        await asyncio.wait_for(joined(), 1)
        provider.release.set()
        before, other = await asyncio.gather(a, b)
        self.assertEqual(before, other)
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 17)
        self.assertFalse(bank.completed)
        provider.results['cygldRefGramsFp18'] = '0x'+(88).to_bytes(32).hex()
        after = await first.get()
        self.assertEqual(after['context'], before['context'])
        self.assertEqual(after['reference']['value'], '88')
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 34)
        self.assertFalse(bank.completed)

    async def test_one_cancelled_facts_subscriber_survives_and_last_cancel_releases_reads(self):
        provider, bank = Provider(chain=1), SharedReads()
        self.addAsyncCleanup(bank.close)
        first, second = service(provider, pool_reads=bank), service(provider, pool_reads=bank)
        self.addAsyncCleanup(first.close); self.addAsyncCleanup(second.close)
        provider.release = asyncio.Event()
        a, b = asyncio.create_task(first.get()), asyncio.create_task(second.get())
        async def joined():
            while len(bank.pending) != 11 or any(entry.users != 2 for entry in bank.pending.values()):
                await asyncio.sleep(0)
        await asyncio.wait_for(joined(), 1)
        a.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await a
        self.assertEqual(provider.cancelled, 0)
        provider.release.set()
        self.assertEqual((await b)['basket']['assets']['status'], 'success')
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 17)
        provider.release.clear(); provider.started.clear(); provider.hash = '0x'+'d'*64
        last = asyncio.create_task(first.get())
        async def sent():
            while len(bank.pending) != 11 or sum(method == 'eth_call' for method, _ in provider.calls) < 28:
                await asyncio.sleep(0)
        await asyncio.wait_for(sent(), 1)
        last.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await last
        self.assertEqual(provider.cancelled, 11)
        self.assertFalse(bank.pending)
        self.assertEqual(len(bank.completed), 17)

    async def test_borrower_close_preserves_shared_getters_for_another_service(self):
        provider, bank = Provider(chain=1), SharedReads()
        self.addAsyncCleanup(bank.close)
        settings = service(provider).settings
        first = ProtocolFacts(settings, pool_reads=bank, now=lambda:'2026-10-01T00:00:00.000Z')
        self.assertIsNone(first.rpc)
        with patch('cybergold_candidate.protocol_facts.ProtocolFactsRpc',
                   side_effect=lambda settings, **kwargs: ProtocolFactsRpc(settings, AsyncWeb3(provider), **kwargs)):
            result = await first.get()
        self.assertFalse(first.rpc.owns_pool_reads)
        await first.close()
        self.assertEqual(len(bank.completed), 17)
        other_provider = Provider(chain=1)
        other = service(other_provider, pool_reads=bank)
        self.addAsyncCleanup(other.close)
        self.assertEqual(await other.get(), result)
        self.assertFalse(any(method == 'eth_call' for method, _ in other_provider.calls))
        self.assertEqual(len(bank.completed), 17)

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
