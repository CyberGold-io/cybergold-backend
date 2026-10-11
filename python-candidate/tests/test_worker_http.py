import asyncio
import json
from pathlib import Path
import sys
import httpx

from cybergold_candidate.worker_http import create_worker_app
from test_worker_contract import revive


async def run(path):
    cases=revive(json.loads(Path(path).read_text()))
    for case in cases:
        calls=[];mode=case.get('mode','normal');status=case.get('status','reconciled')
        class Controller:
            async def last_receipt(self):
                if mode=='error':raise ValueError('fixture worker failure')
                return None if mode=='absent' else {'fixture':'receipt'}
            async def run_once(self,force,on_stage):
                calls.append({'force':force,'diagnostic':on_stage is not None})
                if on_stage:on_stage('fixture-stage')
                if mode=='error':raise ValueError('fixture worker failure')
                if mode=='secret':raise ValueError('Bearer fixture-private-value')
                return {'status':status,'dashboardHistoryProgress':None}
            def refresh_product_metrics(self):pass
            async def fork_status(self):
                if mode=='error':raise ValueError('failure')
                return None
            async def transition(self,input):
                calls.append(input)
                if mode=='error':raise ValueError('failure')
                return {'status':status,'plan':{'kind':'reuse-prefix','invalidateFrom':101,'retainedThrough':100}} if status=='applied' else {'status':status}
        app=create_worker_app(Controller(),'a'*32)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as client:
            auth=case.get('auth','Bearer '+'a'*32)
            headers={'authorization':auth or '','content-type':case.get('type','application/json')}
            route='fork-generation' if case['route']=='fork' else 'reconcile'
            response=await client.request(case['method'],'/api/internal/onchain-indexer/'+route+case.get('query',''),
                headers=headers,content=case.get('raw','').encode())
        actual=(response.status_code,response.json(),response.headers.get('cache-control'),response.headers.get('retry-after'),calls)
        assert actual==(case['code'],case['result'],case['cache'],case['retry'],case['calls']),(case,actual)
    print(f'PASS: {len(cases)} actual Node/Python worker HTTP authorization, outcomes, fork requests and diagnostics comparisons')


asyncio.run(run(sys.argv[1]))
