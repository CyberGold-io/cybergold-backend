"""Slow native simulations cannot occupy the serialized SDK's pricing places."""
import asyncio
import sys
from types import SimpleNamespace
import unittest

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.plan_transport import execute_plan_call
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.sdk_simulation import simulate_sdk
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.search_observations import search_observation_scope
from cybergold_candidate.shared_reads import SharedReads
from test_universal_quote import CORE, settings


CHILD = '''import json,sys
pending={}
for line in sys.stdin:
    row=json.loads(line); key=row['id']; operation=row.get('operation')
    if operation=='cancel':
        pending.pop(key,None)
        if row.get('acknowledge'): print(json.dumps({'id':key,'cancelled':True}),flush=True)
        continue
    if operation=='resume':
        value=pending.pop(key)
    else:
        value=row['value']
        if row.get('needState'):
            pending[key]=value
            print(json.dumps({'id':key,'stateRequest':[{'poolId':'p','wordPositions':[1]}]}),flush=True)
            continue
    print(json.dumps({'id':key,'result':{'value':value}}),flush=True)
'''


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


class NativeRpc:
    def __init__(self):
        self.w3 = SimpleNamespace(provider=self)
        self.release = asyncio.Event()
        self.running = self.peak = self.calls = 0

    async def make_request(self, method, _params):
        assert method == 'eth_call'
        self.calls += 1
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await self.release.wait()
            return {'result': '0x'}
        finally:
            self.running -= 1


class HelpersSdkAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        registry = SimpleNamespace(chain=31338, core=CORE, pending=SharedReads(), inventory={}, seed=None)
        self.addAsyncCleanup(registry.pending.close)
        sdk = SdkWorker(command=[sys.executable, '-u', '-c', CHILD])
        self.engine = RouteQuoteEngine(settings(), registry, sdk=sdk)
        self.quoter = Quoter(settings(), self.engine)
        self.rpc = NativeRpc()
        self.calls = []
        self.addAsyncCleanup(self.close)
        # Exclude child startup from progress/deadlock assertions.
        self.assertEqual(await sdk.request({'operation': 'quote', 'value': -1}), {'value': -1})

    async def close(self):
        self.rpc.release.set()
        for task in self.calls:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.calls, return_exceptions=True)
        await self.engine.close()

    def call(self, quoter=None):
        task = asyncio.create_task(execute_plan_call(self.rpc, [],
            semaphore=(quoter or self.quoter).plan_simulator.semaphore,
            now=lambda: 'control', shared=False))
        self.calls.append(task)
        return task

    async def fill_helpers(self):
        for _ in range(8):
            self.call()
        await until(lambda: self.rpc.running == 8)

    def restored(self):
        self.assertEqual(self.engine.semaphore._value, 8)
        self.assertEqual(self.engine.helpers_semaphore._value, 8)
        self.assertEqual(self.rpc.running, 0)

    async def test_sdk_progress_and_queued_active_helpers_cancellation(self):
        await self.fill_helpers()
        other = Quoter(settings(), self.engine)
        ninth = self.call(other)
        await until(lambda: bool(self.engine.helpers_semaphore._ordinary))
        async with search_observation_scope():
            values = await asyncio.wait_for(asyncio.gather(*(simulate_sdk(self.engine,
                {'operation': 'quote', 'value': index}) for index in range(16))), 3)
        self.assertEqual(values, [{'value': index} for index in range(16)])
        self.assertFalse(self.rpc.release.is_set())
        self.assertEqual((self.rpc.calls, self.rpc.peak), (8, 8))
        self.assertFalse(ninth.done())
        ninth.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await ninth
        self.calls[0].cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.calls[0]
        self.assertEqual(self.engine.helpers_semaphore._value, 1)
        self.rpc.release.set()
        await asyncio.gather(*self.calls, return_exceptions=True)
        self.restored()

    async def test_helpers_progress_while_all_sdk_pricing_places_are_owned(self):
        for _ in range(8):
            await self.engine.semaphore.acquire()
        try:
            self.rpc.release.set()
            response, _counts = await asyncio.wait_for(self.call(), 3)
            self.assertEqual(response['result'], '0x')
            self.assertEqual(self.engine.semaphore._value, 0)
            self.assertEqual(self.engine.helpers_semaphore._value, 8)
        finally:
            for _ in range(8):
                self.engine.semaphore.release()
        self.restored()

    async def continuation(self, *, cancel):
        await self.fill_helpers()
        entered, release = asyncio.Event(), asyncio.Event()
        async def acquire(requests):
            self.assertEqual(requests, [{'poolId': 'p', 'wordPositions': [1]}])
            entered.set()
            await release.wait()
            return [{'id': 'p', 'bitmapWords': [{'wordPosition': 1, 'bitmap': '0'}], 'ticks': []}]
        payload = {'operation': 'quote', 'value': 42, 'needState': True,
            'pools': [{'id': 'p', 'bitmapWords': [], 'ticks': []}]}
        async with search_observation_scope():
            task = asyncio.create_task(simulate_sdk(self.engine, payload, acquire))
            await asyncio.wait_for(entered.wait(), 3)
            self.assertEqual(self.engine.semaphore._value, 8)
            self.assertEqual(self.engine.helpers_semaphore._value, 0)
            if cancel:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            else:
                release.set()
                self.assertEqual(await asyncio.wait_for(task, 3), {'value': 42})
                self.assertFalse(self.rpc.release.is_set())
        self.assertEqual(self.engine.semaphore._value, 8)
        self.assertEqual(self.engine.helpers_semaphore._value, 0)
        self.rpc.release.set()
        await asyncio.gather(*self.calls)
        self.restored()
        self.assertEqual(await self.engine.sdk.request({'operation': 'quote', 'value': 7}), {'value': 7})

    async def test_required_state_continuation_restores_only_its_owned_capacity(self):
        await self.continuation(cancel=False)

    async def test_cancelled_required_state_does_not_release_running_helpers_capacity(self):
        await self.continuation(cancel=True)


if __name__ == '__main__':
    unittest.main()
