"""Lazy nominations and SDK-lock parking preserve request-owned work.

These controls execute the real bootstrap, SDK request/lock, Helpers admission
and CandidateWork paths. Events replace worker exchange/chain IO; no child,
network, amount search or elapsed-time performance assertion is involved.
"""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate import route_work_slots as work
from cybergold_candidate import sdk_bridge
from cybergold_candidate.quoter import bootstrap
from cybergold_candidate.quoter.plan_transport import execute_plan_call
from cybergold_candidate.quoter.route_tools import round_robin
from cybergold_candidate.route_scheduler import schedule_routes
from cybergold_candidate.sdk_worker import SdkWorker
from test_hint_union_reuse import crossed, expected_union, signature, A, D
from cybergold_candidate.quoter.candidate_hints import normalize_hints
from cybergold_candidate.quoter.discovery import TopologyCache, topology_scope, route_candidates
from cybergold_candidate.routing_encoding import ZERO


async def reached(event):
    # A test-harness deadlock allowance, never a production quote deadline.
    await asyncio.wait_for(event.wait(), 3)


async def feed(values):
    for value in values:
        yield value


@contextmanager
def captured_leases():
    rows = []
    original = work.CandidateWork.__init__
    def initialize(lease, *args):
        original(lease, *args)
        rows.append(lease)
    with patch.object(work.CandidateWork, '__init__', initialize):
        yield rows


class ObservedLock(asyncio.Lock):
    def __init__(self):
        super().__init__()
        self.waiting = asyncio.Event()
        self.seven_waiters = asyncio.Event()
        self.waits = 0

    async def acquire(self):
        if self.locked():
            self.waits += 1
            self.waiting.set()
            if self.waits == 7:
                self.seven_waiters.set()
        return await super().acquire()


class ObservedSlots(work.PricingSlots):
    def __init__(self, value):
        super().__init__(value)
        self.waiting = asyncio.Event()

    async def acquire(self, span=None):
        if self.locked():
            self.waiting.set()
        return await super().acquire(span)


class ObservedSemaphore(asyncio.Semaphore):
    def __init__(self, value):
        super().__init__(value)
        self.waiting = asyncio.Event()

    async def acquire(self):
        if self.locked():
            self.waiting.set()
        return await super().acquire()


class QuickOfferCopyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = bootstrap.RouteBootstrap([])
        self.key = A.lower(), D.lower(), 100
        self.session._queries[self.key] = []

    async def asyncTearDown(self):
        await self.session.close()

    def offers(self, count):
        return [crossed(origin=f'provider-{index}') for index in range(count)]

    async def quick(self, offers, callback):
        return await self.session._quick_pass(callback, {self.key: offers})

    def iterator(self):
        return round_robin(self.session.offer_feeds(A, D, 100, 'local-block'))

    async def test_first_offer_copies_only_consumed_body_and_close_skips_unused(self):
        offers = self.offers(16)
        original = deepcopy(offers)
        async def consume():
            with patch.object(bootstrap, 'deepcopy', wraps=deepcopy) as copy:
                iterator = self.iterator()
                try:
                    self.assertEqual(copy.call_count, 0, 'Prefix construction must stay lazy')
                    first = next(iterator)
                    self.assertEqual(first, original[0])
                    self.assertEqual(copy.call_count, 1)
                    first['origins'].append('consumer')
                    first['branches'][0]['hops'][0]['pool']['token0']['symbol'] = 'private'
                finally:
                    iterator.close()
                self.assertEqual(copy.call_count, 1, 'Closing unused feeds must not copy them')
        await self.quick(offers, consume)
        self.assertEqual(offers, original)

    async def test_complete_feed_preserves_round_robin_order_origins_and_isolation(self):
        offers = self.offers(3)
        ordinary = self.offers(2)
        for index, value in enumerate(ordinary):
            value['origins'] = [f'ordinary-{index}']
        self.session._completed_offers[self.key] = {
            str(index): (index, value) for index, value in enumerate(ordinary)}
        original = deepcopy((offers, ordinary))
        async def consume():
            with patch.object(bootstrap, 'deepcopy', wraps=deepcopy) as copy:
                iterator = self.iterator()
                try:
                    values = list(iterator)
                finally:
                    iterator.close()
                self.assertEqual(values, [offers[0], offers[1], offers[2], *ordinary])
                self.assertEqual(copy.call_count, 5)
                for value in values:
                    value['origins'].append('private-consumer')
                    value['branches'][0]['hops'][0]['zeroForOne'] = None
        await self.quick(offers, consume)
        self.assertEqual((offers, ordinary), original)

    async def test_late_batch_and_origins_are_seen_by_next_snapshot(self):
        entry = {'offers': [], 'offer_revisions': []}
        attempt = {'batches': 0, 'candidates': 0, 'firstCandidateMs': None, 'provider': 'late-provider'}
        self.session._queries[self.key] = [entry]
        first, late = self.offers(2)
        self.session._publish_batch([first['branches']], entry, attempt)
        snapshot = self.session._ready_offers()
        before = deepcopy(snapshot[self.key])
        async def consume_old():
            iterator = self.iterator()
            try:
                self.session._publish_batch([late['branches']], entry, attempt)
                entry['offers'][0]['origins'].append('later-origin')
                self.assertEqual(list(iterator), before,
                                 'A new arrival must not rewrite an existing quick snapshot')
            finally:
                iterator.close()
        await self.session._quick_pass(consume_old, snapshot)
        async def consume_new():
            iterator = self.iterator()
            try:
                return list(iterator)
            finally:
                iterator.close()
        values = await self.session._quick_pass(consume_new, self.session._ready_offers())
        self.assertEqual([row['branches'] for row in values], [late['branches'], first['branches']])
        self.assertEqual([row['origins'] for row in values],
                         [['late-provider'], ['late-provider', 'later-origin']])
        self.assertEqual((attempt['batches'], attempt['candidates']), (2, 2))

    async def test_cancelled_quick_owner_closes_without_copying_unused_bodies(self):
        offers, entered, drained = self.offers(16), asyncio.Event(), asyncio.Event()
        restored = []
        async def consume():
            iterator = self.iterator()
            try:
                self.assertEqual(next(iterator), offers[0])
                entered.set()
                await asyncio.Event().wait()
            finally:
                iterator.close()
                drained.set()
        async def owned():
            try:
                await self.quick(offers, consume)
            finally:
                restored.append(bootstrap._quick_offers.get())
        with patch.object(bootstrap, 'deepcopy', wraps=deepcopy) as copy:
            task = asyncio.create_task(owned())
            try:
                await reached(entered)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(drained.is_set())
                self.assertEqual(copy.call_count, 1)
                self.assertEqual(restored, [None], 'The cancelled owner must reset its own quick context')
                self.assertIsNone(bootstrap._quick_offers.get())
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


class SdkLockOwnershipTests(unittest.IsolatedAsyncioTestCase):
    def assert_restored(self, lease, slots, engines):
        self.assertTrue(lease.closed)
        self.assertFalse(lease.owned)
        self.assertEqual(lease.engines, [])
        self.assertEqual(slots._value, 1)
        for engine in engines:
            self.assertEqual(engine._value, 1)
            self.assertFalse(engine._ordinary)
            self.assertFalse(engine._priority)
        self.assertIsNone(work._current.get())

    async def test_sdk_lock_waiters_allow_independent_helpers_and_defer_ninth_candidate(self):
        engine, sdk = work.PricingSlots(8), SdkWorker()
        sdk.lock = ObservedLock()
        sdk.process = SimpleNamespace(returncode=None)
        entered, release, helped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        exchanges, results, calls = [], {}, []
        source = {'id': 'local-pool', 'protocol': 'v3', 'liquidity': '100',
                  'bitmapWords': [], 'ticks': []}
        original = deepcopy(source)
        async def exchange(_process, outgoing):
            exchanges.append(outgoing['amount'])
            # SdkWorker must own this descriptor, even across parked siblings.
            outgoing['pools'][0]['liquidity'] = 'private-' + outgoing['amount']
            entered.set()
            await release.wait()
            return {'id': outgoing['id'], 'result': {'amountIn': outgoing['amount'],
                                                     'amountOut': str(int(outgoing['amount']) + 1)}}
        async def rpc(method, params):
            calls.append((method, deepcopy(params)))
            helped.set()
            return {'result': 'local-Helpers-result'}
        params = [{'to': 'local-Helpers', 'data': 'unchanged-plan'}, 'latest']
        rpc_owner = SimpleNamespace(w3=SimpleNamespace(provider=SimpleNamespace(make_request=rpc)))
        async def evaluate(_index, value):
            async with work.engine_work(engine):
                results[value] = await sdk.request({'operation': 'simulateRoute', 'mode': 'exactIn',
                    'amount': str(value + 1), 'pools': [source]})
        with captured_leases() as leases, patch.object(sdk_bridge, 'exchange', exchange):
            task = asyncio.create_task(schedule_routes(
                lambda _: [feed(range(9))], evaluate))
            try:
                await reached(entered)
                await reached(sdk.lock.seven_waiters)
                # The ninth candidate waits for this scheduler's lifetime
                # place; separately owned known work must still obtain engine
                # capacity while all eight evaluations are unfinished.
                with work.bootstrap_priority():
                    response, counts = await execute_plan_call(rpc_owner, params, semaphore=engine,
                                                               now=lambda: 'local-time', shared=False)
                self.assertEqual((response['result'], counts['issued']), ('local-Helpers-result', 1))
                await reached(helped)
                self.assertEqual(len(leases), 8)
                self.assertFalse(release.is_set(), 'Helpers must run before the active exchange finishes')
                self.assertEqual(len(exchanges), 1)
                self.assertEqual(len(sdk.lock._waiters), 7)
                self.assertEqual(engine._value, 7)
                self.assertEqual(sum(lease.owned for lease in leases), 1)
                self.assertEqual(source, original)
                release.set()
                await asyncio.wait_for(task, 3)
                self.assertEqual([results[index]['amountOut'] for index in range(9)],
                                 [str(index + 2) for index in range(9)])
                self.assertEqual(exchanges, [str(index + 1) for index in range(9)])
                self.assertEqual(calls, [('eth_call', params)])
                self.assertEqual(engine._value, 8)
                self.assertEqual(leases[0].slots._value, 8)
                self.assertTrue(all(lease.closed and not lease.owned and not lease.engines for lease in leases))
                self.assertFalse(sdk.lock.locked())
                self.assertEqual(source, original)
            finally:
                release.set()
                # Let the inert exchange finish before cancelling the owner,
                # avoiding any synthetic subprocess cleanup in this test.
                if not task.done():
                    await asyncio.wait_for(asyncio.shield(task), 3)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                sdk.process = None
                await sdk.close()

    async def cancel_lock_wait(self, boundary):
        scheduler, engine, lock = ObservedSemaphore(1), ObservedSlots(1), ObservedLock()
        await scheduler.acquire()
        lease = work.CandidateWork(scheduler, asyncio.Event())
        await lock.acquire()  # An independent exchange owns the worker.
        entered = []
        async def evaluate(_index, _value):
            async with work.engine_work(engine):
                async with sdk_bridge.exchange_lock(lock):
                    entered.append('must not exchange after cancellation')
        task = asyncio.create_task(work.run_candidate(lease, evaluate, 0, None))
        foreign_engine = foreign_scheduler = False
        try:
            await reached(lock.waiting)
            self.assertFalse(lease.owned)
            self.assertEqual((scheduler._value, engine._value), (1, 1))
            if boundary == 'engine-reacquire':
                await engine.acquire()
                foreign_engine = True
                lock.release()
                await reached(engine.waiting)
                self.assertTrue(lock.locked())
            elif boundary == 'scheduler-reacquire':
                await scheduler.acquire()
                foreign_scheduler = True
                lock.release()
                await reached(scheduler.waiting)
                self.assertTrue(lock.locked())
            elif boundary == 'lock-granted':
                lock.release()  # Grant then cancel before the waiting task runs.
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(entered, [])
            self.assertEqual(engine._value, 0 if foreign_engine else 1)
            self.assertEqual(scheduler._value, 0 if foreign_scheduler else 1)
            if boundary == 'waiting':
                self.assertTrue(lock.locked(), 'The independent lock owner must survive')
                lock.release()
            else:
                self.assertFalse(lock.locked(), 'Reacquisition cancellation must release the SDK lock')
            if foreign_engine:
                engine.release()
                foreign_engine = False
            if foreign_scheduler:
                scheduler.release()
                foreign_scheduler = False
            self.assert_restored(lease, scheduler, [engine])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if lock.locked():
                lock.release()
            if foreign_engine:
                engine.release()
            if foreign_scheduler:
                scheduler.release()

    async def test_cancel_while_waiting_for_sdk_lock_preserves_foreign_owner(self):
        await self.cancel_lock_wait('waiting')

    async def test_cancel_immediately_after_sdk_lock_grant_restores_capacity(self):
        await self.cancel_lock_wait('lock-granted')

    async def test_cancel_during_engine_reacquire_releases_sdk_lock(self):
        await self.cancel_lock_wait('engine-reacquire')

    async def test_cancel_during_candidate_reservation_reacquire_releases_sdk_lock(self):
        await self.cancel_lock_wait('scheduler-reacquire')

    async def test_cancel_partial_nested_engine_reacquire_preserves_foreign_permit(self):
        scheduler, first, second, lock = (asyncio.Semaphore(1), ObservedSlots(1),
                                          ObservedSlots(1), ObservedLock())
        await scheduler.acquire()
        lease = work.CandidateWork(scheduler, asyncio.Event())
        await lock.acquire()
        async def evaluate(_index, _value):
            async with work.engine_work(first):
                async with work.engine_work(second):
                    async with sdk_bridge.exchange_lock(lock):
                        self.fail('Cancelled work must not enter an exchange')
        task = asyncio.create_task(work.run_candidate(lease, evaluate, 0, None))
        foreign = False
        try:
            await reached(lock.waiting)
            self.assertEqual((scheduler._value, first._value, second._value), (1, 1, 1))
            await second.acquire()
            foreign = True
            lock.release()
            await reached(second.waiting)
            self.assertEqual(first._value, 0, 'Nested permits reacquire in their original order')
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual((scheduler._value, first._value, second._value), (1, 1, 0))
            self.assertFalse(lock.locked())
            second.release()
            foreign = False
            self.assert_restored(lease, scheduler, [first, second])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if lock.locked():
                lock.release()
            if foreign:
                second.release()

    async def test_inherited_foreign_lease_keeps_parent_capacity_while_child_waits(self):
        engine, lock = work.PricingSlots(1), ObservedLock()
        await lock.acquire()
        async with work.engine_work(engine):
            parent = work._current.get()
            async def child():
                self.assertIs(work._current.get(), parent)
                async with sdk_bridge.exchange_lock(lock):
                    self.assertTrue(parent.owned)
                    self.assertEqual(engine._value, 0)
            task = asyncio.create_task(child())
            try:
                await reached(lock.waiting)
                self.assertTrue(parent.owned, 'A child cannot park its inherited foreign lease')
                self.assertEqual(engine._value, 0)
                lock.release()
                await task
                self.assertTrue(parent.owned)
                self.assertEqual(engine._value, 0)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if lock.locked():
                    lock.release()
        self.assertEqual(engine._value, 1)
        self.assertTrue(parent.closed)
        self.assertIsNone(work._current.get())

    async def test_state_continuation_keeps_private_coverage_and_same_request_identity(self):
        engine, sdk = work.PricingSlots(1), SdkWorker()
        sdk.process = SimpleNamespace(returncode=None)
        source = {'id': 'local-pool', 'protocol': 'v3', 'bitmapWords': [], 'ticks': []}
        payload = {'operation': 'simulateRoute', 'mode': 'exactIn', 'amount': '7', 'pools': [source]}
        original, outgoing, states = deepcopy(payload), [], []
        async def exchange(_process, value):
            outgoing.append(deepcopy(value))
            if value['operation'] != 'resume':
                return {'id': value['id'], 'stateRequest': [
                    {'poolId': source['id'], 'wordPositions': [0], 'ticks': []}]}
            return {'id': value['id'], 'result': {'amountIn': '7', 'amountOut': '11'}}
        async def acquire(requests):
            self.assertFalse(sdk.lock.locked())
            self.assertEqual(engine._value, 1)
            self.assertFalse(leases[0].owned)
            state = {'id': requests[0]['poolId'], 'bitmapWords': [{'wordPosition': 0, 'bitmap': '0'}], 'ticks': []}
            states.append(deepcopy(state))
            return [state]
        results = []
        async def evaluate(_index, _value):
            async with work.engine_work(engine):
                results.append(await sdk.request(payload, on_state=acquire))
        with captured_leases() as leases, patch.object(sdk_bridge, 'exchange', exchange):
            try:
                await schedule_routes(lambda _: [feed([0])], evaluate, limit=1)
                self.assertEqual(results, [{'amountIn': '7', 'amountOut': '11'}])
                self.assertEqual([row['operation'] for row in outgoing], ['simulateRoute', 'resume'])
                self.assertEqual([row['id'] for row in outgoing], ['1', '1'])
                self.assertEqual(outgoing[1]['coverage'], states)
                self.assertTrue(outgoing[0]['continueState'])
                self.assertEqual(payload, original)
                self.assertEqual((engine._value, leases[0].slots._value), (1, 1))
                self.assertTrue(all(lease.closed and not lease.owned for lease in leases))
                self.assertFalse(sdk.lock.locked())
            finally:
                sdk.process = None
                await sdk.close()


class SiblingUnionReuseTests(unittest.TestCase):
    def normalize(self, offers, source=A):
        return [list(normalize_hints([offer], source, D)) for offer in offers]

    def assert_expected(self, actual, offer, source=A):
        self.assertEqual([signature(rows) for rows, _ in actual], expected_union(offer, source))
        self.assertTrue(all(origins == offer['origins'] for _, origins in actual))

    def test_sibling_single_offer_feeds_reuse_full_expansion_including_native_paths(self):
        for source in (A, ZERO):
            with self.subTest(source=source):
                offers = [crossed(origin='first'), crossed((33, 67), origin='second'),
                          crossed((19, 81), origin='third')]
                original = deepcopy(offers)
                with topology_scope(TopologyCache()), patch(
                        'cybergold_candidate.quoter.candidate_hints.route_candidates',
                        wraps=route_candidates) as expansion:
                    actual = self.normalize(offers, source)
                    self.assertEqual(expansion.call_count, 1)
                for offered, values in zip(offers, actual, strict=True):
                    self.assert_expected(values, offered, source)
                self.assertEqual(offers, original)

    def test_total_or_current_order_change_rebuilds_across_sibling_feeds(self):
        first, total, reordered = crossed(), crossed((34, 67), origin='total'), crossed(origin='reordered')
        for row in reordered['branches']:
            for hop in row['hops']:
                hop['pool']['id'] = '0x' + format(1000 - int(hop['pool']['id'], 16), '040x')
        self.assertNotEqual(expected_union(first), expected_union(reordered))
        offers = [first, total, reordered]
        with topology_scope(TopologyCache()), patch(
                'cybergold_candidate.quoter.candidate_hints.route_candidates',
                wraps=route_candidates) as expansion:
            actual = self.normalize(offers)
            self.assertEqual(expansion.call_count, 3)
        for offered, values in zip(offers, actual, strict=True):
            self.assert_expected(values, offered)

    def test_last_completed_entry_does_not_accumulate_a_b_a(self):
        offers = [crossed(origin='a'), crossed((34, 67), origin='b'), crossed(origin='a-again')]
        with topology_scope(TopologyCache()), patch(
                'cybergold_candidate.quoter.candidate_hints.route_candidates',
                wraps=route_candidates) as expansion:
            actual = self.normalize(offers)
            self.assertEqual(expansion.call_count, 3)
        for offered, values in zip(offers, actual, strict=True):
            self.assert_expected(values, offered)

    def test_reuse_rebinds_current_metadata_origins_and_private_hop_containers(self):
        first, current = crossed(), crossed((33, 67), origin='current', epoch='new')
        original = deepcopy((first, current))
        with topology_scope(TopologyCache()), patch(
                'cybergold_candidate.quoter.candidate_hints.route_candidates',
                wraps=route_candidates) as expansion:
            previous = list(normalize_hints([first], A, D))
            expected = expected_union(current)
            for rows, origins in previous:
                origins.append('consumer-only')
                for row in rows:
                    row['amountIn'] = '999999'
                    for hop in row['hops']:
                        hop['consumerOnly'] = True
            actual = list(normalize_hints([current], A, D))
            self.assertEqual(expansion.call_count, 1)
        self.assertEqual([signature(rows) for rows, _ in actual], expected)
        for rows, origins in actual:
            self.assertEqual(origins, ['current'])
            for row in rows:
                for hop in row['hops']:
                    self.assertNotIn('consumerOnly', hop)
                    pool = hop['pool']
                    self.assertEqual(pool['observationEpoch'], 'new')
                    self.assertEqual(pool['liquidity'], '2000')
        self.assertEqual((first, current), original)

    def test_closed_partial_expansion_is_not_reused_as_completed(self):
        first, second, third = crossed(origin='partial'), crossed(origin='full'), crossed(origin='reuse')
        with topology_scope(TopologyCache()), patch(
                'cybergold_candidate.quoter.candidate_hints.route_candidates',
                wraps=route_candidates) as expansion:
            iterator = iter(normalize_hints([first], A, D))
            try:
                self.assertEqual(signature(next(iterator)[0]), expected_union(first)[0])
                self.assertEqual(expansion.call_count, 1)
            finally:
                iterator.close()
            actual = self.normalize([second, third])
            self.assertEqual(expansion.call_count, 2, 'Only the fully drained second feed may be reused')
        self.assert_expected(actual[0], second)
        self.assert_expected(actual[1], third)

    def test_interleaved_misses_preserve_full_outputs_and_one_completed_entry(self):
        first, other = crossed(origin='slow-a'), crossed((34, 67), origin='full-b')
        with topology_scope(TopologyCache()), patch(
                'cybergold_candidate.quoter.candidate_hints.route_candidates',
                wraps=route_candidates) as expansion:
            iterator = iter(normalize_hints([first], A, D))
            try:
                head = next(iterator)
                second = list(normalize_hints([other], A, D))
                completed_first = [head, *iterator]
                again = list(normalize_hints([other], A, D))
                self.assertEqual(expansion.call_count, 3,
                                 'Completing A after B replaces the single completed entry')
            finally:
                iterator.close()
        self.assert_expected(completed_first, first)
        self.assert_expected(second, other)
        self.assert_expected(again, other)

    def test_cache_clear_and_other_search_start_with_no_shared_pattern(self):
        offer, first, second = crossed(), TopologyCache(), TopologyCache()
        with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                   wraps=route_candidates) as expansion:
            for cache, count in ((first, 1), (first, 1), (second, 2)):
                with topology_scope(cache):
                    self.assert_expected(list(normalize_hints([offer], A, D)), offer)
                self.assertEqual(expansion.call_count, count)
            first.clear()
            with topology_scope(first):
                self.assert_expected(list(normalize_hints([offer], A, D)), offer)
            self.assertEqual(expansion.call_count, 3)

    def test_without_search_scope_existing_iterator_local_reuse_is_unchanged(self):
        first, second = crossed(origin='first'), crossed((33, 67), origin='second')
        with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                   wraps=route_candidates) as expansion:
            same_iterator = list(normalize_hints([first, second], A, D))
            separate = list(normalize_hints([first], A, D))
            self.assertEqual(expansion.call_count, 2)
        self.assert_expected([row for row in same_iterator if row[1] == ['first']], first)
        self.assert_expected([row for row in same_iterator if row[1] == ['second']], second)
        self.assert_expected(separate, first)


if __name__ == '__main__':
    unittest.main()
