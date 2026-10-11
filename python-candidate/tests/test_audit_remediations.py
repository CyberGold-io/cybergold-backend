"""Failure, cancellation and resource regressions from the October backend audit."""
import asyncio
from contextlib import asynccontextmanager
import unittest
from unittest.mock import patch

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.authoritative_pool_cache import AuthoritativePoolCache
from cybergold_candidate.environment import load_environment
from cybergold_candidate.permit2_context import Permit2Context
from cybergold_candidate.pool_producer import PoolProducer
from cybergold_candidate.safe_status import SafeEventInputError
from cybergold_candidate.supplier_dispatch import dispatch, SUPPLIER_CONCURRENCY
from cybergold_candidate import worker_engine

ADDRESS='0x'+'1'*40
HASH='0x'+'a'*64


class ResourceRegression(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_preserves_all_inputs_and_order_with_bounded_work(self):
        active=peak=0
        async def supplier(value):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            try:
                await asyncio.sleep(0)
                return value*2
            finally:active-=1
        self.assertEqual(await dispatch(range(1024),supplier),[i*2 for i in range(1024)])
        self.assertEqual(peak,SUPPLIER_CONCURRENCY)
        self.assertEqual(active,0)
        self.assertEqual(await dispatch([],supplier),[])

    async def test_supplier_failure_and_cancellation_leave_no_sibling_work(self):
        for fail in (True,False):
            started=asyncio.Event();active=0
            async def supplier(value):
                nonlocal active
                active+=1;started.set()
                try:
                    if fail and value==0:
                        await asyncio.sleep(0)
                        raise ValueError('synthetic supplier failure')
                    await asyncio.Event().wait()
                finally:active-=1
            task=asyncio.create_task(dispatch(range(1024),supplier))
            await started.wait()
            if not fail:task.cancel()
            with self.assertRaises(ValueError if fail else asyncio.CancelledError):await task
            self.assertEqual(active,0)

    async def test_duplicate_allowances_use_one_read_preserving_response_multiplicity(self):
        class Rpc:
            chain_id,helpers=1,ADDRESS
            calls=0
            async def block(self):return {'hash':HASH,'number':10,'timestamp':20}
            async def assert_canonical(self,_block):pass
            async def permit2_read(self,_address,name,_args,_block):
                if name=='permit2':return ADDRESS
                self.calls+=1
                return 2**255
        rpc=Rpc()
        result=await Permit2Context(None,rpc).get({'mode':'allowances','owner':ADDRESS,'tokens':[ADDRESS]*1024})
        self.assertEqual(rpc.calls,1)
        self.assertEqual(result['result']['allowances'],[{'token':ADDRESS,'value':str(2**255)}]*1024)

    async def test_distinct_pool_identifiers_are_all_observed_in_bounded_waves(self):
        class Producer:
            calls=active=peak=0
            async def get(self,identifier):
                self.calls+=1;self.active+=1;self.peak=max(self.peak,self.active)
                try:
                    await asyncio.sleep(0)
                    return identifier['fee']
                finally:self.active-=1
        producer=Producer()
        entries=[{'tokenA':ADDRESS,'tokenB':'0x'+'2'*40,'fee':fee} for fee in range(1024)]
        self.assertEqual(await AuthoritativePoolCache(None,producer).refresh(entries),list(range(1024)))
        self.assertEqual((producer.calls,producer.peak,producer.active),(1024,SUPPLIER_CONCURRENCY,0))

    async def test_pool_read_failure_drains_actual_producer_siblings_then_recovers(self):
        class Rpc:
            factory=ADDRESS
            active=0
            fail=True
            async def block(self,_number):return {'hash':HASH,'number':10,'timestamp':20}
            async def assert_canonical(self,_block):pass
            async def read(self,_group,_address,name,_block,_args=()):
                if name=='getPool':return '0x'+'3'*40
                self.active+=1
                try:
                    if self.fail:
                        if name=='slot0':
                            await asyncio.sleep(0)
                            raise ValueError('synthetic pool read failure')
                        await asyncio.Event().wait()
                    return (2**200,1) if name=='slot0' else 2**255
                finally:self.active-=1
        rpc=Rpc()
        settings=load_environment({'NEXT_PUBLIC_CHAIN_ID':'1','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS':ADDRESS,
            'NEXT_PUBLIC_RPC_URL':'http://fixture.invalid'})
        producer=PoolProducer(settings,rpc=rpc)
        identifier={'tokenA':ADDRESS,'tokenB':'0x'+'2'*40,'fee':500}
        with self.assertRaises(ValueError):await producer.get(identifier)
        self.assertEqual(rpc.active,0)
        rpc.fail=False
        result=await producer.get(identifier)
        self.assertEqual(result['activeLiquidityRaw'],str(2**255))
        self.assertEqual(result['sqrtPriceX96Raw'],str(2**200))
        self.assertEqual(rpc.active,0)


class SafeErrorsRegression(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_value_and_database_errors_are_redacted(self):
        for failure in (ValueError('private supplier detail'),RuntimeError('private database detail')):
            class Service:
                async def get(self,*_args):raise failure
            app=create_app(safe_status=Service())
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as api:
                with self.assertLogs('cybergold.candidate',level='ERROR') as logs:
                    response=await api.post('/api/safe/events',json={'safeAddress':ADDRESS,'safeTxHashes':[HASH]})
            self.assertEqual(response.status_code,500)
            self.assertEqual(response.json()['error'],'Safe event observations are temporarily unavailable.')
            self.assertIn('correlationId',response.json())
            self.assertNotIn('private',response.text)
            self.assertNotIn('private',''.join(logs.output))

    async def test_fixed_validation_error_contract_is_preserved(self):
        class Service:
            async def get(self,*_args):raise SafeEventInputError('Invalid Safe address.')
        app=create_app(safe_status=Service())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as api:
            response=await api.post('/api/safe/events',json={'safeAddress':'invalid','safeTxHashes':[HASH]})
        self.assertEqual((response.status_code,response.json()),(500,{'error':'Invalid Safe address.'}))


class WorkerCancellationRegression(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_caller_cancellation_retains_lock_through_helpers_and_close(self):
        shared={'locked':False,'active':0,'peak':0,'closed':False}
        started,release,helpers_started,helpers_release=(asyncio.Event() for _ in range(4))
        class Database:
            async def ensure_schema(self):pass
            @asynccontextmanager
            async def advisory_lock(self,_key):
                acquired=not shared['locked']
                if acquired:shared['locked']=True
                try:yield acquired
                finally:
                    if acquired:shared['locked']=False
            async def close(self):shared['closed']=True
        class Rpc:
            async def close(self):pass
        class Collector:
            def __init__(self,*_args):pass
            async def reconcile(self,*_args,**_kwargs):
                shared['active']+=1;shared['peak']=max(shared['peak'],shared['active'])
                try:
                    started.set();await release.wait()
                    return {'completed':False,'dashboardHistoryProgress':None,'finalizedAnchor':None}
                finally:shared['active']-=1
        settings=load_environment({'DATABASE_URL':'postgresql://fixture.invalid/db','NEXT_PUBLIC_RPC_URL':'http://fixture.invalid',
            'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS':ADDRESS,'NEXT_PUBLIC_CHAIN_ID':'1'})
        with patch.object(worker_engine,'CoreCollector',Collector):
            first=worker_engine.WorkerEngine(Database(),settings,rpc_factory=lambda *_args:Rpc())
            second=worker_engine.WorkerEngine(Database(),settings,rpc_factory=lambda *_args:Rpc())
            async def helpers(_anchor):helpers_started.set();await helpers_release.wait()
            first.collect_helpers=helpers
            caller=asyncio.create_task(first.run_once())
            await started.wait();caller.cancel();caller.cancel()
            with self.assertRaises(asyncio.CancelledError):await caller
            self.assertTrue(shared['locked'])
            self.assertEqual((await second.run_once())['status'],'busy')
            close=asyncio.create_task(first.close())
            await asyncio.sleep(0)
            self.assertFalse(close.done())
            close.cancel()
            with self.assertRaises(asyncio.CancelledError):await close
            self.assertTrue(shared['locked'])
            self.assertEqual((await second.run_once())['status'],'busy')
            close=asyncio.create_task(first.close())
            await asyncio.sleep(0)
            release.set();await helpers_started.wait()
            self.assertTrue(shared['locked'])
            self.assertEqual((await second.run_once())['status'],'busy')
            helpers_release.set();await close
            self.assertFalse(shared['locked'])
            self.assertEqual(shared['peak'],1)
            self.assertTrue(shared['closed'])
            await second.close()


if __name__=='__main__':unittest.main()
