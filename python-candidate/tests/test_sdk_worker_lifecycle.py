"""Real subprocess lifecycle checks; upstream SDK arithmetic is qualified separately."""
import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

from cybergold_candidate.sdk_worker import SdkWorker


SCRIPT = '''import json, pathlib, sys, time
for line in sys.stdin:
    request = json.loads(line)
    if request.get('block'):
        pathlib.Path(request['started']).write_text('ready')
        time.sleep(60)
    print(json.dumps({'id': request['id'], 'result': request.get('value')}), flush=True)
'''


class SdkWorkerLifecycle(unittest.IsolatedAsyncioTestCase):
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
