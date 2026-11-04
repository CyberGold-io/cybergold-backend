"""Flow diagnostics remain bounded and independent of product HTTP and loop CPU."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
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
