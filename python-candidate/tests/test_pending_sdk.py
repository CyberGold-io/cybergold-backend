"""Private inert failure-observation controls; never reaches a chain provider."""
import asyncio
from copy import deepcopy
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate import rpc_diagnostics as diag
from cybergold_candidate.quote_budget import SearchStopped
from cybergold_candidate.quote_cache import IntentSharing
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.route_scheduler import schedule_routes
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.trade_observation import failure

SCRIPT='''import json,sys
pending={}
for line in sys.stdin:
 r=json.loads(line);i=r['id']; op=r.get('operation')
 if op=='cancel':
  pending.pop(i,None)
  if r.get('acknowledge'): print(json.dumps({'id':i,'cancelled':True}),flush=True)
 elif op=='resume':
  x=pending.pop(i)
  print(json.dumps({'id':i,'result':x.get('value')}),flush=True)
 elif r.get('continueState'):
  pending[i]=r
  print(json.dumps({'id':i,'stateRequest':[{'poolId':r['pools'][0]['id'],'wordPositions':[-1],'ticks':[-60]}]}),flush=True)
 else: print(json.dumps({'id':i,'result':r.get('value')}),flush=True)
'''

def payload(index=1, **changes):
    return {'operation':'simulateRoute','mode':'exactOut','value':{'amountIn':'1005','amountOut':'1000'},
            'pools':[{'id':'0x'+f'{index:040x}','protocol':'v3','address':'0x'+f'{index:040x}',
                      'bitmapWords':[],'ticks':[]}], **changes}

def observed(requests):
    return [{'id':r['poolId'],'bitmapWords':[{'wordPosition':w,'bitmap':'0'} for w in r['wordPositions']],
             'ticks':[]} for r in requests]

class PendingSdkTests(unittest.IsolatedAsyncioTestCase):
    def worker(self):
        w=SdkWorker([sys.executable,'-u','-c',SCRIPT])
        self.addAsyncCleanup(w.close)
        return w

    async def capture_wave(self, action):
        class Routes:
            @diag.route_work_scope
            async def get(self, request):
                return await action()
        @diag.quote_work_scope
        async def quote():
            diag.quote_phase('initial-search')
            try:
                return await Routes().get({'mode':'exact-out'})
            except BaseException as error:
                return error, diag.quote_failure_context(error), public_quote_error(error)
        return await quote()

    async def test_eight_required_state_sessions_freeze_before_scheduler_cleanup(self):
        worker=self.worker(); all_started=asyncio.Event(); release=asyncio.Event(); fills=[]
        async def fill(rows):
            fills.append(deepcopy(rows))
            if len(fills)==8: all_started.set()
            await release.wait()
            return observed(rows)
        async def feed():
            for i in range(1,9): yield i
        async def evaluate(_index, i):
            return await worker.request(payload(i),on_state=fill)
        async def action():
            scheduled=asyncio.create_task(all_started.wait())
            async def expire():
                await scheduled
                raise TimeoutError('synthetic cutoff')
            # Existing scheduler owns/cancels all eight SDK tasks. The completed
            # failing discovery is an ordinary source exception, not a new timer.
            return await schedule_routes(lambda _expanded:[feed()],evaluate,discover=expire)
        error, context, public=await self.capture_wave(action)
        self.assertIsInstance(error,TimeoutError)
        summary=context['pendingSdk']
        self.assertEqual(summary['count'],8)
        self.assertEqual(len(summary['rows']),8)
        self.assertEqual({r['poolId'] for r in summary['rows']},{payload(i)['pools'][0]['id'] for i in range(1,9)})
        self.assertTrue(all(r['state']=='required-read' and r['wordPositions']==[-1] and r['ticks']==[-60]
                            and r['stateWaits']==1 and r['emptyWords']==r['wordsReturned']==0 for r in summary['rows']))
        self.assertNotIn('pendingSdk',json.dumps(public))
        frozen=deepcopy(summary)
        self.assertEqual(await worker.request({'value':'after cancelled sessions'}),'after cancelled sessions')
        self.assertEqual(summary,frozen)
        self.assertEqual(worker.sequence,9)

    async def test_owner_cancel_during_required_read_freezes_before_session_removal(self):
        worker=self.worker(); started=asyncio.Event(); release=asyncio.Event()
        async def fill(rows):
            started.set(); await release.wait(); return observed(rows)
        async def action():
            owner=asyncio.current_task()
            async def cancel():
                await started.wait(); owner.cancel()
            task=asyncio.create_task(cancel())
            try: await worker.request(payload(),on_state=fill)
            finally: await task
        error,context,_=await self.capture_wave(action)
        self.assertIsInstance(error,asyncio.CancelledError)
        self.assertIn('pendingSdk',context)
        self.assertEqual(context['pendingSdk']['rows'][0]['state'],'required-read')
        self.assertEqual(await worker.request({'value':'clean'}),'clean')

    async def test_nonowner_cancel_does_not_freeze_later_owned_failure(self):
        worker=self.worker();started=asyncio.Event()
        async def fill(rows):
            started.set(); await asyncio.Event().wait()
        async def action():
            child=asyncio.create_task(worker.request(payload(),on_state=fill))
            await started.wait();child.cancel();await asyncio.gather(child,return_exceptions=True)
            raise TimeoutError('later owner failure')
        _,context,_=await self.capture_wave(action)
        self.assertNotIn('pendingSdk',context)

    async def test_background_and_other_quote_owner_are_excluded(self):
        worker=self.worker(); started=asyncio.Event(); release=asyncio.Event()
        async def fill(rows):
            started.set(); await release.wait(); return observed(rows)
        @diag.quote_work_scope
        async def foreign():
            class Route:
                @diag.route_work_scope
                async def get(self,r):return await worker.request(payload(99),on_state=fill)
            return await Route().get({'mode':'exact-out'})
        foreign_task=asyncio.create_task(foreign());await started.wait()
        async def action():
            with diag.quote_background():
                observer=diag.quote_sdk_session(payload(88));observer.call('missing',[{'poolId':payload(88)['pools'][0]['id'],'wordPositions':[2],'ticks':[]}])
            raise TimeoutError('owned error')
        try:
            _,context,_=await self.capture_wave(action)
            self.assertNotIn('pendingSdk',context)
        finally:
            release.set();await foreign_task

    async def test_resume_queue_reports_new_delta_without_scanning_prefix(self):
        worker=self.worker(); got=asyncio.Event(); allow=asyncio.Event()
        big=payload();big['pools'][0]['bitmapWords']=[{'wordPosition':i,'bitmap':'0'} for i in range(2,302)]
        async def fill(rows):
            got.set();await allow.wait();return observed(rows)
        async def action():
            child=asyncio.create_task(worker.request(big,on_state=fill));await got.wait()
            async with worker.lock:
                allow.set()
                # The bridge has computed its delta once it waits for this lock.
                for _ in range(20):
                    await asyncio.sleep(0)
                    wave=diag._quote_scope.get().wave
                    if next(iter(wave.sdk_sessions.values())).state=='resume-queued':break
                snapshot=diag._quote_scope.get().snapshot()
                self.assertEqual(snapshot['pendingSdk']['rows'][0]['wordsReturned'],1)
                self.assertEqual(snapshot['pendingSdk']['rows'][0]['emptyWords'],1)
                self.assertEqual(snapshot['pendingSdk']['rows'][0]['state'],'resume-queued')
                child.cancel();await asyncio.gather(child,return_exceptions=True)
            raise TimeoutError('after child cancellation')
        _,context,_=await self.capture_wave(action)
        self.assertNotIn('pendingSdk',context)

    async def test_failure_log_only_safe_projection_and_immutable_public_payload(self):
        private='private-url-secret-signed-calldata'
        error=TimeoutError(private)
        safe='0x'+'a'*40
        error.quote_diagnostics={'phase':'initial-search','qualified':False,'elapsedMs':1,'pendingSdk':{
            'count':1,'rows':[{'session':1,'mode':'exactOut','state':'required-read','poolId':'https://'+private,
            'poolAddress':safe,'protocol':'v3','wordPositions':[-1,True,private]+list(range(30)),
            'wordCount':33,'ticks':[-60],'tickCount':1,'stateWaits':2,'wordsReturned':1,'emptyWords':1,
            'payload':private,'authorization':private}],'private':private}}
        wire=public_quote_error(error); logs=[]
        req=SimpleNamespace(scope={'state':{'request_id':'11111111-1111-4111-8111-111111111111'}})
        with patch('cybergold_candidate.trade_observation.logging.getLogger') as logger:
            logger.return_value.error.side_effect=logs.append
            returned=failure(req,error,'/api/quotes/intent/stream')
        record=json.loads(logs[0]);row=record['pendingSdk']['rows'][0]
        self.assertNotIn('poolId',row);self.assertEqual(row['poolAddress'],safe)
        self.assertLessEqual(len(row['wordPositions']),16)
        self.assertNotIn(private,json.dumps(record));self.assertNotIn('pendingSdk',json.dumps(returned))
        self.assertEqual(public_quote_error(error),wire)
        record['pendingSdk']['rows'][0]['ticks'].append(1)
        self.assertEqual(diag.quote_failure_context(error)['pendingSdk']['rows'][0]['ticks'],[-60])

    async def test_row_list_bounds_and_safe_canonical_identity_fallback(self):
        async def action():
            sessions=[]
            for i in range(12):
                data=payload(i+1)
                data['pools'][0]['id']='v3:0x'+'1'*40+':0x'+'2'*40+':3000' if i==0 else 'unsafe/'+str(i)
                session=diag.quote_sdk_session(data)
                session.call('missing',[{'poolId':data['pools'][0]['id'],'wordPositions':list(range(50)),'ticks':list(range(50))}])
                sessions.append(session)
            error=TimeoutError();diag.freeze_quote_work(error)
            saved=diag.quote_failure_context(error)
            for session in sessions:session.call('close')
            return saved
        context=await self.capture_wave(action);summary=context['pendingSdk']
        self.assertEqual((summary['count'],len(summary['rows']),summary['omittedRows']),(12,8,4))
        row=summary['rows'][0]
        self.assertTrue(row['poolId'].startswith('v3:'))
        self.assertEqual((len(row['wordPositions']),row['wordCount'],row['wordsOmitted']),(16,50,34))

    async def test_caught_ordinary_callback_failure_keeps_wave_open_for_later_work(self):
        worker=self.worker();expected=OSError('synthetic required read failed')
        async def failed(rows):raise expected
        async def action():
            try:
                await worker.request(payload(1),on_state=failed)
            except OSError as error:
                self.assertIs(error,expected)
                current=diag._quote_scope.get()
                self.assertIsNone(current.frozen)
                self.assertIsNone(current.wave.frozen)
                self.assertEqual(current.wave.sdk_sessions,{})
            diag.route_count('typedCompleted')
            self.assertEqual(await worker.request(payload(2),on_state=lambda rows:asyncio.sleep(0,result=observed(rows))),
                             payload(2)['value'])
            self.assertEqual(diag._quote_scope.get().wave.counts['sdkRequests'],3)
            self.assertEqual(diag._quote_scope.get().wave.counts['typedCompleted'],1)
            raise TimeoutError('later terminal failure')
        error,context,public=await self.capture_wave(action)
        self.assertIsInstance(error,TimeoutError)
        self.assertNotIn('pendingSdk',context)
        self.assertEqual(public['quoteDiagnostics']['routeWave']['sdkRequests'],3)

    async def test_diagnostic_callback_failure_does_not_change_result_error_or_cleanup(self):
        worker=self.worker()
        async def action():
            with patch.object(diag._SdkSession,'missing',side_effect=ValueError('diagnostic only')):
                value=await worker.request(payload(),on_state=lambda rows:asyncio.sleep(0,result=observed(rows)))
                self.assertEqual(value,payload()['value'])
            expected=OSError('actual callback failure')
            async def failed(rows):raise expected
            with patch.object(diag._SdkSession,'observed',side_effect=ValueError('diagnostic only')):
                self.assertEqual(await worker.request(payload(),on_state=lambda rows:asyncio.sleep(0,result=observed(rows))),payload()['value'])
            observer=diag.quote_sdk_session(payload())
            with patch.object(diag._SdkSession,'snapshot',side_effect=ValueError('diagnostic only')):
                self.assertNotIn('pendingSdk',diag._quote_scope.get().snapshot())
                try:await worker.request(payload(),on_state=failed)
                except OSError as error:self.assertIs(error,expected)
            observer.call('close')
            self.assertEqual(diag._quote_scope.get().wave.sdk_sessions,{})
            return 'success'
        self.assertEqual(await self.capture_wave(action),'success')

    async def test_unified_provider_and_sharing_preserve_primary_log_context(self):
        from test_trade_quote import Engines, request
        from cybergold_candidate.quote_errors import QuoteFailure
        engines=Engines();engines.market_error=QuoteFailure('quote-no-route')
        @diag.quote_work_scope
        async def core_failed(value,publish,**options):
            class Routes:
                @diag.route_work_scope
                async def get(self,r):
                    observer=diag.quote_sdk_session(payload(5))
                    observer.call('missing',[{'poolId':payload(5)['pools'][0]['id'],'wordPositions':[-5],'ticks':[]}])
                    error=TimeoutError('synthetic Core tail')
                    diag.freeze_quote_work(error)
                    observer.call('close')
                    raise error
            return await Routes().get({'mode':'exact-out'})
        engines.core.get=core_failed
        frames=[]
        async def update(frame):frames.append(frame)
        with self.assertRaises(TimeoutError) as raised:
            await engines.quotes.get(request(native=True),update)
        context=diag.quote_failure_context(raised.exception)
        self.assertEqual(context['pendingSdk']['rows'][0]['wordPositions'],[-5])
        self.assertNotIn('pendingSdk',json.dumps(frames))
        self.assertNotIn('pendingSdk',json.dumps(public_quote_error(raised.exception)))
        self.assertEqual(engines.quotes.sharing.pending,{})

    async def test_shared_exception_has_separate_owner_context_and_bounded_transfer(self):
        error=TimeoutError('shared physical failure');barrier=asyncio.Event();count=0
        async def caller(identity):
            nonlocal count
            async def action():
                observer=diag.quote_sdk_session(payload(identity));observer.call('missing',[{'poolId':payload(identity)['pools'][0]['id'],'wordPositions':[-identity],'ticks':[]}])
                diag.freeze_quote_work(error)
                count+=1
                if count==2:barrier.set()
                await barrier.wait()
                observer.call('close')
                raise error
            return await self.capture_wave(action)
        first,second=await asyncio.gather(caller(1),caller(2))
        self.assertEqual(first[1]['pendingSdk']['rows'][0]['wordPositions'],[-1])
        self.assertEqual(second[1]['pendingSdk']['rows'][0]['wordPositions'],[-2])
        self.assertIsNone(diag.quote_failure_context(error))

    async def test_budget_intent_sharing_transfers_log_context_to_each_subscriber(self):
        started=asyncio.Event();release=asyncio.Event();calls=0
        class Producer:
            history=None
            routes=SimpleNamespace(rpc=object())
            @diag.quote_work_scope
            async def get(self,request,update,**options):
                nonlocal calls
                calls+=1
                class Routes:
                    @diag.route_work_scope
                    async def get(self,r):
                        observer=diag.quote_sdk_session(payload(7))
                        observer.call('missing',[{'poolId':payload(7)['pools'][0]['id'],'wordPositions':[-7],'ticks':[]}])
                        try:
                            started.set();await release.wait();raise SearchStopped()
                        except BaseException as error:
                            diag.freeze_quote_work(error);raise
                        finally:observer.call('close')
                return await Routes().get({'mode':'exact-out'})
        sharing=IntentSharing(Producer(),head=lambda:asyncio.sleep(0,result={'hash':'0x'+'a'*64}))
        async def subscriber():
            try:await sharing.get({'mode':'redeem-exact-out'},lambda frame:asyncio.sleep(0))
            except TimeoutError as error:return diag.quote_failure_context(error),public_quote_error(error)
        first=asyncio.create_task(subscriber());await started.wait()
        second=asyncio.create_task(subscriber())
        while sharing.joined<1:await asyncio.sleep(0)
        release.set();a,b=await asyncio.gather(first,second)
        self.assertEqual(calls,1);self.assertEqual(sharing.pending,{})
        self.assertIn('pendingSdk',a[0])
        self.assertIn('pendingSdk',b[0])
        self.assertEqual(a[0]['pendingSdk'],b[0]['pendingSdk'])
        self.assertEqual(a[0]['pendingSdk']['rows'][0]['wordPositions'],[-7])
        self.assertEqual(a[1]['code'],'quote-timeout');self.assertNotIn('pendingSdk',json.dumps(a[1]))
        a[0]['pendingSdk']['rows'][0]['wordPositions'].append(2)
        self.assertEqual(b[0]['pendingSdk']['rows'][0]['wordPositions'],[-7])

if __name__=='__main__':unittest.main()
