"""Executable universal quotes: actual ordered pool arithmetic, wire and HTTP."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import httpx
from web3 import Web3

from cybergold_candidate.app import create_app
from cybergold_candidate.exact_input_plan import PLAN, compile_plan
from cybergold_candidate.protocol_config import ProtocolConfiguration, select_adapter
from cybergold_candidate.route_encoding import encode_route, register_routing_adapter
from cybergold_candidate.routing_encoding import ZERO, ROUTING_ENCODING, ROUTING_TYPE, split_runtime
from cybergold_candidate.universal_quote import UniversalQuotes, PAXG
from cybergold_candidate.wallet_balances import TOKENS
from cybergold_candidate.route_search import WETH
from cybergold_candidate.uniswap_routes import pool_identity

CORE, HELPERS, OTHER, USER = ['0x'+part*40 for part in '1235']
ADAPTER = '0x'+'a1'*20
BLOCK={'number':21,'hash':'0x'+'ab'*32}

def settings(configured=True):
    return SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
        NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=HELPERS,
        CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS=ADAPTER if configured else None)


def pool(a,b,name,canonical=False):
    a,b=sorted((a.lower(),b.lower()))
    return {'id':name,'address':name,'protocol':'v4' if canonical else 'v2',
        'token0':{'address':a,'decimals':18,'chainId':1},
        'token1':{'address':b,'decimals':18,'chainId':1},
        'feePips':3000,'tickSpacing':60,'hooks':ZERO,'reserve0':'1000000','reserve1':'1000000'}


class Engine:
    def __init__(self):
        rows=[pool(WETH,PAXG,'0x'+'66'*20),pool(WETH,OTHER,'0x'+'77'*20),
              pool(OTHER,PAXG,'0x'+'88'*20),pool(PAXG,CORE,'0x'+'99'*20,True)]
        self.registry=SimpleNamespace(inventory={row['id']:row for row in rows},chain=1,core=CORE,seed=rows[-1])
        self.registry.get_rpc=lambda:self
        self.calls=[]
        self.semaphore=asyncio.Semaphore(8)
        self.cap=None
    async def block(self,_): return deepcopy(BLOCK)
    async def assert_canonical(self,block): self.calls.append(('canonical',block))
    async def quote_sdk_branches(self,branches,mode,amount,block,*,candidate,canonical):
        # Independent forward constant-product formula, mutating only this
        # candidate. Shared bank proves branch/order interaction, not a mock
        # that would return identical outputs irrespective of execution order.
        hop=branches[0]['hops'][0]; source=hop['pool']; key=pool_identity(source)
        state=candidate.setdefault(key,deepcopy(source))
        left,right=('reserve0','reserve1') if hop['zeroForOne'] else ('reserve1','reserve0')
        used=min(amount,self.cap) if self.cap else amount
        x,y=int(state[left]),int(state[right]); received=used*997*y//(x*1000+used*997)
        state[left],state[right]=str(x+used),str(y-received)
        return {'amountIn':str(used),'amountOut':str(received)}


class Quotes(UniversalQuotes):
    def __init__(self,engine,configured=True):
        self.previews=[]; self.evaluated=[]
        super().__init__(settings(configured),engine,preview=self.preview_call,basis_reader=self.basis_call)
    async def basis_call(self,block): return [PAXG,OTHER],[500000,500000]
    def seed_routes(self,*_): pass
    async def discover(self,*_): pass
    async def preview_call(self,mode,value,block):
        self.previews.append((mode,deepcopy(value)))
        if mode=='issue-exact-in':
            amounts=list(map(int,value['maximumAmountsIn'])); matched=min(amounts)
            exact=[matched,matched]
            return {'netCygldOut':str(matched*2),'amountsInExact':list(map(str,exact)),
                'orderedCoreAssets':[PAXG,OTHER], 'fees':{'protocolFeeCygld':'0','helperFeeCygld':'0'}}
        gross=int(value['grossCygldIn']); lot=gross//2
        return {'projectedCoreOutputs':[{'kind':0,'token':PAXG,'id':'0','amount':str(lot)},
            {'kind':1,'token':OTHER,'id':'7','amount':'3'},
            {'kind':0,'token':OTHER,'id':'0','amount':str(gross-lot)}],
            'fees':{'protocolFeeCygld':'0','helperFeeCygld':'0'}}
    async def candidate(self,request,share,order,*args,**kwargs):
        self.evaluated.append((share,order))
        return await super().candidate(request,share,order,*args,**kwargs)


def request(intent=0):
    return {'intent':intent,'inputs':[{'currency':ZERO if intent==0 else CORE,'amount':'10001'}],
        'outputCurrency':CORE if intent in (0,2) else ZERO,'recipient':USER,'deadline':'2000000000','slippageBps':100}


class UniversalQuoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_market_and_trade_producers_delegate_when_release_is_configured(self):
        from cybergold_candidate.market_swap import MarketQuotes
        from cybergold_candidate.trade_quote import TradeQuotes
        service=Quotes(Engine()); req={'side':'buy','mode':'exact-in','counterToken':PAXG,
            'amount':'10001','recipient':USER,'deadline':'2000000000','slippageBps':100}
        market=MarketQuotes.__new__(MarketQuotes); market.universal_quotes=service
        trade=TradeQuotes.__new__(TradeQuotes); trade.universal_quotes=service
        app=create_app(market_quotes=market,trade_quotes=trade)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            market_result=await client.post('/api/quotes/market',json=req)
            trade_result=await client.post('/api/quotes/trade/stream',json=req)
        self.assertEqual(market_result.status_code,200,market_result.text)
        self.assertEqual(market_result.json()['operation'],'executeExactInput')
        frames=[json.loads(line) for line in trade_result.text.splitlines()]
        complete=next(frame['value'] for frame in frames if frame['type']=='complete')
        self.assertEqual(complete['operation'],'executeExactInput')
        self.assertTrue(all(frame['value']['strategy']=='universal' for frame in frames if frame['type'] in ('qualified','complete')))
        self.assertNotIn('adapterData',market_result.json())

    async def test_recipient_less_core_api_is_explicitly_numeric_after_release_adoption(self):
        class Legacy:
            universal_quotes=Quotes(Engine())
            async def get(self,req,publish):
                value={'mode':req['mode'],'context':{},'displayAmount':'7','executionAmount':'8',
                    'maximumInputAmount':'9','preview':{'minimumAmountOut':'6'},'quotes':[{'data':'0xdeadbeef'}]}
                await publish({'type':'qualified','value':value})
                return value
        app=create_app(quote_intent=Legacy())
        req={'mode':'redeem-exact-in','token':PAXG,'quoteToken':PAXG,'native':False,
            'amount':'8','deadline':'2000000000','orderedAssets':[PAXG,OTHER],'targets':[]}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            response=await client.post('/api/quotes/intent/stream',json=req)
        self.assertEqual(response.status_code,200,response.text)
        frames=[json.loads(line) for line in response.text.splitlines()]
        for frame in frames:
            if frame['type'] in ('qualified','complete'):
                self.assertTrue(frame['value']['readOnly']); self.assertNotIn('quotes',frame['value'])
                self.assertEqual(frame['value']['executionAmount'],'8')
        self.assertNotIn('deadbeef',response.text)

    async def test_output_target_core_sale_gets_fresh_core_only_plan_at_solved_input_and_accepted_minima(self):
        from cybergold_candidate.trade_quote import TradeQuotes
        service=Quotes(Engine()); trade=TradeQuotes.__new__(TradeQuotes); trade.universal_quotes=service
        async def resolve(req): return {**req,'adapter':ADAPTER}
        trade.resolve=resolve; trade.packet=lambda _:{}
        expected=[{'kind':0,'token':PAXG,'id':'0','minimumAmount':'100'},
            {'kind':1,'token':OTHER,'id':'7','minimumAmount':'2'},
            {'kind':0,'token':OTHER,'id':'0','minimumAmount':'100'}]
        legacy={'strategy':'core','outputMinimum':'1000','providerQuote':{
            'executionAmount':'10001','expectedCoreOutputs':expected}}
        class Shared:
            async def get(self,req,publish):
                await publish({'type':'qualified','value':legacy})
                await publish({'type':'provider-qualified','strategy':'core','value':legacy})
                return legacy
        trade.sharing=Shared();frames=[]
        async def publish(frame): frames.append(frame)
        result=await trade.get({'side':'sell','mode':'exact-out','counterToken':WETH,'native':False,
            'amount':'1000','recipient':USER,'deadline':'2000000000','slippageBps':100},publish)
        self.assertEqual(result['strategy'],'universal');self.assertEqual(result['plan']['inputs'][0]['amount'],'10001')
        self.assertEqual(result['plan']['minimumOutput'],'1000')
        branch=result['planDescription']['branches'][0]
        self.assertEqual(branch['kind'],0);self.assertEqual(branch['amountIn'],'10001')
        self.assertEqual(branch['data']['expectedOutputs'],expected)
        self.assertTrue(all(frame.get('value',{}).get('strategy')!='core' for frame in frames if frame['type'] in ('qualified','provider-qualified')))

    async def test_share_only_core_sale_keeps_zero_scalar_bound_and_forwards_shares(self):
        service=Quotes(Engine())
        async def shares(mode,value,block):
            return {'projectedCoreOutputs':[{'kind':1,'token':OTHER,'id':'7','amount':'5'}],
                'fees':{'protocolFeeCygld':'0','helperFeeCygld':'0'}}
        service.preview=shares
        service.engine.registry.inventory={}
        result=await service.get(request(1))
        self.assertEqual(result['quotedOutput'],'0');self.assertEqual(result['plan']['minimumOutput'],'0')
        self.assertEqual(result['recoveryShares'],[{'kind':1,'token':OTHER,'id':'7','amount':'5'}])
        self.assertEqual(result['routeFamily'],'core')

    async def test_http_runs_joint_core_market_grid_and_compiles_authoritative_plan(self):
        service=Quotes(Engine());app=create_app(universal_quotes=service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            response=await client.post('/api/quotes/universal-exact-input',json=request())
        self.assertEqual(response.status_code,200,response.text)
        value=response.json(); self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(value['strategy'],'universal');self.assertEqual(value['quotedInput'],'10001')
        expected={(0,'core-first'),(100,'core-first'),*( (share,order) for share in (25,50,75) for order in ('core-first','market-first'))}
        self.assertEqual(set(service.evaluated),expected)
        self.assertEqual(len(service.evaluated),16)
        self.assertEqual(value['plan']['inputs'],request()['inputs'])
        self.assertGreater(int(value['quotedOutput']),int(value['outputMinimum']))
        self.assertEqual(compile_plan(value['plan'],value['planDescription'],int(value['outputMinimum'])),value['plan'])
        self.assertEqual(value['retentionDisclosure']['custodian'],HELPERS)
        self.assertEqual(service.engine.calls[-1],('canonical',BLOCK))
        for mode,args in service.previews:
            self.assertEqual(mode,'issue-exact-in');self.assertEqual(len(args['maximumAmountsIn']),2)

    async def test_two_orders_replay_shared_pool_state_instead_of_summing_stale_quotes(self):
        service=Quotes(Engine());req=request(1);req['outputCurrency']=WETH
        assets,weights=await service.basis_call(BLOCK)
        first=await service.candidate(req,50,'core-first',BLOCK,assets,weights,first=True)
        second=await service.candidate(req,50,'market-first',BLOCK,assets,weights,first=True)
        self.assertNotEqual(first['quotedOutput'],second['quotedOutput'])
        self.assertEqual(len(first['planDescription']['branches'][0]['data']['conversions']),3)
        self.assertEqual(first['recoveryShares'][0]['kind'],1)
        # All scalar variants disclose gross spend irrespective of any AMM remainder.
        self.assertEqual(first['inputMaximum'],'10001')

    async def test_cold_native_pool_discovery_preserves_six_decimal_and_unknown_metadata(self):
        service=Quotes(Engine());registry=service.engine.registry
        usdc,xaut=[dict(TOKENS)[name] for name in ('usdc','xaut')]
        async def loaded(): pass
        async def connectors(*_): pass
        async def metadata(currency,block):
            if currency.lower()==OTHER.lower(): raise OSError('optional metadata unavailable')
            return registry.token(currency,6 if currency.lower() in (usdc.lower(),xaut.lower()) else 18)
        registry.ensure_loaded=loaded;registry.token_metadata=metadata
        registry.token=lambda address,decimals:{'address':Web3.to_checksum_address(address),'decimals':decimals,'chainId':1}
        service.engine.connector_inventory=connectors
        await UniversalQuotes.discover(service,request(),[usdc,xaut,OTHER],BLOCK)
        for address in (usdc,xaut):
            row=next(pool for pool in registry.inventory.values() if {pool['token0']['address'].lower(),
                pool['token1']['address'].lower()}=={ZERO,address.lower()})
            token=next(token for token in (row['token0'],row['token1']) if token['address'].lower()==address.lower())
            self.assertEqual(token['decimals'],6)
        unknown=next(pool for pool in registry.inventory.values() if {pool['token0']['address'].lower(),
            pool['token1']['address'].lower()}=={ZERO,OTHER.lower()})
        self.assertFalse(unknown['token1']['decimalsKnown'])
        unknown.update(reserve0='1000000',reserve1='2000000')
        # Unknown display scale cannot veto ordinary raw-unit swap pricing.
        _,output,_=await service.conversion(OTHER,ZERO,1000,BLOCK,{}, {},first=True)
        self.assertGreater(output,0)

    async def test_route_identity_seed_does_not_wait_for_optional_discovery(self):
        service=Quotes(Engine());service.engine.registry.metadata={}
        UniversalQuotes.seed_routes(service,request(),[PAXG,OTHER])
        pools=list(service.engine.registry.inventory.values())
        self.assertTrue(any(row['protocol']=='v3' and row['feePips']==3000 for row in pools))
        native=next(row for row in pools if row['protocol']=='v4' and
            {row['token0']['address'].lower(),row['token1']['address'].lower()}=={ZERO,OTHER.lower()})
        self.assertEqual(native['token0']['decimals'],18)
        self.assertIsNone(native['token1']['decimals'])
        # Optional discovery can remain parked while the seeded selected graph
        # qualifies a real candidate under the unchanged producer budget.
        entered=asyncio.Event();qualified=asyncio.Event();finished=False
        async def slow_discovery(*_):
            nonlocal finished
            entered.set();await qualified.wait();finished=True
        async def publish(frame):
            if frame['type']=='qualified' and not qualified.is_set():
                self.assertFalse(finished);qualified.set()
        service=Quotes(Engine());service.discover=slow_discovery
        result=await asyncio.wait_for(service.get(request(),publish),2)
        self.assertTrue(entered.is_set());self.assertTrue(finished)
        self.assertGreater(int(result['quotedOutput']),0)

    async def test_warm_discovery_keeps_v3_seed_first_without_removing_refinement_routes(self):
        service=Quotes(Engine());registry=service.engine.registry
        seeded=pool(OTHER,PAXG,'0x'+'66'*20);seeded['protocol']='v3'
        thin_v2=pool(OTHER,PAXG,'0x'+'22'*20)
        alternative_v4=pool(OTHER,PAXG,'0x'+'33'*20,True)
        priced=[]
        async def price(route,amount,*_):
            protocol=route[0]['pool']['protocol'];priced.append(protocol)
            output=max(1,amount//1000) if protocol=='v2' else amount*({'v3':3,'v4':4}[protocol])
            return amount,output
        service.price_path=price
        registry.inventory={seeded['id']:seeded}
        _,cold,_=await service.conversion(OTHER,PAXG,1000,BLOCK,{}, {},first=True)
        self.assertEqual(cold,3000)
        # Discovery adds a real but nearly exhausted V2 acquisition. Its tiny
        # output would leave a large Core residual requiring slower V4 coverage.
        registry.inventory.update({thin_v2['id']:thin_v2,alternative_v4['id']:alternative_v4})
        for observed in (True,False):
            with self.subTest(seedAddressObserved=observed):
                if observed: seeded['address']=seeded['id']
                else: seeded.pop('address',None)
                priced.clear()
                _,warm,_=await service.conversion(OTHER,PAXG,1000,BLOCK,{}, {},first=True)
                self.assertEqual(warm,cold)
                self.assertEqual(priced,['v3'])
        # The initial preference is not eligibility: ordinary refinement still
        # compares V2/V3/V4, including split paths, and can choose another protocol.
        priced.clear()
        _,refined,_=await service.conversion(OTHER,PAXG,1000,BLOCK,{}, {},first=False)
        self.assertEqual(set(priced),{'v2','v3','v4'})
        self.assertEqual(refined,4000)

    async def test_real_sdk_engine_replays_pool_post_state_across_core_and_market_branches(self):
        from cybergold_candidate.route_quote_engine import RouteQuoteEngine
        from cybergold_candidate.shared_reads import SharedReads
        source=Engine(); registry=source.registry; registry.pending=SharedReads()
        canonical=registry.seed
        canonical.update(sqrtRatioX96=str(2**96),tick=0,liquidity=str(10**18),lpFee=3000,protocolFee=0,
            bitmapWords=[{'wordPosition':-1,'bitmap':str(1<<246)},{'wordPosition':0,'bitmap':str(1<<10)}],
            ticks=[{'index':-600,'liquidityGross':str(10**18),'liquidityNet':str(10**18)},
                   {'index':600,'liquidityGross':str(10**18),'liquidityNet':str(-(10**18))}])
        reads=[]
        async def snapshot(pool,block):
            reads.append(pool['id'])
            return deepcopy(pool)
        registry.snapshot=snapshot
        class RecordingEngine(RouteQuoteEngine):
            def __init__(self):
                super().__init__(settings(),registry);self.before=[]
            async def quote_sdk_branches(self,branches,mode,amount,block,**kwargs):
                identity=branches[0]['hops'][0]['pool']['id']
                self.before.append((identity,deepcopy(kwargs['candidate'].get(identity))))
                return await super().quote_sdk_branches(branches,mode,amount,block,**kwargs)
        engine=RecordingEngine();service=Quotes(engine);req=request(1);req['outputCurrency']=WETH
        try:
            observations={}
            value=await service.candidate(req,50,'core-first',BLOCK,[PAXG,OTHER],[1,1],first=True,observations=observations)
            self.assertGreater(int(value['quotedOutput']),0)
            reused=[state for _,state in engine.before if state is not None]
            self.assertTrue(reused)
            self.assertTrue(any(int(state.get('reserve0','1000000'))!=1000000 or
                                int(state.get('reserve1','1000000'))!=1000000 for state in reused))
            acquired=len(reads)
            repeated=await service.candidate(req,50,'core-first',BLOCK,[PAXG,OTHER],[1,1],first=True,observations=observations)
            self.assertEqual(value['quotedOutput'],repeated['quotedOutput'])
            self.assertEqual(len(reads),acquired) # quote-local observations, separate replay banks
            self.assertTrue(all(row.get('reserve0','1000000')=='1000000' for row in observations.values()))
            # Initial observations remain canonical despite the selected post-state bank.
            self.assertTrue(all(row['reserve0']=='1000000' for row in registry.inventory.values()))
        finally:
            await engine.close();await registry.pending.close()

    async def test_declared_input_remainder_is_disclosed_without_reducing_gross_spend(self):
        engine=Engine();engine.cap=4000;service=Quotes(engine);req=request();req['inputs'][0]['currency']=PAXG
        value=await service.candidate(req,0,'core-first',BLOCK,[PAXG,OTHER],[1,1],first=True)
        charges=value['estimatedRetainedInputCharges'];self.assertTrue(charges)
        self.assertEqual(sum(int(row['amount']) for row in charges),6001)
        self.assertEqual(value['quotedInput'],'10001');self.assertEqual(value['plan']['inputs'][0]['amount'],'10001')
        self.assertEqual(charges[0]['currency'].lower(),PAXG.lower())

    async def test_basket_vectors_keep_full_output_positions_and_omit_scalar_input_total(self):
        service=Quotes(Engine());req=request(2)
        req['inputs']=[{'currency':PAXG,'amount':'10000'},{'currency':OTHER,'amount':'0'}]
        value=await service.get(req)
        self.assertNotIn('quotedInput',value);self.assertGreater(int(value['quotedOutput']),0)
        self.assertEqual(value['fees']['coreHelpersFeeCygld'],'0')
        self.assertEqual(value['routeFamily'],'mixed') # zero issuance still executes continuation
        value=await service.get(request(3))
        self.assertEqual(len(value['planDescription']['expectedOutputs']),3)
        self.assertEqual(len(value['estimatedRecipientOutputs']),3)
        self.assertEqual(value['estimatedRecipientOutputs'][1]['kind'],1) # Core output positions are preserved
        self.assertEqual(value['recoveryShares'][0]['id'],'7')

    async def test_missing_release_address_does_not_invent_capability(self):
        service=Quotes(Engine(),False);app=create_app(universal_quotes=service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            response=await client.post('/api/quotes/universal-exact-input',json=request())
        self.assertEqual(response.status_code,503);self.assertEqual(response.json()['code'],'quote-unavailable')

    async def test_default_changes_only_after_successor_is_configured_and_observed_approved(self):
        old='0xc2c210979674db1349f812ea116f2f6d131ab839'
        self.assertEqual(select_adapter([old,ADAPTER])[0].lower(),old)
        self.assertEqual(select_adapter([old],ADAPTER)[0].lower(),old)
        self.assertEqual(select_adapter([old,ADAPTER],ADAPTER),(Web3.to_checksum_address(ADAPTER),ROUTING_ENCODING))
        config=ProtocolConfiguration(settings())
        retained={'retainedPlan':{'params':{'adapter':old}}}
        self.assertEqual((await config.resolve_request(retained))['adapter'],old)
        await config.close()

    def test_successor_exactout_encoding_and_runtime_rounding(self):
        fixture=json.loads((Path(__file__).parents[2]/'tests/fixtures/universal-exact-input.json').read_text())
        register_routing_adapter(ADAPTER)
        for row in fixture['adapterCases']:
            self.assertEqual(encode_route(row['route'],ADAPTER),row['encoded'])
            decoded=Web3().codec.decode([ROUTING_TYPE],bytes.fromhex(row['encoded'][2:]))[0]
            self.assertEqual(decoded[0],row['route']['mode']=='exactIn')
        self.assertEqual(split_runtime(7,[{'sharePpm':333333},{'sharePpm':0}]),[2,5])

if __name__=='__main__': unittest.main()
