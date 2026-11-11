"""Known SDK work and temporary engine resumption priority share ownership.

Actual SdkWorker, common exchange lock, CandidateWork and Helpers admission
execute against event-controlled IO leaves. No SDK process, network, economic
oracle, elapsed-time target or production scheduling limit is introduced.
"""
import asyncio
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate import route_work_slots as work
from cybergold_candidate import sdk_bridge
from cybergold_candidate.quoter.inverse import inverse_hops
from cybergold_candidate.quoter.plan_transport import execute_plan_call
from cybergold_candidate.sdk_worker import SdkWorker


STATE = {'id': 'local-pool', 'protocol': 'v3', 'liquidity': '100',
         'bitmapWords': [], 'ticks': []}


async def until(predicate):
    # Only a deadlock allowance for deterministic test events.
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


class ObservedEngine(work.PricingSlots):
    def __init__(self, value):
        super().__init__(value)
        self.request_classes = []

    async def acquire(self, span=None):
        self.request_classes.append((asyncio.current_task().get_name(), work._bootstrap.get()))
        return await super().acquire(span)


class ObservedReservation(asyncio.Semaphore):
    def __init__(self):
        super().__init__(1)
        self.request_classes = []

    async def acquire(self):
        self.request_classes.append(work._bootstrap.get())
        return await super().acquire()


class KnownSdkPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.worker = SdkWorker()
        self.worker.process = SimpleNamespace(returncode=None)
        self.engine = ObservedEngine(8)
        self.tasks, self.releases, self.calls = [], [], []
        self.exchange = patch.object(sdk_bridge, 'exchange', self.exchanged)
        self.exchange.start()
        self.holds = {}

    async def asyncTearDown(self):
        for event in self.releases:
            event.set()
        # This is an inert IO control, not the separate child cancellation
        # protocol suite. No subprocess handle exists to terminate or retire.
        self.worker.process = None
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.worker.close()
        self.exchange.stop()

    async def exchanged(self, _process, payload):
        name = asyncio.current_task().get_name()
        self.calls.append({'task': name, 'priority': work._bootstrap.get(),
                           'payload': deepcopy(payload), 'engineFree': self.engine._value})
        if event := self.holds.get(name):
            await event.wait()
        return {'id': payload['id'], 'result': {'amountIn': str(int(payload.get('amount', 7)) + 1),
                                               'amountOut': payload.get('amount', '7')}}

    def event(self):
        event = asyncio.Event()
        self.releases.append(event)
        return event

    def start(self, operation, name):
        task = asyncio.create_task(operation, name=name)
        self.tasks.append(task)
        return task

    async def quote(self, amount, *, priority=False, on_state=None):
        with work.bootstrap_priority() if priority else nullcontext():
            async with work.engine_work(self.engine):
                return await self.worker.request({'operation': 'quote', 'mode': 'exactIn',
                    'amount': str(amount), 'pools': [STATE], 'poolId': STATE['id'],
                    'zeroForOne': True}, on_state=on_state)

    async def inverse(self):
        quoter = SimpleNamespace(engine=SimpleNamespace(semaphore=self.engine, sdk=self.worker))
        hop = SimpleNamespace(pre_state=STATE, hop={'zeroForOne': True})
        with work.bootstrap_priority():
            return await inverse_hops(quoter, [hop], 7)

    def assert_clean(self, capacity=8):
        self.assertEqual(self.engine._value, capacity)
        self.assertFalse(self.engine._ordinary)
        self.assertFalse(self.engine._priority)
        self.assertEqual(self.worker.lock._value, 1)
        self.assertFalse(self.worker.lock._ordinary)
        self.assertFalse(self.worker.lock._priority)
        self.assertFalse(self.worker.lock.locked())
        self.assertFalse(work._bootstrap.get())
        self.assertIsNone(work._current.get())

    async def test_known_inverse_overtakes_ordinary_sdk_backlog_and_both_classes_keep_fifo(self):
        original = deepcopy(STATE)
        self.holds['active'] = self.event()
        active = self.start(self.quote(1000), 'active')
        await until(lambda: len(self.calls) == 1)
        ordinary = [self.start(self.quote(100 + index), f'ordinary-{index}') for index in range(3)]
        await until(lambda: len(self.worker.lock._ordinary) == 3)
        known = [self.start(self.inverse(), f'known-{index}') for index in range(3)]
        await until(lambda: len(self.worker.lock._ordinary) + len(self.worker.lock._priority) == 6)
        self.assertEqual(self.engine._value, 7)
        self.assertFalse(self.engine._priority)
        self.holds['active'].set()
        await asyncio.gather(active, *ordinary, *known)
        self.assertEqual([call['task'] for call in self.calls],
                         ['active', *[f'known-{i}' for i in range(3)], *[f'ordinary-{i}' for i in range(3)]])
        self.assertEqual([call['priority'] for call in self.calls], [False, True, True, True, False, False, False])
        self.assertEqual([task.result() for task in known], [8, 8, 8])
        self.assertEqual(len(self.calls), 7, 'Changing admission must not duplicate arithmetic requests')
        self.assertEqual(STATE, original)
        self.assertTrue(all(0 <= call['engineFree'] < 8 for call in self.calls))
        self.assert_clean()

    async def test_sdk_lock_holder_resumes_behind_older_priority_work_before_later_arrivals(self):
        self.engine = ObservedEngine(2)
        self.holds['active'] = self.event()
        helpers = {f'helper-{i}': self.event() for i in range(9)}
        entered = []
        async def rpc(_method, _params):
            name = asyncio.current_task().get_name()
            entered.append(name)
            await helpers[name].wait()
            return {'result': 'inert-Helpers-response'}
        owner = SimpleNamespace(w3=SimpleNamespace(provider=SimpleNamespace(make_request=rpc)))
        async def helper():
            with work.bootstrap_priority():
                await execute_plan_call(owner, [{'data': 'unchanged'}, 'latest'],
                    semaphore=self.engine, now=lambda: 'local', shared=False)
        active = self.start(self.quote(1000), 'active')
        await until(lambda: len(self.calls) == 1)
        head = self.start(self.quote(1001), 'ordinary-head')
        await until(lambda: len(self.worker.lock._ordinary) == 1)
        self.start(helper(), 'helper-0')
        await until(lambda: entered == ['helper-0'])
        self.start(helper(), 'helper-1')
        await until(lambda: len(self.engine._priority) == 1)
        known = self.start(self.inverse(), 'known-inverse')
        await until(lambda: len(self.engine._priority) == 2)
        for index in range(2, 6):
            self.start(helper(), f'helper-{index}')
        await until(lambda: len(self.engine._priority) == 6)
        self.holds['active'].set()
        await until(lambda: 'helper-1' in entered and head._fut_waiter in self.engine._priority)
        self.assertEqual([call['task'] for call in self.calls], ['active'])
        self.assertTrue(self.worker.lock.locked())
        self.assertFalse(self.engine._ordinary, 'A lock holder must not remain an ordinary engine waiter')
        helpers['helper-0'].set()
        await until(lambda: 'helper-2' in entered and len(self.worker.lock._priority) == 1)
        position = list(self.engine._priority).index(head._fut_waiter)
        self.assertEqual(position, 3, 'Three older priority Helpers retain their order')
        for index in range(6, 9):
            self.start(helper(), f'helper-{index}')
        await until(lambda: len(self.engine._priority) == 7)
        self.assertEqual(list(self.engine._priority).index(head._fut_waiter), position)
        for index in range(1, 6):
            helpers[f'helper-{index}'].set()
        await until(lambda: any(call['task'] == 'ordinary-head' for call in self.calls))
        self.assertFalse(any(helpers[f'helper-{i}'].is_set() for i in range(6, 9)))
        self.assertTrue(set(f'helper-{i}' for i in range(6)).issubset(entered))
        self.assertFalse(next(call for call in self.calls if call['task'] == 'ordinary-head')['priority'])
        self.assertIn(('ordinary-head', True), self.engine.request_classes,
                      'Only engine reacquisition inherits priority')
        for event in helpers.values():
            event.set()
        await asyncio.gather(*self.tasks)
        self.assertEqual([call['task'] for call in self.calls], ['active', 'ordinary-head', 'known-inverse'])
        self.assertEqual(known.result(), 8)
        self.assert_clean(2)

    async def test_ordinary_state_continuation_requeues_as_ordinary_with_same_identity_and_private_input(self):
        entered, resume = self.event(), self.event()
        original, frames = deepcopy(STATE), []
        async def exchange(_process, payload):
            name = asyncio.current_task().get_name()
            frames.append((name, work._bootstrap.get(), deepcopy(payload)))
            if name == 'ordinary' and payload['operation'] != 'resume':
                return {'id': payload['id'], 'stateRequest': [
                    {'poolId': STATE['id'], 'wordPositions': [0], 'ticks': []}]}
            return {'id': payload['id'], 'result': {'amountIn': '8', 'amountOut': '7'}}
        async def observe(requests):
            self.assertFalse(work._bootstrap.get())
            self.assertFalse(self.worker.lock.locked())
            entered.set()
            await resume.wait()
            return [{'id': requests[0]['poolId'], 'bitmapWords': [{'wordPosition': 0, 'bitmap': '0'}], 'ticks': []}]
        with patch.object(sdk_bridge, 'exchange', exchange):
            ordinary = self.start(self.quote(7, on_state=observe), 'ordinary')
            await asyncio.wait_for(entered.wait(), 3)
            await self.worker.lock.acquire()
            try:
                resume.set()
                await until(lambda: len(self.worker.lock._ordinary) == 1)
                known = self.start(self.inverse(), 'known')
                await until(lambda: len(self.worker.lock._priority) == 1)
            finally:
                self.worker.lock.release()
            await asyncio.gather(ordinary, known)
        self.assertEqual([name for name, _, _ in frames], ['ordinary', 'known', 'ordinary'])
        self.assertEqual([priority for _, priority, _ in frames], [False, True, False])
        self.assertEqual([row['id'] for _, _, row in frames], ['1', '2', '1'])
        self.assertEqual(frames[-1][2]['operation'], 'resume')
        self.assertEqual(frames[-1][2]['coverage'], [
            {'id': STATE['id'], 'bitmapWords': [{'wordPosition': 0, 'bitmap': '0'}], 'ticks': []}])
        self.assertEqual(STATE, original)
        self.assert_clean()

    async def test_cancelled_waiters_leave_other_sdk_classes_and_fifo_intact(self):
        await self.worker.lock.acquire()
        try:
            ordinary = [self.start(self.quote(100 + i), f'ordinary-{i}') for i in range(2)]
            known = [self.start(self.quote(200 + i, priority=True), f'known-{i}') for i in range(2)]
            await until(lambda: len(self.worker.lock._ordinary) == len(self.worker.lock._priority) == 2)
            ordinary[0].cancel()
            known[0].cancel()
            outcomes = await asyncio.gather(ordinary[0], known[0], return_exceptions=True)
            self.assertTrue(all(isinstance(outcome, asyncio.CancelledError) for outcome in outcomes))
            self.assertEqual((len(self.worker.lock._ordinary), len(self.worker.lock._priority)), (1, 1))
            self.assertEqual(self.engine._value, 8)
            self.assertEqual(self.calls, [])
        finally:
            self.worker.lock.release()
        await asyncio.gather(ordinary[1], known[1])
        self.assertEqual([call['task'] for call in self.calls], ['known-1', 'ordinary-1'])
        self.assert_clean()

    async def test_cancelled_sdk_grant_restores_single_capacity_in_both_classes(self):
        restored = []
        async def job(priority):
            try:
                return await self.quote(7, priority=priority)
            finally:
                restored.append((work._bootstrap.get(), work._current.get()))
        for priority in (False, True):
            with self.subTest(priority=priority):
                await self.worker.lock.acquire()
                task = self.start(job(priority), 'cancelled-grant')
                queue = self.worker.lock._priority if priority else self.worker.lock._ordinary
                await until(lambda: bool(queue))
                self.worker.lock.release()
                task.cancel()  # The SDK permit was granted, but the task has not resumed.
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(self.calls, [])
                self.assert_clean()
        self.assertEqual(restored, [(False, None), (False, None)])

    async def test_cancel_during_donated_engine_reacquire_releases_sdk_lock_and_preserves_foreign_engine(self):
        self.engine = ObservedEngine(1)
        await self.worker.lock.acquire()
        task = self.start(self.quote(7), 'cancelled-reacquire')
        await until(lambda: len(self.worker.lock._ordinary) == 1)
        await self.engine.acquire()  # Independent holder; it must survive cancellation.
        self.worker.lock.release()
        await until(lambda: bool(self.engine._priority))
        self.assertTrue(self.worker.lock.locked())
        self.assertFalse(self.engine._ordinary)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.engine._value, 0)
        self.assertEqual(self.worker.lock._value, 1)
        self.assertFalse(self.worker.lock.locked())
        self.assertEqual(self.calls, [])
        self.engine.release()
        self.assert_clean(1)

    async def test_candidate_reservation_restore_keeps_original_class_and_cancellation_ownership(self):
        reservation = ObservedReservation()
        await reservation.acquire()
        lease = work.CandidateWork(reservation, asyncio.Event())
        await self.worker.lock.acquire()
        async def evaluate(_index, _value):
            async with work.engine_work(self.engine):
                return await self.worker.request({'operation': 'quote', 'mode': 'exactIn',
                    'amount': '7', 'pools': [STATE], 'poolId': STATE['id'], 'zeroForOne': True})
        task = self.start(work.run_candidate(lease, evaluate, 0, None), 'candidate')
        await until(lambda: len(self.worker.lock._ordinary) == 1)
        await reservation.acquire()  # An independent scheduler owner.
        self.worker.lock.release()
        await until(lambda: bool(reservation._waiters))
        self.assertTrue(self.worker.lock.locked())
        self.assertFalse(reservation.request_classes[-1], 'Donation must not broaden scheduler restoration')
        self.assertEqual(self.engine._value, 8)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(reservation._value, 0)
        self.assertTrue(lease.closed)
        self.assertFalse(lease.owned)
        self.assertEqual(lease.engines, [])
        self.assertEqual(self.calls, [])
        reservation.release()
        self.assertEqual(reservation._value, 1)
        self.assert_clean()


if __name__ == '__main__':
    unittest.main()
