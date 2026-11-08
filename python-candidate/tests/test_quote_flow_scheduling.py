"""Observability owns no permit, callback or transport eligibility decision."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from aiohttp import ClientResponseError
import test_rpc_transport as rpc_fixture

from cybergold_candidate.quote_flow import Flow, flow_scope
from cybergold_candidate.route_work_slots import PricingSlots, engine_work
from cybergold_candidate import sdk_bridge
from cybergold_candidate.pool_snapshot import copy_pool_descriptor, copy_pool_snapshot
from cybergold_candidate.route_observations import RouteObservations, route_observation_scope


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


class FlowSchedulingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 0.0
        self.flow = Flow('quote', clock=lambda: self.now)

    async def waiter(self, slots):
        with flow_scope(self.flow):
            async with engine_work(slots, stage_name='helpers.permit'):
                pass

    def row(self):
        return self.flow.snapshot()['stages'][0]

    async def test_grant_and_resume_are_separate_and_keep_waiting_flow_owner(self):
        slots = PricingSlots(1)
        await slots.acquire()
        task = asyncio.create_task(self.waiter(slots))
        await until(lambda: len(slots._spans) == 1)
        releasing = Flow('different-request', clock=lambda: self.now)
        self.now = 2
        with flow_scope(releasing):
            slots.release()
        self.assertFalse(slots._spans)
        self.now = 5
        await task
        row = self.row()
        self.assertEqual((row['summedWallMs'], row['summedReadyWaitMs'], row['summedResumeDelayMs']),
                         (5000, 2000, 3000))
        self.assertEqual((row['completed'], row['inFlight']), (1, 0))
        self.assertEqual(releasing.snapshot()['stages'], [])
        self.assertEqual(slots._value, 1)

    async def test_cancel_before_grant_drops_span_and_queue_without_capacity_change(self):
        slots = PricingSlots(0)
        task = asyncio.create_task(self.waiter(slots))
        await until(lambda: len(slots._spans) == 1)
        self.now = 3
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual((slots._value, len(slots._priority), len(slots._ordinary), len(slots._spans)), (0, 0, 0, 0))
        row = self.row()
        self.assertEqual((row['cancelled'], row['inFlight'], row['summedWallMs']), (1, 0, 3000))

    async def test_cancel_after_grant_restores_capacity_and_records_resume_delay(self):
        slots = PricingSlots(0)
        task = asyncio.create_task(self.waiter(slots))
        await until(lambda: len(slots._spans) == 1)
        self.now = 2
        slots.release()
        self.now = 5
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        row = self.row()
        self.assertEqual((slots._value, len(slots._spans)), (1, 0))
        self.assertEqual((row['cancelled'], row['summedReadyWaitMs'], row['summedResumeDelayMs']), (1, 2000, 3000))

    async def test_unrecorded_waiter_retains_no_span(self):
        slots = PricingSlots(0)
        async def wait():
            async with engine_work(slots):
                pass
        task = asyncio.create_task(wait())
        await until(lambda: bool(slots._ordinary))
        self.assertFalse(slots._spans)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual((slots._value, len(slots._ordinary), len(slots._spans)), (0, 0, 0))

    async def test_native_semaphore_keeps_wall_wait_without_invented_grant_time(self):
        slots = asyncio.Semaphore(0)
        task = asyncio.create_task(self.waiter(slots))
        await until(lambda: bool(slots._waiters))
        self.now = 2
        slots.release()
        self.now = 5
        await task
        row = self.row()
        self.assertEqual((row['summedWallMs'], row['summedReadyWaitMs'], row['summedResumeDelayMs']), (5000, 0, 0))
        self.assertEqual(slots._value, 1)

    async def test_jsonl_exchange_separates_queue_cpu_and_await_without_changing_bytes(self):
        writes = []
        async def drain():
            self.now += 1
            await asyncio.sleep(0)
        async def readline():
            self.now += 2
            await asyncio.sleep(0)
            return b'{"id":"1","result":{"amountOut":"7"}}\n'
        process = SimpleNamespace(stdin=SimpleNamespace(write=writes.append, drain=drain),
                                  stdout=SimpleNamespace(readline=readline))
        lock = asyncio.Lock()
        payload = {'id': '1', 'amount': '3'}
        with flow_scope(self.flow):
            async with sdk_bridge.exchange_lock(lock):
                response = await sdk_bridge.exchange(process, payload)
        self.assertEqual(writes, [(json.dumps(payload, separators=(',', ':'))+'\n').encode()])
        self.assertEqual(response, {'id': '1', 'result': {'amountOut': '7'}})
        self.assertFalse(lock.locked())
        rows = {row['stage']: row for row in self.flow.snapshot()['stages']}
        self.assertEqual({name: row['kind'] for name, row in rows.items()},
            {'sdk.queue': 'queue', 'sdk.exchange': 'await', 'sdk.encode': 'cpu', 'sdk.write': 'await',
             'sdk.read': 'await', 'sdk.decode': 'cpu'})
        self.assertEqual((rows['sdk.write']['summedWallMs'], rows['sdk.read']['summedWallMs']), (1000, 2000))
        self.assertTrue(all(row['inFlight'] == 0 for row in rows.values()))

    async def test_cancelled_bridge_owner_releases_only_its_existing_lock(self):
        lock = asyncio.Lock()
        entered = asyncio.Event()
        async def operation():
            with flow_scope(self.flow):
                async with sdk_bridge.exchange_lock(lock):
                    entered.set()
                    await asyncio.Event().wait()
        task = asyncio.create_task(operation())
        await entered.wait()
        self.assertTrue(lock.locked())
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(lock.locked())

    async def test_context_only_lock_preserves_entry_value_and_times_acquisition_only(self):
        owner = self
        value, exits = object(), []
        class ContextOnlyLock:
            async def __aenter__(self):
                owner.now = 1
                return value
            async def __aexit__(self, *error):
                exits.append(error)
                owner.now = 21
        with flow_scope(self.flow):
            async with sdk_bridge.exchange_lock(ContextOnlyLock()) as entered:
                self.assertIs(entered, value)
                self.now = 20
        self.assertEqual(exits, [(None, None, None)])
        self.assertEqual(self.row()['summedWallMs'], 1000,
                         'SDK queue timing must exclude the body and context exit')

    async def test_context_only_lock_preserves_exception_suppression(self):
        error, observed = RuntimeError('body failure'), []
        class ContextOnlyLock:
            async def __aenter__(self):
                return self
            async def __aexit__(self, kind, value, traceback):
                observed.append((kind, value, traceback))
                return True
        with flow_scope(self.flow):
            async with sdk_bridge.exchange_lock(ContextOnlyLock()):
                raise error
        self.assertEqual(len(observed), 1)
        self.assertIs(observed[0][0], RuntimeError)
        self.assertIs(observed[0][1], error)
        self.assertIsNotNone(observed[0][2])
        self.assertEqual(self.row()['completed'], 1)

    async def test_context_only_lock_preserves_body_error_and_cancellation(self):
        inner, observed = asyncio.Lock(), []
        class ContextOnlyLock:
            async def __aenter__(self):
                return await inner.__aenter__()
            async def __aexit__(self, kind, value, traceback):
                observed.append((kind, value))
                return await inner.__aexit__(kind, value, traceback)
        error = RuntimeError('body failure')
        with self.assertRaises(RuntimeError) as caught:
            async with sdk_bridge.exchange_lock(ContextOnlyLock()):
                raise error
        self.assertIs(caught.exception, error)
        self.assertFalse(inner.locked())
        entered = asyncio.Event()
        async def operation():
            async with sdk_bridge.exchange_lock(ContextOnlyLock()):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(operation())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual([kind for kind, _ in observed], [RuntimeError, asyncio.CancelledError])
        self.assertIs(observed[0][1], error)
        self.assertFalse(inner.locked())

    async def test_context_only_cancelled_entry_keeps_existing_holder_and_does_not_exit(self):
        inner, exits = asyncio.Lock(), []
        await inner.acquire()
        class ContextOnlyLock:
            async def __aenter__(self):
                return await inner.__aenter__()
            async def __aexit__(self, *error):
                exits.append(error)
                return await inner.__aexit__(*error)
        async def operation():
            with flow_scope(self.flow):
                async with sdk_bridge.exchange_lock(ContextOnlyLock()):
                    self.fail('cancelled entry must never enter the body')
        task = asyncio.create_task(operation())
        await until(lambda: bool(inner._waiters))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(inner.locked())
        self.assertEqual(exits, [])
        inner.release()
        self.assertFalse(inner.locked())
        self.assertEqual((self.row()['cancelled'], self.row()['inFlight']), (1, 0))

    async def test_pool_clone_boundary_preserves_mutable_caller_ownership(self):
        original = {'id': 'pool', 'token0': {'metadata': {'labels': ['a']}},
                    'bitmapWords': [{'wordPosition': 0, 'bitmap': '1'}], 'ticks': [{'index': 0, 'liquidityNet': '2'}]}
        with flow_scope(self.flow):
            descriptor = copy_pool_descriptor(original)
            snapshot = copy_pool_snapshot(original)
        self.assertEqual(descriptor, snapshot)
        descriptor['token0']['metadata']['labels'].append('b')
        snapshot['token0']['metadata']['labels'].append('c')
        snapshot['bitmapWords'][0]['bitmap'] = 'changed'
        self.assertEqual(original['token0']['metadata']['labels'], ['a'])
        self.assertEqual(original['bitmapWords'][0]['bitmap'], '1')
        self.assertEqual({(row['stage'], row['kind']) for row in self.flow.snapshot()['stages']},
                         {('topology.clone', 'cpu'), ('state.clone', 'cpu')})


class FlowRpcTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = rpc_fixture.TransportParity()
        await self.fixture.asyncSetUp()
        self.addAsyncCleanup(self.fixture.asyncTearDown)

    @staticmethod
    def rows(flow):
        return {row['stage']: row for row in flow.snapshot()['stages']}

    async def test_blocked_session_is_visible_before_any_physical_http_attempt(self):
        flow, transport = Flow('quote'), RouteObservations()
        async with self.fixture.held_session_lock() as (manager, started, release):
            with flow_scope(flow), route_observation_scope(transport):
                task = asyncio.create_task(self.fixture.provider.make_request('eth_chainId', []))
                try:
                    await asyncio.wait_for(started.wait(), 1)
                    rows = self.rows(flow)
                    self.assertEqual(rows['rpc.session']['inFlight'], 1)
                    self.assertNotIn('rpc.http', rows)
                    self.assertEqual(transport.metrics['requests'], 0)
                    self.assertEqual(self.fixture.requests, [])
                    release()
                    self.assertEqual((await task)['result'], '0x01')
                finally:
                    release()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            rows = self.rows(flow)
            self.assertEqual((rows['rpc.session']['completed'], rows['rpc.http']['completed']), (1, 1))
            self.assertEqual((transport.metrics['requests'], transport.metrics['completed']), (1, 1))
            self.assertEqual(len(self.fixture.requests), 1)
            self.assertFalse(manager.pending)

    async def test_cancelled_session_lookup_stays_pre_http_and_later_caller_recovers(self):
        flow, transport = Flow('quote'), RouteObservations()
        async with self.fixture.held_session_lock() as (manager, started, release):
            with flow_scope(flow), route_observation_scope(transport):
                task = asyncio.create_task(self.fixture.provider.make_request('eth_chainId', []))
                await asyncio.wait_for(started.wait(), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(self.rows(flow)['rpc.session']['cancelled'], 1)
            self.assertNotIn('rpc.http', self.rows(flow))
            self.assertEqual(transport.metrics['requests'], 0)
            self.assertEqual(len(manager.pending), 1)
            release()
            await manager.finish_pending()
            later = Flow('another-request')
            with flow_scope(later), route_observation_scope(transport):
                self.assertEqual((await self.fixture.provider.make_request('eth_chainId', []))['result'], '0x01')
            self.assertEqual(self.rows(later)['rpc.http']['completed'], 1)
            self.assertEqual((len(self.fixture.requests), transport.metrics['requests']), (1, 1))
            self.assertNotIn('rpc.http', self.rows(flow))

    async def test_http_error_records_one_failed_attempt_without_retry(self):
        self.fixture.fail = True
        flow, transport = Flow('quote'), RouteObservations()
        with flow_scope(flow), route_observation_scope(transport):
            with self.assertRaises(ClientResponseError):
                await self.fixture.provider.make_request('eth_blockNumber', [])
        rows = self.rows(flow)
        self.assertEqual((rows['rpc.session']['completed'], rows['rpc.http']['failed']), (1, 1))
        self.assertEqual((len(self.fixture.requests), transport.metrics['requests'], transport.metrics['errors']), (1, 1, 1))

    async def test_http_cancellation_retains_one_cancelled_attempt(self):
        self.fixture.delay = .2
        flow, transport = Flow('quote'), RouteObservations()
        with flow_scope(flow), route_observation_scope(transport):
            task = asyncio.create_task(self.fixture.provider.make_request('eth_blockNumber', []))
            await until(lambda: bool(self.fixture.requests))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        rows = self.rows(flow)
        self.assertEqual((rows['rpc.session']['completed'], rows['rpc.http']['cancelled']), (1, 1))
        self.assertEqual((len(self.fixture.requests), transport.metrics['requests'], transport.metrics['cancelled']), (1, 1, 1))


if __name__ == '__main__':
    unittest.main()
