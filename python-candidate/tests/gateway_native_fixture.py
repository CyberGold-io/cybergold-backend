"""Synthetic loopback broker: real HTTPX/Web3, concurrency and cancellation."""
import asyncio
import json
import sys
import time

from aiohttp import web
import httpx
from web3 import AsyncWeb3

from cybergold_candidate.gateway_lease import GatewayClient, GatewayLeaseError, restart_required
from cybergold_candidate.reconciliation_receipt import RpcCounter


async def main():
    fixture=json.load(sys.stdin)
    token='a'*43;revision='c'*64;hash='0x'+'b'*64
    expected={'reconciliationId':'fixture:1','expectedRuntimeRevision':revision,
        'expectedFinalizedAnchor':{'blockNumber':100,'blockHash':hash}}
    acquired={'kind':'cybergold-rpc-indexer-lease','formatVersion':1,'reconciliationId':'fixture:1',
        'configRevision':revision,'expiresInSeconds':60,'finalizedAnchor':{'number':100,'hash':hash},'leaseToken':'d'*43}
    state={'order':[],'dispatch':[],'active':0,'maximum':0,'gates':{},'calls':[],'headers':asyncio.Event(),
        'body':asyncio.Event(),'stall':asyncio.Event()}
    async def serve(request):
        body=await request.json();state['calls'].append(body)
        assert request.headers['Authorization']=='Bearer '+token
        if request.path.endswith('/leases'):
            assert body=={'kind':'cybergold-rpc-indexer-lease-acquire-request','formatVersion':2,
                'reconciliationId':'fixture:1','expectedRuntimeRevision':revision,
                'expectedFinalizedAnchor':{'number':100,'hash':hash}}
            return web.json_response(acquired)
        assert request.headers['X-CyberGold-RPC-Lease']=='d'*43
        assert request.headers['X-CyberGold-RPC-Reconciliation']=='fixture:1'
        if request.path.endswith('/release'):
            return web.json_response({'kind':'cybergold-rpc-indexer-lease-release','formatVersion':1,
                'reconciliationId':'fixture:1','released':True})
        params=body.get('params',[])
        if params and type(params[0]) is int:
            index=params[0];state['order'].append(index);state['active']+=1
            state['maximum']=max(state['maximum'],state['active']);gate=asyncio.Event();state['gates'][index]=gate
            await gate.wait();state['active']-=1
        if params and params[0]=='stall-headers':await state['stall'].wait()
        if params and params[0]=='body-after-headers':
            response=web.StreamResponse(headers={'Content-Type':'application/json'})
            await response.prepare(request);state['headers'].set();await state['body'].wait()
            await response.write(b'{"result":"0x1"}');await response.write_eof();return response
        result='0x'+'00'*32 if body['method']=='eth_call' else '0x1'
        return web.json_response({'jsonrpc':'2.0','id':body['id'],'result':result})
    application=web.Application();application.router.add_post('/rpc/indexer',serve)
    application.router.add_post('/rpc/indexer/leases',serve);application.router.add_post('/rpc/indexer/leases/release',serve)
    runner=web.AppRunner(application,shutdown_timeout=0);await runner.setup()
    listener=web.TCPSite(runner,'127.0.0.1',0);await listener.start()
    url='http://127.0.0.1:'+str(listener._server.sockets[0].getsockname()[1])+'/rpc/indexer'
    async def until(predicate):
        async with asyncio.timeout(5):
            while not predicate():await asyncio.sleep(0.001)
    async def dispatched(request):
        body=json.loads(request.content);params=body.get('params',[])
        if params and type(params[0]) is int:state['dispatch'].append(params[0])
    try:
        async with httpx.AsyncClient(event_hooks={'request':[dispatched]}) as http:
            now=1000;gateway=GatewayClient(url,token,http,lambda:now)
            lease=await gateway.acquire(expected);counter=RpcCounter()
            requests=[asyncio.create_task(lease.request('eth_chainId',[index],counter)) for index in range(9)]
            await until(lambda:len(state['gates'])==4)
            try:await lease.release()
            except GatewayLeaseError:busy=True
            else:raise AssertionError('Retained busy release changed')
            while len(state['order'])<9 or state['active']:
                for gate in state['gates'].values():gate.set()
                await asyncio.sleep(0.001)
            assert await asyncio.gather(*requests)==['0x1']*9
            await lease.release()
            concurrency={'maximum':state['maximum'],'order':state['dispatch'],'busyRelease':busy,'counts':counter.snapshot()}
            assert concurrency==fixture['concurrency'],concurrency

            # Real Web3 uses the acquired transport and keeps EIP-1898 unchanged.
            lease=await gateway.acquire(expected);counter=RpcCounter();web3=AsyncWeb3(lease.provider(counter))
            assert await web3.eth.chain_id==1
            # Use Web3's provider boundary for EIP-1898, as existing candidate
            # recovery does; its high-level eth.call formatter is not this wire contract.
            response=await web3.provider.make_request('eth_call',[{'to':'0x'+'a'*40},
                {'blockHash':hash,'requireCanonical':True}])
            assert response['result']=='0x'+'00'*32
            wire=state['calls'][-1];assert wire['params'][1]=={'blockHash':hash,'requireCanonical':True}
            assert counter.snapshot()['totalAttempts']==2
            await lease.release()

            # Cancel a queued caller without leaking the shared FIFO slot.
            lease=await gateway.acquire(expected);counter=RpcCounter();state.update(order=[],gates={},maximum=0)
            requests=[asyncio.create_task(lease.request('eth_chainId',[index],counter)) for index in range(4)]
            await until(lambda:len(state['gates'])==4)
            queued=asyncio.create_task(lease.request('eth_chainId',[99],counter));await until(lambda:lease._waiting==1)
            queued.cancel()
            try:await queued
            except asyncio.CancelledError:pass
            for gate in state['gates'].values():gate.set()
            await asyncio.gather(*requests)
            assert await lease.request('eth_chainId',[],counter)=='0x1' and 99 not in state['order']
            assert counter.snapshot()['totalAttempts']==6 and counter.snapshot()['failedAttempts']==1
            await lease.release()

            # Recheck expiry after a waiting request acquires its slot.
            lease=await gateway.acquire(expected);counter=RpcCounter();state.update(order=[],gates={},maximum=0)
            requests=[asyncio.create_task(lease.request('eth_chainId',[index],counter)) for index in range(4)]
            await until(lambda:len(state['gates'])==4)
            queued=asyncio.create_task(lease.request('eth_chainId',[99],counter));await until(lambda:lease._waiting==1)
            now=61000
            for gate in state['gates'].values():gate.set()
            await asyncio.gather(*requests)
            try:await queued
            except GatewayLeaseError:pass
            else:raise AssertionError('Expired queued request reached broker')
            assert 99 not in state['order'] and counter.snapshot()['failedAttempts']==1
            now=1000

            # Fetch headers, rather than complete body decoding, own the slot.
            lease=await gateway.acquire(expected);counter=RpcCounter()
            pending=asyncio.create_task(lease.request('eth_chainId',['body-after-headers'],counter))
            await state['headers'].wait();await until(lambda:lease._active==0)
            assert not pending.done();await lease.release();state['body'].set();assert await pending=='0x1'

            lease=await gateway.acquire(expected);counter=RpcCounter();start=time.monotonic()
            try:await lease.request('eth_chainId',['stall-headers'],counter)
            except GatewayLeaseError as failure:assert restart_required(failure)
            else:raise AssertionError('Retained 35-second fetch deadline changed')
            deadline=round(time.monotonic()-start,2);assert 34.5<=deadline<=37,deadline
            assert len([call for call in state['calls'] if call.get('params')==['stall-headers']])==1
            assert counter.snapshot()['failedAttempts']==1
            state['stall'].set()
        print(json.dumps({'result':'pass','nativeFourRequestConcurrencyMatchesNode':True,
            'nativeWeb3LeaseAndEip1898':True,'cancelledQueueSlotRecovered':True,
            'queuedExpiryNotForwarded':True,'headerSlotReleaseMatchesNode':True,
            'fetchDeadlineSeconds':deadline,'noImplicitRetry':True,'installedEndpointsOrDatabaseUsed':False}))
    finally:
        state['stall'].set();state['body'].set()
        for gate in state['gates'].values():gate.set()
        await runner.cleanup()


if __name__=='__main__':asyncio.run(main())
