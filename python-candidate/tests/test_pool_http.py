import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.pool_cache import PoolCache


async def run(path):
    cases=json.loads(Path(path).read_text())
    for case in cases:
        calls=[]
        class Cursor:
            async def fetchall(self):return []
        class Database:
            async def ensure_schema(self):pass
            @asynccontextmanager
            async def connection(self):yield self
            async def execute(self,sql,parameters):
                record='INSERT INTO quote_pool_cache' in sql
                parameters=list(parameters[:13] if record else parameters)
                # PostgreSQL's same numeric bind value; no JSON wire conversion.
                if not record:parameters[0]=float(parameters[0]) if '.' in parameters[0] else int(parameters[0])
                calls.append({'operation':'record' if record else 'list','params':parameters})
                if case['fail']:raise RuntimeError('fixture-private-sql-text')
                return Cursor()
        app=create_app(pool_cache=PoolCache(Database()))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                response=await api.post('/api/quote-pool-cache',content=case['raw'])
                result=response.json()
                if 'correlationId' in result:result['correlationId']='correlated'
                assert (response.status_code,result,response.headers.get('cache-control'),calls)==(
                    case['status'],case['result'],case['cache'],case['calls']),case
                assert 'fixture-private' not in response.text
    print(f'PASS: {len(cases)} actual Node/Pydantic pool-cache HTTP, normalization and SQL-bind comparisons')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))
