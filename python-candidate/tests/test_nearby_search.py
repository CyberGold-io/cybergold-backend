"""Nearby cache work at the actual search ownership and candidate boundary."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, patch

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.path_families import quote_path_family
from cybergold_candidate.quoter.search import alongside_bootstrap
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.route_work_slots import PricingSlots, bootstrap_priority, engine_work, required_state_wait
from cybergold_candidate.recovery_rpc import SnapshotChanged
from test_universal_quote import Engine, Quotes, request


class NearbySearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_and_neighbor_budget_failures_feed_the_shared_backward_repair(self):
        from cybergold_candidate.quoter.reuse_routes import neighbor_proposals
        for source in ('exact', 'lower'):
            with self.subTest(source=source):
                q, saved, edited, expanded = await self.budget_replay_fixture()
                q.amm.async_family_offers = AsyncMock(return_value=[])
                q.route_provider_factory = lambda: []
                saved['request'] = deepcopy(edited)
                assets, weights = await q.basis(None)
                proposal = neighbor_proposals(saved, 40004, assets)[-1]
                reference = await q.candidate({**edited, 'inputs': proposal['inputs']},
                    100, 'core-first', None, assets, weights, selected=proposal['plan'])
                original = q.candidate
                hint = {'currency': saved['inputs'][0]['currency'], 'amount': 7}
                async def candidate(value, *args, **options):
                    if options.get('selected') is not None and value['inputs'] == edited['inputs']:
                        error = QuoteFailure('quote-contract-reverted')
                        error.unsettled_intermediate = deepcopy(hint)
                        raise error
                    if options.get('selected') is not None:
                        return await original(value, *args, **options)
                    result = deepcopy(expanded)
                    result['quotedOutput'] = result['estimatedRecipientOutputs'][0]['amount'] = '1'
                    return result
                q.candidate = candidate
                recovery = AsyncMock(return_value=[proposal])
                options = {'seed': saved} if source == 'exact' else {
                    'neighbors': AsyncMock(return_value=[{'family': quote_path_family(saved), 'side': 'lower', **{'quote': saved}}])}
                with patch('cybergold_candidate.quoter.capacity_recovery.recover_selected', recovery):
                    async with asyncio.timeout(2):
                        result = await Quoter.get(q, edited, **options)
                self.assertEqual(result['inputs'], proposal['inputs'])
                self.assertEqual(result['quotedOutput'], reference['quotedOutput'])
                self.assertEqual(result['request'], edited)
                self.assertEqual(result['searchCoverage']['selectedPhase'], 'backward-prefix')
                self.assertTrue(result['searchCoverage']['inputLimitObserved'])
                recovery.assert_awaited_once()
                self.assertEqual(recovery.await_args.args[1]['inputs'], edited['inputs'])
                self.assertEqual(recovery.await_args.kwargs['unsettled'], hint)
                self.assertEqual(sum(int(row['amountIn']) for row in
                    recovery.await_args.args[2]['allocations']), 50005)
                self.assertEqual(result['routeOrigins']['discoveryProviders'],
                    ['uniroute-local', 'uniswap-alpharouter'])

    async def test_started_requested_budget_replay_outlives_ordinary_completion(self):
        """A real known route attempt is not owned by optional cache latency."""
        q, saved, edited, expanded = await self.budget_replay_fixture()
        saved['request'] = deepcopy(edited)
        q.amm.async_family_offers = AsyncMock(return_value=[])
        q.route_provider_factory = lambda: []
        original = q.candidate
        full_started, bootstrap_closed = asyncio.Event(), asyncio.Event()
        cancelled = []
        async def candidate(value, *args, **options):
            if options.get('selected') is not None:
                if value['inputs'][0]['amount'] == edited['inputs'][0]['amount']:
                    full_started.set()
                    try:
                        await bootstrap_closed.wait()
                    except asyncio.CancelledError:
                        cancelled.append(True)
                        raise
                return await original(value, *args, **options)
            await full_started.wait()
            result = await original(value, *args, **options)
            result['quotedOutput'] = result['estimatedRecipientOutputs'][0]['amount'] = '1'
            return result
        q.candidate = candidate
        async def bootstrap(ordinary, offered, **options):
            result = await alongside_bootstrap(ordinary, offered, **options)
            bootstrap_closed.set()
            return result
        with patch('cybergold_candidate.quoter.search.alongside_bootstrap', bootstrap):
            async with asyncio.timeout(2):
                result = await Quoter.get(q, edited, seed=saved)
        self.assertTrue(bootstrap_closed.is_set())
        self.assertFalse(cancelled)
        self.assertEqual(result['inputs'], edited['inputs'])
        self.assertEqual(result['quotedOutput'], expanded['quotedOutput'])

    async def budget_replay_fixture(self):
        """Native mixed-Core topology, resolved against current fixture state."""
        from cybergold_candidate.quoter.reuse_routes import neighbor_proposals
        q = Quotes(Engine())
        sdk = q.engine.quote_sdk_branches
        async def acquire(branches, *args, **kwargs):
            resolved = deepcopy(branches)
            for branch in resolved:
                for hop in branch['hops']:
                    hop['pool'] = deepcopy(q.engine.registry.inventory[hop['pool']['id']])
            return await sdk(resolved, *args, **kwargs)
        q.engine.quote_sdk_branches = acquire
        old_request = {key: request()[key] for key in ('intent', 'inputs', 'outputCurrency')}
        from test_universal_quote import BLOCK
        assets, weights = await q.basis(BLOCK)
        saved = await q.candidate(old_request, 50, 'core-first', BLOCK, assets, weights, first=True)
        for chosen in saved['plan']['conversions'].values():
            chosen['discoveryOrigins'] = ['uniroute-local', 'uniswap-alpharouter']
        edited = {**old_request, 'inputs': [{**old_request['inputs'][0], 'amount': '50005'}]}
        proposal = neighbor_proposals(saved, 50005, assets)[-1]
        expanded = await q.candidate(edited, 100, 'core-first', BLOCK, assets, weights, selected=proposal['plan'])
        self.assertGreater(int(expanded['quotedOutput']), int(saved['quotedOutput']))
        return q, saved, edited, expanded

    async def test_exact_low_funding_seed_starts_full_budget_and_keeps_fallback_and_ordinary_winner(self):
        from cybergold_candidate.quoter.reuse_routes import neighbor_proposals
        for outcome in ('expanded-wins', 'expanded-fails', 'ordinary-wins'):
            with self.subTest(outcome=outcome):
                q, saved, edited, expanded = await self.budget_replay_fixture()
                saved['request'] = deepcopy(edited)  # Exact key, lower actual funding.
                saved['searchCoverage']['selectedPhase'] = 'backward-prefix'  # Pre-field canonical observation.
                saved['plan']['_budget_replay_fixture'] = True
                q.route_provider_factory = lambda: []
                q.amm.async_family_offers = AsyncMock(return_value=[])
                original = q.candidate
                full_started, both_settled = asyncio.Event(), asyncio.Event()
                calls, settled = [], []
                async def candidate(value, *args, **options):
                    if (options.get('selected') or {}).get('_budget_replay_fixture'):
                        amount = value['inputs'][0]['amount']
                        calls.append((amount, deepcopy(options['selected'])))
                        try:
                            if amount == '50005':
                                full_started.set()
                                if outcome == 'expanded-fails':
                                    raise QuoteFailure('quote-contract-reverted')
                            else:
                                # An older replay may be slow. The expanded
                                # proposal must enter before it can complete.
                                await full_started.wait()
                            return await original(value, *args, **options)
                        finally:
                            settled.append(amount)
                            if len(settled) == 2:
                                both_settled.set()
                    await both_settled.wait()
                    result = deepcopy(expanded)
                    output = int(expanded['quotedOutput']) + 1000 if outcome == 'ordinary-wins' else 1
                    result['quotedOutput'] = str(output)
                    result['estimatedRecipientOutputs'][0]['amount'] = str(output)
                    return result
                def marked(*args):
                    rows = neighbor_proposals(*args)
                    for row in rows:
                        row['plan']['_budget_replay_fixture'] = True
                    return rows
                q.candidate = candidate
                with patch('cybergold_candidate.quoter.search.neighbor_proposals', marked):
                    async with asyncio.timeout(2):
                        result = await Quoter.get(q, edited, seed=saved)
                self.assertEqual({amount for amount, _ in calls}, {'10001', '50005'})
                self.assertEqual(result['request'], edited)
                expected = saved if outcome == 'expanded-fails' else expanded
                self.assertEqual(result['inputs'], edited['inputs'] if outcome == 'ordinary-wins' else expected['inputs'])
                self.assertEqual(result['quotedOutput'], str(int(expanded['quotedOutput']) + 1000)
                                 if outcome == 'ordinary-wins' else expected['quotedOutput'])
                self.assertEqual(result['searchCoverage'].get('inputLimitObserved', False),
                                 outcome == 'expanded-fails')
                plan = next(plan for amount, plan in calls if amount == '50005')
                self.assertEqual(sum(int(row['amountIn']) for row in plan['allocations']), 50005)
                self.assertEqual({row['kind'] for row in plan['allocations']}, {0, 1})
                self.assertTrue(all(chosen['inputCurrency'].lower() == edited['inputs'][0]['currency'].lower()
                    for operation, chosen in plan['conversions'].items() if ':acquire:' in operation or ':market' in operation))
                if outcome != 'ordinary-wins':
                    self.assertEqual(result['routeOrigins']['discoveryProviders'], ['uniroute-local', 'uniswap-alpharouter'])
                self.assertEqual(q.engine.semaphore._value, 8)

    async def test_lower_neighbor_replays_original_while_full_budget_is_pending(self):
        from cybergold_candidate.quoter.reuse_routes import neighbor_proposals
        q, saved, edited, expanded = await self.budget_replay_fixture()
        saved['plan']['_budget_replay_fixture'] = True
        q.route_provider_factory = lambda: []
        q.amm.async_family_offers = AsyncMock(return_value=[])
        original = q.candidate
        full_started, fitting_started, release_full, published = (asyncio.Event() for _ in range(4))
        visible = []
        async def candidate(value, *args, **options):
            if (options.get('selected') or {}).get('_budget_replay_fixture'):
                if value['inputs'][0]['amount'] == '50005':
                    full_started.set()
                    await release_full.wait()
                else:
                    fitting_started.set()
                    await full_started.wait()
                return await original(value, *args, **options)
            await asyncio.gather(full_started.wait(), fitting_started.wait())
            result = deepcopy(expanded)
            result['quotedOutput'] = result['estimatedRecipientOutputs'][0]['amount'] = '1'
            return result
        def marked(*args):
            rows = neighbor_proposals(*args)
            for row in rows:
                row['plan']['_budget_replay_fixture'] = True
            return rows
        async def neighbors():
            return [{'family': quote_path_family(saved), 'side': 'lower',
                     'identity': 'fitting-native-core', 'quote': saved}]
        async def publish(frame):
            if frame['type'] == 'qualified':
                visible.append(deepcopy(frame['value']))
                if frame['value']['inputs'] == saved['inputs']:
                    published.set()
        q.candidate = candidate
        with patch('cybergold_candidate.quoter.search.neighbor_proposals', marked):
            async with asyncio.timeout(2):
                task = asyncio.create_task(Quoter.get(q, edited, publish, neighbors=neighbors))
                try:
                    await asyncio.gather(full_started.wait(), fitting_started.wait(), published.wait())
                    self.assertFalse(task.done())
                    fitting = next(value for value in visible if value['inputs'] == saved['inputs'])
                    self.assertEqual(fitting['quotedOutput'], saved['quotedOutput'])
                    release_full.set()
                    result = await task
                finally:
                    release_full.set()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(result['inputs'], edited['inputs'])
        self.assertEqual(result['quotedOutput'], expanded['quotedOutput'])
        attempts = result['metrics']['nearbySearch']['sources'][0]['attempts']
        self.assertCountEqual([row['funding'] for row in attempts], ['50005', '10001'])
        self.assertTrue(all(row['completed'] for row in attempts))
        self.assertEqual(q.engine.semaphore._value, 8)

    async def test_fitting_and_requested_budget_attempts_start_independently_on_failure(self):
        from cybergold_candidate.quoter.reuse_routes import neighbor_proposals
        for unavailable in (False, True):
            with self.subTest(fitting_replay_unavailable=unavailable):
                q, saved, edited, expanded = await self.budget_replay_fixture()
                saved['searchCoverage']['selectedPhase'] = 'capacity-limited'
                expected = saved['quotedOutput']
                saved['quotedOutput'] = '999999999999999999999999'
                saved['plan']['_fitting_fixture'] = True
                q.route_provider_factory = lambda: []
                q.amm.async_family_offers = AsyncMock(return_value=[])
                original, order = q.candidate, []
                full_started, fitting_started = asyncio.Event(), asyncio.Event()
                async def candidate(value, *args, **options):
                    if (options.get('selected') or {}).get('_fitting_fixture'):
                        if value['inputs'][0]['amount'] == edited['inputs'][0]['amount']:
                            order.append('full-budget'); full_started.set()
                            await fitting_started.wait()
                            raise QuoteFailure('quote-no-route')
                        order.append('fitting'); fitting_started.set()
                        await full_started.wait()
                        if unavailable:
                            raise QuoteFailure('quote-no-route')
                        return await original(value, *args, **options)
                    await asyncio.gather(full_started.wait(), fitting_started.wait())
                    result = deepcopy(expanded)
                    result['quotedOutput'] = result['estimatedRecipientOutputs'][0]['amount'] = '1'
                    return result
                q.candidate = candidate
                async def neighbors():
                    return [{'family': quote_path_family(saved), 'side': 'lower',
                             'identity': 'best-fitting', 'quote': saved}]
                def marked(*args):
                    rows = neighbor_proposals(*args)
                    for row in rows:
                        row['plan']['_fitting_fixture'] = True
                    return rows
                with patch('cybergold_candidate.quoter.search.neighbor_proposals', marked):
                    async with asyncio.timeout(2):
                        result = await Quoter.get(q, edited, neighbors=neighbors)
                self.assertCountEqual(order, ['full-budget', 'fitting'])
                self.assertEqual(result['request']['inputs'], edited['inputs'])
                self.assertEqual(result['quotedOutput'], '1' if unavailable else expected)
                self.assertEqual(result['inputs'][0]['amount'], '50005' if unavailable else '10001')
                self.assertNotEqual(result['quotedOutput'], saved['quotedOutput'])
                self.assertEqual(result['searchCoverage'].get('inputLimitObserved', False), not unavailable)
                self.assertEqual(q.engine.semaphore._value, 8)

    async def test_upper_settles_once_for_absent_unusable_or_failed_cache(self):
        for source in ['absent', 'unusable', 'failed']:
            with self.subTest(source=source):
                q = Quotes(Engine()); frames = []
                async def neighbors():
                    if source == 'failed':
                        raise OSError('optional database unavailable')
                    return [] if source == 'absent' else [{'family': quote_path_family({}), 'side': 'upper', **{'quote': {}}}]
                async def update(frame):
                    frames.append(deepcopy(frame))
                value = await q.quote(request(), update, neighbors=neighbors)
                self.assertGreater(int(value['quotedOutput']), 0)
                self.assertEqual(sum(frame['type'] == 'upper-replay-settled' for frame in frames), 1)

    async def test_cancelled_upper_uses_terminal_completion_instead_of_an_early_marker(self):
        from cybergold_candidate.quote_budget import QuoteBudget, budget_context
        q = Quotes(Engine()); saved = await q.quote(request())
        budget = QuoteBudget()
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
            return [{'family': quote_path_family(saved), 'side': 'upper', **{'identity': 'upper', 'quote': saved}}]
        frames = []
        async def update(frame):
            frames.append(deepcopy(frame))
            if frame['type'] == 'qualified':
                budget.finish_selection('best-initial')
        from cybergold_candidate.quoter.reuse_routes import neighbor_proposals
        def marked(*args):
            rows = neighbor_proposals(*args)
            for row in rows:
                row['plan']['_upper_replay'] = True
            return rows
        with patch('cybergold_candidate.quoter.search.neighbor_proposals', marked):
            with budget_context(budget):
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

    async def test_optional_cache_failure_or_sdk_disproof_leaves_completed_helpers_alternatives(self):
        for disproof in [False, True]:
            q = Quotes(Engine())
            async def unavailable():
                if disproof:
                    raise SnapshotChanged('captured context changed')
                raise OSError('optional database unavailable')
            value = await q.quote(request(), neighbors=unavailable)
            self.assertGreater(int(value['quotedOutput']), 0)
            self.assertEqual(q.engine.semaphore._value, 8)

    async def test_independent_optional_cancellation_preserves_no_route_instead_of_cancelling_caller(self):
        q = Quotes(Engine())
        q.amm.async_family_offers = AsyncMock(return_value=[])
        async def no_route(*_, **__):
            raise QuoteFailure('quote-no-route')
        async def stopped_lookup():
            raise asyncio.CancelledError('optional lookup stopped itself')
        q.candidate = no_route
        with self.assertRaises(QuoteFailure) as caught:
            await q.quote(request(), neighbors=stopped_lookup)
        self.assertEqual(caught.exception.code, 'quote-no-route')
        self.assertEqual(asyncio.current_task().cancelling(), 0)

    async def test_lookup_overlaps_sdk_preparation_and_cancellation_drains_both(self):
        q = Quotes(Engine())
        lookup, preparing, lookup_drained, preparation_drained = (asyncio.Event() for _ in range(4))
        async def read(_):
            preparing.set()
            try:
                await lookup.wait()
                await asyncio.Event().wait()
            finally:
                preparation_drained.set()
        async def neighbors():
            lookup.set()
            try:
                await preparing.wait()
                await asyncio.Event().wait()
            finally:
                lookup_drained.set()
        q.basis_reader = read
        q.engine.block = AsyncMock(side_effect=AssertionError('Quote lookup cannot acquire a header'))
        task = asyncio.create_task(q.quote(request(), neighbors=neighbors))
        try:
            async with asyncio.timeout(2):
                await asyncio.gather(preparing.wait(), lookup.wait())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(lookup_drained.is_set())
        self.assertTrue(preparation_drained.is_set())
        q.engine.block.assert_not_awaited()
        self.assertFalse(any(row[0] == 'canonical' for row in q.engine.calls))

    async def test_equivalent_lower_upper_routes_share_one_requested_budget_replay(self):
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
            return [{'family': quote_path_family(lower), 'side': 'lower', **{'identity': 'lower', 'quote': lower}}, {'family': quote_path_family(upper), 'side': 'upper', **{'identity': 'upper', 'quote': upper}}]
        value = await q.quote(edited, neighbors=neighbors)
        funded = {int(rows[0]['amount']) for rows in evaluations}
        self.assertEqual(funded, {10001, 20002})
        self.assertEqual(value['request']['inputs'], edited['inputs'])
        self.assertNotEqual(value['quotedOutput'], upper['quotedOutput'])
        self.assertEqual(sum(int(row['amountIn']) for row in value['plan']['allocations']),
                         int(value['inputs'][0]['amount']))
        metrics = value['metrics']['nearbySearch']
        # One expanded topology and one distinct fitting original are priced;
        # lower/upper aliases do not duplicate either funded observation.
        self.assertEqual(metrics['starts'], 2)
        self.assertEqual(metrics['completed'], 2)
        self.assertEqual(metrics['sources'][0]['side'], 'lower')
        self.assertEqual(metrics['sources'][0]['aliases'][0]['side'], 'upper')
        self.assertIsNone(value['metrics']['optionalSearch']['randomSeed'])
        self.assertTrue(all('elapsedMs' in row for source in metrics['sources'] for row in source['attempts']))

    async def test_unusable_blueprint_does_not_remove_an_ordinary_winner(self):
        q = Quotes(Engine())
        async def neighbors():
            return [{'family': quote_path_family({}), 'side': 'upper', **{'identity': 'old', 'quote': {}}}]
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
                return [{'family': quote_path_family(saved), 'side': 'upper', **{'identity': 'legacy', 'quote': saved}}]
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
            return [{'family': quote_path_family(saved), 'side': 'upper', **{'identity': 'legacy', 'quote': saved}}]
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
