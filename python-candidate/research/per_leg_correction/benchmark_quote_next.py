"""Read-only paired per-leg correction experiment; integration remains inactive.

--help lists arguments. No credentials, calldata or upstream URLs in output.
Independent variant services, pinned canonical hashes, alternating orders.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .benchmark_quote_followup import settings, resolve
from cybergold_candidate.quote_cache import BasketMath, SharingQuoterRpc, VerifiedGrossSeed
from .quote_component_correction import ComponentCorrection
from cybergold_candidate.quote_correction import delayed_local_step
from cybergold_candidate.quote_history import QuoteHistory, economic_path
from cybergold_candidate.quote_intent import QuoteIntent
from cybergold_candidate.route_search import RouteSearch


def selector(error):
    value=error.get('data')
    if isinstance(value,str) and value.startswith('0x') and len(value)>=10:return value[:10]
    if isinstance(value,dict):
        for child in value.values():
            if isinstance(child,dict):
                result=selector(child)
                if result:return result
    return None


class MeasuredRpc(SharingQuoterRpc):
    def __init__(self,cfg):
        super().__init__(cfg,completed=True)
        self.started=time.perf_counter();self.observations=[]
        original=self.w3.provider.make_request
        async def request(method,params):
            start=time.perf_counter();result=await original(method,params)
            row={'transport':'single','method':method,'members':1,
                'startMs':1000*(start-self.started),'endMs':1000*(time.perf_counter()-self.started)}
            if method=='eth_call':row['functionSelector']=params[0]['data'][:10]
            if 'error' in result:row.update(rpcCode=result['error'].get('code'),revertSelector=selector(result['error']))
            self.observations.append(row);return result
        self.w3.provider.make_request=request

    async def call_batch(self,calls,block):
        start=time.perf_counter();rows=await super().call_batch(calls,block)
        quoter=[]
        for (address,data),response in zip(calls,rows,strict=True):
            if address.lower()!=self.quoter.lower():continue
            _,arguments=self.contract.decode_function_input(data)
            entry={'path':'0x'+arguments['path'].hex(),'amount':str(arguments['amount'])}
            if 'error' in response:
                raw=response['error'].get('data')
                if isinstance(raw,str) and raw.startswith('0x08c379a0'):
                    entry['revertReason']=self.w3.codec.decode(['string'],bytes.fromhex(raw[10:]))[0]
            quoter.append(entry)
        self.observations.append({'transport':'batch','method':'eth_call','members':len(calls),'quoterInputs':quoter,
            'functionSelectors':list(dict.fromkeys(data[:10] for _,data in calls)),
            'startMs':1000*(start-self.started),'endMs':1000*(time.perf_counter()-self.started),
            'errors':[{'rpcCode':row['error'].get('code'),'revertSelector':selector(row['error'])} for row in rows if 'error' in row]})
        return rows


def economic(result,mode):
    metric='maximumInputAmount' if mode=='issue-exact-out' else 'executionAmount' if mode in ('issue-exact-in','redeem-exact-out') else 'displayAmount'
    return str(result[metric])


async def run_variant(cfg,body,block,variant,state=None,baselines=None,planner=None):
    rpc=MeasuredRpc(cfg)
    size=2
    search=RouteSearch(cfg,rpc,direct_batch_size=size,remaining_batch_size=size,group_planner=planner)
    decode=lambda data:'0x'+rpc.w3.codec.decode(['bytes','uint256','uint256','bool'],bytes.fromhex(data[2:]))[0].hex()
    correction=ComponentCorrection(state,body['quoteToken'],decode,baselines,use_upper_rate=variant=='upper-rate') if variant in ('component','upper-rate') else delayed_local_step
    service=QuoteIntent(cfg,search,basket_math=BasketMath(),seeds=VerifiedGrossSeed(),
        correction=correction,qualification=True)
    start=time.perf_counter();events=[]
    async def update(event):
        row={'type':event['type'],'arrivedMs':1000*(time.perf_counter()-start)}
        if event['type']=='qualified':row.update(economic=economic(event['value'],body['mode']))
        if event['type']=='estimate':row.update(amount=event['amount'])
        if event['type']=='progress':row.update(stage=event['stage'],completed=event['completed'],total=event['total'])
        events.append(row)
    result=None
    try:
        result=await service.get(deepcopy(body),update,block=block)
        row={'status':'complete','elapsedMs':1000*(time.perf_counter()-start),'events':events,
            'economic':economic(result,body['mode']),'executionAmount':result['executionAmount'],
            'minimumOutput':result['preview'].get('minimumAmountOut'), 'metrics':result['metrics'],
            'paths':[decode(leg['data']) for leg in result['quotes']]}
        row['firstQualifiedMs']=next((e['arrivedMs'] for e in events if e['type']=='qualified'),None)
        if body['mode']=='redeem-exact-out':
            target=int(body['amount']);minimum=int(row['minimumOutput'])
            row['originalIntervalPreserved']=target<=minimum<=(target*10100+9999)//10000
        if isinstance(correction,ComponentCorrection):row.update(proposals=correction.proposals,fallbacks=correction.fallbacks)
    except Exception as error:
        row={'status':'failure','errorType':type(error).__name__,
            'elapsedMs':1000*(time.perf_counter()-start),'events':events}
    finally:
        row['rpcObservations']=rpc.observations
        await service.close();await search.close()
    return row,result


async def main(args):
    cfg=settings(args.origin)
    labels=json.loads(Path(args.seed).read_text())['publicContracts']
    samples=json.loads(Path(args.evidence).read_text())['samples']
    doc={'observedAt':datetime.now(timezone.utc).isoformat(),'experiment':args.experiment,
        'scope':'Local source, read-only dedicated tooling transport, not App client or private host attribution. Independent empty variant services; one current pinned canonical hash per paired amount, alternating variant order. Cold per-leg setup and paid route baseline acquisition reported separately; warm candidates assume those immutable state observations already exist. No new calibration quote grid, execution margin or eleven-check budget change.', 'samples':[]}
    output=Path(args.output)
    def save():output.write_text(json.dumps(doc,indent=2)+'\n')
    assets=args.assets.split(',')
    for asset in assets:
        mode='redeem-exact-out'
        if asset=='XAUt':
            template={'mode':mode,'token':labels['basketAsset2'],'quoteToken':labels['basketAsset2'],'native':False,
                'amount':'3000000','adapter':labels['adapter'],'orderedAssets':[labels['basketAsset1'],labels['basketAsset2']],
                'targets':[{'inputAsset':labels['basketAsset2'],'outputAsset':labels['basketAsset1'],'amount':'1800000'}]}
        else:template=next(s['request'] for s in samples if s['mode']==mode and s['asset']==asset and s['phase']=='fresh')
        for index in range(args.start_index,args.start_index+args.samples):
            body=resolve(template,labels,113*index if asset=='XAUt' else args.raw_offset+index*10003)
            if asset=='XAUt':body['targets'][0]['amount']=str(int(body['amount'])*600000//1000000)
            head=MeasuredRpc(cfg);block=await head.block(None);await head.assert_canonical(block)
            row={'asset':asset,'mode':mode,'index':index+1,'amount':body['amount'],'block':block,'variants':{}}
            state,baselines,planner=None,{},None
            history=QuoteHistory(cfg);start=time.perf_counter()
            context={'chainId':1,'blockNumber':str(block['number']),'blockHash':block['hash'],'observedAt':doc['observedAt']}
            try:
                await history.acquire_state(head,block,context)
            except Exception as error:
                row.update(status='setup-failure',errorType=type(error).__name__,stage='state-acquisition',setupRpcObservations=head.observations)
                doc['samples'].append(row);save();await head.close();continue
            raw=history.states[block['hash'].lower()]['state']
            state={k:list(map(int,v)) if k in ('weights','conversions','available','recoveryShares','recoveryValues') else int(v) if k in ('issueFee','helperFee','redeemFee','supply','maxSupply','effectiveCap') else v for k,v in raw.items()}
            row['stateSetup']={'elapsedMs':1000*(time.perf_counter()-start),'reads':history.reads,'envelopes':history.envelopes}
            # Use real pool marginal prices/fees on the ordinary baseline's
            # selected paths; charge these setup reads rather than fabricating a decomposition.
            baseline,result=await run_variant(cfg,body,block,'shipped')
            row['variants']['shipped']=baseline
            start=time.perf_counter();before=history.reads
            if result:
                for path in baseline['paths']:
                    tokens,fees=economic_path(path,'exact-in');key=(tuple(tokens),tuple(fees),block['hash'].lower())
                    await history.acquire_pool(head,tokens,fees,block,context,key)
                    baselines[path]=history.baselines[key][0]
            row['poolSetup']={'elapsedMs':1000*(time.perf_counter()-start),'reads':history.reads-before,'realMarginalBaselines':len(baselines)}
            variants=['component','upper-rate'] if index%2==0 else ['upper-rate','component']
            try:
                for variant in variants:
                    value,_=await run_variant(cfg,body,block,variant,state,baselines,None)
                    row['variants'][variant]=value
                    print(json.dumps({'asset':asset,'index':index+1,'variant':variant,'status':value['status'],'ms':round(value['elapsedMs']),'firstQualifiedMs':value.get('firstQualifiedMs')}),flush=True)
                try:
                    await head.assert_canonical(block);row['canonicalAtEnd']=True
                except Exception as error:
                    row.update(canonicalAtEnd=False,qualificationErrorType=type(error).__name__)
            finally:
                row['setupRpcObservations']=head.observations;await head.close()
                doc['samples'].append(row);save()
    save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',default='https://app.cybergold.io')
    parser.add_argument('--seed',required=True);parser.add_argument('--evidence',required=True);parser.add_argument('--output',required=True)
    parser.set_defaults(experiment='correction')
    parser.add_argument('--assets',default='WETH,USDC');parser.add_argument('--samples',type=int,default=3)
    parser.add_argument('--raw-offset',type=int,default=1000,help='Distinct raw-unit offset; avoid turning a small 6-decimal redemption into an amount above supply.')
    parser.add_argument('--start-index',type=int,default=0)
    asyncio.run(main(parser.parse_args()))
