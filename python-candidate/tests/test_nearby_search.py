"""Nearby cache work at the actual search ownership and candidate boundary."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.search import alongside_bootstrap
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.route_work_slots import PricingSlots, bootstrap_priority, engine_work, required_state_wait
from cybergold_candidate.recovery_rpc import SnapshotChanged
from test_universal_quote import Engine, Quotes, request


class NearbySearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_upper_settles_once_for_absent_unusable_or_failed_cache(self):
        for source in ['absent', 'unusable', 'failed']:
            with self.subTest(source=source):
                q = Quotes(Engine()); frames = []
                async def neighbors():
                    if source == 'failed':
                        raise OSError('optional database unavailable')
                    return {} if source == 'absent' else {'upper': {'quote': {}}}
                async def update(frame):
                    frames.append(deepcopy(frame))
                value = await q.quote(request(), update, neighbors=neighbors)
                self.assertGreater(int(value['quotedOutput']), 0)
                self.assertEqual(sum(frame['type'] == 'upper-replay-settled' for frame in frames), 1)

    async def test_cancelled_upper_uses_terminal_completion_instead_of_an_early_marker(self):
        q = Quotes(Engine()); saved = await q.quote(request())
        entered, drained = asyncio.Event(), asyncio.Event()
        candidate = q.candidate
        async def measured(*args, **kwargs):
            if (kwargs.get('selected') or {}).get('_upper_replay'):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            await entered.wait()
            return await candidate(*args, **kwargs)
        q.candidate = measured
        async def neighbors():
            return {'upper': {'identity': 'upper', 'quote': saved}}
        frames = []
        async def update(frame):
            frames.append(deepcopy(frame))
        from cybergold_candidate.quoter.reuse_routes import neighbor_proposals
        def marked(*args):
            rows = neighbor_proposals(*args)
            for row in rows:
                row['plan']['_upper_replay'] = True
            return rows
        with patch('cybergold_candidate.quoter.search.neighbor_proposals', marked):
            async with asyncio.timeout(2):
                value = await q.quote(request(), update, neighbors=neighbors)
        self.assertTrue(drained.is_set())
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertFalse(any(frame['type'] == 'upper-replay-settled' for frame in frames))

    async def test_legacy_universal_callback_still_contains_only_executable_values(self):
        q = Quotes(Engine()); frames = []
        async def update(frame):
            frames.append(deepcopy(frame))
        value = await q.get(request(), update)
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertTrue(frames)
        self.assertTrue(all(frame['type'] == 'qualified' and 'minimumOutput' in frame['value']['plan']
                            and 'economicQuote' in frame['value'] for frame in frames))

    async def test_pending_cache_never_delays_ordinary_completion_and_is_drained(self):
        q = Quotes(Engine())
        entered, drained = asyncio.Event(), asyncio.Event()
        async def slow():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        async with asyncio.timeout(2):
            value = await q.quote(request(), neighbors=slow)
        self.assertTrue(entered.is_set())
        self.assertTrue(drained.is_set())
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(value['metrics']['nearbySearch']['starts'], 0)
        self.assertEqual(q.engine.semaphore._value, 8)

    async def test_cache_failure_is_optional_and_disproof_is_not(self):
        for disproof in [False, True]:
            q = Quotes(Engine())
            async def unavailable():
                if disproof:
                    raise SnapshotChanged('captured context changed')
                raise OSError('optional database unavailable')
            if disproof:
                with self.assertRaises(SnapshotChanged):
                    await q.quote(request(), neighbors=unavailable)
            else:
                value = await q.quote(request(), neighbors=unavailable)
                self.assertGreater(int(value['quotedOutput']), 0)
            self.assertEqual(q.engine.semaphore._value, 8)

    async def test_lookup_overlaps_head_and_cancellation_drains_it(self):
        q = Quotes(Engine()); lookup, head, drained = (asyncio.Event() for _ in range(3))
        async def read(_):
            head.set()
            await lookup.wait()
            await asyncio.Event().wait()
        async def neighbors():
            lookup.set()
            await head.wait()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        q.engine.block = read
        task = asyncio.create_task(q.quote(request(), neighbors=neighbors))
        await head.wait(); await lookup.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(drained.is_set())
        self.assertFalse(any(row[0] == 'canonical' for row in q.engine.calls))

    async def test_upper_and_lower_are_fresh_full_candidates_plus_fitting_funding(self):
        q = Quotes(Engine())
        # The small independent formula engine normally embeds its reserves
        # in route refs. Resolve stripped blueprints from the current registry,
        # just as the production engine acquires its current observations.
        sdk = q.engine.quote_sdk_branches
        async def acquire(branches, *args, **kwargs):
            resolved = deepcopy(branches)
            for branch in resolved:
                for hop in branch['hops']:
                    hop['pool'] = deepcopy(q.engine.registry.inventory[hop['pool']['id']])
            return await sdk(resolved, *args, **kwargs)
        q.engine.quote_sdk_branches = acquire
        original = await q.quote(request())
        lower = deepcopy(original)
        upper = deepcopy(original)
        upper['request']['inputs'][0]['amount'] = '30000'
        upper['quotedOutput'] = '999999999999999999999'  # Never a new quote's output.
        edited = {**request(), 'inputs': [{**request()['inputs'][0], 'amount': '20002'}]}
        evaluations = []; candidate = q.candidate
        async def measured(value, *args, **kwargs):
            if kwargs.get('selected') is not None:
                evaluations.append(deepcopy(value['inputs']))
            return await candidate(value, *args, **kwargs)
        async def delayed_discovery(*_):
            await asyncio.sleep(.03)
        q.candidate = measured; q.discover = delayed_discovery
        async def neighbors():
            return {'lower': {'identity': 'lower', 'quote': lower},
                    'upper': {'identity': 'upper', 'quote': upper}}
        value = await q.quote(edited, neighbors=neighbors)
        funded = {int(rows[0]['amount']) for rows in evaluations}
        self.assertEqual(funded, {10001, 20002})
        self.assertEqual(value['request']['inputs'], edited['inputs'])
        self.assertNotEqual(value['quotedOutput'], upper['quotedOutput'])
        self.assertEqual(sum(int(row['amountIn']) for row in value['plan']['allocations']),
                         int(value['inputs'][0]['amount']))
        metrics = value['metrics']['nearbySearch']
        self.assertEqual(metrics['starts'], 2)  # Identical proposals deduplicate across neighbors.
        self.assertEqual(metrics['completed'], 2)
        self.assertLessEqual(value['metrics']['optionalSearch']['starts'], 16)
        self.assertIsNone(value['metrics']['optionalSearch']['randomSeed'])
        self.assertTrue(all('elapsedMs' in row for source in metrics['sources'] for row in source['attempts']))

    async def test_unusable_blueprint_does_not_remove_an_ordinary_winner(self):
        q = Quotes(Engine())
        async def neighbors():
            return {'upper': {'identity': 'old', 'quote': {}}}
        value = await q.quote(request(), neighbors=neighbors)
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertNotEqual(value['searchCoverage']['selectedPhase'], 'nearby-upper')

    async def test_malformed_optional_cache_does_not_change_ordinary_no_route(self):
        for saved in [{}, {'request': {}}]:
            q = Quotes(Engine())
            async def no_route(*_, **__):
                raise QuoteFailure('quote-no-route')
            q.candidate = no_route
            async def neighbors():
                return {'upper': {'identity': 'legacy', 'quote': saved}}
            with self.assertRaises(QuoteFailure) as caught:
                await q.quote(request(), neighbors=neighbors)
            self.assertEqual(caught.exception.code, 'quote-no-route')

    async def test_optional_replay_error_does_not_replace_ordinary_rpc_error(self):
        q = Quotes(Engine()); saved = await q.quote(request())
        async def no_route(*_, **options):
            if options.get('selected') is not None:
                raise KeyError('obsolete optional route')
            raise QuoteFailure('rpc-rate-limit')
        q.candidate = no_route
        async def neighbors():
            return {'upper': {'identity': 'legacy', 'quote': saved}}
        with self.assertRaises(QuoteFailure) as caught:
            await q.quote(request(), neighbors=neighbors)
        self.assertEqual(caught.exception.code, 'rpc-rate-limit')

    async def test_lower_can_complete_while_upper_waits_and_optional_work_is_drained(self):
        ordinary_release, upper_entered, upper_drained, lower_done = (asyncio.Event() for _ in range(4))
        async def ordinary():
            await lower_done.wait()
            ordinary_release.set()
        async def upper():
            upper_entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                upper_drained.set()
        async def lower():
            await upper_entered.wait()
            lower_done.set()
        from cybergold_candidate.uniswap_state import owned_reads
        await alongside_bootstrap(ordinary(), owned_reads(upper(), lower()))
        self.assertTrue(ordinary_release.is_set())
        self.assertTrue(upper_drained.is_set())

    async def test_exact_seed_and_neighbor_feed_do_not_share_e17_wait_condition(self):
        q = Quotes(Engine()); seed = await q.quote(request())
        entered, drained = asyncio.Event(), asyncio.Event()
        async def delayed():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        value = await q.quote(request(), seed=seed, neighbors=delayed)
        self.assertTrue(entered.is_set() and drained.is_set())
        self.assertGreater(value['metrics']['optionalSearch']['starts'], 0)
        self.assertIsNotNone(value['metrics']['optionalSearch']['randomSeed'])


class NearbyPricingAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_next_free_permit_prefers_ready_bootstrap_then_fifo_ordinary(self):
        slots = PricingSlots(1); await slots.acquire(); order = []
        async def ordinary(name):
            async with engine_work(slots):
                order.append(name)
        async def bootstrap():
            with bootstrap_priority():
                await ordinary('cached')
        tasks = [asyncio.create_task(ordinary('one')), asyncio.create_task(ordinary('two'))]
        await asyncio.sleep(0)
        tasks.append(asyncio.create_task(bootstrap()))
        await asyncio.sleep(0)
        slots.release()
        await asyncio.gather(*tasks)
        self.assertEqual(order, ['cached', 'one', 'two'])
        self.assertEqual(slots._value, 1)

    async def test_cancelled_priority_grant_returns_permit_to_waiting_ordinary(self):
        slots = PricingSlots(1); await slots.acquire(); order = []
        async def work(name):
            async with engine_work(slots):
                order.append(name)
        async def bootstrap():
            with bootstrap_priority():
                await work('cached')
        cached = asyncio.create_task(bootstrap())
        ordinary = asyncio.create_task(work('ordinary'))
        await asyncio.sleep(0)
        slots.release(); cached.cancel()
        await asyncio.gather(cached, return_exceptions=True)
        await ordinary
        self.assertEqual(order, ['ordinary'])
        self.assertEqual(slots._value, 1)

    async def test_required_state_suspension_preserves_bootstrap_priority_on_resume(self):
        slots = PricingSlots(1); ready, resume = asyncio.Event(), asyncio.Event(); order = []
        async def cached():
            with bootstrap_priority():
                async with engine_work(slots):
                    async with required_state_wait():
                        ready.set(); await resume.wait()
                    order.append('cached')
        task = asyncio.create_task(cached()); await ready.wait()
        await slots.acquire()
        async def ordinary():
            async with engine_work(slots):
                order.append('ordinary')
        other = asyncio.create_task(ordinary()); await asyncio.sleep(0)
        resume.set(); await asyncio.sleep(0)
        slots.release()
        await asyncio.gather(task, other)
        self.assertEqual(order, ['cached', 'ordinary'])
        self.assertEqual(slots._value, 1)


if __name__ == '__main__':
    unittest.main()
