"""Native ERC20 approval gas wire, configured spender and ordinary failure."""
import asyncio,json,sys,unittest
from pathlib import Path
from types import SimpleNamespace
import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider
from cybergold_candidate.app import create_app
from cybergold_candidate.permit2_approval_gas import ApprovalRequest,Permit2ApprovalGas,Permit2ApprovalGasRpc

REFERENCE=json.loads(Path(sys.argv[1]).read_text());HASH='0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self,failure=False,blocked=False,reorg=False,chain='0x7a6a'):
        super().__init__();self.calls=[];self.failure,self.blocked,self.reorg,self.chain=failure,blocked,reorg,chain
        self.started,self.cancelled=asyncio.Event(),False

    async def make_request(self,method,params):
        self.calls.append((method,params))
        if method=='eth_chainId':result=self.chain
        elif method=='eth_getBlockByNumber':result={'number':'0x65','timestamp':'0x6a000001','hash':'0x'+'b'*64 if self.reorg and params[0]!='latest' else HASH}
        elif method=='eth_call':
            assert params[0]==REFERENCE[0]['helpersCall'];result=REFERENCE[0]['helpersResult']
        elif method=='eth_estimateGas':
            self.started.set()
            if self.blocked:
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:self.cancelled=True;raise
            if self.failure:return {'jsonrpc':'2.0','id':1,'error':{'code':3,'message':'https://password@private.invalid'}}
            row=next(row for row in REFERENCE if params==row['calls'][0]['params']);result=hex(int(row['gas']))
        else:raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    async def disconnect(self):pass


def service(provider):
    settings=SimpleNamespace(RPC_URL='http://synthetic.invalid',RPC_AUTHORIZATION='Bearer fixture',NEXT_PUBLIC_CHAIN_ID='31338',NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=REFERENCE[0]['helpers'])
    return Permit2ApprovalGas(settings,Permit2ApprovalGasRpc(settings,AsyncWeb3(provider)))


class ApprovalGasTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_viem_estimate_wire_and_full_allowance_fixed_spender(self):
        provider=Provider();observer=service(provider)
        for row in REFERENCE:
            result=await observer.get(ApprovalRequest.model_validate(row['payload']))
            self.assertEqual(result['gas'],row['gas']);self.assertEqual(result['permit2'].lower(),row['permit2']);self.assertEqual(result['blockTag'],'latest')
        self.assertEqual([{'method':method,'params':params} for method,params in provider.calls if method=='eth_estimateGas'],[row['calls'][0] for row in REFERENCE])
        self.assertTrue(all(params[1]=={'blockHash':HASH,'requireCanonical':True} for method,params in provider.calls if method=='eth_call'))

    async def test_concurrent_owners_are_fresh_and_not_reserved(self):
        provider=Provider();observer=service(provider)
        result=await asyncio.gather(*(observer.get(ApprovalRequest.model_validate(row['payload'])) for row in REFERENCE))
        self.assertEqual([row['gas'] for row in result],[row['gas'] for row in REFERENCE])
        await observer.get(ApprovalRequest.model_validate(REFERENCE[0]['payload']))
        self.assertEqual(sum(method=='eth_estimateGas' for method,_ in provider.calls),4)

    async def test_chain_and_reorg_failures_do_not_return_estimate(self):
        for provider,message in ((Provider(chain='0x1'),'chain mismatch'),(Provider(reorg=True),'head changed')):
            with self.assertRaisesRegex(ValueError,message):await service(provider).get(ApprovalRequest.model_validate(REFERENCE[0]['payload']))

    async def test_cancellation_stops_native_estimation(self):
        provider=Provider(blocked=True);task=asyncio.create_task(service(provider).get(ApprovalRequest.model_validate(REFERENCE[0]['payload'])))
        await provider.started.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(provider.cancelled)

    async def test_native_failure_is_redacted_not_a_default_gas_number(self):
        app=create_app(permit2_approval_gas=service(Provider(failure=True)))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            result=await client.post('/api/transaction/permit2-approval-gas',json=REFERENCE[0]['payload'])
            self.assertEqual(result.status_code,503);self.assertEqual(result.headers['cache-control'],'no-store')
            self.assertNotIn('password',result.text);self.assertNotIn('gas',result.json())

    async def test_fixed_shape_ignores_unrelated_provider_or_spender_without_writes(self):
        provider=Provider();app=create_app(permit2_approval_gas=service(provider))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            for payload in ({},{'owner':'bad','token':REFERENCE[0]['payload']['token']}):self.assertEqual((await client.post('/api/transaction/permit2-approval-gas',json=payload)).status_code,400)
            result=await client.post('/api/transaction/permit2-approval-gas',json={**REFERENCE[0]['payload'],'spender':REFERENCE[0]['payload']['owner'],'provider':'http://unused.invalid','amount':'7'})
            self.assertEqual(result.status_code,200);self.assertEqual(result.json()['permit2'].lower(),REFERENCE[0]['permit2'])
        self.assertTrue(all(method in ('eth_chainId','eth_getBlockByNumber','eth_call','eth_estimateGas') for method,_ in provider.calls))


if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
