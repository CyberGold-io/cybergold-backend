"""Actual operation ownership and Helpers boundaries remain observational only."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from cybergold_candidate.economic_quotes import request_operation
from cybergold_candidate.quote_flow import Flow, flow_scope
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.quoter.plan_transport import simulation_scope
from cybergold_candidate.quoter.bootstrap import RouteBootstrap
from test_quoter_plan_simulation import fixture, market, encoded, measured, stage, WETH, CORE


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


def rows(flow):
    return {(row['stage'],row['kind']):row for row in flow.snapshot()['stages']}


class QuoteFlowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_close_waits_for_owned_cancellation_before_measuring_memo_cpu(self):
        clock, cpu = [0.0], [0.0]
        flow = Flow('/api/economic-quotes/stream', clock=lambda:clock[0], cpu_clock=lambda:cpu[0])
        bank = SharedReads()
        entered, settling, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Memo(dict):
            def clear(self):
                clock[0] += .25
                cpu[0] += .125
                super().clear()
        bank.completed = Memo({'ready':'retained-value'})
        async def produce():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                clock[0], cpu[0] = 1.0, 1.0
                settling.set()
                await release.wait()
        reader = closer = None
        try:
            with flow_scope(flow):
                reader = asyncio.create_task(bank.one('held-read', produce))
                await until(entered.is_set)
                closer = asyncio.create_task(bank.close())
            await until(settling.is_set)
            snapshot = rows(flow)
            self.assertEqual(snapshot['sharing.settle','await']['inFlight'],1)
            self.assertNotIn(('sharing.clear','cpu'),snapshot)
            self.assertFalse(closer.done(),'close still owns the cancelled physical read')
            clock[0] = 3.0
            release.set()
            await closer
            with self.assertRaises(asyncio.CancelledError):await reader
            snapshot = rows(flow)
            self.assertEqual(snapshot['sharing.settle','await']['summedWallMs'],3000)
            self.assertEqual(snapshot['sharing.settle','await']['summedCpuMs'],0)
            self.assertEqual(snapshot['sharing.clear','cpu']['summedWallMs'],250)
            self.assertEqual(snapshot['sharing.clear','cpu']['summedCpuMs'],125)
            self.assertEqual((bank.pending,bank.groups,bank.completed),({},{},{}))
            self.assertTrue(all(row['inFlight']==0 for row in snapshot.values()))
        finally:
            release.set()
            for task in (reader,closer):
                if task is not None and not task.done():task.cancel()
            await asyncio.gather(*(task for task in (reader,closer)if task is not None),return_exceptions=True)
            await bank.close()

    async def test_bootstrap_cancellation_keeps_owner_provider_and_close_drains_in_order(self):
        clock, cpu, trace = [0.0], [0.0], []
        flow = Flow('/api/economic-quotes/stream', clock=lambda:clock[0], cpu_clock=lambda:cpu[0])
        ordinary_started, provider_started = asyncio.Event(), asyncio.Event()
        owner_settling, provider_settling, provider_closing = asyncio.Event(), asyncio.Event(), asyncio.Event()
        owner_release, provider_release, close_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Provider:
            name = 'controlled-provider'
            async def discover(self,*_args):
                provider_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    trace.append('provider-settle')
                    provider_settling.set()
                    await provider_release.wait()
            async def close(self):
                trace.append('provider-close')
                provider_closing.set()
                await close_release.wait()
        async def ordinary():
            ordinary_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                trace.append('owner-settle')
                owner_settling.set()
                await owner_release.wait()
        async def reevaluate():pass
        bootstrap, task = None, None
        try:
            with flow_scope(flow):
                bootstrap = RouteBootstrap([Provider()])
                clear = bootstrap.topology.clear
                def clear_topology():
                    trace.append('topology-clear')
                    clock[0] += .25
                    cpu[0] += .125
                    clear()
                with patch.object(bootstrap.topology,'clear',side_effect=clear_topology):
                    bootstrap.offers(WETH,CORE,100,{})
                    task = asyncio.create_task(bootstrap.run(ordinary(),reevaluate))
                    await until(ordinary_started.is_set)
                    await until(provider_started.is_set)
                    clock[0] = 1.0
                    task.cancel()
                    await until(owner_settling.is_set)
                    self.assertEqual(rows(flow)['discovery.owners.settle','await']['inFlight'],1)
                    self.assertFalse(provider_settling.is_set())
                    clock[0] = 2.0
                    owner_release.set()
                    await until(provider_settling.is_set)
                    self.assertEqual(rows(flow)['discovery.providers.settle','await']['inFlight'],1)
                    self.assertFalse(provider_closing.is_set())
                    clock[0] = 3.0
                    provider_release.set()
                    await until(provider_closing.is_set)
                    self.assertEqual(rows(flow)['discovery.providers.close','await']['inFlight'],1)
                    self.assertFalse(task.done(),'caller cancellation still owns provider close')
                    clock[0] = 4.0
                    close_release.set()
                    with self.assertRaises(asyncio.CancelledError):await task
            snapshot = rows(flow)
            for name in ('discovery.owners.settle','discovery.providers.settle','discovery.providers.close'):
                self.assertEqual(snapshot[name,'await']['summedWallMs'],1000)
                self.assertEqual(snapshot[name,'await']['summedCpuMs'],0)
            self.assertEqual(snapshot['discovery.clear','cpu']['summedWallMs'],250)
            self.assertEqual(snapshot['discovery.clear','cpu']['summedCpuMs'],125)
            self.assertEqual(trace,['owner-settle','provider-settle','provider-close','topology-clear'])
            self.assertTrue(all(task.done() for task in bootstrap._tasks))
            self.assertTrue(all(row['inFlight']==0 for row in snapshot.values()))
        finally:
            owner_release.set();provider_release.set();close_release.set()
            if task is not None and not task.done():task.cancel()
            if task is not None:await asyncio.gather(task,return_exceptions=True)
            if bootstrap is not None:await bootstrap.close()

    async def test_result_ready_closes_before_held_receive_cleanup_and_preserves_result(self):
        clock = [0.0]
        flow = Flow('/api/economic-estimates',clock=lambda:clock[0],cpu_clock=lambda:0)
        receiving,cleanup_entered,cleanup_release = asyncio.Event(),asyncio.Event(),asyncio.Event()
        value = {'estimate':{'amount':'123'}}
        class Request:
            async def receive(self):
                receiving.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    clock[0] = 2.0
                    cleanup_entered.set()
                    await cleanup_release.wait()
        async def execute():
            await receiving.wait()
            clock[0] = 1.0
            return value
        with flow_scope(flow):
            task = asyncio.create_task(request_operation(Request(),execute))
        try:
            await asyncio.wait_for(cleanup_entered.wait(),2)
            snapshot = rows(flow)
            waited = snapshot['http.await_result','queue']
            cleanup = snapshot['http.cleanup','await']
            self.assertEqual((waited['completed'],waited['inFlight'],waited['readyMarkers']),(1,0,1))
            self.assertEqual(waited['summedWallMs'],1000)
            self.assertEqual(waited['summedReadyWaitMs'],1000)
            self.assertEqual(waited['summedResumeDelayMs'],0)
            self.assertEqual((cleanup['started'],cleanup['inFlight']),(1,1))
            self.assertEqual(cleanup['activePeriodMs'],1000)
            self.assertFalse(task.done(),'completed domain result still owns receive-watcher cleanup')
            clock[0] = 3.0
            cleanup_release.set()
            self.assertIs(await task,value)
            self.assertEqual(rows(flow)['http.cleanup','await']['summedWallMs'],2000)
            self.assertEqual(rows(flow)['http.await_result','queue']['summedWallMs'],1000)
            self.assertTrue(all(row['summedCpuMs']==0 for row in rows(flow).values()))
        finally:
            cleanup_release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)

    async def shared_read_case(self, *, broken_observer=False, cancel_subscriber=False):
        bank = SharedReads()
        owner = Flow('/api/economic-quotes/stream')
        subscriber = Flow('/api/economic-quotes/stream')
        started,release = asyncio.Event(),asyncio.Event()
        calls = []
        async def produce():
            calls.append('physical-read')
            started.set()
            await release.wait()
            return {'result':'same-owned-result'}
        first = second = None
        try:
            with flow_scope(owner):
                first = asyncio.create_task(bank.one('read-key',produce))
            await started.wait()
            with patch.object(subscriber,'link',side_effect=RuntimeError('observer failed')) if broken_observer else nullcontext():
                with flow_scope(subscriber):
                    second = asyncio.create_task(bank.one('read-key',produce))
                await until(lambda:second.done() or bank.pending['read-key'].users==2)
                if cancel_subscriber:
                    links = subscriber.snapshot()['sharedOwners']
                    self.assertEqual(links,[{'flowId':owner.flow_id,'relation':'shared-read','subscriptions':1}])
                    second.cancel()
                    with self.assertRaises(asyncio.CancelledError):await second
                    self.assertFalse(first.done())
                    self.assertEqual(bank.pending['read-key'].users,1)
                    release.set()
                    self.assertEqual(await first,{'result':'same-owned-result'})
                else:
                    release.set()
                    self.assertEqual(await asyncio.gather(first,second),
                                     [{'result':'same-owned-result'},{'result':'same-owned-result'}])
            self.assertEqual(calls,['physical-read'])
            self.assertEqual(bank.pending,{})
        finally:
            release.set()
            for task in (first,second):
                if task is not None and not task.done():task.cancel()
            await asyncio.gather(*(task for task in (first,second)if task is not None),return_exceptions=True)
            await bank.close()

    async def test_coalesced_subscriber_links_issuing_flow_without_owning_its_cancellation(self):
        await self.shared_read_case(cancel_subscriber=True)

    async def test_shared_owner_link_failure_does_not_change_read_or_coalescing(self):
        await self.shared_read_case(broken_observer=True)

    async def test_cancelled_originator_emits_once_after_shared_read_finishes_for_surviving_subscriber(self):
        clock = [0.0]
        records, measured = [], []
        owner = Flow('/api/economic-quotes/stream', request_id='originator', clock=lambda: clock[0],
                     sink=records.append, metrics=SimpleNamespace(observe_quote_flow=measured.append))
        subscriber = Flow('/api/economic-quotes/stream', request_id='subscriber', clock=lambda: clock[0])
        bank = SharedReads()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def produce():
            from cybergold_candidate.quote_flow import stage
            with stage('rpc.http'):
                calls.append('physical-read')
                entered.set()
                await release.wait()
                return {'result': 'surviving-subscriber-value'}
        first = second = None
        try:
            with flow_scope(owner):
                first = asyncio.create_task(bank.one('read-key', produce))
            await entered.wait()
            with flow_scope(subscriber):
                second = asyncio.create_task(bank.one('read-key', produce))
            await until(lambda: bank.pending['read-key'].users == 2)
            clock[0] = 1.0
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            owner.finish('cancelled')
            self.assertFalse(second.done(), 'diagnostic retention must not cancel the surviving read')
            self.assertEqual((records, measured), ([], []))
            self.assertEqual(owner.shared_producers, 1)
            clock[0] = 3.0
            release.set()
            self.assertEqual(await second, {'result': 'surviving-subscriber-value'})
            await until(lambda: len(records) == 1)
            self.assertEqual(calls, ['physical-read'])
            self.assertEqual(owner.shared_producers, 0)
            record = records[0]
            self.assertEqual((record['outcome'], record['elapsedMs'], record['ownedWorkElapsedMs']),
                             ('cancelled', 1000, 3000))
            physical = next(row for row in record['stages'] if row['stage'] == 'rpc.http')
            self.assertEqual((physical['completed'], physical['inFlight'], physical['summedWallMs']), (1, 0, 3000))
            self.assertEqual(measured, [record], 'one complete metric observation, without partial/double counts')
            self.assertEqual(subscriber.snapshot()['sharedOwners'],
                             [{'flowId': owner.flow_id, 'relation': 'shared-read', 'subscriptions': 1}])
            owner.finish('succeeded')
            self.assertEqual(len(records), 1)
            self.assertEqual(len(measured), 1)
        finally:
            release.set()
            for task in (first, second):
                if task is not None and not task.done(): task.cancel()
            await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)
            await bank.close()

    async def test_two_key_shared_batch_retains_one_physical_producer_and_one_terminal_record(self):
        clock, records = [0.0], []
        flow = Flow('/api/economic-quotes/stream', clock=lambda: clock[0], sink=records.append)
        bank, entered, release = SharedReads(), asyncio.Event(), asyncio.Event()
        calls = []
        async def produce(keys):
            calls.append(keys)
            entered.set()
            await release.wait()
            return [{'result': key} for key in keys]
        task = None
        try:
            with flow_scope(flow):
                task = asyncio.create_task(bank.many(['first-key', 'second-key'], produce))
            await entered.wait()
            self.assertEqual(flow.shared_producers, 1, 'retain the batch task rather than each key')
            clock[0] = 0.5
            flow.finish('succeeded')
            self.assertEqual(records, [])
            clock[0] = 1.5
            release.set()
            values, counts = await task
            await until(lambda: len(records) == 1)
            self.assertEqual(values, [{'result': 'first-key'}, {'result': 'second-key'}])
            self.assertEqual(counts['issued'], 2)
            self.assertEqual(calls, [['first-key', 'second-key']])
            self.assertEqual(flow.shared_producers, 0)
            self.assertEqual((records[0]['elapsedMs'], records[0]['ownedWorkElapsedMs']), (500, 1500))
        finally:
            release.set()
            if task is not None and not task.done(): task.cancel()
            if task is not None: await asyncio.gather(task, return_exceptions=True)
            await bank.close()

    async def test_cancelled_before_first_producer_turn_releases_diagnostic_retention(self):
        records, clock = [], [0.0]
        flow = Flow('/api/economic-quotes/stream', clock=lambda: clock[0], sink=records.append)
        bank, ran = SharedReads(), []
        original_create = asyncio.create_task
        def cancelled_before_start(coroutine):
            task = original_create(coroutine)
            task.cancel()
            clock[0] = 1.0
            # FIFO callback order requests finish after retention, before the
            # cancelled task's done callback releases it. No producer body runs.
            asyncio.get_running_loop().call_soon(flow.finish, 'cancelled')
            return task
        async def produce():
            ran.append(True)
            return {'result': 'must-not-run'}
        try:
            with flow_scope(flow), patch('cybergold_candidate.shared_reads.asyncio.create_task',
                                         side_effect=cancelled_before_start):
                with self.assertRaises(asyncio.CancelledError):
                    await bank.one('read-key', produce)
            await until(lambda: len(records) == 1)
            self.assertEqual(ran, [])
            self.assertEqual((flow.shared_producers, bank.pending, bank.groups), (0, {}, {}))
            self.assertEqual((records[0]['outcome'], records[0]['elapsedMs']), ('cancelled', 1000))
            self.assertEqual(records[0]['stages'], [])
        finally:
            await bank.close()

    async def test_selected_preparation_trace_has_one_latest_call_and_separate_cpu_boundaries(self):
        request,plan = market()
        _,quoter,rpc,provider = fixture(encoded(measured(200,stages=[stage(0,WETH,CORE,10000,200)])))
        flow = Flow('/api/tx-preparations')
        try:
            with flow_scope(flow):
                value = await quoter.evaluate_selected(request,plan,minimum=1)
            snapshot = rows(flow)
            for name in ('plan.compile','observation.project'):
                self.assertEqual(snapshot[name,'cpu']['completed'],1)
            for name,kind in [('helpers.permit','queue'),('helpers.rpc','await')]:
                self.assertEqual(snapshot[name,kind]['completed'],1)
                self.assertEqual(snapshot[name,kind]['summedCpuMs'],0)
            self.assertNotIn(('helpers.shared','await'),snapshot)
            self.assertEqual(value['quotedOutput'],'200')
            self.assertEqual(len(provider.calls),1)
            self.assertEqual(provider.calls[0][0],'eth_call')
            self.assertEqual(provider.calls[0][1][1],'latest')
            self.assertEqual(rpc.heads,[])
            quoter.engine.quote_sdk_branches.assert_not_called()
            self.assertEqual(quoter.engine.semaphore._value,8)
        finally:
            await quoter.close()

    async def test_helpers_sharing_stays_one_physical_call_with_two_logical_observations(self):
        request,plan = market()
        _,quoter,rpc,provider = fixture(encoded(measured(200,stages=[stage(0,WETH,CORE,10000,200)])))
        provider.release = asyncio.Event()
        flow = Flow('/api/economic-quotes/stream')
        first = second = None
        try:
            with flow_scope(flow):
                async with simulation_scope():
                    first = asyncio.create_task(quoter.plan_simulator(request,plan))
                    await provider.entered.wait()
                    second = asyncio.create_task(quoter.plan_simulator(request,plan))
                    await asyncio.sleep(0)
                    await asyncio.sleep(0)
                    provider.release.set()
                    values = await asyncio.gather(first,second)
            self.assertEqual([value['pricingEvidence']['rpcCalls']for value in values],[1,0])
            self.assertEqual([value['pricingEvidence']['coalesced']for value in values],[0,1])
            self.assertEqual(values[0]['quotedOutput'],values[1]['quotedOutput'])
            self.assertEqual(len(provider.calls),1)
            snapshot = rows(flow)
            self.assertEqual(snapshot['helpers.shared','await']['completed'],2)
            self.assertEqual(snapshot['helpers.rpc','await']['completed'],1)
            self.assertEqual(snapshot['plan.compile','cpu']['completed'],2)
            self.assertEqual(quoter.engine.semaphore._value,8)
        finally:
            provider.release.set()
            for task in (first,second):
                if task is not None and not task.done():task.cancel()
            await asyncio.gather(*(task for task in (first,second)if task is not None),return_exceptions=True)
            await quoter.close()


if __name__=='__main__':unittest.main()
