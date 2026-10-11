"""Configured role roster bytes, partial reads and the retained first-50 UI policy."""
import asyncio,json,sys,unittest
from pathlib import Path
from types import SimpleNamespace

import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider
from cybergold_candidate.app import create_app
from cybergold_candidate.governance_roles import GovernanceRoles,GovernanceRolesRpc,SURFACES

REFERENCE=json.loads(Path(sys.argv[1]).read_text())
HASH='0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self,failure=None,reorg=False,blocked=False):
        super().__init__();self.calls=[]
        self.failure,self.reorg,self.blocked=failure,reorg,blocked
        self.started,self.cancelled=asyncio.Event(),False

    async def make_request(self,method,params):
        self.calls.append((method,params))
        if method=='eth_chainId':result='0x7a6a'
        elif method=='eth_getBlockByNumber':
            result={'number':'0x65','timestamp':'0x6a000001','hash':'0x'+'b'*64 if self.reorg and params[0]!='latest' else HASH}
        elif method=='eth_call':
            self.started.set()
            if self.blocked:
                try: await asyncio.Event().wait()
                except asyncio.CancelledError:self.cancelled=True;raise
            call=params[0]
            if self.failure=='all' or call['data']==self.failure:
                return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://password@private.invalid'}}
            row=next(row for row in REFERENCE if row['address'].lower()==call['to'].lower())
            reads=[read for role in row['roles'] for read in [role['countCall'],*role['members']]]
            result=next(read['result'] for read in reads if read['data']==call['data'])
        else:raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    async def disconnect(self):pass


def service(provider,missing=None):
    values={'RPC_URL':'http://synthetic.invalid','RPC_AUTHORIZATION':'Bearer fixture','NEXT_PUBLIC_CHAIN_ID':'31338'}
    values.update({SURFACES[row['surface']][0]:None if row['surface']==missing else row['address'] for row in REFERENCE})
    settings=SimpleNamespace(**values)
    return GovernanceRoles(settings,GovernanceRolesRpc(settings,AsyncWeb3(provider)))


class GovernanceRolesTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_configured_role_bytes_members_and_retained_display_limit(self):
        for row in REFERENCE:
            provider=Provider();value=await service(provider).get(row['surface'])
            self.assertEqual(value['memberDisplayLimit'],50)
            for actual,expected in zip(value['roles'],row['roles'],strict=True):
                self.assertEqual(actual['count'],{'status':'success','value':expected['count']})
                self.assertEqual([member['value'].lower() for member in actual['members']],[member['address'] for member in expected['members']])
            expected=sorted(read['data'] for role in row['roles'] for read in [role['countCall'],*role['members']])
            calls=[params for method,params in provider.calls if method=='eth_call']
            self.assertEqual(sorted(params[0]['data'] for params in calls),expected)
            self.assertTrue(all(params[1]=={'blockHash':HASH,'requireCanonical':True} for params in calls))

    async def test_partial_count_failure_is_distinct_from_empty_success(self):
        row=REFERENCE[0];value=await service(Provider(failure=row['roles'][0]['countCall']['data'])).get('core')
        self.assertEqual(value['roles'][0]['count']['status'],'failure')
        self.assertEqual(value['roles'][1]['count'],{'status':'success','value':'0'})
        self.assertEqual(value['roles'][1]['members'],[])

    async def test_partial_member_failure_retains_count_and_other_members(self):
        role=REFERENCE[0]['roles'][0]
        value=await service(Provider(failure=role['members'][0]['data'])).get('core')
        self.assertEqual(value['roles'][0]['count']['value'],'2')
        self.assertEqual([member['status'] for member in value['roles'][0]['members']],['failure','success'])

    async def test_missing_surface_does_not_probe_an_arbitrary_or_other_contract(self):
        provider=Provider();value=await service(provider,missing='staking').get('staking')
        self.assertIsNone(value['address'])
        self.assertTrue(all(role['count']['error']=='not-configured' for role in value['roles']))
        self.assertFalse(any(method=='eth_call' for method,_ in provider.calls))

    async def test_concurrent_surfaces_and_reorg_context(self):
        observer=service(Provider());results=await asyncio.gather(*(observer.get(row['surface']) for row in REFERENCE))
        self.assertEqual([value['surface'] for value in results],[row['surface'] for row in REFERENCE])
        with self.assertRaisesRegex(ValueError,'head changed'):await service(Provider(reorg=True)).get('core')

    async def test_caller_cancellation_stops_the_member_operation(self):
        provider=Provider(blocked=True);task=asyncio.create_task(service(provider).get('core'))
        await provider.started.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(provider.cancelled)

    async def test_fixed_http_surface_no_store_head_and_partial_outage_redaction(self):
        app=create_app(governance_roles=service(Provider(failure='all')))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            result=await client.get('/api/governance/roles?surface=arbitrary&address=private-password')
            self.assertEqual(result.status_code,400);self.assertNotIn('private-password',result.text)
            result=await client.get('/api/governance/roles?surface=core&address=0x5555555555555555555555555555555555555555')
            self.assertEqual(result.status_code,200);self.assertEqual(result.headers['cache-control'],'no-store')
            self.assertEqual(result.json()['address'],REFERENCE[0]['address'])
            self.assertTrue(all(role['count']['status']=='failure' for role in result.json()['roles']))
            self.assertNotIn('password',result.text)
            head=await client.head('/api/governance/roles?surface=core')
            self.assertEqual(head.status_code,200);self.assertEqual(head.content,b'')


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
