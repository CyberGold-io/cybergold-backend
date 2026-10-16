"""Real subprocess lifecycle checks; upstream SDK arithmetic is qualified separately."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest

from cybergold_candidate.sdk_worker import SdkWorker, SdkWorkerError
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.rpc_diagnostics import quote_work_scope, route_work_scope


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


if __name__ == '__main__':
    unittest.main()
