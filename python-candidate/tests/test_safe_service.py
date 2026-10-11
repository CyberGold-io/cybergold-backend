import asyncio
import json
from pathlib import Path
import sys

import httpx

from cybergold_candidate.app import create_app


async def write_success_regressions():
    payload={'signature':'fixture-signature','nonce':7}
    cases=[(201,'',200,{}),(201,' \r\n',200,{}),(204,'',200,{}),
           (201,'{"accepted":true}',200,{'accepted':True}),
           (201,'{',502,None),(422,'',422,None)]
    for action in ('propose-transaction','confirm-transaction'):
        for status,raw,expected_status,expected_body in cases:
            calls=[]
            async def supplier(request):
                calls.append((request.method,json.loads(request.content)))
                return httpx.Response(status,content=raw.encode())
            async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as client:
                app=create_app(client=client,safe_service_url='http://fixture-supplier')
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                        response=await api.post('/api/safe',json={'action':action,
                            'safeAddress':'0x'+'a'*40,'safeTxHash':'0x'+'b'*64,'payload':payload})
                        assert response.status_code==expected_status,(action,status,response.text)
                        assert response.headers.get('cache-control')=='no-store'
                        if expected_body is not None:assert response.json()==expected_body
                        else:
                            assert response.json()['error']==('Failed to propose multisig transaction.'
                                if action=='propose-transaction' else 'Failed to confirm multisig transaction.')
                            assert isinstance(response.json()['correlationId'],str)
                        assert calls==[('POST',payload)],'Signed writes must not be retried'
    print('PASS: 12 independent Safe write response regressions; signed payload preserved, one submission')


async def run(path):
    await write_success_regressions()
    cases=json.loads(Path(path).read_text())
    for case in cases:
        calls=[]
        async def supplier(request):
            body=json.loads(request.content) if request.content else None
            calls.append({'url':str(request.url),'method':request.method,'body':body,
                          'contentType':request.headers.get('content-type')})
            if case['supplier'].get('throw'):raise OSError('fixture-private-transport-error')
            return httpx.Response(case['supplier']['status'],content=case['supplier']['body'].encode(),
                headers={'Retry-After':case['supplier']['retry']} if 'retry' in case['supplier'] else {})
        async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as client:
            app=create_app(client=client,safe_service_url=None if case.get('configured') is False else 'http://fixture-supplier/')
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app,raise_app_exceptions=False),base_url='http://fixture') as api:
                    response=await api.post('/api/safe',content=case['raw'])
                    result=response.json() if response.content else None
                    if isinstance(result,dict) and 'correlationId' in result:result['correlationId']='correlated'
                    assert (response.status_code,result,response.headers.get('cache-control'),
                            response.headers.get('retry-after'),calls)==(
                        case['status'],case['result'],case['cache'],case['retry'],case['calls']),case
                    assert 'fixture-private' not in response.text and 'supplier-error' not in response.text
    # The configured deadline is total rather than an implicit retry loop.
    attempts=0
    async def blocked(_request):
        nonlocal attempts
        attempts+=1
        await asyncio.sleep(1)
        return httpx.Response(200,json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(blocked)) as client:
        app=create_app(client=client,safe_service_url='http://fixture-supplier',safe_timeout_seconds=.01)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                response=await api.post('/api/safe',json={'action':'safe-info','safeAddress':'0x'+'a'*40})
                assert response.status_code==503 and attempts==1
    print(f'PASS: {len(cases)} actual Node/FastAPI Safe service action, supplier/error and forwarding comparisons; deadline/no retry')


if __name__=='__main__':asyncio.run(run(sys.argv[1]))
