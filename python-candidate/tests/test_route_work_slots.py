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
    async def test_direct_no_lease_retains_the_original_semaphore(self):
        semaphore=asyncio.Semaphore(1)
        async with work.engine_work(semaphore):
            self.assertTrue(semaphore.locked())
            async with work.required_state_wait():
                self.assertTrue(semaphore.locked())
        self.assertEqual(semaphore._value,1)

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
