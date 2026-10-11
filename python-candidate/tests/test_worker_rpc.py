import asyncio
import json
from pathlib import Path
import sys
import unittest

from aiohttp import web,ClientResponseError
from web3.exceptions import Web3RPCError
from cybergold_candidate.worker_rpc import approved_range_reduction,RawLogTransport
from cybergold_candidate.adaptive_logs import execute_ranges


class WorkerRpc(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls=[];self.mode='http';self.headers=[]
        async def rpc(request):
            body=await request.json();self.calls.append(body['params'][0]);self.headers.append(request.headers.get('Authorization'))
            range=body['params'][0];width=int(range['toBlock'],16)-int(range['fromBlock'],16)+1
            if self.mode=='terminal':return web.Response(status=429,text='range limit')
            if width>1:
                if self.mode=='http':return web.Response(status=413)
                return web.json_response({'jsonrpc':'2.0','id':body['id'],'error':{'code':-32005,'message':'range limit'}})
            return web.json_response({'jsonrpc':'2.0','id':body['id'],'result':[range['fromBlock']]})
        app=web.Application();app.router.add_post('/',rpc);self.runner=web.AppRunner(app);await self.runner.setup()
        site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        self.transport=RawLogTransport('http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/',
            'Bearer fixture-private',timeout_seconds=.2)

    async def asyncTearDown(self):
        await self.transport.close();await self.runner.cleanup()

    async def test_approved_http_and_rpc_signals_use_left_first_ranges(self):
        for mode in ['http','rpc']:
            self.calls=[];self.mode=mode
            async def request(attempt):return await self.transport.logs('0x'+'a'*40,attempt['range'])
            async def validate(value,_range):return value
            result=await execute_ranges({'fromBlock':100,'toBlock':103},request,validate,approved_range_reduction)
            self.assertEqual(result['values'],['0x64','0x65','0x66','0x67'])
            self.assertEqual(result['attemptCount'],7)
            self.assertEqual([(value['fromBlock'],value['toBlock']) for value in self.calls],
                [('0x64','0x67'),('0x64','0x65'),('0x64','0x64'),('0x65','0x65'),('0x66','0x67'),('0x66','0x66'),('0x67','0x67')])
        self.assertTrue(all(value=='Bearer fixture-private' for value in self.headers))

    async def test_unapproved_http_does_not_split_or_retry(self):
        self.mode='terminal'
        async def request(attempt):return await self.transport.logs('0x'+'a'*40,attempt['range'])
        async def validate(value,_range):return value
        with self.assertRaisesRegex(ValueError,'without an approved range-reduction signal'):
            await execute_ranges({'fromBlock':100,'toBlock':103},request,validate,approved_range_reduction)
        self.assertEqual(len(self.calls),1)


cases=json.loads(Path(sys.argv.pop()).read_text())
for case in cases:
    value=case['value']
    if value['name']=='HttpRequestError':error=ClientResponseError(None,(),status=value['status'])
    elif value['name']=='RpcRequestError':error=Web3RPCError('fixture',rpc_response={'error':{'code':value['code']}})
    else:error=ValueError('fixture')
    assert approved_range_reduction(error)==case['result'],case
print(f'PASS: {len(cases)} actual Node/Python direct-provider error-signal mappings')
unittest.main()
