"""Public protocol snapshots/catalog share canonical quote observations."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import httpx
from web3 import Web3

from cybergold_candidate.app import create_app
from cybergold_candidate.pool_producer import PoolProducer, PoolIdentifier, identifier_from_pool
from cybergold_candidate.authoritative_pool_cache import AuthoritativePoolCache
from cybergold_candidate.uniswap_routes import v4_pool_id
from cybergold_candidate.uniswap_state import PoolRegistry, UniswapRpc, EVENTS, DISCOVERY, ZERO
from cybergold_candidate.recovery_rpc import RecoveryApiError

A, B, C = ('0x'+str(index).rjust(40,'0') for index in (1,2,3))
BLOCK = {'number':123,'hash':'0x'+'ab'*32}
NOW = '2026-10-11T00:00:00.000Z'
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A,
                          RPC_URL='http://unused.invalid', RPC_AUTHORIZATION=None)


class Rpc(UniswapRpc):
    """Real shared read/ABI codec, synthetic canonical headers/contract returns."""
    def __init__(self):
        super().__init__(SETTINGS)
        self.calls = []
        self.current = deepcopy(BLOCK)
        self.reject_canonical = False
        self.pairs = {('v2',A,B,3000):C, ('v3',A,B,500):C}
        self.v4_states = {}
        self.w3.provider.make_request = AsyncMock(side_effect=self.request)

    async def block(self, _hash):
        return deepcopy(self.current)

    async def assert_canonical(self, block):
        if self.reject_canonical or block != self.current:
            raise RecoveryApiError('Synthetic canonical history changed',retry=1)

    async def logs(self, query):
        return []

    async def request(self, method, params):
        self.calls.append((method,deepcopy(params)))
        self_assert = params[1] == {'blockHash':self.current['hash'],'requireCanonical':True}
        assert self_assert
        data = bytes.fromhex(params[0]['data'][2:])
        descriptions = {
            'getPair(address,address)': (['address','address'],['address']),
            'getPool(address,address,uint24)': (['address','address','uint24'],['address']),
            'decimals()': ([],['uint8']), 'tickSpacing()': ([],['int24']),
            'slot0()': ([],['uint160','int24','uint16','uint16','uint16','uint8','bool']),
            'liquidity()': ([],['uint128']), 'balanceOf(address)': (['address'],['uint256']),
            'getReserves()': ([],['uint112','uint112','uint32']),
            'getSlot0(bytes32)': (['bytes32'],['uint160','int24','uint24','uint24']),
            'getLiquidity(bytes32)': (['bytes32'],['uint128']),
        }
        for signature,(inputs,outputs) in descriptions.items():
            if data[:4] != Web3.keccak(text=signature)[:4]:
                continue
            args = self.w3.codec.decode(inputs,data[4:])
            if signature.startswith('getPair'):
                values = [self.pairs.get(('v2',*args,3000),ZERO)]
            elif signature.startswith('getPool'):
                values = [self.pairs.get(('v3',*args),ZERO)]
            elif signature == 'decimals()': values = [18]
            elif signature == 'tickSpacing()': values = [10]
            elif signature == 'slot0()': values = [2**100,-12,1,2,3,0x65,True]
            elif signature == 'liquidity()': values = [2**100]
            elif signature == 'balanceOf(address)': values = [2**200]
            elif signature == 'getReserves()': values = [100_000,200_000,0]
            else:
                state = self.v4_states['0x'+args[0].hex()]
                values = (state['price'],state['tick'],102425,100) if signature == 'getSlot0(bytes32)' else [state['liquidity']]
            return {'result':Web3.to_hex(self.w3.codec.encode(outputs,values))}
        raise AssertionError(data.hex())


class Pools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rpc = Rpc()
        self.registry = PoolRegistry(SETTINGS,self.rpc)
        self.registry.inventory.clear()
        self.producer = PoolProducer(SETTINGS,registry=self.registry,now=lambda:NOW)
        self.addAsyncCleanup(self.registry.close)

    def v4(self,spacing=1,hooks=ZERO):
        key = (A,B,100,spacing,hooks)
        pool = {'id':v4_pool_id(key),'protocol':'v4','poolManager':self.rpc.pool_manager,
                'token0':self.registry.token(A,18),'token1':self.registry.token(B,18),
                'feePips':100,'tickSpacing':spacing,'hooks':hooks}
        self.rpc.v4_states[pool['id']] = {'price':441947936735403526595706575860+spacing,
                                        'tick':34378,'liquidity':879772594612909362900+spacing}
        return pool

    async def test_rejected_positive_and_negative_acquisition_publishes_nothing(self):
        for protocol in ('v2','v3'):
            for exists in (True,False):
                with self.subTest(protocol=protocol,exists=exists):
                    fee = 500 if protocol == 'v3' else 3000
                    self.registry.inventory.clear()
                    self.registry.observed.clear()
                    self.registry.metadata.clear()
                    self.registry.lookups.clear()
                    self.registry.lookup_anchors.clear()
                    self.rpc.reads.completed.clear()
                    self.rpc.pairs[(protocol,A,B,fee)] = C if exists else ZERO
                    self.rpc.reject_canonical = True
                    with self.assertRaises(RecoveryApiError):
                        await self.producer.get({'protocol':protocol,'tokenA':A,'tokenB':B,'fee':fee})
                    self.assertEqual(self.registry.inventory,{})
                    self.assertEqual(self.registry.lookups,{})
                    self.assertEqual(self.registry.observed,{})
                    self.assertEqual(self.registry.metadata,{})
                    self.assertEqual((await self.producer.catalog(A,B))['entries'],[])
                    self.rpc.reject_canonical = False
                    self.rpc.current = {'number':123,'hash':'0x'+'cd'*32}
                    # The replacement branch has a pool even if rejected old
                    # history reported absence; the factory must be read anew.
                    self.rpc.pairs[(protocol,A,B,fee)] = C
                    result = await self.producer.get({'protocol':protocol,'tokenA':A,'tokenB':B,'fee':fee})
                    self.assertTrue(result['exists'])
                    self.assertEqual(self.registry.inventory[C]['acquisition']['blockHash'],self.rpc.current['hash'])
                    self.rpc.current = deepcopy(BLOCK)

    async def test_persisted_acquisition_and_negative_anchor_recover_on_replacement_history(self):
        from test_uniswap_market import Store
        store = Store()
        self.registry.store = store
        positive = {'protocol':'v3','tokenA':A,'tokenB':B,'fee':500}
        negative = {'protocol':'v3','tokenA':A,'tokenB':B,'fee':3000}
        await self.producer.get(positive)
        await self.producer.get(negative)
        await asyncio.gather(*tuple(self.registry.background))
        anchor = deepcopy(self.registry.inventory[C]['acquisition'])
        self.assertEqual(anchor,{'blockNumber':'123','blockHash':BLOCK['hash']})
        self.assertIsNone(self.registry.lookups[('v3',(A,B),3000)])
        # Stored identities and negative process hints share the same orphan
        # recovery semantics; the latter are intentionally not persisted.
        self.rpc.current = {'number':123,'hash':'0x'+'cd'*32}
        self.rpc.assert_canonical = AsyncMock(wraps=self.rpc.assert_canonical)
        self.assertTrue(await self.registry.recover_catalog())
        self.assertEqual(self.rpc.assert_canonical.await_count,1)  # All old anchors are identical.
        self.assertNotIn(C,self.registry.inventory)
        self.assertNotIn(C,self.registry.observed)
        self.assertEqual(self.registry.lookups,{})
        self.assertNotIn(C,store.data['inventory'])
        restarted = PoolRegistry(SETTINGS,self.rpc,store)
        restarted.inventory.clear()
        self.addAsyncCleanup(restarted.close)
        await restarted.ensure_loaded(wait=True)
        self.assertNotIn(C,restarted.inventory)
        self.rpc.pairs[('v3',A,B,3000)] = C
        producer = PoolProducer(SETTINGS,registry=restarted,now=lambda:NOW)
        self.assertTrue((await producer.get(negative))['exists'])

    async def test_private_and_public_snapshot_share_one_event_advancement(self):
        await self.producer.get({'protocol':'v3','tokenA':A,'tokenB':B,'fee':500})
        pool = deepcopy(self.registry.inventory[C])
        self.rpc.current = {'number':124,'hash':'0x'+'cd'*32}
        async def canonical(block):
            self.assertIn(block,(BLOCK,self.rpc.current))
        started, release = asyncio.Event(), asyncio.Event()
        async def logs(_query):
            started.set()
            await release.wait()
            return []
        self.rpc.assert_canonical = canonical
        self.rpc.logs = AsyncMock(side_effect=logs)
        private = asyncio.create_task(self.registry.snapshot(pool,self.rpc.current,publish=False))
        public = asyncio.create_task(self.registry.snapshot(pool,self.rpc.current))
        await started.wait()
        key = ('v3',C,self.rpc.current['hash'])
        while self.registry.pending.pending[key].users != 2:
            await asyncio.sleep(0)
        release.set()
        left,right = await asyncio.gather(private,public)
        self.assertEqual(left,right)
        self.assertEqual(self.rpc.logs.await_count,1)
        self.assertEqual(self.registry.observed[C]['context']['blockHash'],self.rpc.current['hash'])

    async def test_explicit_negative_snapshot_reuses_only_its_observed_hash(self):
        request = {'protocol':'v3','tokenA':A,'tokenB':B,'fee':3000}
        self.assertFalse((await self.producer.get(request))['exists'])
        before = len(self.rpc.calls)
        original = deepcopy(self.registry.lookup_anchors[('v3',(A,B),3000)])
        self.assertFalse((await self.producer.get(request))['exists'])
        self.assertEqual(len(self.rpc.calls),before)
        self.assertEqual(self.registry.lookup_anchors[('v3',(A,B),3000)],original)
        self.rpc.current = {'number':124,'hash':'0x'+'cd'*32}
        self.rpc.pairs[('v3',A,B,3000)] = C
        self.assertTrue((await self.producer.get(request))['exists'])
        self.assertGreater(len(self.rpc.calls),before)
        self.assertEqual(self.registry.lookup_anchors[('v3',(A,B),3000)]['blockHash'],self.rpc.current['hash'])

    async def test_v3_default_shape_and_explicit_state_reuse(self):
        identifier = {'tokenA':B,'tokenB':A,'fee':500}
        legacy = await self.producer.get(identifier)
        self.assertEqual(set(legacy),{'context','dex','token0','token1','fee','exists','poolAddress',
            'activeLiquidityRaw','sqrtPriceX96Raw','tick','token0BalanceRaw','token1BalanceRaw'})
        self.assertEqual(legacy['activeLiquidityRaw'],str(2**100))
        before = len(self.rpc.calls)
        explicit = await self.producer.get({**identifier,'protocol':'v3'})
        self.assertEqual(len(self.rpc.calls),before)
        self.assertEqual(explicit['protocolFee'],0x65)
        self.assertEqual(explicit['lpFee'],500)
        self.assertEqual(explicit['marginalPrice'],{'numerator':str(2**200),'denominator':str(2**192)})
        cached = await self.registry.snapshot(explicit['pool'],BLOCK)
        self.assertEqual(cached['liquidity'],legacy['activeLiquidityRaw'])
        self.assertEqual(len(self.rpc.calls),before)
        self.registry.apply_event(cached,{'topics':[EVENTS['SetFeeProtocol']],
            'data':Web3.to_hex(self.rpc.w3.codec.encode(['uint8']*4,[5,6,4,7]))})
        self.assertEqual(cached['protocolFee'],0x74)

    async def test_optional_display_metadata_outage_does_not_hold_pool_state(self):
        async def metadata(_address,_block):
            raise ValueError('Optional decimals unavailable')
        self.registry.token_metadata = metadata
        result = await self.producer.get({'protocol':'v3','tokenA':A,'tokenB':B,'fee':500})
        self.assertTrue(result['exists'])
        self.assertEqual(result['activeLiquidityRaw'],str(2**100))
        self.assertFalse(result['pool']['token0']['decimalsKnown'])

    async def test_v4_full_key_collision_coverage_wide_state_and_no_singleton_balances(self):
        rows = []
        for pool in (self.v4(),self.v4(60),self.v4(1,C)):
            self.registry.inventory[pool['id']] = pool
            result = await self.producer.get(identifier_from_pool(pool))
            rows.append(result)
            self.assertEqual(result['poolKey'],dict(currency0=A,currency1=B,fee=100,
                tickSpacing=pool['tickSpacing'],hooks=pool['hooks']))
            self.assertEqual(result['poolId'],pool['id'])
            self.assertEqual(result['protocolFee'],102425)
            self.assertEqual(result['activeLiquidityRaw'],str(self.rpc.v4_states[pool['id']]['liquidity']))
            self.assertNotIn('token0BalanceRaw',result)
            self.assertNotIn('token1BalanceRaw',result)
            self.assertNotIn('tvl',result)
        self.assertEqual(len({row['id'] for row in rows}),3)
        self.assertEqual(len(self.rpc.calls),6)
        canonical = await self.producer.get({**identifier_from_pool(rows[0]['pool']),
            'fee':500,'tickSpacing':60,'hooks':C,'tokenA':C})
        self.assertEqual(canonical['poolKey'],rows[0]['poolKey'])
        self.registry.observed[rows[0]['id']]['bitmapWords'] = [{'wordPosition':-1,'bitmap':str(1<<255)}]
        self.registry.observed[rows[0]['id']]['ticks'] = [{'index':-1,'liquidityGross':str(2**100),'liquidityNet':str(-2**99)}]
        warm = await self.producer.get(identifier_from_pool(rows[0]['pool']))
        self.assertEqual(warm['bitmapWords'][0]['bitmap'],str(1<<255))
        self.assertEqual(warm['ticks'][0]['liquidityNet'],str(-2**99))
        self.assertEqual(len(self.rpc.calls),6)

    async def test_v2_reserves_rate_and_static_metadata_reuse(self):
        result = await self.producer.get({'protocol':'v2','tokenA':A,'tokenB':B})
        self.assertEqual((result['reserve0Raw'],result['reserve1Raw']),('100000','200000'))
        self.assertEqual(result['marginalPrice'],{'numerator':'200000','denominator':'100000'})
        self.assertNotIn('activeLiquidityRaw',result)
        self.assertNotIn('token0BalanceRaw',result)
        self.assertNotIn('token1BalanceRaw',result)
        before = len(self.rpc.calls)
        self.assertEqual(await self.producer.get(identifier_from_pool(result['pool'])),result)
        self.assertEqual(len(self.rpc.calls),before)
        other = await self.producer.get({'protocol':'v2','tokenA':B,'tokenB':C})
        self.assertFalse(other['exists'])

    async def test_preinitialization_observation_uses_initialized_static_lp_fee(self):
        entry = self.v4()
        state = {**entry,'sqrtRatioX96':'0','tick':0,'liquidity':'0','lpFee':0,'protocolFee':0}
        self.registry.apply_event(state,{'topics':[DISCOVERY['v4'],entry['id']],
            'data':Web3.to_hex(self.rpc.w3.codec.encode(['uint24','int24','address','uint160','int24'],
                [100,1,ZERO,2**96,0]))})
        self.assertEqual((state['lpFee'],state['sqrtRatioX96'],state['liquidity']),(100,str(2**96),'0'))
        state['lpFee'] = 123
        self.registry.apply_event(state,{'topics':[DISCOVERY['v4'],entry['id']],
            'data':Web3.to_hex(self.rpc.w3.codec.encode(['uint24','int24','address','uint160','int24'],
                [0x800000,1,ZERO,2**96,0]))})
        self.assertEqual(state['lpFee'],123)  # Dynamic flag supplies no LP-pips observation.

    async def test_catalog_known_identities_no_pool_getters_and_http_legacy_compatibility(self):
        pools = [self.v4(),self.v4(60)]
        for pool in pools: self.registry.inventory[pool['id']] = pool
        self.registry.inventory['v3:path'] = {'id':'v3:path','protocol':'v3','token0':self.registry.token(A,18),
            'token1':self.registry.token(B,18),'feePips':500}
        catalog = await self.producer.catalog()
        self.assertEqual(len(catalog['entries']),2)
        self.assertEqual(self.rpc.calls,[])
        self.assertEqual((await self.producer.catalog(B,C))['entries'],[])
        app = create_app(pool_producer=self.producer)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
            self.assertEqual((await api.get('/api/pools/catalog')).json(),catalog)
            self.assertEqual((await api.get('/api/pools/catalog?tokenA=broken')).status_code,400)
            old = await api.post('/api/pools/snapshot',json={'tokenA':A,'tokenB':B,'fee':500,
                'activeLiquidityRaw':'0','protocolFee':0})
            self.assertEqual(old.status_code,200)
            self.assertNotIn('protocol',old.json())
            explicit = await api.post('/api/pools/snapshot',json=identifier_from_pool(pools[0]))
            self.assertEqual(explicit.status_code,200)
            self.assertEqual(explicit.json()['protocol'],'v4')

    async def test_cache_identity_spacing_hooks_manager_and_forged_state(self):
        class Database:
            def __init__(self): self.identities = {}
            async def ensure_schema(self): pass
            def connection(self):
                from contextlib import asynccontextmanager
                @asynccontextmanager
                async def connect(): yield self
                return connect()
            async def execute(self,sql,args):
                if sql.startswith('INSERT INTO quote_pool_identity_cache'):
                    self.identities[args[:3]] = json.loads(args[6])
                self.rows = [{'identifier':deepcopy(value)} for value in self.identities.values()]
                return self
            async def fetchall(self): return self.rows
        database = Database()
        cache = AuthoritativePoolCache(database,self.producer)
        pools = [self.v4(),self.v4(60),self.v4(1,C)]
        for pool in pools: self.registry.inventory[pool['id']] = pool
        entries = [{**identifier_from_pool(pool),'chainId':1,'dex':'uniswap_v4','exists':False,
                    'activeLiquidityRaw':'0','token0BalanceRaw':'99999999'} for pool in pools]
        await cache.record(entries)
        self.assertEqual(len(database.identities),3)
        self.assertNotEqual(cache.identity(entries[0]),cache.identity({**entries[0],'poolManager':C}))
        rows = await cache.list(1,'uniswap_v4',[{'tokenA':A,'tokenB':B}])
        self.assertEqual(len(rows),3)
        self.assertTrue(all(row['exists'] and 'token0BalanceRaw' not in row for row in rows))
        precise = await cache.list(1,'uniswap_v4',[{**identifier_from_pool(pools[1])}])
        self.assertEqual([row['id'] for row in precise],[pools[1]['id']])
        app = create_app(pool_cache=cache)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
            listed = await api.post('/api/quote-pool-cache',json={'action':'list-pools','chainId':1,
                'dex':'uniswap_v4','pairs':[{'tokenA':A,'tokenB':B,'poolId':pools[1]['id']}]})
            self.assertEqual(listed.status_code,200)
            self.assertEqual([row['id'] for row in listed.json()['entries']],[pools[1]['id']])
            incomplete = {**entries[0]}
            incomplete.pop('hooks')
            failed = await api.post('/api/quote-pool-cache',json={'action':'record-observations','entries':[incomplete]})
            self.assertEqual(failed.status_code,400)
        # Rebuild service; persisted identity hints re-acquire canonical state.
        self.registry.inventory.clear()
        restarted = AuthoritativePoolCache(database,self.producer)
        self.assertEqual(len(await restarted.list(1,'uniswap_v4',[{'tokenA':A,'tokenB':B}])),3)
        self.assertEqual(await restarted.list(1,'uniswap_v3',[]),[])


if __name__ == '__main__': unittest.main()
