"""Completion, fairness and ownership of the common route scheduler."""
import asyncio
import unittest
from unittest.mock import patch

from cybergold_candidate import route_scheduler as scheduler
from cybergold_candidate.route_work_slots import PricingSlots, engine_work, required_state_wait

from cybergold_candidate.route_scheduler import schedule_routes
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

    async def test_parked_work_keeps_all_candidates_without_repeated_wait_registration(self):
        release, parked = asyncio.Event(), asyncio.Event()
        pricing = PricingSlots(8)
        admitted, finished, closed = [], [], []
        owned = set()
        async def feed(index):
            try:
                for number in range(16):
                    yield index, number
            finally:
                closed.append(index)
        async def price(index, row):
            owned.add(asyncio.current_task())
            admitted.append(row)
            async with engine_work(pricing):
                async with required_state_wait():
                    if len(admitted) == 48:
                        parked.set()
                    await release.wait()
                finished.append((index, row))
        with patch.object(scheduler.asyncio, 'wait', wraps=asyncio.wait) as registrations:
            task = asyncio.create_task(schedule_routes(lambda _: [feed(index) for index in range(3)], price))
            try:
                await asyncio.wait_for(parked.wait(), 1)
                self.assertEqual(admitted[:3], [(0, 0), (1, 0), (2, 0)])
                self.assertEqual(len(owned), 48)
                self.assertFalse(task.done())
                self.assertEqual(finished, [])
                self.assertEqual(pricing._value, 8)
                release.set()
                await asyncio.wait_for(task, 1)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            # Allow other completion implementations, but keep registration
            # work linear in candidates and their feed advances.
            waiter_visits = sum(len(call.args[0]) for call in registrations.await_args_list)
            self.assertLessEqual(waiter_visits, 2 * len(owned) + len(closed))
        self.assertEqual(sorted(finished), [(index, (index, number)) for index in range(3) for number in range(16)])
        self.assertCountEqual(closed, [0, 1, 2])
        self.assertTrue(all(task.done() for task in owned))
        self.assertEqual((pricing._value, len(pricing._ordinary), len(pricing._priority)), (8, 0, 0))

    async def test_already_set_capacity_event_gives_ready_peer_a_turn(self):
        peer, observed = [], []
        original_event = asyncio.Event
        class AlreadySetEvent(original_event):
            def __init__(self):
                super().__init__()
                self.set()
            async def wait(self):
                if self.is_set() and not observed:
                    observed.append(bool(peer))
                return await super().wait()
        async def feed():
            yield 'ready'
        completed = []
        async def price(_index, row):
            completed.append(row)
        # Stay in this task: wrapping the scheduler in wait_for/create_task
        # would itself give the peer a turn before the tested boundary.
        asyncio.get_running_loop().call_soon(peer.append, 'ran')
        with patch.object(scheduler.asyncio, 'Event', AlreadySetEvent):
            async with asyncio.timeout(1):
                await schedule_routes(lambda _: [feed()], price)
        self.assertEqual(observed, [True])
        self.assertEqual(completed, ['ready'])

    async def test_discovery_replacement_drops_old_feed_notifications_not_active_work(self):
        expand, old_started, pending_started, new_finished, release = (asyncio.Event() for _ in range(5))
        finished, closed = [], []
        async def cached(index):
            try:
                if index == 0:
                    yield 'old-held'
                pending_started.set()
                await asyncio.Event().wait()
            finally:
                closed.append(('cached', index))
        async def fresh(index):
            try:
                yield 'new-' + str(index)
            finally:
                closed.append(('fresh', index))
        async def discover():
            await expand.wait()
        async def price(_index, row):
            if row == 'old-held':
                old_started.set()
                await release.wait()
            finished.append(row)
            if 'new-0' in finished and 'new-1' in finished:
                new_finished.set()
        task = asyncio.create_task(schedule_routes(
            lambda expanded: [fresh(index) if expanded else cached(index) for index in range(2)],
            price, discover=discover))
        try:
            await asyncio.wait_for(old_started.wait(), 1)
            await asyncio.wait_for(pending_started.wait(), 1)
            expand.set()
            await asyncio.wait_for(new_finished.wait(), 1)
            self.assertNotIn('old-held', finished)
            self.assertFalse(task.done())
            release.set()
            await asyncio.wait_for(task, 1)
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertCountEqual(finished, ['old-held', 'new-0', 'new-1'])
        self.assertCountEqual(closed, [('cached', 0), ('cached', 1), ('fresh', 0), ('fresh', 1)])

    async def test_caller_cancellation_drains_every_parked_candidate_and_feed(self):
        parked = asyncio.Event()
        pricing = PricingSlots(8)
        admitted, drained, closed = [], [], []
        owned = set()
        async def feed():
            try:
                for number in range(32):
                    yield number
                await asyncio.Event().wait()
            finally:
                closed.append('feed')
        async def price(_index, number):
            owned.add(asyncio.current_task())
            admitted.append(number)
            try:
                async with engine_work(pricing):
                    async with required_state_wait():
                        if len(admitted) == 32:
                            parked.set()
                        await asyncio.Event().wait()
            finally:
                drained.append(number)
        task = asyncio.create_task(schedule_routes(lambda _: [feed()], price))
        try:
            await asyncio.wait_for(parked.wait(), 1)
            self.assertEqual(pricing._value, 8)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(sorted(drained), list(range(32)))
        self.assertEqual(closed, ['feed'])
        self.assertTrue(all(task.done() for task in owned))
        self.assertEqual((pricing._value, len(pricing._ordinary), len(pricing._priority)), (8, 0, 0))

    async def test_ordinary_error_is_preserved_after_parked_siblings_drain(self):
        parked = asyncio.Event()
        entered, drained = [], []
        failure = ValueError('ordinary candidate failed')
        async def feed():
            for row in ('held-0', 'held-1', 'failed'):
                yield row
        async def price(_index, row):
            if row == 'failed':
                await parked.wait()
                raise failure
            entered.append(row)
            try:
                async with required_state_wait():
                    if len(entered) == 2:
                        parked.set()
                    await asyncio.Event().wait()
            finally:
                drained.append(row)
        with self.assertRaises(ValueError) as caught:
            await asyncio.wait_for(schedule_routes(lambda _: [feed()], price), 1)
        self.assertIs(caught.exception, failure)
        self.assertCountEqual(drained, ['held-0', 'held-1'])


if __name__ == '__main__':
    unittest.main()
