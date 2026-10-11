import asyncio
import json
from pathlib import Path
import sys
import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.aliases import AliasAuthError


async def run(path):
    cases=json.loads(Path(path).read_text())
    for case in cases:
        calls=[];mode=case.get('mode','normal')
        class Service:
            async def mutate(self,input):
                await self.authorize(input)
                if input['action']=='upsert':
                    return await self.upsert(input['editorAddress'],input['ownerAddress'],input['alias'])
                return await self.delete(input['editorAddress'],input['ownerAddress'])
            async def authorize(self,input):
                calls.append({'operation':'authorize','input':input})
                if mode=='auth-error':raise AliasAuthError('Alias authorization nonce has already been used.')
            async def list(self,editor,owners):
                calls.append({'operation':'list','input':{'editorAddress':editor,'ownerAddresses':owners}})
                if mode=='db-error':raise ValueError('private fixture')
                return []
            async def upsert(self,editor,owner,alias):
                calls.append({'operation':'upsert','input':{'editorAddress':editor,'ownerAddress':owner,'alias':alias}})
                return {'fixture':'entry'}
            async def delete(self,editor,owner):
                calls.append({'operation':'delete','input':{'editorAddress':editor,'ownerAddress':owner}})
                return True
        app=create_app(aliases=Service())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app,raise_app_exceptions=False),base_url='http://fixture') as client:
                response=await client.post('/api/governance/owner-aliases',content=case['raw'].encode())
        result=response.json() if response.content else None
        if result and 'correlationId' in result:result['correlationId']='generated'
        actual=(response.status_code,result,response.headers.get('cache-control'),calls)
        assert actual==(case['status'],case['result'],case['cache'],case['calls']),(case,actual)
    print(f'PASS: {len(cases)} actual Node/Python alias HTTP parsing, UTF-16 limits, write authorization order and errors comparisons; runtime authorization has its separate comparison')


asyncio.run(run(sys.argv[1]))
