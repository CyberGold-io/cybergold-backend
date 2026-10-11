"""Controlled final-quote comparison against archived stage-separated services.

Usage: python benchmark_quote_intent.py BEFORE_PACKAGE_DIR OUTPUT_JSON
BEFORE_PACKAGE_DIR is an immutable git archive of the pre-change Python package.
Fixture transports inject 15 ms per RPC HTTP request; no live network or signing.
Optional provisional Helpers reads are excluded from the legacy final-only flow.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

import httpx
from web3 import AsyncWeb3, Web3

from test_quote_intent import Provider, QuoteWire, SETTINGS, request
from test_route_search import ASSET_C
from cybergold_candidate.quote_intent import QuoteIntent, floor, ceil
from cybergold_candidate.route_search import RouteSearch, RouteSearchRpc

before = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('cybergold_before', before / '__init__.py', submodule_search_locations=[str(before)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from cybergold_before.route_search import RouteSearch as BeforeRoutes, RouteSearchRpc as BeforeRouteRpc
from cybergold_before.basket_preview import BasketPreview as BeforeBasket, BasketPreviewRpc as BeforeBasketRpc
from cybergold_before.token_preview import TokenPreview as BeforeToken, TokenPreviewRpc as BeforeTokenRpc
from cybergold_before.core_recovery_assets import CoreRecoveryAssets, ABI as RECOVERY_ABI
from cybergold_before.protocol_facts import ProtocolFactsRpc

DELAY = .015
SETTINGS.NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS = SETTINGS.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS
class DelayedProvider(Provider):
    async def make_request(self, method, params):
        await asyncio.sleep(DELAY)
        result = await super().make_request(method, params)
        if method.startswith('eth_getBlock'):
            result['result']['timestamp'] = '0x64'
        return result

class DelayedWire(QuoteWire):
    async def send(self, value):
        await asyncio.sleep(DELAY)
        return await super().send(value)

async def legacy(value, routes, w3):
    basket = BeforeBasket(SETTINGS, BeforeBasketRpc(SETTINGS, w3))
    token = BeforeToken(SETTINGS, BeforeTokenRpc(SETTINGS, w3))
    stages = 0
    async def preview(service, payload):
        nonlocal stages
        stages += 1
        return (await service.get(payload))['result']
    async def search(targets, mode):
        nonlocal stages
        stages += 1
        return (await routes.get({'mode': mode, 'targets': targets}, on_update=lambda event: asyncio.sleep(0)))['results']
    def legs(targets, rows, mode, redeem=False):
        output = []
        for target, row in zip(targets, rows, strict=True):
            best = row['best']; limit = floor(int(best['quote'])) if mode == 'exact-in' else int(target['amount'])
            data = '0x' + w3.codec.encode(['bytes','uint256','uint256','bool'], [bytes.fromhex(best['path'][2:]),limit,int(value['deadline']),mode=='exact-in']).hex()
            leg = {'adapter':value['adapter'],'minimumAmountOut':str(limit),'data':data}
            if redeem: leg.update(inputAsset=target['inputAsset'],inputAmount=target['amount'])
            else: leg.update(outputAsset=target['outputAsset'],amountIn=target['amount'] if mode=='exact-in' else str(ceil(int(best['quote']))))
            output.append(leg)
        return output
    def issue_request(mode, quotes, maximum, net=None):
        result = {'mode':'issue-' + ('native' if value['native'] else 'token') + '-' + mode,'quotes':quotes}
        if not value['native']: result['inputToken']=value['token']
        if mode=='exact-in': result['inputAmount']=str(maximum)
        else: result.update({('maximumNativeIn' if value['native'] else 'maximumInputAmount'):str(maximum)}, netCygldOut=str(net))
        return result
    async def redeem(gross):
        required = await preview(basket, {'mode':'redeem-exact-in','grossCygldIn':str(gross)})
        targets = [{'inputAsset':row['token'],'outputAsset':value['quoteToken'],'amount':row['amount']}
                   for row in required['projectedCoreOutputs'] if row['kind']==0 and int(row['amount'])>0 and row['token'].lower()!=value['quoteToken'].lower()]
        quotes = legs(targets,await search(targets,'exact-in'),'exact-in',True)
        final = await preview(token,{'mode':'redeem-'+('native' if value['native'] else 'token')+'-exact-in',
            'outputToken':value['token'],'grossCygldIn':str(gross),'quotes':quotes})
        return {'quotes':quotes,'preview':final,'executionAmount':str(gross),'maximumInputAmount':'0','displayAmount':final['minimumAmountOut']}
    amount = int(value['amount'])
    if value['mode'].startswith('issue'):
        initial = None
        if value['mode']=='issue-exact-in':
            targets=value['targets']; quotes=legs(targets,await search(targets,'exact-in'),'exact-in')
            initial=await preview(token,issue_request('exact-in',quotes,amount)); net=floor(int(initial['netCygldOut']))
        else: net=amount
        required=await preview(basket,{'mode':'issue-exact-out','netCygldOut':str(net)})
        targets=[{'inputAsset':value['quoteToken'],'outputAsset':asset,'amount':raw} for asset,raw in zip(required['orderedCoreAssets'],required['amountsInExact'],strict=True) if int(raw)>0 and asset.lower()!=value['quoteToken'].lower()]
        quotes=legs(targets,await search(targets,'exact-out'),'exact-out')
        direct=sum(int(raw) for asset,raw in zip(required['orderedCoreAssets'],required['amountsInExact'],strict=True) if asset.lower()==value['quoteToken'].lower())
        maximum=amount if initial else direct+sum(int(row['amountIn']) for row in quotes)
        final=await preview(token,issue_request('exact-out',quotes,maximum,net))
        result={'quotes':quotes,'preview':final,'executionAmount':str(net),'maximumInputAmount':str(maximum),
            'displayAmount':initial['netCygldOut'] if initial else str(maximum)}
    elif value['mode']=='redeem-exact-in': result=await redeem(amount)
    else:
        targets=value['targets']; rows=await search(targets,'exact-out')
        stages+=1
        recovery=await CoreRecoveryAssets(SETTINGS,ProtocolFactsRpc(SETTINGS,w3,abi=RECOVERY_ABI)).get()
        by_asset={target['inputAsset'].lower():row['best']['quote'] for target,row in zip(targets,rows,strict=True)}
        minimums=[{'kind':0,'token':asset,'id':'0','minimumAmount':by_asset.get(asset.lower(),'0')} for asset in value['orderedAssets']]
        minimums.extend({'kind':1,'token':SETTINGS.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS,'id':str(int(asset,16)),'minimumAmount':'0'} for asset in recovery['assets'])
        initial=await preview(basket,{'mode':'redeem-exact-out','minimumOutputs':minimums}); gross=int(initial['grossCygldIn'])
        for iteration in range(11):
            result=await redeem(gross); quoted=int(result['preview']['minimumAmountOut'])
            if amount<=quoted<=ceil(amount): result['displayAmount']=str(gross);break
            if iteration==10 or quoted<=0: raise ValueError('Legacy solver did not converge')
            next_gross=gross*amount//quoted;gross=next_gross if next_gross!=gross else gross+(1 if quoted<amount else -1)
    return result, stages

async def sample(value, old):
    provider,wire=DelayedProvider(),DelayedWire(); w3=AsyncWeb3(provider)
    route=(BeforeRoutes if old else RouteSearch)(SETTINGS,(BeforeRouteRpc if old else RouteSearchRpc)(SETTINGS,w3,httpx.AsyncClient(transport=httpx.MockTransport(wire.send))))
    started=time.perf_counter()
    try:
        if old: result,stages=await legacy(value,route,w3)
        else: result=await QuoteIntent(SETTINGS,route).get(value,lambda event:asyncio.sleep(0));stages=1
        return {'ms':round((time.perf_counter()-started)*1000,3),'rpcReads':len(provider.calls)+sum(map(len,wire.batches)),
                'rpcHttpRequests':len(provider.calls)+len(wire.batches),'routeBatchSizes':list(map(len,wire.batches)),
                'browserApiStages':stages,'result':{key:result[key] for key in ('quotes','preview','executionAmount','maximumInputAmount','displayAmount')}}
    finally: await route.close()

async def main():
    rows=[]
    for mode in ('issue-exact-in','issue-exact-out','redeem-exact-in','redeem-exact-out'):
        for generic in (False,True):
            value=request(mode)
            if generic:
                original=value['quoteToken'];value['quoteToken']=value['token']=ASSET_C
                for target in value['targets']:
                    for key in ('inputAsset','outputAsset'):
                        if target[key]==original:target[key]=ASSET_C
            samples=[]
            for repeat in range(3):
                old,new=await sample(value,True),await sample(value,False)
                assert old['result']==new['result'],(mode,generic,old['result'],new['result'])
                samples.append({'before':old,'after':new})
            before_ms=statistics.median(row['before']['ms'] for row in samples)
            after_ms=statistics.median(row['after']['ms'] for row in samples)
            row={'mode':mode,'asset':'generic' if generic else 'WETH','beforeMedianMs':before_ms,'afterMedianMs':after_ms,
                'controlledTimeSavingPercent':round((1-after_ms/before_ms)*100,2),'samples':samples}
            rows.append(row);print(json.dumps({key:val for key,val in row.items() if key!='samples'}),flush=True)
    Path(sys.argv[2]).write_text(json.dumps({'scope':'Controlled fixtures: 15 ms per RPC HTTP request, cold services; no browser RTT or input debounce; legacy final-only stages use archived pre-change service source. Optional legacy provisional Helpers reads excluded. All final tuples identical. These are not deployed Mainnet savings.','rows':rows},indent=2)+'\n')

asyncio.run(main())
