"""Completion, fairness and ownership of the common route scheduler."""
import asyncio
import unittest
from unittest.mock import patch

from cybergold_candidate import route_scheduler

from cybergold_candidate.route_scheduler import schedule_routes
from cybergold_candidate.route_work_slots import engine_work, required_state_wait
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.quote_budget import QuoteBudget, budget_context


class RouteScheduler(unittest.IsolatedAsyncioTestCase):
    async def test_slow_leg_iterator_and_discovery_do_not_hold_other_leg_result(self):
        release, completed, started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        closed = []
        async def feed(index):
            try:
                if index == 0:
                    started.set()
                    await release.wait()
                yield index
            finally:
                closed.append(index)
        async def discover():
            await release.wait()
        async def price(index, _row):
            if index == 1:
                completed.set()
        task = asyncio.create_task(schedule_routes(lambda _expanded: [feed(0), feed(1)], price,
                                                   discover=discover))
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(completed.wait(), 1)
        self.assertFalse(task.done())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertCountEqual(closed, [0, 1])

    async def test_eight_owned_jobs_and_fair_first_turns_with_completion_callback(self):
        release, full = asyncio.Event(), asyncio.Event()
        running = peak = callbacks = 0
        order = []
        async def feed(index):
            for number in range(10):
                yield (index, number)
        async def price(index, row):
            nonlocal running, peak
            order.append(row)
            running += 1
            peak = max(peak, running)
            if running == 8:
                full.set()
            try:
                await release.wait()
            finally:
                running -= 1
        async def done():
            nonlocal callbacks
            callbacks += 1
        task = asyncio.create_task(schedule_routes(lambda _expanded: [feed(0), feed(1)], price,
                                                   on_completed=done))
        await asyncio.wait_for(full.wait(), 1)
        self.assertEqual(peak, 8)
        self.assertEqual(order[:2], [(0, 0), (1, 0)])
        release.set()
        await asyncio.wait_for(task, 1)
        self.assertEqual(peak, 8)
        self.assertEqual(len(order), 20)
        self.assertGreater(callbacks, 0)
        self.assertEqual(running, 0)

    async def test_expansion_restarts_feeds_without_cancelling_active_quote(self):
        discover_now, quote_started, released = asyncio.Event(), asyncio.Event(), asyncio.Event()
        finished = []
        async def feed(expanded):
            yield 'new' if expanded else 'cached'
        async def discover():
            await discover_now.wait()
        async def price(_index, row):
            if row == 'cached':
                quote_started.set()
                await released.wait()
            finished.append(row)
        task = asyncio.create_task(schedule_routes(lambda expanded: [feed(expanded)], price,
                                                   discover=discover))
        await asyncio.wait_for(quote_started.wait(), 1)
        discover_now.set()
        while 'new' not in finished:
            await asyncio.sleep(0)
        self.assertFalse(task.done())
        released.set()
        await asyncio.wait_for(task, 1)
        self.assertCountEqual(finished, ['cached', 'new'])

    async def test_context_disproof_drains_owned_quotes_and_discovery(self):
        entered, drained = asyncio.Event(), []
        async def feed():
            yield 'held'
            yield 'invalid'
        async def discover():
            try:
                await asyncio.Event().wait()
            finally:
                drained.append('discovery')
        async def price(_index, row):
            if row == 'held':
                try:
                    entered.set()
                    await asyncio.Event().wait()
                finally:
                    drained.append('quote')
            await entered.wait()
            raise SnapshotChanged('changed')
        with self.assertRaisesRegex(SnapshotChanged, 'changed'):
            await asyncio.wait_for(schedule_routes(lambda _: [feed()], price, discover=discover), 1)
        self.assertCountEqual(drained, ['quote', 'discovery'])

    async def test_policy_stop_preserves_context_disproof_from_owned_drain(self):
        started, drained = asyncio.Event(), asyncio.Event()
        async def feed():
            yield 'canonical-read'
        async def price(_index, _row):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                drained.set()
                raise SnapshotChanged('owned canonical read disproved while draining') from None
        budget = QuoteBudget()
        with budget_context(budget):
            task = asyncio.create_task(budget.discovery(schedule_routes(lambda _: [feed()], price)))
        await asyncio.wait_for(started.wait(), 1)
        budget.finish_selection('timeout')
        with self.assertRaisesRegex(SnapshotChanged, 'owned canonical read disproved'):
            await asyncio.wait_for(task, 1)
        self.assertTrue(drained.is_set())

    async def test_ordinary_caller_cancel_drains_without_changing_cancellation(self):
        started, drained = asyncio.Event(), asyncio.Event()
        async def feed():
            yield 'read'
        async def price(_index, _row):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        budget = QuoteBudget()
        with budget_context(budget):
            task = asyncio.create_task(budget.discovery(schedule_routes(lambda _: [feed()], price)))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(drained.is_set())
        self.assertFalse(budget.stop.is_set())

    async def test_simultaneously_completed_disproof_outranks_ordinary_tail_error(self):
        async def feed(value):
            yield value
        async def price(_index, row):
            if row == 'ordinary':
                raise ValueError('ordinary tail failed')
            raise SnapshotChanged('completed canonical disproof')
        with self.assertRaisesRegex(SnapshotChanged, 'completed canonical disproof'):
            await schedule_routes(lambda _: [feed('ordinary'), feed('disproof')], price)


    async def test_pending_feed_admits_work_while_another_candidate_is_parked(self):
        parked, offer_next, next_started, finish = (asyncio.Event() for _ in range(4))
        async def feed():
            yield 'parked'
            await offer_next.wait()
            yield 'next'
        async def price(_index, row):
            if row == 'parked':
                async with required_state_wait():
                    parked.set()
                    await finish.wait()
            else:
                next_started.set()
        task = asyncio.create_task(schedule_routes(lambda _: [feed()], price, limit=1))
        try:
            await asyncio.wait_for(parked.wait(), 1)
            offer_next.set()
            await asyncio.wait_for(next_started.wait(), 1)
            self.assertFalse(task.done())
            finish.set()
            await asyncio.wait_for(task, 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_ready_work_is_admitted_when_active_candidate_releases_capacity(self):
        started, offered, blocked, begin_read, next_started, finish = (asyncio.Event() for _ in range(6))
        original_wait = asyncio.wait
        async def observe_wait(waiters, **options):
            # The first wait after this offered feed result has been consumed
            # has one active job and ready work blocked on its pricing permit.
            if offered.is_set():
                blocked.set()
            return await original_wait(waiters, **options)
        async def feed():
            yield 'first'
            offered.set()
            yield 'next'
        async def price(_index, row):
            if row == 'first':
                started.set()
                await begin_read.wait()
                async with required_state_wait():
                    await finish.wait()
            else:
                next_started.set()
        with patch.object(route_scheduler.asyncio, 'wait', observe_wait):
            task = asyncio.create_task(schedule_routes(lambda _: [feed()], price, limit=1))
            try:
                await asyncio.wait_for(started.wait(), 1)
                await asyncio.wait_for(blocked.wait(), 1)
                self.assertFalse(next_started.is_set())
                begin_read.set()
                await asyncio.wait_for(next_started.wait(), 1)
                self.assertFalse(task.done())
                finish.set()
                await asyncio.wait_for(task, 1)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_cancel_drains_parked_work_and_pending_feed(self):
        parked, feed_waiting, work_drained, feed_drained = (asyncio.Event() for _ in range(4))
        engine = asyncio.Semaphore(1)
        async def feed():
            try:
                yield 'read'
                feed_waiting.set()
                await asyncio.Event().wait()
            finally:
                feed_drained.set()
        async def price(_index, _row):
            try:
                async with engine_work(engine):
                    async with required_state_wait():
                        parked.set()
                        await asyncio.Event().wait()
            finally:
                work_drained.set()
        task = asyncio.create_task(schedule_routes(lambda _: [feed()], price, limit=1))
        try:
            await asyncio.wait_for(parked.wait(), 1)
            await asyncio.wait_for(feed_waiting.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(work_drained.is_set())
            self.assertTrue(feed_drained.is_set())
            self.assertEqual(engine._value, 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)



if __name__ == '__main__':
    unittest.main()
