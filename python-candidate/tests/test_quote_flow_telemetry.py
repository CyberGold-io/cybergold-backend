"""Flow diagnostics remain bounded and independent of product HTTP and loop CPU."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import unittest

from cybergold_candidate.app import create_app
from cybergold_candidate.quote_flow import Flow, current_flow, stage
from cybergold_candidate.quote_flow_monitor import LoopMonitor
from cybergold_candidate.telemetry import Metrics, TelemetryMiddleware


PATH = '/api/economic-estimates'


def samples(metric, suffix):
    return [sample for family in metric.collect() for sample in family.samples if sample.name.endswith(suffix)]


async def invoke(app, metrics, *, path=PATH):
    sent = []
    scope = {'type':'http','path':path,'method':'POST','headers':[],
             'route':SimpleNamespace(path=path)}
    async def receive():
        await asyncio.Event().wait()
    async def send(message):
        sent.append(deepcopy(message))
    await TelemetryMiddleware(app, metrics, 'api', release='a'*40)(scope,receive,send)
    return scope,sent


class FlowTelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_flow_preserves_response_and_existing_headers(self):
        metrics = Metrics()
        async def app(scope,receive,send):
            flow = current_flow()
            self.assertEqual(flow.request_id,scope['state']['request_id'])
            with stage('http.parse',kind='cpu'):
                value = b'ordinary response'
            await send({'type':'http.response.start','status':503,
                        'headers':[(b'server-timing',b'existing;dur=1')]})
            await send({'type':'http.response.body','body':value})
        scope,sent = await invoke(app,metrics)
        self.assertEqual(sent[0]['status'],503)
        self.assertEqual(sent[1]['body'],b'ordinary response')
        self.assertIn((b'x-cybergold-request-id',scope['state']['request_id'].encode()),sent[0]['headers'])
        timings = [value for key,value in sent[0]['headers'] if key==b'server-timing']
        self.assertEqual(timings[0],b'existing;dur=1')
        self.assertIn(b'cg_backend_headers;dur=',timings[1])
        self.assertIsNone(current_flow())
        values = samples(metrics.flow_stage_calls,'_total')
        self.assertTrue(any(row.labels['stage']=='http.parse' and row.labels['outcome']=='completed'
                            and row.value==1 for row in values))
        self.assertTrue(any(row.labels['outcome']=='failed' and row.value==1
                            for row in samples(metrics.flow_duration,'_count')))

    async def test_flow_constructor_failure_cannot_replace_product_response(self):
        metrics = Metrics()
        async def app(scope,receive,send):
            self.assertIsNone(current_flow())
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'ok'})
        with patch('cybergold_candidate.telemetry.Flow',side_effect=RuntimeError('observer unavailable')):
            _,sent = await invoke(app,metrics)
        self.assertEqual(sent[0]['status'],200)
        self.assertEqual(sent[1]['body'],b'ok')

    async def test_flow_header_and_emission_failure_preserve_product_error(self):
        metrics = Metrics()
        async def app(scope,receive,send):
            await send({'type':'http.response.start','status':503,'headers':[]})
            await send({'type':'http.response.body','body':b'ordinary failure'})
        with patch.object(Flow,'server_timing',side_effect=ValueError('timing failed')), \
                patch.object(Flow,'finish',side_effect=RuntimeError('sink failed')):
            _,sent = await invoke(app,metrics)
        self.assertEqual(sent[0]['status'],503)
        self.assertEqual(sent[1]['body'],b'ordinary failure')

    async def test_unhandled_product_failure_keeps_its_original_exception(self):
        metrics = Metrics()
        error = RuntimeError('product error')
        async def app(*_args):
            with stage('http.operation',kind='await'):
                raise error
        with self.assertRaises(RuntimeError) as caught:
            await invoke(app,metrics)
        self.assertIs(caught.exception,error)
        self.assertTrue(any(row.labels['outcome']=='failed' and row.value==1
                            for row in samples(metrics.flow_stage_calls,'_total')))

    async def test_cancellation_is_observed_without_becoming_an_error_response(self):
        metrics = Metrics()
        entered = asyncio.Event()
        async def app(*_args):
            with stage('http.operation',kind='await'):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(invoke(app,metrics))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(any(row.labels['outcome']=='cancelled' and row.value==1
                            for row in samples(metrics.flow_stage_calls,'_total')))
        self.assertTrue(any(row.labels['outcome']=='cancelled' and row.value==1
                            for row in samples(metrics.flow_duration,'_count')))

    async def test_projection_bounds_labels_and_never_assigns_await_cpu(self):
        metrics = Metrics()
        metrics.observe_quote_flow({'operation':'/private-address-123','flowKind':'user-selected-kind',
            'requestId':'private-request-value','flowId':'private-flow-value','elapsedMs':500,
            'outcome':'succeeded','stages':[
                {'stage':'private-stage-value','kind':'await','started':1,'completed':1,
                 'summedWallMs':400,'summedCpuMs':9000},
                {'stage':'helpers.permit','kind':'queue','started':1,'cancelled':1,
                 'summedWallMs':100,'summedReadyWaitMs':70,'summedResumeDelayMs':30,'readyMarkers':1},
                {'stage':'publication.queue','kind':'queue','started':1,'completed':1,
                 'summedWallMs':50,'summedReadyWaitMs':0,'summedResumeDelayMs':0,'readyMarkers':0},
                {'stage':'http.encode','kind':'cpu','started':1,'completed':1,
                 'summedWallMs':10,'summedCpuMs':8}]})
        text = metrics.render().decode()
        for value in ('private-address-123','private-request-value','private-flow-value','private-stage-value',
                      'user-selected-kind'):
            self.assertNotIn(value,text)
        cpu = samples(metrics.flow_stage_cpu,'_total')
        self.assertEqual(len(cpu),1)
        self.assertEqual((cpu[0].labels['kind'],cpu[0].value),('cpu',0.008))
        ready = samples(metrics.flow_queue_ready,'_total')
        resumed = samples(metrics.flow_queue_resume,'_total')
        self.assertEqual(len(ready),1,'an absent grant marker is not a measured zero queue wait')
        self.assertEqual((ready[0].value,resumed[0].value),(0.07,0.03))
        self.assertEqual(ready[0].labels['flow_kind'],'other')
        markers={row.labels['stage']:row.value for row in samples(metrics.flow_queue_markers,'_total')}
        self.assertEqual(markers,{'helpers.permit':1,'publication.queue':0})


class LoopMonitorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Exercise observer callbacks without installing one in the interpreter
        # or triggering a real collection or GC policy change.
        self.gc = SimpleNamespace(callbacks=[])
        self.gc_clocks = [0, 0]
        for name, value in (
                ('gc', self.gc),
                ('time', SimpleNamespace(monotonic_ns=lambda:self.gc_clocks[0],
                                         process_time_ns=lambda:self.gc_clocks[1]))):
            replacement = patch('cybergold_candidate.quote_flow_monitor.'+name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def phase(self, callback, phase, generation, wall_ns, cpu_ns):
        self.gc_clocks[:] = wall_ns, cpu_ns
        callback(phase, {'generation':generation, 'collected':'private-object-value',
                         'uncollectable':object()})

    async def test_gc_callback_lifecycle_preserves_foreign_identity_and_original_start_error(self):
        class EqualForeignCallback:
            def __call__(self, *_args): pass
            def __eq__(self, _other): return True

        foreign = EqualForeignCallback()
        self.gc.callbacks.append(foreign)
        entered = asyncio.Event()
        async def sleep(_delay):
            entered.set()
            await asyncio.Event().wait()
        monitor = LoopMonitor(Metrics(), sleep=sleep)
        self.addAsyncCleanup(monitor.close)
        monitor.start()
        task = monitor.task
        callback = self.gc.callbacks[-1]
        monitor.start()
        self.assertIs(monitor.task, task)
        self.assertEqual([id(value) for value in self.gc.callbacks], [id(foreign), id(callback)])
        await asyncio.wait_for(entered.wait(), 1)
        await monitor.close()
        self.assertTrue(task.done())
        self.assertIsNone(monitor.task)
        self.assertEqual([id(value) for value in self.gc.callbacks], [id(foreign)])
        monitor.start()
        self.assertIsNot(monitor.task, task)
        self.assertIs(self.gc.callbacks[-1], callback)
        await monitor.close()
        self.assertEqual([id(value) for value in self.gc.callbacks], [id(foreign)])

        error = RuntimeError('ordinary task creation failure')
        def unavailable(coroutine):
            coroutine.close()  # The fake task factory owns its rejected input.
            raise error
        with patch('cybergold_candidate.quote_flow_monitor.asyncio.create_task', side_effect=unavailable):
            with self.assertRaises(RuntimeError) as caught:
                monitor.start()
        self.assertIs(caught.exception, error)
        self.assertIsNone(monitor.task)
        self.assertEqual([id(value) for value in self.gc.callbacks], [id(foreign)])

    async def test_gc_pairs_generations_and_keeps_captured_cumulative_values_immutable(self):
        entered = asyncio.Event()
        async def sleep(_delay):
            entered.set()
            await asyncio.Event().wait()
        monitor = LoopMonitor(Metrics(), sleep=sleep)
        self.addAsyncCleanup(monitor.close)
        monitor.start()
        await asyncio.wait_for(entered.wait(), 1)
        callback = self.gc.callbacks[0]
        empty = monitor._gc_snapshot()
        self.phase(callback, 'stop', 1, 5_000_000, 500_000)  # No matching start.
        self.phase(callback, 'start', 1, 10_000_000, 1_000_000)
        self.phase(callback, 'stop', 1, 16_000_000, 3_000_000)
        first = monitor._gc_snapshot()
        self.phase(callback, 'stop', 1, 20_000_000, 4_000_000)  # Cannot count twice.
        self.phase(callback, 'start', 0, 21_000_000, 5_000_000)
        self.phase(callback, 'stop', 0, 24_000_000, 9_000_000)
        self.assertEqual(empty, ((0, 0, 0),)*3)
        self.assertEqual(first, ((0, 0, 0), (1, 6_000_000, 2_000_000), (0, 0, 0)))
        self.assertEqual(monitor._gc_snapshot(),
                         ((1, 3_000_000, 4_000_000), (1, 6_000_000, 2_000_000), (0, 0, 0)))

        # Failed clock reads must not reuse an earlier start or leak into GC.
        self.phase(callback, 'start', 2, 30_000_000, 10_000_000)
        with patch('cybergold_candidate.quote_flow_monitor.time.process_time_ns',
                   side_effect=ValueError('ordinary clock failure')):
            callback('start', {'generation':2})
        self.phase(callback, 'stop', 2, 40_000_000, 12_000_000)
        self.assertEqual(monitor._gc_snapshot()[2], (0, 0, 0))
        self.phase(callback, 'start', 2, 41_000_000, 13_000_000)
        with patch('cybergold_candidate.quote_flow_monitor.time.monotonic_ns',
                   side_effect=ValueError('ordinary stop clock failure')):
            callback('stop', {'generation':2})
        self.phase(callback, 'stop', 2, 45_000_000, 14_000_000)
        self.assertEqual(monitor._gc_snapshot()[2], (0, 0, 0))
        with patch('cybergold_candidate.quote_flow_monitor.time.monotonic_ns',
                   side_effect=ValueError('ordinary clock failure')):
            callback('start', {'generation':0})
        callback('stop', {'generation':0})
        for info in (None, {}, {'generation':True}, {'generation':-1}, {'generation':3}):
            callback('start', info)
            callback('stop', info)
        self.phase(callback, 'start', 2, 50_000_000, 20_000_000)
        self.phase(callback, 'stop', 2, 55_000_000, 21_000_000)
        self.assertEqual(monitor._gc_snapshot()[2], (1, 5_000_000, 1_000_000))
        await monitor.close()
        self.assertIsNone(monitor._gc_snapshot())

    async def test_gc_deltas_advance_on_unlogged_ticks_and_charge_crossing_span_at_stop(self):
        metrics, clock = Metrics(), [0.0]
        finished = asyncio.Event()
        ticks = 0
        async def sleep(_delay):
            nonlocal ticks
            ticks += 1
            callback = self.gc.callbacks[0]
            if ticks == 1:
                self.phase(callback, 'start', 0, 20_000_000, 1_000_000)
                self.phase(callback, 'stop', 0, 30_000_000, 2_000_000)
                self.phase(callback, 'start', 2, 90_000_000, 3_000_000)
                clock[0] = .1  # Normal tick: no lag event is emitted.
            elif ticks == 2:
                self.phase(callback, 'stop', 2, 450_000_000, 53_000_000)
                clock[0] = .45
            else:
                finished.set()
                await asyncio.Event().wait()
        monitor = LoopMonitor(metrics, clock=lambda:clock[0], sleep=sleep)
        self.addAsyncCleanup(monitor.close)
        with self.assertLogs('cybergold.candidate', level='INFO') as logs:
            monitor.start()
            await asyncio.wait_for(finished.wait(), 1)
            await monitor.close()
        self.assertEqual(len(logs.records), 1)
        event = json.loads(logs.records[0].getMessage())
        self.assertEqual((event['event'],event['lagMs'],event['intervalMs']),
                         ('quote_event_loop_lag',250,100))
        gc_span = event['gcSincePreviousLoopMeasurement']
        self.assertEqual(gc_span['measurementIntervalMs'], 350)
        self.assertEqual(gc_span['scope'], 'process-gc-callback-spans')
        self.assertEqual(gc_span['spanAccounting'], 'whole-span-at-stop')
        rows = gc_span['generations']
        self.assertEqual([row['generation'] for row in rows], [0,1,2])
        self.assertEqual([row['completedCollections'] for row in rows], [0,0,1])
        self.assertEqual(rows[2]['summedCollectionSpanWallMs'], 360)
        self.assertEqual(rows[2]['summedProcessCpuDuringCollectionSpansMs'], 50)
        self.assertGreater(rows[2]['summedCollectionSpanWallMs'], gc_span['measurementIntervalMs'])
        self.assertEqual(set(rows[2]), {'generation','completedCollections',
                         'summedCollectionSpanWallMs','summedProcessCpuDuringCollectionSpansMs'})
        self.assertNotIn('private-object-value', logs.records[0].getMessage())
        self.assertEqual(samples(metrics.event_loop_lag,'_count')[0].value, 2)
        self.assertAlmostEqual(samples(metrics.event_loop_lag,'_sum')[0].value, .25)

    async def test_gc_update_during_serialization_survives_to_next_measurement(self):
        clock, ticks = [0.0], 0
        finished = asyncio.Event()
        captured = []
        frozen = None
        async def sleep(_delay):
            nonlocal ticks, frozen
            ticks += 1
            if ticks == 1:
                self.phase(self.gc.callbacks[0], 'start', 1, 10_000_000, 1_000_000)
                self.phase(self.gc.callbacks[0], 'stop', 1, 20_000_000, 2_000_000)
                frozen = monitor._gc_snapshot()
                clock[0] = .3
            elif ticks == 2:
                clock[0] = .6
            else:
                finished.set()
                await asyncio.Event().wait()
        original_dumps = json.dumps
        def encode(event):
            if not captured:
                self.phase(self.gc.callbacks[0], 'start', 1, 310_000_000, 3_000_000)
                self.phase(self.gc.callbacks[0], 'stop', 1, 330_000_000, 6_000_000)
            captured.append(deepcopy(event))
            return original_dumps(event)
        monitor = LoopMonitor(Metrics(), clock=lambda:clock[0], sleep=sleep)
        self.addAsyncCleanup(monitor.close)
        with patch('cybergold_candidate.quote_flow_monitor.json.dumps', side_effect=encode), \
                self.assertLogs('cybergold.candidate', level='INFO'):
            monitor.start()
            await asyncio.wait_for(finished.wait(), 1)
            await monitor.close()
        self.assertEqual(len(captured), 2)
        rows = [event['gcSincePreviousLoopMeasurement']['generations'][1] for event in captured]
        self.assertEqual([row['completedCollections'] for row in rows], [1,1])
        self.assertEqual([row['summedCollectionSpanWallMs'] for row in rows], [10,20])
        self.assertEqual([row['summedProcessCpuDuringCollectionSpansMs'] for row in rows], [1,3])
        self.assertEqual(frozen[1], (1,10_000_000,1_000_000))

    async def test_registration_metric_and_serialization_failures_keep_monitor_running(self):
        class UnavailableCallbacks(list):
            def append(self, _callback):
                raise RuntimeError('ordinary registration failure')
        self.gc.callbacks = UnavailableCallbacks()
        metric = Mock(side_effect=ValueError('ordinary metric failure'))
        metrics = SimpleNamespace(event_loop_lag=SimpleNamespace(observe=metric))
        clock, ticks = [0.0], 0
        finished = asyncio.Event()
        async def sleep(_delay):
            nonlocal ticks
            ticks += 1
            if ticks <= 2:
                clock[0] = ticks*.3
            else:
                finished.set()
                await asyncio.Event().wait()
        original_dumps = json.dumps
        attempts = 0
        def encode(event):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ValueError('ordinary serialization failure')
            return original_dumps(event)
        monitor = LoopMonitor(metrics, clock=lambda:clock[0], sleep=sleep)
        self.addAsyncCleanup(monitor.close)
        with patch('cybergold_candidate.quote_flow_monitor.json.dumps', side_effect=encode), \
                self.assertLogs('cybergold.candidate', level='INFO') as logs:
            monitor.start()
            await asyncio.wait_for(finished.wait(), 1)
            self.assertFalse(monitor.task.done())
            await monitor.close()
        self.assertEqual(metric.call_count, 2)
        self.assertEqual(attempts, 2)
        self.assertEqual(len(logs.records), 1)
        event = json.loads(logs.records[0].getMessage())
        self.assertEqual(set(event), {'event','component','lagMs','intervalMs'})
        self.assertEqual(event['intervalMs'], 100)
        self.assertFalse(self.gc.callbacks)

    async def test_sampler_measures_ready_to_resumed_and_drains_one_owned_task(self):
        metrics = Metrics()
        clock = [0.0]
        count = 0
        sampled = asyncio.Event()
        async def sleep(delay):
            nonlocal count
            count += 1
            if count==1:
                clock[0] += delay+0.25
            else:
                sampled.set()
                await asyncio.Event().wait()
        monitor = LoopMonitor(metrics,clock=lambda:clock[0],sleep=sleep)
        monitor.start()
        original = monitor.task
        monitor.start()
        self.assertIs(monitor.task,original)
        await sampled.wait()
        await monitor.close()
        self.assertIsNone(monitor.task)
        self.assertTrue(original.done())
        total = samples(metrics.event_loop_lag,'_sum')
        count = samples(metrics.event_loop_lag,'_count')
        self.assertAlmostEqual(total[0].value,0.25)
        self.assertEqual(count[0].value,1)
        self.assertEqual(samples(metrics.flow_stage_cpu,'_total'),[])

    async def test_monitor_failure_does_not_gate_app_start_or_replace_shutdown_error(self):
        error = RuntimeError('ordinary shutdown error')
        monitor = SimpleNamespace(start=lambda:(_ for _ in ()).throw(ValueError('monitor failed')),
                                  close=AsyncMock(side_effect=ValueError('monitor close failed')))
        with patch('cybergold_candidate.quote_flow_monitor.LoopMonitor',return_value=monitor):
            app = create_app(on_shutdown=AsyncMock(side_effect=error))
        with self.assertRaises(RuntimeError) as caught:
            async with app.router.lifespan_context(app):
                pass
        self.assertIs(caught.exception,error)
        monitor.close.assert_awaited_once()


if __name__=='__main__':
    unittest.main()
