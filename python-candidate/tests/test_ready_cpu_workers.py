"""Ready replacement capacity and ownership, including actual subprocess drain."""
import asyncio
from contextvars import ContextVar
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter import cpu
from cybergold_candidate.quote_flow import Flow, current_flow, flow_scope


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate(): await asyncio.sleep(0)


context = ContextVar('ready-worker-test', default=None)


class Process:
    def __init__(self, owner):
        self.returncode = None
        self.owner = owner
        self.stdout = self
        self.terminated = False
        owner.processes.append(self)
        owner.peak_processes = max(owner.peak_processes, sum(p.returncode is None for p in owner.processes))
    async def readline(self): return b'{"ready":true}\n'
    def terminate(self): self.terminated = True; self.returncode = -15
    async def communicate(self):
        if self.returncode is None: self.returncode = 0
        await asyncio.sleep(0)
        return b'', b''


class Factory:
    def __init__(self):
        self.workers, self.processes = [], []
        self.peak_processes = self.active = self.peak_jobs = 0
        self.hold_new = False
        self.fail_indices = set()
    def __call__(self):
        owner = self
        class Worker:
            def __init__(self):
                self.index = len(owner.workers)
                self.process = None
                self.starting, self.ready = asyncio.Event(), asyncio.Event()
                self.gate = asyncio.Event()
                if not owner.hold_new: self.gate.set()
                self.job_entered, self.job_release = asyncio.Event(), asyncio.Event()
                self.job_release.set()
                self.contexts = []
                owner.workers.append(self)
            async def start(self):
                if self.process is not None and self.process.returncode is None: return
                self.contexts.append((current_flow(), context.get()))
                self.process = Process(owner); self.starting.set()
                try:
                    await self.gate.wait()
                    if self.index in owner.fail_indices: raise ValueError('fixture startup failure')
                    self.ready.set()
                except BaseException:
                    await self.close()
                    raise
            async def close(self):
                process, self.process = self.process, None
                if process is not None:
                    if process.returncode is None: process.terminate()
                    await process.communicate()
            async def encode_plan(self, value):
                await self.start()
                owner.active += 1
                owner.peak_jobs = max(owner.peak_jobs, owner.active)
                self.job_entered.set()
                try:
                    await self.job_release.wait()
                    return value
                except BaseException:
                    await self.close()
                    raise
                finally: owner.active -= 1
        return Worker()


class ReadyPoolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.factory = Factory()
        self.mock = patch.object(cpu, '_Worker', self.factory)
        self.mock.start(); self.addCleanup(self.mock.stop)
        self.pool = cpu.CpuWorkers()
        self.addAsyncCleanup(self.pool.close)
    async def started(self): await self.pool.start()

    async def test_starts_two_slots_and_one_standby_without_admitting_a_third_job(self):
        await self.started()
        self.assertEqual(self.pool.available.qsize(), 2)
        self.assertEqual(len(self.factory.processes), 3)
        for w in self.pool.workers: w.job_release.clear()
        tasks=[asyncio.create_task(self.pool.encode_plan(str(i))) for i in range(3)]
        await until(lambda:self.factory.active==2)
        self.assertFalse(tasks[2].done())
        self.assertFalse(self.pool._spare.job_entered.is_set())
        for w in self.pool.workers: w.job_release.set()
        self.assertEqual(await asyncio.gather(*tasks), ['0','1','2'])
        self.assertEqual(self.factory.peak_jobs, 2)
        self.assertEqual(self.factory.peak_processes, 3)

    async def test_cancelled_job_uses_ready_standby_while_refill_is_blocked(self):
        await self.started()
        first, held = [await self.pool.available.get() for _ in range(2)]
        self.pool.available.put_nowait(first)
        original, standby = first.process, self.pool._spare.process
        first.job_release.clear(); self.factory.hold_new = True
        task=asyncio.create_task(self.pool.encode_plan('cancelled'))
        await first.job_entered.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertIsNotNone(original.returncode)
        self.assertIs(first.process, standby)
        await until(lambda:len(self.factory.workers)==4)
        self.assertFalse(self.factory.workers[3].ready.is_set())
        first.job_release.set()
        self.assertEqual(await self.pool.encode_plan('next'), 'next')
        self.assertIs(first.process, standby)
        self.pool.available.put_nowait(held)
        self.assertEqual(self.factory.peak_processes, 3)

    async def test_burst_cancellation_repairs_only_missing_capacity_and_recovers(self):
        await self.started(); self.factory.hold_new = True
        for w in self.pool.workers:
            w.job_release.clear(); w.gate.clear(); w.starting.clear()
        tasks=[asyncio.create_task(self.pool.encode_plan(i)) for i in range(2)]
        await until(lambda:self.factory.active==2)
        for t in tasks: t.cancel()
        self.assertTrue(all(isinstance(v,asyncio.CancelledError) for v in await asyncio.gather(*tasks,return_exceptions=True)))
        await until(lambda:len(self.factory.workers)==4 and self.pool.workers[1].starting.is_set())
        self.assertEqual(self.pool.available.qsize(), 1)
        # There is one standby, not an unlimited reserve. Missing capacity is
        # queued only after its background startup finishes.
        for w in self.factory.workers: w.gate.set(); w.job_release.set()
        await until(lambda:self.pool.available.qsize()==2 and self.pool._spare is not None)
        self.assertEqual(await self.pool.encode_plan('recovered'), 'recovered')
        self.assertLessEqual(self.factory.peak_processes, 3)

    async def test_maintenance_does_not_capture_cancelled_query_context(self):
        await self.started()
        worker=self.pool.workers[0]; worker.job_release.clear()
        flow=Flow('fixture',sink=lambda _:None); token=context.set('private-query-context')
        try:
            with flow_scope(flow):
                task=asyncio.create_task(self.pool.encode_plan('held'))
                await worker.job_entered.wait(); task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
        finally: context.reset(token)
        await until(lambda:len(self.factory.workers)==4)
        self.assertEqual(self.factory.workers[3].contexts, [(None,None)])

    async def test_close_during_initial_startup_drains_startup_and_all_children(self):
        self.factory.hold_new=True
        for worker in self.pool.workers:worker.gate.clear()
        starting=asyncio.create_task(self.pool.start())
        await until(lambda:len(self.factory.processes)==3)
        await self.pool.close()
        with self.assertRaises(asyncio.CancelledError):await starting
        self.assertTrue(all(p.returncode is not None for p in self.factory.processes))
        self.assertFalse(self.pool._maintenance)
        self.assertIsNone(self.pool._spare_task)

    async def test_optional_standby_failure_does_not_veto_startup_or_ordinary_work(self):
        self.factory.fail_indices.add(2)
        await self.started()
        self.assertIsNone(self.pool._spare)
        self.assertEqual(await self.pool.encode_plan('available'), 'available')
        await until(lambda:self.pool._spare is not None)
        self.assertLessEqual(self.factory.peak_processes, 3)

    async def test_failed_background_slot_repair_preserves_ordinary_error_and_future_recovery(self):
        await self.started()
        first,held=[await self.pool.available.get() for _ in range(2)]
        self.pool.available.put_nowait(first)
        standby,self.pool._spare=self.pool._spare,None
        await standby.close()
        self.factory.hold_new=True;self.factory.fail_indices.add(first.index)
        first.job_release.clear()
        task=asyncio.create_task(self.pool.encode_plan('cancelled'))
        await first.job_entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        await until(lambda:self.pool.available.qsize()==1)
        with self.assertRaisesRegex(ValueError,'fixture startup failure'):
            await self.pool.encode_plan('ordinary failure')
        self.factory.fail_indices.clear();first.job_release.set()
        await until(lambda:self.pool.available.qsize()==1)
        self.assertEqual(await self.pool.encode_plan('recovered'),'recovered')
        self.pool.available.put_nowait(held)

    async def test_primary_startup_failure_drains_all_started_children(self):
        self.factory.fail_indices.add(0)
        with self.assertRaisesRegex(ValueError,'fixture startup failure'): await self.started()
        self.assertTrue(all(p.returncode is not None for p in self.factory.processes))
        self.assertFalse(self.pool._maintenance)

    async def test_shutdown_during_refill_reaps_all_children_and_can_restart(self):
        await self.started(); self.factory.hold_new=True
        worker=self.pool.workers[0]; worker.job_release.clear()
        task=asyncio.create_task(self.pool.encode_plan('cancelled'))
        await worker.job_entered.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        await until(lambda:len(self.factory.workers)==4 and self.factory.workers[3].starting.is_set())
        await self.pool.close()
        self.assertTrue(all(p.returncode is not None for p in self.factory.processes))
        self.assertFalse(self.pool._maintenance)
        self.assertIsNone(self.pool._spare_task)
        self.factory.hold_new=False
        for w in self.factory.workers: w.gate.set(); w.job_release.set()
        await self.pool.start()
        self.assertEqual(await self.pool.encode_plan('reopened'), 'reopened')

    async def test_shutdown_immediately_after_scheduling_refill_leaves_no_task_reference(self):
        await self.started()
        standby,self.pool._spare=self.pool._spare,None
        await standby.close()
        self.pool._ensure_spare()
        await self.pool.close()
        self.assertIsNone(self.pool._spare_task)
        self.assertFalse(self.pool._maintenance)
        self.assertTrue(all(p.returncode is not None for p in self.factory.processes))

    async def test_failed_close_still_drains_other_owned_children(self):
        await self.started()
        first,second=self.pool.workers
        close_first,close_second=first.close,second.close
        entered,release=asyncio.Event(),asyncio.Event()
        async def failed():
            await close_first()
            raise ValueError('fixture close failure')
        async def held():
            entered.set(); await release.wait(); await close_second()
        with patch.object(first,'close',failed),patch.object(second,'close',held):
            closing=asyncio.create_task(self.pool.close())
            await entered.wait(); await asyncio.sleep(0)
            self.assertFalse(closing.done(),'close owns every sibling through its drain')
            release.set()
            with self.assertRaisesRegex(ValueError,'fixture close failure'):await closing
        self.assertTrue(all(p.returncode is not None for p in self.factory.processes))

    async def test_cancelled_waiter_does_not_take_capacity_or_kill_a_worker(self):
        await self.started()
        held=[await self.pool.available.get() for _ in range(2)]
        processes=[w.process for w in held]
        task=asyncio.create_task(self.pool.encode_plan('waiting')); await asyncio.sleep(0); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(all(p.returncode is None for p in processes))
        for w in held:self.pool.available.put_nowait(w)
        self.assertEqual(self.pool.available.qsize(),2)

    async def test_unstarted_script_consumer_keeps_lazy_start_and_no_background_standby(self):
        self.assertEqual(await self.pool.encode_plan('lazy'), 'lazy')
        self.assertEqual(len(self.factory.processes),1)
        self.assertFalse(self.pool._maintenance)
        self.assertIsNone(self.pool._spare)

    async def test_dead_idle_slot_adopts_ready_standby_without_starting_that_slot(self):
        await self.started()
        worker=self.pool.workers[0]; original=worker.process; original.returncode=1
        standby=self.pool._spare.process
        self.assertEqual(await self.pool.encode_plan('recovered'), 'recovered')
        self.assertIs(worker.process,standby)
        self.assertEqual(len(worker.contexts),1)


class SpawnOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_during_creation_recovers_handle_then_terminates_and_reaps(self):
        factory=Factory(); process=Process(factory)
        entered,release=asyncio.Event(),asyncio.Event()
        async def launch(*args,**kwargs): entered.set(); await release.wait(); return process
        worker=cpu._Worker()
        with patch.object(cpu.asyncio,'create_subprocess_exec',launch):
            task=asyncio.create_task(worker.start()); await entered.wait(); task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done(),'creation must remain owned through cancellation')
            release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(process.terminated)
        self.assertIsNone(worker.process)


if __name__=='__main__': unittest.main()
