"""Actual retained configuration/worker cadence and accounting comparisons."""
import asyncio
from contextlib import asynccontextmanager
import json
import sys

from cybergold_candidate.environment import load_environment
from cybergold_candidate import worker_engine

BASE={'DATABASE_URL':'postgresql://fixture.invalid/db','NEXT_PUBLIC_RPC_URL':'http://fixture.invalid',
    'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS':'0x'+'1'*40,'NEXT_PUBLIC_CHAIN_ID':'1'}


async def check(fixture):
    for case in fixture['configCases']:
        values={**BASE,**case['values']}
        # The configuration function can also receive an internally absent
        # required public address; ordinary startup validation is qualified in
        # the environment suite and remains unchanged.
        settings=load_environment(values) if values['NEXT_PUBLIC_CORE_DIAMOND_ADDRESS'] is not None else load_environment(BASE).model_copy(update=case['values'])
        config=worker_engine.indexer_config(settings)
        actual={key:str(value) if key in ('chainId','startBlock','chunkSize','maxBlocksPerRun','reorgWindow') else value
            for key,value in config.items()} if config else None
        assert actual==case['expected'],(case,actual)
    original=worker_engine.CoreCollector
    try:
        for case in fixture['runs']:
            mode,calls=case['mode'],[]
            class Database:
                async def ensure_schema(self):calls.append('schema')
                @asynccontextmanager
                async def advisory_lock(self,key):
                    calls.append(['lock',key]);yield mode!='busy'
                async def close(self):pass
            class Rpc:
                async def close(self):pass
            class Collector:
                def __init__(self,*args):pass
                async def reconcile(self,counter,*args,**kwargs):
                    calls.append('collect');counter.plan('core-address')
                    if mode=='failed':raise ValueError('fixture collection failure')
                    if mode=='forced-empty':return None
                    return {'completed':mode!='partial','dashboardHistoryProgress':{'fixture':'progress'} if mode=='partial' else None}
            worker_engine.CoreCollector=Collector
            engine=worker_engine.WorkerEngine(Database(),load_environment(BASE),now_ms=lambda:100000,rpc_factory=lambda *_args:Rpc())
            if mode=='disabled':engine.config=None
            if 'cadence' in mode:engine.runtime['lastReconciledAtMs']=99999
            if mode=='shared-promise':
                async def shared():return {'completed':True,'dashboardHistoryProgress':None}
                engine.runtime['reconcilePromise']=asyncio.create_task(shared())
            result=error=None
            try:
                result=await engine.run_once(mode=='force-after-cadence' or 'cadence' not in mode,
                    lambda value:calls.append(['stage',value]),gateway_expectation={} if mode=='expectation' else None)
            except Exception as failure:error=str(failure)
            actual={'result':result,'error':error,'calls':calls,'lastReconciledAtMs':engine.runtime['lastReconciledAtMs'],
                'lastRpcRequestCounts':engine.runtime['lastRpcRequestCounts'],'promiseCleared':engine.runtime['reconcilePromise'] is None}
            assert actual==case['expected'],(mode,actual,case['expected'])
    finally:worker_engine.CoreCollector=original
    print(f"PASS: {len(fixture['configCases'])} actual worker configurations and {len(fixture['runs'])} retained run/cadence/lock/accounting paths")


if __name__=='__main__':asyncio.run(check(json.load(open(sys.argv[1]))))
