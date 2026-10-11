import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
from pathlib import Path
import sys

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.safe_status import SafeStatus


async def run(path):
    cases=json.loads(Path(path).read_text())
    for case in cases:
        calls=[]
        class Cursor:
            def __init__(self,rows):self.rows=rows
            async def fetchone(self):return self.rows[0] if self.rows else None
            async def fetchall(self):return self.rows
        class Database:
            @asynccontextmanager
            async def connection(self):yield self
            @asynccontextmanager
            async def transaction(self):yield
            async def execute(self,sql,params=()):
                if 'onchain_api_rate_limits' in sql:
                    calls.append({'operation':'rate','params':list(params)})
                    mode=case.get('mode')
                    limited=mode=='global-limit' or mode=='safe-limit' and not params[0].endswith(':global')
                    return Cursor([] if limited else [{'request_count':1}])
                if 'generate_series' in sql:return Cursor([] if case.get('mode')=='busy' else [{'slot':0}])
                if 'FROM onchain_event_logs' in sql:
                    calls.append({'operation':'read','params':list(params)})
                    if case.get('mode')=='sql-error':raise RuntimeError('fixture-sql-error')
                    return Cursor([{'event_name':name,'tx_hash':'0x'+char*64,'block_number':block,
                        'block_timestamp':datetime.fromisoformat(date),'safe_tx_hash':'0x'+'c'*64}
                        for name,char,block,date in [('ExecutionFailure','d',9007199254740993,'2026-09-30T10:00:00+00:00'),
                            ('ExecutionSuccess','e',1,'2026-09-30T09:00:00+00:00')]])
                return Cursor([])
        app=create_app(safe_status=SafeStatus(Database(),31337,['0x'+'a'*40],lambda:1790762430123))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app,raise_app_exceptions=False),base_url='http://fixture') as api:
                response=await api.post('/api/safe/events',content=case['raw'],
                    headers={'content-length':case['declared']} if 'declared' in case else {})
                result=response.json() if response.content else None
                expected=case['result']
                if case.get('mode')=='sql-error':
                    assert 'correlationId' in result and 'fixture-sql-error' not in response.text
                    result={**result,'correlationId':'generated'}
                    expected={'error':'Safe event observations are temporarily unavailable.','correlationId':'generated'}
                assert (response.status_code,result,response.headers.get('cache-control'),response.headers.get('retry-after'),calls)==(
                    case['status'],expected,case['cache'],case['retry'],case['calls']),case
    print(f'PASS: {len(cases)} actual Node/Python Safe execution-status HTTP, rate and projection comparisons')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))
