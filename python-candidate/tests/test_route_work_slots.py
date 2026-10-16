"""Inert candidate permit ownership, suspension and cleanup controls."""
import asyncio
from contextlib import contextmanager
import unittest
from unittest.mock import patch

from cybergold_candidate import route_work_slots as work
from cybergold_candidate.route_scheduler import schedule_routes
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.shared_reads import SharedReads


@contextmanager
def leases():
    rows=[]
    original=work.CandidateWork.__init__
    def initialize(self,*args):
        original(self,*args);rows.append(self)
    with patch.object(work.CandidateWork,'__init__',initialize):
        yield rows


async def feed(values):
    for value in values:
        yield value


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


class RouteWorkSlotsTests(unittest.IsolatedAsyncioTestCase):
    async def test_standalone_scope_yields_only_its_original_engine_permit(self):
        semaphore=asyncio.Semaphore(1)
        self.assertIsNone(work._current.get())
        async with work.engine_work(semaphore):
            lease=work._current.get()
            self.assertIs(lease.owner,asyncio.current_task())
            self.assertIsNone(lease.slots)
            self.assertIsNone(lease.changed)
            self.assertTrue(semaphore.locked())
            async with work.required_state_wait():
                self.assertFalse(semaphore.locked())
                self.assertFalse(lease.owned)
            self.assertTrue(semaphore.locked())
            self.assertTrue(lease.owned)
        self.assertTrue(lease.closed)
        self.assertEqual(lease.engines,[])
        self.assertIsNone(work._current.get())
        self.assertEqual(semaphore._value,1)

    async def test_nested_engine_scopes_share_owned_permits_and_restore_context(self):
        first,second=asyncio.Semaphore(1),asyncio.Semaphore(1)
        async with work.engine_work(first):
            lease=work._current.get()
            async with work.engine_work(second):
                self.assertIs(work._current.get(),lease)
                async with work.required_state_wait():
                    self.assertEqual((first._value,second._value),(1,1))
                self.assertEqual((first._value,second._value),(0,0))
            self.assertEqual((first._value,second._value),(0,1))
            self.assertFalse(lease.closed)
        self.assertEqual((first._value,second._value),(1,1))
        self.assertTrue(lease.closed)
        self.assertIsNone(work._current.get())

    async def test_foreign_child_engine_scope_owns_only_its_new_permit(self):
        parent_engine,child_engine=asyncio.Semaphore(1),asyncio.Semaphore(1)
        async with work.engine_work(parent_engine):
            parent=work._current.get()
            async def child():
                self.assertIs(work._current.get(),parent)
                async with work.engine_work(child_engine):
                    own=work._current.get()
                    self.assertIsNot(own,parent)
                    self.assertIs(own.owner,asyncio.current_task())
                    async with work.required_state_wait():
                        self.assertEqual((parent_engine._value,child_engine._value),(0,1))
                        self.assertTrue(parent.owned)
                    self.assertEqual(child_engine._value,0)
                self.assertTrue(own.closed)
                self.assertIs(work._current.get(),parent)
                async with work.required_state_wait():
                    self.assertEqual(parent_engine._value,0)
            await asyncio.create_task(child())
            self.assertIs(work._current.get(),parent)
        self.assertEqual((parent_engine._value,child_engine._value),(1,1))

    async def test_pricing_inside_parked_callback_gets_fresh_no_slot_lease(self):
        outer_engine,inner_engine=asyncio.Semaphore(1),asyncio.Semaphore(1)
        async def evaluate(index,value):
            async with work.engine_work(outer_engine):
                outer=work._current.get()
                async with work.required_state_wait():
                    self.assertFalse(outer.owned)
                    async with work.engine_work(inner_engine):
                        inner=work._current.get()
                        self.assertIsNot(inner,outer)
                        self.assertIsNone(inner.slots)
                        async with work.required_state_wait():
                            self.assertEqual((outer_engine._value,inner_engine._value),(1,1))
                            self.assertFalse(outer.owned)
                        self.assertEqual(inner_engine._value,0)
                    self.assertTrue(inner.closed)
                    self.assertIs(work._current.get(),outer)
                    self.assertFalse(outer.owned)
                self.assertTrue(outer.owned)
                self.assertEqual(outer_engine._value,0)
        with leases() as rows:
            await schedule_routes(lambda _:[feed([1])],evaluate,limit=1)
        self.assertEqual((rows[0].slots._value,outer_engine._value,inner_engine._value),(1,1,1))
        self.assertIsNone(work._current.get())

    async def standalone_first_acquire_cancel(self,after_grant):
        semaphore=asyncio.Semaphore(0)
        restored=[]
        async def blocked():
            try:
                async with work.engine_work(semaphore):
                    self.fail('Cancelled acquisition must not enter pricing')
            finally:
                restored.append(work._current.get())
        task=asyncio.create_task(blocked())
        await until(lambda:bool(semaphore._waiters))
        if after_grant:semaphore.release()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(restored,[None])
        self.assertEqual(semaphore._value,int(after_grant))

    async def test_standalone_cancel_before_first_engine_grant_resets_context(self):
        await self.standalone_first_acquire_cancel(False)

    async def test_standalone_cancel_after_first_engine_grant_resets_context(self):
        await self.standalone_first_acquire_cancel(True)

    async def test_standalone_partial_nested_reacquire_drains_only_owned_grants(self):
        first,second=asyncio.Semaphore(1),asyncio.Semaphore(1)
        parked,release=asyncio.Event(),asyncio.Event();captured=[]
        async def price():
            async with work.engine_work(first):
                captured.append(work._current.get())
                async with work.engine_work(second):
                    async with work.required_state_wait():
                        parked.set();await release.wait()
        task=asyncio.create_task(price())
        try:
            await parked.wait();await second.acquire()
            release.set();await until(lambda:bool(second._waiters))
            self.assertEqual(first._value,0,'Engine entry order must reacquire first before second')
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertEqual((first._value,second._value),(1,0))
            self.assertTrue(captured[0].closed)
            self.assertFalse(captured[0].owned)
            self.assertEqual(captured[0].engines,[])
        finally:
            release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)
            second.release()
        self.assertEqual((first._value,second._value),(1,1))

    async def test_cancelled_nested_entry_keeps_active_outer_permit(self):
        first,second=asyncio.Semaphore(1),asyncio.Semaphore(0)
        captured=[]
        async def price():
            async with work.engine_work(first):
                lease=work._current.get();captured.append(lease)
                try:
                    async with work.engine_work(second):self.fail('No second permit is available')
                except asyncio.CancelledError:
                    self.assertIs(work._current.get(),lease)
                    self.assertFalse(lease.closed)
                    self.assertTrue(lease.owned)
                    self.assertEqual(first._value,0)
                    self.assertEqual(len(lease.engines),1)
        task=asyncio.create_task(price());await until(lambda:bool(second._waiters));task.cancel();await task
        self.assertEqual((first._value,second._value),(1,0))
        self.assertTrue(captured[0].closed)

    async def test_zero_limit_retains_no_work_termination(self):
        called=[]
        await schedule_routes(lambda _:[feed([1])],lambda i,v:called.append(v),limit=0)
        self.assertEqual(called,[])

    async def test_eager_task_factory_initializes_exact_candidate_owner(self):
        loop=asyncio.get_running_loop();previous=loop.get_task_factory()
        try:
            loop.set_task_factory(asyncio.eager_task_factory)
            observed=[]
            async def evaluate(i,v):
                lease=work._current.get()
                observed.append(lease.owner is asyncio.current_task())
                async with work.required_state_wait():
                    observed.append(not lease.owned)
            await schedule_routes(lambda _:[feed([1])],evaluate,limit=1)
            self.assertEqual(observed,[True,True])
        finally:loop.set_task_factory(previous)

    async def test_eight_parked_allow_ninth_without_losing_any_candidate(self):
        semaphore=asyncio.Semaphore(8);release=asyncio.Event();all_parked=asyncio.Event();fast=asyncio.Event()
        parked=set();done=[];peaks=[]
        async def evaluate(index,value):
            async with work.engine_work(semaphore):
                if value<8:
                    async with work.required_state_wait():
                        parked.add(value)
                        if len(parked)==8:all_parked.set()
                        await release.wait()
                else:fast.set()
                done.append(value)
                peaks.append(sum(row.owned for row in rows))
        with leases() as rows:
            task=asyncio.create_task(schedule_routes(lambda _:[feed(range(9))],evaluate))
            try:
                await until(lambda:all_parked.is_set() and fast.is_set())
                self.assertEqual(done,[8]);self.assertEqual(len(parked),8)
                self.assertEqual(len(rows),9)
                release.set();await task
                self.assertEqual(sorted(done),list(range(9)))
                self.assertTrue(all(row.closed and not row.owned for row in rows))
                self.assertEqual(rows[0].slots._value,8)
                self.assertLessEqual(max(peaks),8)
                self.assertEqual(semaphore._value,8)
            finally:
                release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_foreign_inherited_child_cannot_release_parent_permits(self):
        semaphore=asyncio.Semaphore(1)
        async def evaluate(i,v):
            async with work.engine_work(semaphore):
                lease=work._current.get()
                async def foreign():
                    self.assertIs(work._current.get(),lease)
                    async with work.required_state_wait():
                        self.assertTrue(lease.owned)
                        self.assertTrue(semaphore.locked())
                await asyncio.create_task(foreign())
                self.assertTrue(lease.owned)
        with leases() as rows:
            await schedule_routes(lambda _:[feed([1])],evaluate,limit=1)
        self.assertEqual(rows[0].slots._value,1)
        self.assertEqual(semaphore._value,1)

    async def test_cancel_before_first_turn_releases_reserved_permit(self):
        slots=asyncio.Semaphore(1);await slots.acquire()
        lease=work.CandidateWork(slots,asyncio.Event())
        async def unexpected(*args):self.fail('Cancelled task must not start')
        task=asyncio.create_task(work.run_candidate(lease,unexpected,0,None))
        task.add_done_callback(lambda _:lease.close());task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        self.assertTrue(lease.closed);self.assertFalse(lease.owned)
        self.assertEqual(slots._value,1)

    async def test_ordinary_required_read_error_does_not_reacquire_or_overrelease(self):
        semaphore=asyncio.Semaphore(1);expected=OSError('required read failed')
        async def evaluate(i,v):
            async with work.engine_work(semaphore):
                async with work.required_state_wait():raise expected
        with leases() as rows:
            with self.assertRaises(OSError) as raised:
                await schedule_routes(lambda _:[feed([1])],evaluate,limit=1)
        self.assertIs(raised.exception,expected)
        self.assertEqual((rows[0].slots._value,semaphore._value),(1,1))
        self.assertTrue(rows[0].closed)

    async def test_cancel_during_engine_reacquire_preserves_foreign_engine_holder(self):
        semaphore=asyncio.Semaphore(1);entered=asyncio.Event();release=asyncio.Event()
        async def evaluate(i,v):
            async with work.engine_work(semaphore):
                async with work.required_state_wait():
                    entered.set();await release.wait()
        with leases() as rows:
            task=asyncio.create_task(schedule_routes(lambda _:[feed([1])],evaluate,limit=1))
            try:
                await entered.wait();await semaphore.acquire()
                release.set();await until(lambda:rows[0].owned)
                self.assertTrue(semaphore.locked())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                self.assertEqual(rows[0].slots._value,1)
                self.assertEqual(semaphore._value,0)
                semaphore.release();self.assertEqual(semaphore._value,1)
            finally:
                release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_cancel_after_scheduler_grant_notifies_restored_capacity(self):
        slots=asyncio.Semaphore(0);changed=asyncio.Event()
        lease=work.CandidateWork(slots,changed);lease.owned=False
        task=asyncio.create_task(lease.acquire())
        await until(lambda:bool(slots._waiters))
        slots.release();changed.clear();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(slots._value,1)
        self.assertFalse(lease.owned)
        self.assertTrue(changed.is_set(),'Cancelled grant restored work capacity but did not notify scheduler')

    async def test_parked_snapshot_disproof_wins_during_owner_cancellation(self):
        semaphore=asyncio.Semaphore(2);parked=asyncio.Event()
        async def evaluate(i,v):
            async with work.engine_work(semaphore):
                try:
                    async with work.required_state_wait():
                        parked.set();await asyncio.Event().wait()
                except asyncio.CancelledError:
                    raise SnapshotChanged('canonical disproof during drain')
        with leases() as rows:
            task=asyncio.create_task(schedule_routes(lambda _:[feed([1])],evaluate,limit=2))
            await parked.wait();task.cancel()
            with self.assertRaises(SnapshotChanged):await task
        self.assertEqual((rows[0].slots._value,semaphore._value),(2,2))
        self.assertTrue(all(row.closed for row in rows))

    async def test_shared_required_read_foreign_subscriber_survives_owner_cancel(self):
        shared=SharedReads();entered=asyncio.Event();release=asyncio.Event();semaphore=asyncio.Semaphore(1)
        calls=[]
        async def produce():
            calls.append('one getter');entered.set();await release.wait();return 7
        foreign=asyncio.create_task(shared.one('same',produce));await entered.wait()
        async def evaluate(i,v):
            async with work.engine_work(semaphore):
                async with work.required_state_wait():return await shared.one('same',produce)
        with leases() as rows:
            task=asyncio.create_task(schedule_routes(lambda _:[feed([1])],evaluate,limit=1))
            await until(lambda:any(entry.users==2 for entry in shared.pending.values()))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertFalse(foreign.done());release.set();self.assertEqual(await foreign,7)
            self.assertEqual(calls,['one getter'])
            self.assertEqual((rows[0].slots._value,semaphore._value),(1,1))
            self.assertEqual(shared.pending,{})
        await shared.close()

    async def test_multi_leg_coverage_and_fifo_resume_complete_all_rows(self):
        semaphore=asyncio.Semaphore(8);done=[]
        async def evaluate(index,value):
            async with work.engine_work(semaphore):
                async with work.required_state_wait():await asyncio.sleep(0)
                done.append((index,value))
        with leases() as rows:
            await schedule_routes(lambda _:[feed(range(5)),feed(range(5))],evaluate)
        self.assertEqual(sorted(done),[(i,v) for i in range(2) for v in range(5)])
        self.assertTrue(all(row.closed for row in rows))
        self.assertEqual(rows[0].slots._value,8);self.assertEqual(semaphore._value,8)


if __name__=='__main__':unittest.main()
