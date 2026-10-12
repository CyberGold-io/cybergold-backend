"""R3: pinned recent-head retained validity versus full route search.

Use your own MAINNET_RPC_URL and optional RPC_AUTHORIZATION. Usage: --help.
No signing or writes; errors are reported by type only.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import urllib.request

from cybergold_candidate.quote_cache import SharingQuoterRpc, BasketMath, VerifiedGrossSeed
from cybergold_candidate.quote_correction import delayed_local_step
from cybergold_candidate.quote_intent import QuoteIntent
from cybergold_candidate.route_search import RouteSearch


def settings(origin):
    with urllib.request.urlopen(origin+'/api/protocol/facts',timeout=30) as response:
        facts=json.load(response)
    return SimpleNamespace(NEXT_PUBLIC_CHAIN_ID=1, RPC_URL=os.environ['MAINNET_RPC_URL'], RPC_AUTHORIZATION=os.environ.get('RPC_AUTHORIZATION'),
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=facts['core'], NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=facts['helpers'],
        NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS='0x61fFE014bA17989E743c5F6cB21bF9697530B21e')


def resolve(body,labels,offset):
    value=deepcopy(body)
    for key in ('token','quoteToken','adapter'): value[key]=labels.get(value[key],value[key])
    value['orderedAssets']=[labels.get(a,a) for a in value['orderedAssets']]
    value['amount']=str(int(value['amount'])+offset)
    for target in value['targets']:
        for key in ('inputAsset','outputAsset'): target[key]=labels.get(target[key],target[key])
    # Targets of minimum-output/initial exact-input are weights, so retain
    # their captured proportions with the new distinct semantic amount.
    allocated=0
    for index,target in enumerate(value['targets']):
        raw=int(value['amount'])*int(target['amount'])//int(body['amount'])
        if index==len(value['targets'])-1: raw=int(value['amount'])-allocated
        target['amount']=str(raw);allocated+=raw
    value['deadline']=str(int(time.time())+600)
    return value


async def main(args):
    cfg=settings(args.origin)
    labels=json.loads(Path(args.seed).read_text())['publicContracts']
    samples=json.loads(Path(args.evidence).read_text())['samples']
    document={'observedAt':datetime.now(timezone.utc).isoformat(),
        'scope':'Read-only local backend via dedicated tooling client. Each paired case pins a new current canonical hash so long cohorts do not unintentionally age every later context. Captured full plans at recent historical heads compared with selected validation and fresh full search at that paired hash. No App-key attribution or production before/after claim; per-case caches empty and order alternated. Different horizons are separate paired samples, not cadence percentages.',
        'samples':[]}
    output=Path(args.output)
    def save():output.write_text(json.dumps(document,indent=2)+'\n')
    for mode in args.modes.split(','):
        for asset in args.assets.split(','):
            template=next(s['request'] for s in samples if s['mode']==mode and s['asset']==asset and s['phase']=='fresh')
            for index,horizon in enumerate(map(int,args.horizons.split(','))):
                body=resolve(template,labels,args.raw_offset+index)
                rpc=SharingQuoterRpc(cfg,completed=True)
                routes=RouteSearch(cfg,rpc,remaining_batch_size=2)
                service=QuoteIntent(cfg,routes,basket_math=BasketMath(),seeds=VerifiedGrossSeed(),
                    correction=delayed_local_step,retain_plans=True,qualification=True)
                row={'mode':mode,'asset':asset,'horizonBlocks':horizon,'status':'failure','variants':{},'stage':'head'}
                started_case=time.perf_counter()
                try:
                    current=await rpc.block(None)
                    await rpc.assert_canonical(current)
                    row['currentContext']=current
                    row['stage']='prime'
                    prior=await rpc.block(hex(int(current['number'])-horizon))
                    previous=await service.get(body,lambda _:asyncio.sleep(0),block=prior)
                    body['retainedPlan']={'executionAmount':previous['executionAmount'],
                        'maximumInputAmount':previous['maximumInputAmount'],
                        'minimumAmountOut':previous['preview'].get('minimumAmountOut','0'),
                        'quotes':previous['quotes'],'expectedCoreOutputs':previous.get('expectedCoreOutputs',[])}
                    values=row['variants']
                    for variant in (('retained','full') if index%2==0 else ('full','retained')):
                        # A fresh service/rpc prevents previous variant reads
                        # from being credited to this variant's local bank.
                        wire=SharingQuoterRpc(cfg,completed=True)
                        search=RouteSearch(cfg,wire,remaining_batch_size=2)
                        quote=QuoteIntent(cfg,search,basket_math=BasketMath(),seeds=VerifiedGrossSeed(),
                            correction=delayed_local_step,retain_plans=variant=='retained',qualification=True)
                        payload=deepcopy(body)
                        if variant=='full':payload.pop('retainedPlan',None)
                        row['stage']=variant
                        start=time.perf_counter()
                        try:
                            result=await quote.get(payload,lambda _:asyncio.sleep(0),block=current)
                            values[variant]={'elapsedMs':(time.perf_counter()-start)*1000,
                                'executionAmount':result['executionAmount'],'maximumInputAmount':result['maximumInputAmount'],
                                'minimumOutput':result['preview'].get('minimumAmountOut','0'),'metrics':result['metrics'],
                                'coreBoundsPreserved':result.get('expectedCoreOutputs')==previous.get('expectedCoreOutputs'),
                                'paths':['0x'+wire.w3.codec.decode(['bytes','uint256','uint256','bool'],bytes.fromhex(leg['data'][2:]))[0].hex() for leg in result['quotes']]}
                        finally:await quote.close();await search.close()
                    row.update(status='complete',stage='comparison')
                    old,new=values['retained'],values['full']
                    metric='maximumInputAmount' if mode=='issue-exact-out' else 'executionAmount' if mode in ('redeem-exact-out','issue-exact-in') else 'minimumOutput'
                    a,b=int(old[metric]),int(new[metric])
                    row['fullSearchPriceImprovementPercent']=100*(a-b)/a if mode in ('issue-exact-out','redeem-exact-out') else 100*(b-a)/a
                    row['extraReadsForFull']=new['metrics']['rpcReads']-old['metrics']['rpcReads']
                    row['retainedSelectedOnly']=old['metrics']['candidateCalls']<=2 and old['metrics']['iterations']==0
                    await rpc.assert_canonical(current)
                    row['canonicalAtEnd']=True
                except Exception as error:row.update(errorType=type(error).__name__)
                finally:await service.close();await routes.close()
                row['caseElapsedMs']=(time.perf_counter()-started_case)*1000
                document['samples'].append(row);save()
                print(json.dumps({k:v for k,v in row.items() if k!='variants'}),flush=True)
    save()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--origin',default='https://app.cybergold.io')
    parser.add_argument('--seed',required=True);parser.add_argument('--evidence',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--horizons',default='1,8,32')
    parser.add_argument('--assets',default='USDC')
    parser.add_argument('--raw-offset',type=int,default=1000)
    parser.add_argument('--modes',default='issue-exact-in,issue-exact-out,redeem-exact-in,redeem-exact-out')
    asyncio.run(main(parser.parse_args()))
