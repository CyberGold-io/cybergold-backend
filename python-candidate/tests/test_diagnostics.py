import asyncio
import json
from pathlib import Path
import sys

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.diagnostics import project


async def run(path):
    # Python's direct projection must also ignore values that cannot be sent as JSON.
    for code in [float('nan'),float('inf'),-float('inf')]:
        assert project({'errorCode':code,'errorSelector':'0xAbCd0123'})=={'errorSelector':'0xabcd0123'}
    cases=json.loads(Path(path).read_text())
    for case in cases:
        logs=[]
        class Logger:
            def info(self,message):
                record=json.loads(message);record.pop('requestId')
                logs.append(record)
        assert project(case.get('body'))==case['projection'],case
        app=create_app(diagnostic_logger=Logger())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                response=await api.post('/api/diagnostics',content=case['raw'],headers={'content-type':case.get('type','application/json')})
                assert (response.status_code,response.json(),response.headers.get('cache-control'),logs)==(
                    case['status'],case['result'],case['cache'],case['records']),case
                assert 'fixture-private' not in json.dumps(logs)
    class FailingLogger:
        def info(self,_message):raise RuntimeError('fixture-logging-failure')
    app=create_app(diagnostic_logger=FailingLogger())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
            assert (await api.post('/api/diagnostics',json={'operation':'quote','outcome':'failed'})).status_code==202
    print(f'PASS: {len(cases)} actual Fastify/Python diagnostic parser, projection and redaction comparisons; logging outage isolated')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))
