import asyncio
import json
from pathlib import Path
import sys

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.faucet import normalize_ip
from cybergold_candidate.faucet import REQUEST_ID


async def run(path):
    reference=json.loads(Path(path).read_text())
    for ip in reference['ips']:assert normalize_ip(ip['value'])==ip['normalized'],ip
    for case in reference['cases']:
        calls=[]
        async def supplier(request):
            calls.append({'url':str(request.url),'method':request.method,'body':json.loads(request.content),
                'privateAuthorization':request.headers.get('authorization')=='Bearer '+'1'*64,'redirect':'error'})
            if case.get('throw'):raise httpx.ConnectError('fixture-private-transport')
            reply=case.get('supplier',{})
            headers={'content-type':reply.get('type','application/json')}
            if 'retry' in reply:headers['retry-after']=reply['retry']
            if 'declared' in reply:headers['content-length']=reply['declared']
            raw=reply.get('raw',json.dumps(reply.get('value',reference['success'])))
            return httpx.Response(reply.get('status',200),content=raw,headers=headers)
        async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as client:
            app=create_app(client=client,faucet_settings={'enabled':case.get('enabled',True),
                'url':case.get('url','http://127.0.0.1:9999/fund'),'token':case.get('token','1'*64)})
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                    headers={'content-type':case.get('type','application/json'),'origin':'http://localhost:3030'}
                    ip=case.get('ip',['127.0.0.1','127.0.0.1'])
                    if ip[0] is not None:headers['x-real-ip']=ip[0]
                    if ip[1] is not None:headers['x-forwarded-for']=ip[1]
                    if 'declared' in case:headers['content-length']=case['declared']
                    response=await api.post('/api/faucet',content=case['raw'],headers=headers)
                    result=response.json()
                    if response.status_code!=200:
                        assert REQUEST_ID.fullmatch(result.pop('correlationId')),result
                    actual=(response.status_code,result,response.headers.get('cache-control'),
                        response.headers.get('retry-after'),response.headers.get('x-cybergold-faucet-request-id'),calls)
                    expected=(case['status'],case['result'],case['cache'],case['retry'],case['replace'],case['calls'])
                    assert actual==expected,(case,actual)
                    assert 'fixture-private' not in response.text
    calls=0
    async def slow(_request):
        nonlocal calls
        calls+=1
        await asyncio.sleep(.1)
        return httpx.Response(200,json=reference['success'])
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        app=create_app(client=client,faucet_settings={'enabled':True,'url':'http://127.0.0.1:9999/fund','token':'1'*64},
            faucet_timeout_seconds=.01)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
                response=await api.post('/api/faucet',json={'address':'0x'+'a'*40,
                    'requestId':'11111111-1111-4111-8111-111111111111'},
                    headers={'x-real-ip':'127.0.0.1','x-forwarded-for':'127.0.0.1'})
                assert response.status_code==504 and calls==1
    print(f"PASS: {len(reference['cases'])} actual Node/Python faucet adapter cases, {len(reference['ips'])} IP cases and total deadline")


if __name__=='__main__':asyncio.run(run(sys.argv[1]))
