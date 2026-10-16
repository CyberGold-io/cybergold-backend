"""Actual SdkWorker lifecycle with an inert JSONL child and owned route permits.

The child uses this interpreter, never Node, a provider, HTTP, RPC, a wallet
or a server.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

from cybergold_candidate import rpc_diagnostics as diag
from cybergold_candidate import route_work_slots as work
from cybergold_candidate.route_scheduler import schedule_routes
from cybergold_candidate.sdk_worker import SdkWorker, SdkWorkerError


PROTOCOL_WORKER = r'''
import json, pathlib, sys
pending, events = {}, []
for line in sys.stdin:
    request = json.loads(line)
    identity, operation = request['id'], request.get('operation', 'request')
    events.append({'id': identity, 'operation': operation,
                   'acknowledge': request.get('acknowledge', False)})
    if operation == 'stats':
        result = {'pending': sorted(pending), 'events': list(events)}
        print(json.dumps({'id': identity, 'result': result}), flush=True)
    elif operation == 'cancel':
        pending.pop(identity, None)
        if request.get('acknowledge'):
            print(json.dumps({'id': identity, 'cancelled': True}), flush=True)
    elif operation == 'resume':
        original = pending[identity]
        if original.get('resumeMarker'):
            pathlib.Path(original['resumeMarker']).write_text('resume received')
        if original.get('holdResume'):
            continue
        pending.pop(identity)
        response = {'error': 'synthetic resumed error'} if original.get('resumeError') else {'result': original['value']}
        print(json.dumps({'id': identity, **response}), flush=True)
    elif request.get('continueState') and not request.get('noState'):
        pending[identity] = request
        print(json.dumps({'id': identity, 'stateRequest': [
            {'poolId': request['pools'][0]['id'], 'wordPositions': [0], 'ticks': []}]}), flush=True)
    else:
        print(json.dumps({'id': identity, 'result': request['value']}), flush=True)
'''


def payload(value='continued', **changes):
    return {'operation': 'simulateRoute', 'mode': 'exactOut', 'value': value,
            'pools': [{'id': '0x' + '01' * 20, 'protocol': 'v3',
                       'bitmapWords': [], 'ticks': []}], **changes}


def observed(requests):
    return [{'id': row['poolId'], 'ticks': [],
             'bitmapWords': [{'wordPosition': position, 'bitmap': '0'}
                             for position in row['wordPositions']]} for row in requests]


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.001)


async def feed(values):
    for value in values:
        yield value


class SdkWorkerRouteLeaseLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.worker = SdkWorker([sys.executable, '-u', '-c', PROTOCOL_WORKER])
        self.engine = asyncio.Semaphore(1)
        self.leases = []
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.worker.close()

    def schedule(self, evaluate, values=('one',), diagnostics=False):
        async def owned(index, value):
            self.leases.append(work._current.get())
            async with work.engine_work(self.engine):
                return await evaluate(value)
        async def run():
            return await schedule_routes(lambda _expanded: [feed(values)], owned, limit=1)
        if diagnostics:
            class Routes:
                @diag.route_work_scope
                async def get(inner, request):
                    return await run()
            @diag.quote_work_scope
            async def quote():
                return await Routes().get({'mode': 'exact-out'})
            coroutine = quote()
        else:
            coroutine = run()
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task

    def assert_permits_restored(self):
        self.assertTrue(self.leases)
        self.assertTrue(all(lease.closed and not lease.owned and not lease.engines for lease in self.leases))
        self.assertEqual(self.leases[0].slots._value, 1)
        self.assertEqual(self.engine._value, 1)

    async def stats(self):
        return await self.worker.request({'operation': 'stats'})

    async def assert_clean_child(self, process):
        self.assertIs(self.worker.process, process)
        self.assertIsNone(process.returncode)
        stats = await self.stats()  # Serial JSONL proves preceding one-way cancel was consumed.
        self.assertEqual(stats['pending'], [])
        await self.worker.close()
        self.assertIsNone(self.worker.process)
        self.assertIsNotNone(process.returncode)
        return stats

    async def test_normal_sdk_resume_releases_work_for_later_candidate(self):
        parked, release, fast = asyncio.Event(), asyncio.Event(), asyncio.Event()
        results = []
        async def fill(requests):
            parked.set()
            await release.wait()
            return observed(requests)
        async def evaluate(value):
            result = await self.worker.request(payload(value, noState=value == 'fast'), on_state=fill)
            results.append(result)
            if value == 'fast':
                fast.set()
        task = self.schedule(evaluate, ('parked', 'fast'))
        await asyncio.wait_for(parked.wait(), 3)
        await asyncio.wait_for(fast.wait(), 3)
        process = self.worker.process
        self.assertEqual(results, ['fast'])
        self.assertFalse(task.done())
        self.assertFalse(self.leases[0].owned)
        self.assertEqual(self.engine._value, 1)
        release.set()
        await asyncio.wait_for(task, 3)
        self.assertEqual(results, ['fast', 'parked'])
        self.assert_permits_restored()
        stats = await self.assert_clean_child(process)
        self.assertEqual([row['operation'] for row in stats['events']],
                         ['simulateRoute', 'simulateRoute', 'resume', 'stats'])

    async def test_ordinary_parked_callback_error_preserves_exception_and_cancels_session(self):
        expected = OSError('inert required observation failed')
        async def fill(_requests):
            self.assertFalse(self.leases[0].owned)
            raise expected
        async def evaluate(_value):
            await self.worker.request(payload(), on_state=fill)
        task = self.schedule(evaluate)
        with self.assertRaises(OSError) as raised:
            await asyncio.wait_for(task, 3)
        self.assertIs(raised.exception, expected)
        self.assert_permits_restored()
        stats = await self.assert_clean_child(self.worker.process)
        cancels = [row for row in stats['events'] if row['operation'] == 'cancel']
        self.assertEqual(cancels, [{'id': '1', 'operation': 'cancel', 'acknowledge': False}])

    async def test_cancel_parked_sdk_read_drains_callback_and_one_way_session(self):
        parked, drained = asyncio.Event(), asyncio.Event()
        async def fill(_requests):
            parked.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        async def evaluate(_value):
            await self.worker.request(payload(), on_state=fill)
        task = self.schedule(evaluate)
        await asyncio.wait_for(parked.wait(), 3)
        process = self.worker.process
        self.assertFalse(self.leases[0].owned)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        self.assertTrue(drained.is_set())
        self.assert_permits_restored()
        stats = await self.assert_clean_child(process)
        self.assertEqual([row['operation'] for row in stats['events']], ['simulateRoute', 'cancel', 'stats'])
        self.assertFalse(stats['events'][1]['acknowledge'])

    async def queued_engine_case(self, cancel):
        parked, release = asyncio.Event(), asyncio.Event()
        scopes, results = [], []
        async def fill(requests):
            parked.set()
            await release.wait()
            return observed(requests)
        async def evaluate(_value):
            scopes.append(diag._quote_scope.get().wave)
            results.append(await self.worker.request(payload(), on_state=fill))
        task = self.schedule(evaluate, diagnostics=True)
        await asyncio.wait_for(parked.wait(), 3)
        process = self.worker.process
        await self.engine.acquire()
        try:
            release.set()
            await until(lambda: self.leases[0].owned and bool(self.engine._waiters))
            wave = scopes[0]
            self.assertEqual(len(wave.sdk_sessions), 1)
            session = next(iter(wave.sdk_sessions))
            self.assertEqual(session.state, 'resume-queued')
            self.assertFalse(self.worker.lock.locked())
            self.assertEqual(self.worker.sequence, 1)  # No resume exchange or stats yet.
            if cancel:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 3)
                self.assertEqual(self.leases[0].slots._value, 1)
                self.assertEqual(self.engine._value, 0)  # Preserve the independent test holder.
                self.assertEqual(wave.sdk_sessions, {})
            else:
                self.assertFalse(task.done())
        finally:
            self.engine.release()
        if not cancel:
            await asyncio.wait_for(task, 3)
            self.assertEqual(results, ['continued'])
            self.assertEqual(scopes[0].sdk_sessions, {})
        self.assert_permits_restored()
        stats = await self.assert_clean_child(process)
        self.assertEqual([row['operation'] for row in stats['events']],
                         ['simulateRoute', 'cancel' if cancel else 'resume', 'stats'])

    async def test_successful_fill_is_resume_queued_before_engine_reacquire(self):
        await self.queued_engine_case(cancel=False)

    async def test_cancel_queued_engine_reacquire_cancels_sdk_session_without_overrelease(self):
        await self.queued_engine_case(cancel=True)

    async def test_resumed_sdk_error_releases_permits_and_removes_session(self):
        async def fill(requests):
            return observed(requests)
        async def evaluate(_value):
            await self.worker.request(payload(resumeError=True), on_state=fill)
        task = self.schedule(evaluate)
        with self.assertRaisesRegex(SdkWorkerError, 'SDK quote unavailable'):
            await asyncio.wait_for(task, 3)
        self.assert_permits_restored()
        stats = await self.assert_clean_child(self.worker.process)
        self.assertEqual([row['operation'] for row in stats['events']], ['simulateRoute', 'resume', 'stats'])

    async def test_cancel_resumed_exchange_acknowledges_retirement_and_reaps_child(self):
        async def fill(requests):
            return observed(requests)
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'resume-received'
            async def evaluate(_value):
                await self.worker.request(payload(holdResume=True, resumeMarker=str(marker)), on_state=fill)
            task = self.schedule(evaluate)
            await until(marker.exists)
            process = self.worker.process
            self.assertTrue(self.leases[0].owned)
            self.assertEqual(self.engine._value, 0)
            self.assertTrue(self.worker.lock.locked())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
        self.assert_permits_restored()
        stats = await self.assert_clean_child(process)
        self.assertEqual([row['operation'] for row in stats['events']], ['simulateRoute', 'resume', 'cancel', 'stats'])
        self.assertTrue(stats['events'][2]['acknowledge'])


if __name__ == '__main__':
    unittest.main()
