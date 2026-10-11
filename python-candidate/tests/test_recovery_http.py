import asyncio
import json
from pathlib import Path
import sys

from aiohttp import ClientResponseError, RequestInfo
import httpx
from fastapi import Request
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from cybergold_candidate.app import create_app
from cybergold_candidate.recovery_http import handle_recovery
from cybergold_candidate.recovery_rpc import RecoveryApiError


async def run(path):
    cases=json.loads(Path(path).read_text())
    for case in cases:
        calls=[]
        class Loader:
            async def get(self,holder,offset,block_hash):
                calls.append({'holder':holder,'offset':str(offset),'blockHash':block_hash})
                failure=case.get('failure','')
                if failure=='ordinary':raise RuntimeError('fixture-private-error')
                if failure=='api-busy':raise RecoveryApiError('Recovery snapshot changed; restart discovery',503,1)
                if failure=='api-unavailable':raise RecoveryApiError('Recovery RPC capacity exhausted',429,30)
                if failure.startswith('http'):
                    headers=CIMultiDictProxy(CIMultiDict({'Retry-After':failure[8:]} if failure.startswith('http429:') else {}))
                    raise ClientResponseError(RequestInfo(URL('http://fixture'), 'POST',headers),(),
                        status=503 if failure=='http503' else 429,headers=headers)
                return {'fixture':'portfolio'}
            async def close(self):pass
        # Fixed observation clock for standard Retry-After date parity.
        app=create_app()
        @app.get('/fixture')
        async def route(request:Request):
            return await handle_recovery(request,Loader(),lambda:1790762400)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                response=await api.get('/fixture'+case['query'])
                assert (response.status_code,response.json(),response.headers.get('cache-control'),
                    response.headers.get('retry-after'),calls)==(case['status'],case['result'],case['cache'],case['retry'],case['calls']),case
    print(f'PASS: {len(cases)} actual Node/Python recovery HTTP pagination, private-error and retry-header comparisons')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))
