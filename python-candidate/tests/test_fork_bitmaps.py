"""Advisory fills must preserve quote independence and search cancellation."""
import asyncio
from types import SimpleNamespace
import unittest

import httpx

from cybergold_candidate.fork_bitmaps import ForkBitmapPrefetch
from cybergold_candidate.search_observations import search_observation_scope
from cybergold_candidate.uniswap_v3 import bitmap_slots, canonical_pool_address
from cybergold_candidate.uniswap_v4 import bitmap_slots as v4_slots

ANCHOR = '0x'+'ab'*32
A = '0x45804880de22913dafe09f4980848ece6ecbaf78'
B = '0xdac17f958d2ee523a2206206994597c13d831ec7'
FACTORY = '0x1f98431c8ad98523631ae4a59f267346ea31f984'
MANAGER = '0x000000000004444c5dc75cb358380d2e3de08a90'
POOL = {'protocol':'v3','token0':{'address':A},'token1':{'address':B},'feePips':500}


class PrefetchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.posts=[]; self.native=[]; self.anchors=0
        self.started=asyncio.Event(); self.release=asyncio.Event(); self.release.set()
        async def request(request):
            import json
            self.posts.append(json.loads(request.content)); self.started.set()
            await self.release.wait()
            return httpx.Response(200,json={'wordsCached':len(self.posts[-1]['wordPositions'])})
        async def native(method,params):
            self.native.append((method,params))
            await asyncio.sleep(0)
            return {'jsonrpc':'2.0','id':1,'result':'0x'+'00'*32}
        async def batch(calls):
            return await asyncio.gather(*(native(method,params) for method,params in calls))
        async def anchor():
            self.anchors+=1
            return ANCHOR
        self.client=httpx.AsyncClient(transport=httpx.MockTransport(request))
        self.prefetch=ForkBitmapPrefetch('http://broker','Bearer consumer',anchor,client=self.client)
        self.rpc=SimpleNamespace(factory=FACTORY,pool_manager=MANAGER,semaphore=asyncio.Semaphore(8),
            w3=SimpleNamespace(provider=SimpleNamespace(make_batch_request=batch)))

    async def asyncTearDown(self):
        await self.prefetch.close(); await self.client.aclose()

    async def settle(self,scope):
        await asyncio.gather(*scope.bitmap_prefetches.values())

    async def test_fill_pins_anchor_and_reads_local_state_without_writes(self):
        async with search_observation_scope() as scope:
            self.prefetch.schedule(POOL,[-77,-347,-77],self.rpc)
            self.prefetch.schedule(POOL,[-77,-347],self.rpc)
            self.prefetch.schedule(POOL,[-78],self.rpc)
            await self.settle(scope)
            self.assertEqual(self.anchors,1)
            self.assertEqual(len(self.posts),2)
            self.assertTrue(all(p['blockHash']==ANCHOR for p in self.posts))
            self.assertEqual(self.posts[0]['pool']['address'],'0x7cb85f75e61226060453a997a7733f76707df337')
            self.assertEqual({(m,p[1],p[2]) for m,p in self.native},
                {('eth_getStorageAt','0x'+slot.hex(),'latest') for slot in bitmap_slots([-77,-347,-78])})
            self.assertEqual(canonical_pool_address(FACTORY,B,A,500),self.posts[0]['pool']['address'])

    async def test_pending_fill_is_advisory_and_cancelled_with_search(self):
        self.release.clear()
        async with search_observation_scope() as scope:
            self.prefetch.schedule(POOL,[-77],self.rpc)
            await self.started.wait()
            # The caller continues while HTTP is still pending.
            self.assertFalse(next(iter(scope.bitmap_prefetches.values())).done())
            self.assertFalse(self.native)
        self.assertFalse(self.prefetch.reads.pending)
        self.assertFalse(self.prefetch.reads.groups)

    async def test_bad_supplier_and_partial_fill_leave_native_reads_alone(self):
        for status,body in [(503,{}),(200,{'wordsCached':0})]:
            async def failed(_request): return httpx.Response(status,json=body)
            await self.client.aclose()
            self.client=httpx.AsyncClient(transport=httpx.MockTransport(failed))
            self.prefetch.client=self.client
            async with search_observation_scope() as scope:
                self.prefetch.schedule(POOL,[-77],self.rpc)
                await self.settle(scope)
                self.assertTrue(all(t.exception() is None for t in scope.bitmap_prefetches.values()))
            self.assertFalse(self.native)

    async def test_two_searches_share_fill_and_one_can_leave(self):
        self.release.clear(); entered=asyncio.Event(); leave=asyncio.Event()
        async def subscriber():
            async with search_observation_scope():
                self.prefetch.schedule(POOL,[-77],self.rpc)
                entered.set(); await leave.wait()
        first=asyncio.create_task(subscriber())
        await self.started.wait(); entered.clear()
        second=asyncio.create_task(subscriber()); await entered.wait()
        await asyncio.sleep(0); await asyncio.sleep(0)
        first.cancel(); await asyncio.gather(first,return_exceptions=True)
        self.assertEqual(len(self.posts),1)
        self.release.set()
        while not self.native: await asyncio.sleep(0)
        leave.set(); await second
        self.assertEqual(len(self.native),1)

    async def test_compiled_topology_covers_actual_pools_once(self):
        route={'inputCurrency':A,'routes':[{'steps':[
            {'kind':1,'currencyOut':B,'fee':500,'tickSpacing':0},
            {'kind':2,'currencyOut':A,'fee':3000,'tickSpacing':60}]}]}
        async with search_observation_scope() as scope:
            self.prefetch.schedule_body({'acquisitions':[{'route':route}],'continuations':[route]},self.rpc)
            self.prefetch.schedule_body(route,self.rpc)
            await self.settle(scope)
            self.assertEqual(len(scope.bitmap_full_pools),2)
            self.assertEqual({p['pool']['protocol'] for p in self.posts},{'v3','v4'})
            v3=[w for p in self.posts if p['pool']['protocol']=='v3' for w in p['wordPositions']]
            self.assertEqual((min(v3),max(v3),len(set(v3))),(-347,346,694))
            v4=next(p for p in self.posts if p['pool']['protocol']=='v4')
            self.assertEqual(v4['pool']['poolManager'],MANAGER)
            expected={'0x'+s.hex() for s in v4_slots(v4['pool']['poolId'],v4['wordPositions'])}
            self.assertEqual({p[1] for _,p in self.native if p[0]==MANAGER},expected)


if __name__=='__main__': unittest.main()
