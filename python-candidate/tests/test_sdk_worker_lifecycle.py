"""Real subprocess lifecycle checks; upstream SDK arithmetic is qualified separately."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cybergold_candidate.sdk_worker import SdkWorker, SdkWorkerError
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.rpc_diagnostics import quote_work_scope, route_work_scope
from cybergold_candidate import sdk_bridge
from cybergold_candidate.quote_flow import Flow, flow_scope, producer_flow
from cybergold_candidate.sdk_timing import ChildClock, operation_timing, RoundTrips


SCRIPT = '''import json, pathlib, sys, time
for line in sys.stdin:
    request = json.loads(line)
    if request.get('block'):
        pathlib.Path(request['started']).write_text('ready')
        time.sleep(60)
    print(json.dumps({'id': request['id'], 'result': request.get('value')}), flush=True)
'''

STATE_SCRIPT = '''import json, sys
pending = {}
for line in sys.stdin:
    request = json.loads(line)
    identity = request['id']
    if request.get('operation') == 'cancel':
        pending.pop(identity, None)
        if request.get('acknowledge'):
            print(json.dumps({'id': identity, 'cancelled': True}), flush=True)
    elif request.get('operation') == 'resume':
        original = pending.pop(identity)
        print(json.dumps({'id': identity, 'result': original['value']}), flush=True)
    elif request.get('continueState'):
        pending[identity] = request
        print(json.dumps({'id': identity, 'stateRequest': [{'poolId': 'pool', 'wordPositions': [0], 'ticks': []}]}), flush=True)
    else:
        print(json.dumps({'id': identity, 'result': request['value']}), flush=True)
'''


class SdkWorkerLifecycle(unittest.IsolatedAsyncioTestCase):
    def state_worker(self):
        worker = SdkWorker([sys.executable, '-u', '-c', STATE_SCRIPT])
        self.addAsyncCleanup(worker.close)
        return worker

    async def test_required_fill_releases_exchange_and_preserves_original_errors(self):
        worker = self.state_worker()
        started, release = asyncio.Event(), asyncio.Event()
        async def fill(_requests):
            started.set()
            await release.wait()
            return [{'id': 'pool', 'ticks': [], 'bitmapWords': [{'wordPosition': 0, 'bitmap': '0'}]}]
        paused = asyncio.create_task(worker.request({'operation': 'simulateRoute', 'value': 'continued',
            'pools': [{'id': 'pool'}]}, on_state=fill))
        await asyncio.wait_for(started.wait(), 2)
        process = worker.process
        self.assertEqual(await worker.request({'value': 'independent'}), 'independent')
        self.assertFalse(paused.done())
        release.set()
        self.assertEqual(await paused, 'continued')
        self.assertIs(worker.process, process)
        for expected in (OSError('required read failed'), SnapshotChanged('canonical disproof')):
            async def failed(_requests):
                raise expected
            with self.assertRaises(type(expected)) as raised:
                await worker.request({'operation': 'simulateRoute', 'pools': [{'id': 'pool'}]}, on_state=failed)
            self.assertIs(raised.exception, expected)
            self.assertEqual(await worker.request({'value': 'after failure'}), 'after failure')

    async def test_cancelled_resume_lock_waiter_discards_only_its_continuation(self):
        worker = self.state_worker()
        started, release = asyncio.Event(), asyncio.Event()
        async def fill(_requests):
            started.set()
            await release.wait()
            return [{'id': 'pool', 'ticks': [], 'bitmapWords': [{'wordPosition': 0, 'bitmap': '0'}]}]
        paused = asyncio.create_task(worker.request({'operation': 'simulateRoute', 'value': 'retired',
            'pools': [{'id': 'pool'}]}, on_state=fill))
        await asyncio.wait_for(started.wait(), 2)
        process = worker.process
        async with worker.lock:
            release.set()
            await asyncio.sleep(0)
            paused.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(paused, 2)
            self.assertIs(worker.process, process)
            self.assertIsNone(process.returncode)
        self.assertEqual(await worker.request({'value': 'foreign successor'}), 'foreign successor')

    async def test_lost_paused_process_is_an_ordinary_error_without_retry(self):
        worker = self.state_worker()
        started, release = asyncio.Event(), asyncio.Event()
        async def fill(_requests):
            started.set()
            await release.wait()
            return [{'id': 'pool', 'ticks': [], 'bitmapWords': []}]
        paused = asyncio.create_task(worker.request({'operation': 'simulateRoute', 'value': 'lost',
            'pools': [{'id': 'pool'}]}, on_state=fill))
        await asyncio.wait_for(started.wait(), 2)
        async with worker.lock:
            await worker._stop()
        release.set()
        with self.assertRaisesRegex(SdkWorkerError, 'continuation worker exited'):
            await paused
        self.assertEqual(worker.sequence, 1)
        self.assertEqual(await worker.request({'value': 'fresh producer'}), 'fresh producer')

    async def test_unresponsive_continuation_uses_only_the_existing_cleanup_allowance(self):
        worker = SdkWorker([sys.executable, '-u', '-c', SCRIPT])
        self.addAsyncCleanup(worker.close)
        async def unexpected(_requests):
            self.fail('The blocked child never requested a state observation')
        grace_values, stop = [], worker._stop
        async def observed_stop(grace=2):
            grace_values.append(grace)
            await stop(grace)
        worker._stop = observed_stop
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'started'
            active = asyncio.create_task(worker.request({'block': True, 'started': str(marker)}, on_state=unexpected))
            await self.wait_started(marker)
            process = worker.process
            active.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(active, 3)
            self.assertEqual(len(grace_values), 1)
            self.assertLess(grace_values[0], .1)
            self.assertIsNotNone(process.returncode)
            self.assertIsNone(worker.process)
            self.assertEqual(await worker.request({'value': 'after unresponsive child'}), 'after unresponsive child')

    async def test_active_sdk_cancellation_preserves_another_paused_calculation(self):
        worker = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'),
            str(Path('src/uniswap-sdk/worker.ts').resolve())])
        self.addAsyncCleanup(worker.close)
        token = lambda digit: {'address': '0x'+digit.rjust(40, '0'), 'decimals': 18, 'chainId': 1}
        pool = {'id': 'pool', 'protocol': 'v3', 'token0': token('1'), 'token1': token('2'),
            'feePips': 3000, 'tickSpacing': 60, 'sqrtRatioX96': str(2**96), 'tick': 0,
            'liquidity': str(10**18), 'ticks': [], 'bitmapWords': []}
        started, release = asyncio.Event(), asyncio.Event()
        async def fill(requests):
            started.set()
            await release.wait()
            words = [word for row in requests for word in row['wordPositions']]
            ticks = [{'index': index, 'liquidityGross': str(10**18), 'liquidityNet': str(net)}
                for index, net in ((-600, 10**18), (600, -10**18)) if index//60 >> 8 in words]
            return [{'id': 'pool', 'bitmapWords': [{'wordPosition': word,
                'bitmap': str(1 << (246 if word == -1 else 10))} for word in words], 'ticks': ticks}]
        async def unexpected(_requests):
            self.fail('The active control is fully covered; no extra read is permitted')
        paused = asyncio.create_task(worker.request({'operation': 'quote', 'mode': 'exactOut',
            'amount': '1000', 'zeroForOne': True, 'pools': [pool]}, on_state=fill))
        active = None
        try:
            await asyncio.wait_for(started.wait(), 3)
            process = worker.process
            covered = {**pool, 'feePips': 100, 'tickSpacing': 1, 'liquidity': '0', 'bitmapWords': [
                {'wordPosition': word, 'bitmap': '0'} for word in range(-3466, 1)]}
            active = asyncio.create_task(worker.request({'operation': 'quote', 'mode': 'exactOut',
                'amount': '1000', 'zeroForOne': True, 'pools': [covered]}, on_state=unexpected))
            async def exchange_started():
                while not worker.lock.locked():
                    await asyncio.sleep(0)
            await asyncio.wait_for(exchange_started(), 2)
            active.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await active
            self.assertIs(worker.process, process)
            self.assertIsNone(process.returncode)
            release.set()
            self.assertEqual((await paused)['amountOut'], '1000')
            # A stray retired response would fail the next request's identity.
            self.assertEqual((await worker.request({'operation': 'quote', 'mode': 'exactOut',
                'amount': '1000', 'zeroForOne': True, 'pools': [pool]}, on_state=fill))['amountOut'], '1000')
        finally:
            release.set()
            for task in (paused, active):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (paused, active) if task is not None), return_exceptions=True)

    async def wait_started(self, marker):
        async def wait():
            while not marker.exists():
                await asyncio.sleep(.005)
        await asyncio.wait_for(wait(), 2)

    async def test_inflight_cancellation_stops_worker_and_queued_client_recovers(self):
        worker = SdkWorker([sys.executable, '-u', '-c', SCRIPT])
        self.addAsyncCleanup(worker.close)
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'started'
            active = asyncio.create_task(worker.request({'block': True, 'started': str(marker)}))
            await self.wait_started(marker)
            process = worker.process
            queued = asyncio.create_task(worker.request({'value': 'after cancellation'}))
            await asyncio.sleep(0)
            active.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await active
            self.assertIsNotNone(process.returncode)
            self.assertEqual(await asyncio.wait_for(queued, 2), 'after cancellation')
            self.assertIsNot(worker.process, process)

    async def test_cancelling_lock_waiter_does_not_interrupt_active_exchange(self):
        worker = SdkWorker([sys.executable, '-u', '-c', SCRIPT])
        self.addAsyncCleanup(worker.close)
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'started'
            active = asyncio.create_task(worker.request({'block': True, 'started': str(marker)}))
            await self.wait_started(marker)
            process = worker.process
            queued = asyncio.create_task(worker.request({'value': 'cancelled waiter'}))
            await asyncio.sleep(0)
            queued.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await queued
            self.assertIs(worker.process, process)
            self.assertIsNone(process.returncode)
            self.assertFalse(active.done())
            active.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await active
            self.assertEqual(await worker.request({'value': 'recovered'}), 'recovered')

    async def test_route_deadline_observes_sdk_lock_wait_without_cancelling_active_client(self):
        worker = SdkWorker([sys.executable, '-u', '-c', SCRIPT])
        self.addAsyncCleanup(worker.close)
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'started'
            active = asyncio.create_task(worker.request({'block': True, 'started': str(marker)}))
            await self.wait_started(marker)
            process = worker.process
            class WaitingRoute:
                @route_work_scope
                async def get(self, _request):
                    async with asyncio.timeout(.03):
                        return await worker.request({'value': 'private request value'})
            @quote_work_scope
            async def quote():
                return await WaitingRoute().get({'mode': 'exact-in'})
            with self.assertRaises(TimeoutError) as raised:
                await quote()
            wave = public_quote_error(raised.exception)['quoteDiagnostics']['routeWave']
            self.assertEqual(wave['sdkRequests'], 1)
            self.assertEqual(wave['sdkWaiting'], 1)
            self.assertGreaterEqual(wave['sdkLockWaitMs'], 20)
            self.assertEqual(wave['sdkExchangeMs'], 0)
            self.assertIs(worker.process, process)
            self.assertIsNone(process.returncode)
            self.assertFalse(active.done())
            self.assertNotIn('private request value', str(wave))
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
            self.assertEqual(await worker.request({'value': 'recovered'}), 'recovered')

    async def test_timeout_stops_blocked_process_and_next_request_restarts_cleanly(self):
        worker = SdkWorker([sys.executable, '-u', '-c', SCRIPT])
        self.addAsyncCleanup(worker.close)
        ordinary_timeout = worker.timeout
        # Bootstrap uses the production budget; the short timeout measures an
        # initialized child's blocked exchange, independently of startup speed.
        self.assertEqual(await worker.request({'value': 'ready'}), 'ready')
        process = worker.process
        worker.timeout = .2
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'started'
            with self.assertRaises(TimeoutError):
                await worker.request({'block': True, 'started': str(marker)})
            self.assertTrue(marker.exists())
            self.assertIsNotNone(process.returncode)
            self.assertIsNone(worker.process)
            worker.timeout = ordinary_timeout
            self.assertEqual(await worker.request({'value': 'after timeout'}), 'after timeout')


class SdkTimingTests(unittest.IsolatedAsyncioTestCase):
    def test_monotonic_calibration_does_not_assume_matching_origins(self):
        clock = ChildClock()
        first = clock.join(100, 500, 550, 200)
        self.assertEqual(first, (0.0, .00005, .00005, False))
        self.assertEqual(clock.join(1000, 1380, 1400, 1025), (0.0, .000005, .000005, False))
        lower, upper, uncertainty, _ = clock.join(2000, 2375, 2385, 2280)
        self.assertEqual((lower, upper, uncertainty), (.000270, .000270, 0.0))
        # Different child origin/discontinuous calibration resets evidence only.
        self.assertTrue(clock.join(3000, 100, 110, 3020)[-1])
        with self.assertRaises(ValueError): clock.join(1, 100, 99, 200)

    async def test_legacy_worker_and_malformed_metadata_keep_business_results_private(self):
        broken = '''import json,sys
for line in sys.stdin:
 request=json.loads(line)
 print(json.dumps({'id':request['id'],'result':request.get('value'),
                   '_sdkTiming':{'receivedNs':'invalid'}}),flush=True)
'''
        for script, field in [(SCRIPT, 'legacyOrMissingFrames'), (broken, 'invalidChildFrames')]:
            worker = SdkWorker([sys.executable, '-u', '-c', script])
            self.addAsyncCleanup(worker.close)
            flow = Flow('test', kind='search')
            with flow_scope(flow):
                self.assertEqual(await worker.request({'value': 'private-input-value'}), 'private-input-value')
            rows = flow.snapshot()['sdkRoundTrips']['rows']
            self.assertEqual((len(rows), rows[0][field]), (1, 1))
            self.assertNotIn('private-input-value', json.dumps(flow.snapshot()['sdkRoundTrips']))

    async def test_real_child_start_resume_and_cpu_join_reach_search_flow(self):
        worker = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'), 'src/uniswap-sdk/worker.ts'])
        self.addAsyncCleanup(worker.close)
        tokens = [{'address': '0x'+value*40, 'decimals': 18, 'chainId': 1} for value in ('1','2')]
        pair = {'id': 'private-pool-identity', 'protocol': 'v2', 'token0': tokens[0], 'token1': tokens[1],
                'reserve0': '1000000', 'reserve1': '2000000', 'feePips': 3000}
        pool = {**pair, 'protocol': 'v3', 'tickSpacing': 60, 'sqrtRatioX96': str(2**96),
                'tick': 0, 'liquidity': '1000000', 'bitmapWords': [], 'ticks': []}
        records, demands = [], []
        flow = Flow('test', kind='search', sink=records.append)
        async def fill(requests):
            demands.append(requests)
            with producer_flow('required-state'):
                return [{'id': pool['id'], 'bitmapWords': [
                    {'wordPosition': -1, 'bitmap': str(1 << 255)}, {'wordPosition': 0, 'bitmap': '2'}],
                    'ticks': [{'index': -60, 'liquidityGross': '1000000', 'liquidityNet': '1000000'},
                              {'index': 60, 'liquidityGross': '1000000', 'liquidityNet': '-1000000'}]}]
        with flow_scope(flow):
            for _ in range(2):
                result = await worker.request({'operation': 'quote', 'mode': 'exactIn', 'pools': [pair],
                    'poolId': pair['id'], 'amount': '1000', 'zeroForOne': True})
                self.assertEqual(result['amountOut'], '1992')
                self.assertNotIn('_sdkTiming', result)
            result = await worker.request({'operation': 'quote', 'mode': 'exactIn', 'pools': [pool],
                'poolId': pool['id'], 'amount': '1000', 'zeroForOne': True}, on_state=fill)
            self.assertEqual(result['amountOut'], '996')
        flow.finish('succeeded')
        search = next(row for row in records if row['flowKind'] == 'search')
        census = search['sdkRoundTrips']
        starts = next(row for row in census['rows'] if row['phase'] == 'start')
        resumes = next(row for row in census['rows'] if row['phase'] == 'resume')
        self.assertEqual(starts['started'], 3)
        self.assertEqual(starts['stateRequestFrames'], 1)
        self.assertEqual(resumes['started'], len(demands))
        self.assertTrue(all(row['childFrames'] == row['completed'] for row in census['rows']))
        self.assertTrue(all(row['invalidChildFrames'] == 0 for row in census['rows']))
        self.assertTrue(all(row['childProcessCpuMs'] >= 0 for row in census['rows']))
        for row in census['rows']:
            self.assertLessEqual(row['responseToReadLowerMs'], row['responseToReadUpperMs'])
            slow = row['slowest']
            self.assertLessEqual(slow['childResponseWriteMsLower'], slow['childResponseWriteMsUpper'])
            self.assertLessEqual(slow['childResponseWriteMsUpper'], slow['parentReadConsumedMs'])
        self.assertNotIn(pool['id'], json.dumps(census))
        self.assertTrue(all('sdkRoundTrips' not in row for row in records if row['flowKind'] == 'required-state'))

    async def test_foreign_task_cannot_inherit_exchange_timing_ownership(self):
        sent = []
        async def drain(): pass
        async def line(): return b'{"id":"1","result":"unchanged"}\n'
        process = SimpleNamespace(stdin=SimpleNamespace(write=lambda raw: sent.append(json.loads(raw)), drain=drain),
                                  stdout=SimpleNamespace(readline=line))
        flow = Flow('test', kind='search')
        with flow_scope(flow), operation_timing(ChildClock(), 'quote', 'exactIn'):
            result = await asyncio.create_task(sdk_bridge.exchange(process, {'id': '1', 'operation': 'quote'}))
        self.assertEqual(result['result'], 'unchanged')
        self.assertNotIn('_sdkTiming', sent[0])
        self.assertNotIn('sdkRoundTrips', flow.snapshot())

    async def test_cancelled_read_and_broken_observer_never_replace_protocol_outcomes(self):
        entered = asyncio.Event()
        async def drain(): pass
        async def read():
            entered.set()
            await asyncio.Event().wait()
        process = SimpleNamespace(stdin=SimpleNamespace(write=lambda _raw: None, drain=drain),
                                  stdout=SimpleNamespace(readline=read))
        flow = Flow('test', kind='search')
        async def request():
            with operation_timing(ChildClock(), 'simulateRoute', 'exactOut'):
                return await sdk_bridge.exchange(process, {'operation': 'simulateRoute'})
        with flow_scope(flow):
            task = asyncio.create_task(request())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        row = flow.snapshot()['sdkRoundTrips']['rows'][0]
        self.assertEqual((row['started'], row['cancelled'], row['completed']), (1, 1, 0))
        with patch.object(RoundTrips, 'snapshot', side_effect=RuntimeError('optional observer failed')):
            self.assertNotIn('sdkRoundTrips', flow.snapshot())


if __name__ == '__main__':
    unittest.main()
