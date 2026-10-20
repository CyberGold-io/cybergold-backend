"""Expose Core and Market pricing/qualification evidence without new policy."""
import asyncio
from copy import deepcopy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cybergold_candidate.quote_errors import QuoteFailure, public_quote_error
from cybergold_candidate.preview_errors import KnownPreviewError
from cybergold_candidate.rpc_diagnostics import (
    quote_work_scope, route_work_scope, freeze_quote_work, quote_error_diagnostics,
    route_legs, route_leg_started, route_leg_finished, provider_qualification_begin,
    provider_qualification_scope, provider_qualification_stage, provider_qualification_finish,
    provider_qualification_current, route_count,
    provider_qualification_selected, provider_qualification_terms,
    quote_candidate_scope, current_quote_diagnostics,
)
from cybergold_candidate.quote_cache import IntentSharing
from cybergold_candidate.token_preview import TokenPreviewRpc
from cybergold_candidate.route_scheduler import schedule_routes
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.basket_preview import InvalidPreview
from test_quote_intent import service, request, retained_plan
import test_uniswap_market as market_fixture
POOL, BLOCK = market_fixture.POOL, market_fixture.BLOCK

A, B = '0x'+'1'*40, '0x'+'2'*40


class SharedCandidateObservations(unittest.IsolatedAsyncioTestCase):
    async def shared(self, *, logger_failure=False):
        entered, release = asyncio.Event(), asyncio.Event()
        @quote_work_scope
        async def provider(name):
            probe = provider_qualification_begin('qualification', provider=name)
            with provider_qualification_scope(probe):
                provider_qualification_terms(executionAmount='123', quotedInput='100', quotedOutput='123')
                probe.row.update(privateRequest='https://secret.invalid', signature='0xprivate')
                provider_qualification_finish(probe, 'qualified')
                provider_qualification_finish(probe, 'rejected', QuoteFailure('quote-no-route'))
            return current_quote_diagnostics()
        async def get(_request, update, **_kwargs):
            entered.set()
            await release.wait()
            return {'core': await provider('core'), 'market': await provider('market')}
        service = SimpleNamespace(get=get, routes=SimpleNamespace(rpc=object()))
        shared = IntentSharing(service, head=lambda: asyncio.sleep(0, result={'hash': '0x'+'a'*64}))
        self.addAsyncCleanup(shared.close)
        frames, messages = [[], []], []
        def logger(message):
            messages.append(json.loads(message))
            if logger_failure:
                raise RuntimeError('inert local log sink unavailable')
        with patch('cybergold_candidate.rpc_diagnostics.logging.getLogger') as mocked:
            mocked.return_value.info.side_effect = logger
            one = asyncio.create_task(shared.get({'amount': '100'}, lambda row: asyncio.sleep(0)))
            await asyncio.wait_for(entered.wait(), 2)
            two = asyncio.create_task(shared.get({'amount': '100'}, lambda row: asyncio.sleep(0)))
            async with asyncio.timeout(2):
                while shared.joined != 1:
                    await asyncio.sleep(0)
            release.set()
            values = await asyncio.gather(one, two)
        self.assertEqual(values[0], values[1])
        self.assertEqual((shared.started, shared.joined), (1, 1))
        self.assertEqual(len(messages), 4)
        self.assertEqual(len({row['workId'] for row in messages}), 1)
        self.assertEqual([(row['provider'], row['phase'], row['candidate']['outcome']) for row in messages],
            [('core', 'started', 'running'), ('core', 'completed', 'qualified'),
             ('market', 'started', 'running'), ('market', 'completed', 'qualified')])
        self.assertNotIn('secret.invalid', repr(messages))
        self.assertNotIn('signature', repr(messages))
        self.assertFalse(shared.pending)
        return values[0]

    async def test_two_subscribers_log_each_provider_candidate_once(self):
        await self.shared()

    async def test_candidate_logger_outage_does_not_change_shared_quote(self):
        self.assertEqual((await self.shared(logger_failure=True))['core']['providerQualifications']['qualified'], 1)

    async def test_cleanup_terminal_is_logged_once_without_rewriting_cutoff_snapshot(self):
        messages = []
        @quote_work_scope
        async def work():
            probe = provider_qualification_begin('qualification', provider='market')
            freeze_quote_work()
            frozen = deepcopy(current_quote_diagnostics())
            provider_qualification_finish(probe, 'cancelled')
            provider_qualification_finish(probe, 'cancelled')
            self.assertEqual(current_quote_diagnostics(), frozen)
            self.assertEqual(frozen['providerQualifications']['rows'][0]['outcome'], 'running')
        with patch('cybergold_candidate.rpc_diagnostics.logging.getLogger') as mocked:
            mocked.return_value.info.side_effect = lambda row: messages.append(json.loads(row))
            with quote_candidate_scope('12345678-1234-1234-1234-123456789abc'):
                await work()
        self.assertEqual([row['candidate']['outcome'] for row in messages], ['running', 'cancelled'])

    async def test_direct_native_work_has_no_invented_shared_work_identifier(self):
        @quote_work_scope
        async def work():
            probe = provider_qualification_begin()
            provider_qualification_finish(probe, 'qualified')
        with patch('cybergold_candidate.rpc_diagnostics.logging.getLogger') as mocked:
            await work()
        mocked.assert_not_called()


class CoreDiscoveryEvidence(unittest.IsolatedAsyncioTestCase):
    async def test_retained_core_leg_tolerance_rejection_retains_compared_bounds_then_falls_back(self):
        for mode in ('issue-exact-in', 'redeem-exact-in'):
            with self.subTest(mode=mode):
                intent, _provider, routes, _wire = service()
                self.addAsyncCleanup(routes.close)
                intent.retain_plans, intent.qualification = True, False
                value = request(mode)
                first = await intent.get(value, lambda _row: asyncio.sleep(0))
                prior = retained_plan(first)
                if mode.startswith('issue'):
                    prior['quotes'][0]['amountIn'] = '1'
                else:
                    prior['quotes'][0]['minimumAmountOut'] = '10000'
                result = await intent.get({**value, 'retainedPlan': prior}, lambda _row: asyncio.sleep(0))
                self.assertEqual(result['executionAmount'], first['executionAmount'])
                rejected = next(row for row in result['quoteDiagnostics']['providerQualifications']['rows']
                                if row['outcome'] == 'rejected')
                self.assertEqual(rejected['stage'], 'tolerance')
                if mode.startswith('issue'):
                    self.assertEqual(rejected['maximumAmountIn'], '1')
                    self.assertGreater(int(rejected['observedAmountIn']), 1)
                else:
                    self.assertEqual(rejected['minimumAmountOut'], '10000')
                    self.assertLess(int(rejected['observedAmountOut']), 10000)

    async def test_successful_retained_core_plan_and_transport_rejection_keep_actual_probe(self):
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        intent.retain_plans = True
        value = request('redeem-exact-in')
        first = await intent.get(value, lambda _row: asyncio.sleep(0))
        retained = {**value, 'retainedPlan': retained_plan(first)}
        result = await intent.get(retained, lambda _row: asyncio.sleep(0))
        self.assertTrue(result['quoteDiagnostics']['qualified'])
        rows = result['quoteDiagnostics']['providerQualifications']['rows']
        self.assertEqual(len(rows), 2)  # Retained revalidation, existing final canonical validation.
        self.assertTrue(all(row['outcome'] == 'qualified' for row in rows))
        async def unavailable(*_args, **_kwargs):
            raise QuoteFailure('rpc-timeout')
        routes.engine.quote_branches = unavailable
        with self.assertRaises(QuoteFailure) as caught:
            await intent.get(retained, lambda _row: asyncio.sleep(0))
        evidence = quote_error_diagnostics(caught.exception)['providerQualifications']
        self.assertEqual((evidence['attempts'], evidence['rejected']), (1, 1))
        self.assertEqual(evidence['rows'][0]['code'], 'rpc-timeout')
        self.assertIn(evidence['rows'][0]['stage'], ('composition', 'route-pricing'))

    async def fixture(self, *, missing=False, composition_error=False):
        intent, provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        engine = routes.engine
        original_compose = engine.compose_core_rows
        calls = {}
        async def quote(_branches, mode, amount, _block):
            calls[amount] = calls.get(amount, 0)+1
            if missing and amount == 101:
                if calls[amount] == 1:
                    raise QuoteFailure('quote-no-route')
                await asyncio.Event().wait()
            return {'amountIn': '100' if mode == 'exactOut' else str(amount),
                    'amountOut': str(amount) if mode == 'exactOut' else str(amount*2)}
        engine.quote_branches = quote
        async def controlled(value, block, evaluate, *, on_completed):
            async def feed(index, target):
                for _ in range(2 if missing and index == 1 else 1):
                    yield next(iter(engine.initial_v3_branches(target,
                        'exactOut' if value['mode'] == 'exact-out' else 'exactIn')))
            await schedule_routes(lambda _expanded: [feed(index, target)
                for index, target in enumerate(value['targets'])], evaluate, on_completed=on_completed)
            await asyncio.Event().wait()
        engine.search_candidates = controlled
        if composition_error:
            async def compose(*args, **kwargs):
                raise QuoteFailure('quote-contract-reverted')
            engine.compose_core_rows = compose
        value = request('redeem-exact-out')
        if missing:
            value['targets'][1]['amount'] = '101'
        return intent, provider, value

    async def failed(self, intent, value):
        timeout = asyncio.timeout
        events = []
        async def emit(event):
            events.append(event)
        # Only an inert in-process quote fixture is shortened for this test.
        with patch('cybergold_candidate.route_search.asyncio.timeout',
                   side_effect=lambda _seconds: timeout(.5)):
            with self.assertRaises(TimeoutError) as caught:
                await intent.get(value, emit)
        self.assertFalse(any(row['type'] == 'qualified' for row in events))
        return public_quote_error(caught.exception)['quoteDiagnostics']

    async def test_initial_timeout_retains_success_missing_leg_and_pending_cleanup_separately(self):
        intent, provider, value = await self.fixture(missing=True)
        diagnostics = await self.failed(intent, value)
        self.assertEqual(diagnostics['phase'], 'initial-search')
        self.assertFalse(diagnostics['qualified'])
        legs = diagnostics['routeWave']['legs']['rows']
        self.assertEqual(len(legs), 2)
        self.assertEqual((legs[0]['succeeded'], legs[0]['bestAvailable']), (1, True))
        self.assertEqual(legs[0]['bestPools'][0]['protocol'], 'v3')
        self.assertEqual((legs[1]['started'], legs[1]['failed'], legs[1]['pending']), (2, 1, 1))
        self.assertFalse(legs[1]['bestAvailable'])
        self.assertEqual(legs[1]['failureCounts'], [{'code': 'quote-no-route', 'count': 1}])
        self.assertEqual(legs[1]['cancelled'], 0)  # Frozen before deadline cleanup.
        self.assertNotIn('providerQualifications', diagnostics)
        self.assertEqual(provider.contract_calls, [])

    async def test_complete_leg_vector_and_composition_rejection_are_not_a_missing_leg(self):
        intent, _provider, value = await self.fixture(composition_error=True)
        diagnostics = await self.failed(intent, value)
        self.assertTrue(all(leg['bestAvailable'] for leg in diagnostics['routeWave']['legs']['rows']))
        probes = diagnostics['providerQualifications']
        self.assertEqual((probes['attempts'], probes['rejected'], probes['pending']), (1, 1, 0))
        self.assertEqual([{key: row[key] for key in ('attempt', 'stage', 'outcome', 'code')}
                          for row in probes['rows']], [{'attempt': 1, 'stage': 'composition', 'outcome': 'rejected',
                                                        'code': 'quote-contract-reverted'}])

    async def test_suppressed_helpers_rejection_retains_only_known_code_and_stage(self):
        intent, _provider, value = await self.fixture()
        async def reject(*_args, **_kwargs):
            raise KnownPreviewError('redemption-capacity-exceeded', 'private payload https://secret.invalid')
        with patch.object(TokenPreviewRpc, 'preview', reject):
            diagnostics = await self.failed(intent, value)
        probe = diagnostics['providerQualifications']['rows'][0]
        self.assertEqual((probe['stage'], probe['outcome'], probe['code']),
                         ('final-preview', 'rejected', 'redemption-capacity-exceeded'))
        self.assertNotIn('private', json.dumps(diagnostics))
        self.assertNotIn('targetAmount', probe)

    async def test_suppressed_tolerance_rejection_has_exact_requested_interval_and_observation(self):
        intent, _provider, value = await self.fixture()
        original = TokenPreviewRpc.preview
        async def zero_output(*args, **kwargs):
            result = await original(*args, **kwargs)
            return {**result, 'minimumAmountOut': '0'}
        with patch.object(TokenPreviewRpc, 'preview', zero_output):
            diagnostics = await self.failed(intent, value)
        probe = diagnostics['providerQualifications']['rows'][0]
        self.assertEqual({key: value for key, value in probe.items() if key not in ('startedMs', 'completedMs', 'elapsedMs')},
            {'attempt': 1, 'stage': 'tolerance', 'outcome': 'rejected',
            'code': 'quote-unavailable', 'targetAmount': '200', 'minimumAmountOut': '200',
            'maximumAmountOut': '202', 'observedAmountOut': '0'})

    async def test_deadline_retains_active_helpers_stage_before_probe_cancellation_cleanup(self):
        intent, _provider, value = await self.fixture()
        async def held(*_args, **_kwargs):
            await asyncio.Event().wait()
        with patch.object(TokenPreviewRpc, 'preview', held):
            diagnostics = await self.failed(intent, value)
        probes = diagnostics['providerQualifications']
        self.assertEqual((probes['pending'], probes['rejected'], probes['cancelled']), (1, 0, 0))
        self.assertEqual((probes['rows'][0]['stage'], probes['rows'][0]['outcome']),
                         ('final-preview', 'running'))

    async def test_optional_diagnostic_observer_failures_do_not_change_executable_core_result(self):
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        observed = await intent.get(request('redeem-exact-out'), lambda _: asyncio.sleep(0))
        with patch('cybergold_candidate.rpc_diagnostics._safe_pools', side_effect=RuntimeError('observer unavailable')), \
                patch('cybergold_candidate.rpc_diagnostics._ProviderQualification.finish', side_effect=RuntimeError('observer unavailable')):
            result = await intent.get(request('redeem-exact-out'), lambda _: asyncio.sleep(0))
        for name in ('executionAmount', 'maximumInputAmount', 'displayAmount', 'quotes', 'expectedCoreOutputs'):
            self.assertEqual(result[name], observed[name])


class ClosedCoreProjection(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_owned_producers_freeze_their_own_legs_and_probes_on_shared_error(self):
        shared = TimeoutError('private shared provider request')
        barrier, started = asyncio.Event(), 0
        class Producer:
            @quote_work_scope
            @route_work_scope
            async def get(inner, value):
                nonlocal started
                leg, = route_legs(value['targets'])
                route_leg_started(leg)
                route_leg_finished(leg, 'failed', code=value['code'])
                probe = provider_qualification_begin('final-preview')
                provider_qualification_finish(probe, 'rejected', QuoteFailure(value['code']))
                started += 1
                if started == 2:
                    barrier.set()
                await barrier.wait()
                freeze_quote_work(shared)
                # Late cleanup cannot change the snapshot or another producer.
                route_leg_finished(leg, 'cancelled')
                return quote_error_diagnostics(shared)
        a, b = await asyncio.gather(*(Producer().get({'mode': 'exact-out', 'code': code,
            'targets': [{'inputAsset': A, 'outputAsset': B, 'amount': str(index)}]})
            for index, code in ((1, 'quote-no-route'), (2, 'rpc-timeout'))))
        for result, amount, code in ((a, '1', 'quote-no-route'), (b, '2', 'rpc-timeout')):
            leg, = result['routeWave']['legs']['rows']
            self.assertEqual((leg['amount'], leg['failed'], leg['cancelled']), (amount, 1, 0))
            self.assertEqual(leg['failureCounts'], [{'code': code, 'count': 1}])
            self.assertEqual(result['providerQualifications']['rows'][0]['code'], code)

    async def test_cancelled_and_superseded_probes_are_not_pricing_rejections_and_rows_are_bounded(self):
        class Producer:
            @quote_work_scope
            @route_work_scope
            async def get(inner, value):
                legs = route_legs(value['targets'])
                route_leg_started(legs[0])
                route_leg_finished(legs[0], 'cancelled')
                for index in range(12):
                    probe = provider_qualification_begin('composition')
                    provider_qualification_finish(probe, 'cancelled' if index % 2 else 'superseded')
                error = TimeoutError()
                freeze_quote_work(error)
                return quote_error_diagnostics(error)
        result = await Producer().get({'mode': 'exact-out', 'targets': [
            {'inputAsset': A, 'outputAsset': B, 'amount': '1'} for _ in range(20)]})
        legs, probes = result['routeWave']['legs'], result['providerQualifications']
        self.assertEqual((legs['count'], len(legs['rows']), legs['omittedRows']), (20, 16, 4))
        self.assertEqual((legs['rows'][0]['cancelled'], legs['rows'][0]['failed']), (1, 0))
        self.assertEqual((probes['attempts'], len(probes['rows']), probes['omittedRows']), (12, 8, 4))
        self.assertEqual((probes['rejected'], probes['cancelled'], probes['superseded']), (0, 6, 6))

    async def test_closed_projection_drops_credentials_and_invalid_quantities_without_losing_valid_fields(self):
        error = TimeoutError()
        error.quote_diagnostics = {'phase': 'initial-search', 'providerQualifications': {
            'provider': 'core', 'attempts': 1, 'pending': 0, 'rejected': 1, 'secret': 'private-token', 'rows': [{
                'attempt': 1, 'stage': 'tolerance', 'outcome': 'rejected', 'code': 'quote-unavailable',
                'targetAmount': '2', 'minimumAmountOut': '-1', 'maximumAmountOut': str(2**256),
                'observedAmountOut': '01', 'message': 'https://private.invalid?key=secret'}]},
            'routeWave': {'mode': 'exact-out', 'legs': {'count': 1, 'rows': [{
                'index': 0, 'failed': 1, 'pending': -1, 'inputAsset': A, 'outputAsset': 'private-token',
                'amount': '3', 'bestAvailable': True, 'request': 'private-token',
                'failureCounts': [{'code': 'rpc-timeout', 'count': 1, 'message': 'private-token'},
                                  {'code': 'private-token', 'count': 1}],
                'bestPools': [{'protocol': 'v3', 'poolId': 'v3:'+A+':'+B+':000500',
                               'poolAddress': B, 'url': 'private-token'},
                              {'protocol': 'v3', 'poolId': 'https://private.invalid'}]}]}}}
        result = quote_error_diagnostics(error)
        self.assertNotIn('private', json.dumps(result))
        probe = result['providerQualifications']['rows'][0]
        self.assertEqual(probe['targetAmount'], '2')
        self.assertFalse(set(probe) & {'minimumAmountOut', 'maximumAmountOut', 'observedAmountOut'})
        leg = result['routeWave']['legs']['rows'][0]
        self.assertNotIn('pending', leg)
        self.assertEqual(leg['failureCounts'], [{'code': 'rpc-timeout', 'count': 1}])
        self.assertEqual(len(leg['bestPools']), 1)

    async def test_nested_producer_cannot_inherit_or_finish_outer_qualification(self):
        class Nested:
            @quote_work_scope
            async def get(inner):
                self.assertIsNone(provider_qualification_current())
                nested = provider_qualification_begin('route-pricing', provider='market')
                provider_qualification_finish(nested, 'rejected', QuoteFailure('quote-no-route'))
                error = TimeoutError()
                freeze_quote_work(error)
                return quote_error_diagnostics(error)
        class Outer:
            @quote_work_scope
            async def get(inner):
                outer = provider_qualification_begin('composition')
                with provider_qualification_scope(outer):
                    nested = await Nested().get()
                    self.assertIs(provider_qualification_current(), outer)
                    provider_qualification_finish(outer, 'not-improved')
                error = TimeoutError()
                freeze_quote_work(error)
                return quote_error_diagnostics(error), nested
        outer, nested = await Outer().get()
        self.assertEqual(outer['providerQualifications']['provider'], 'core')
        self.assertEqual(outer['providerQualifications']['notImproved'], 1)
        self.assertEqual(outer['providerQualifications']['rejected'], 0)
        self.assertEqual(nested['providerQualifications']['provider'], 'market')
        self.assertEqual(nested['providerQualifications']['rejected'], 1)

    async def test_selected_attempt_and_terms_survive_bounded_later_rejections(self):
        class Producer:
            @quote_work_scope
            async def get(inner):
                selected = provider_qualification_begin('selection')
                with provider_qualification_scope(selected):
                    provider_qualification_terms(executionAmount='400', quotedOutput='400', inputMaximum='100')
                    provider_qualification_selected(selected)
                    provider_qualification_finish(selected, 'qualified')
                for _ in range(20):
                    probe = provider_qualification_begin('final-preview')
                    provider_qualification_finish(probe, 'rejected', QuoteFailure('quote-no-route'))
                error = TimeoutError()
                freeze_quote_work(error)
                return quote_error_diagnostics(error)
        evidence = (await Producer().get())['providerQualifications']
        self.assertEqual((evidence['selectedAttempt'], evidence['attempts'], evidence['omittedRows']), (1, 21, 13))
        self.assertEqual(len(evidence['rows']), 8)
        selected = next(row for row in evidence['rows'] if row['attempt'] == evidence['selectedAttempt'])
        self.assertEqual((selected['quotedOutput'], selected['inputMaximum']), ('400', '100'))
        self.assertGreaterEqual(selected['completedMs'], selected['startedMs'])


class MarketDiscoveryEvidence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await market_fixture.MarketIntegration.asyncSetUp(self)
        self.quotes.get_model = AsyncMock(return_value={})
        self.quotes.estimate = lambda *_: None
        self.actions, self.outputs = {}, {}
        self.forced_output = None
        self.qualifying = asyncio.Event()
        self.pending_probe = None
        self.hold_tail = False
        self.selected_ids = [1, 2, 3]
        async def branches(_index):
            for index in self.selected_ids:
                pool = {**deepcopy(POOL), 'id': '0x'+format(index+100, '040x'),
                        'address': '0x'+format(index+100, '040x')}
                yield [{'amountIn': '1000', 'hops': [{'pool': pool, 'zeroForOne': True}]}]
            if self.hold_tail:
                await asyncio.Event().wait()
        async def search(_request, _block, evaluate, **_kwargs):
            async def admitted(index, value):
                route_count('typedEnumerated')
                await evaluate(index, value)
            await schedule_routes(lambda _expanded: [branches(0)], admitted)
        self.quotes.search_candidates = search
        async def price(value, mode, amount, _block):
            index = int(value[0]['hops'][0]['pool']['id'], 16)-100
            action = self.actions.get(index)
            if action == 'pricing-hold':
                self.qualifying.set()
                await asyncio.Event().wait()
            if action == 'pricing-error':
                raise QuoteFailure('quote-no-route')
            output = self.forced_output if self.forced_output is not None else self.outputs.get(index,
                amount if mode == 'exactOut' else amount*2)
            return {'amountIn': str(output if mode == 'exactOut' else amount),
                    'amountOut': str(amount if mode == 'exactOut' else output)}
        self.quotes.quote_branches = price
        ordinary_qualify = self.quotes.qualify_quote
        async def qualify(request, value, *args, **kwargs):
            index = int(value[0]['hops'][0]['pool']['id'], 16)-100
            action = self.actions.get(index)
            if action == 'qualification-hold':
                self.pending_probe = provider_qualification_current()
                self.qualifying.set()
                await asyncio.Event().wait()
            if action == 'qualification-error' and not kwargs.get('retained'):
                raise InvalidPreview('private candidate payload https://secret.invalid')
            return await ordinary_qualify(request, value, *args, **kwargs)
        self.quotes.qualify_quote = qualify

    async def asyncTearDown(self):
        await market_fixture.MarketIntegration.asyncTearDown(self)

    async def public_failure(self, value=None, error_type=TimeoutError):
        frames = []
        async def emit(frame):
            frames.append(frame)
        with budget_context(QuoteBudget(initial=.05, extension=.45)):
            with self.assertRaises(error_type) as caught:
                await self.quotes.get(value or self.request, emit)
        return quote_error_diagnostics(caught.exception), frames

    async def test_public_budget_timeout_keeps_market_pricing_success_rejections_and_pending_route(self):
        self.actions = {1: 'qualification-error', 2: 'pricing-error', 3: 'pricing-hold'}
        diagnostics, frames = await self.public_failure()
        leg, = diagnostics['routeWave']['legs']['rows']
        self.assertEqual((leg['succeeded'], leg['failed'], leg['pending']), (1, 1, 1))
        self.assertTrue(leg['bestAvailable'])
        probes = diagnostics['providerQualifications']
        self.assertEqual(probes['provider'], 'market')
        self.assertEqual((probes['rejected'], probes['pending']), (2, 1))
        self.assertTrue(any(row['stage'] == 'qualification' and row['outcome'] == 'rejected'
                            for row in probes['rows']))
        self.assertTrue(any(row['stage'] == 'route-pricing' and row['outcome'] == 'running'
                            for row in probes['rows']))
        self.assertFalse(any(row['type'] == 'qualified' for row in frames))
        self.assertNotIn('private', json.dumps(diagnostics))
        self.assertEqual(self.quotes.semaphore._value, 8)

    async def test_public_budget_timeout_keeps_active_qualification_after_pricing_completed(self):
        self.actions = {1: 'qualification-error', 2: 'pricing-error', 3: 'qualification-hold'}
        diagnostics, _frames = await self.public_failure()
        leg, = diagnostics['routeWave']['legs']['rows']
        self.assertEqual((leg['succeeded'], leg['failed'], leg['pending']), (2, 1, 0))
        probe = next(row for row in diagnostics['providerQualifications']['rows'] if row['outcome'] == 'running')
        self.assertEqual(probe['stage'], 'qualification')
        self.assertEqual(diagnostics['providerQualifications']['cancelled'], 0)
        self.assertEqual(self.pending_probe.row['outcome'], 'cancelled')  # Live cleanup completed after the frozen cutoff.
        self.assertEqual(self.pending_probe.work.qualifications.counts['cancelled'], 1)

    async def test_best_pool_is_best_pricing_candidate_not_last_successful_candidate(self):
        self.actions = dict.fromkeys((1, 2, 3), 'qualification-error')
        self.outputs = {1: 2000, 2: 1000, 3: 1500}
        diagnostics, _frames = await self.public_failure(error_type=QuoteFailure)
        leg, = diagnostics['routeWave']['legs']['rows']
        self.assertEqual((leg['succeeded'], leg['failed']), (3, 0))
        self.assertEqual(leg['bestPools'][0]['poolId'], '0x'+format(101, '040x'))
        self.assertEqual(diagnostics['providerQualifications']['rejected'], 3)

    async def test_final_canonicality_failure_is_explicit_and_keeps_pricing_evidence(self):
        self.selected_ids = [1]
        reads = 0
        async def canonical(_block):
            nonlocal reads
            reads += 1
            if reads == 2:
                raise SnapshotChanged('canonical block changed')
        self.rpc.assert_canonical = canonical
        diagnostics, frames = await self.public_failure(error_type=SnapshotChanged)
        self.assertTrue(any(row['type'] == 'qualified' for row in frames))
        self.assertFalse(diagnostics['qualified'])
        self.assertTrue(diagnostics['routeWave']['legs']['rows'][0]['bestAvailable'])
        self.assertEqual(diagnostics['providerQualifications']['rows'][-1]['stage'], 'canonicality')
        self.assertEqual(diagnostics['providerQualifications']['rows'][-1]['outcome'], 'rejected')
        self.assertEqual(reads, 2)

    async def test_success_snapshot_gets_actual_complete_selection_reason_after_budget_produce(self):
        self.selected_ids = [1]
        result = await self.quotes.get(self.request)
        evidence = result['quoteDiagnostics']['providerQualifications']
        self.assertEqual(evidence['selectionReason'], 'complete')
        selected = next(row for row in evidence['rows'] if row['attempt'] == evidence['selectedAttempt'])
        self.assertEqual((selected['quotedInput'], selected['quotedOutput']), (result['totalInput'], result['netOutput']))
        self.assertEqual(selected['outcome'], 'qualified')
        self.assertGreaterEqual(evidence['selectionMs'], evidence['firstQualifiedMs'])

    async def test_retained_market_tolerance_failure_records_actual_bounds_and_ordinary_fallback(self):
        self.selected_ids = [1]
        for mode in ('exact-in', 'exact-out'):
            with self.subTest(mode=mode):
                value = {**self.request, 'mode': mode}
                self.actions, self.outputs = {}, {1: 2000 if mode == 'exact-in' else 300}
                self.forced_output = None
                original = await self.quotes.get(value)
                self.outputs = {1: 1 if mode == 'exact-in' else 10000}
                self.forced_output = self.outputs[1]
                self.actions = {1: 'qualification-error'}
                diagnostics, _frames = await self.public_failure({**value, 'retainedPlan': original['plan']}, QuoteFailure)
                probe = next(row for row in diagnostics['providerQualifications']['rows'] if row['stage'] == 'tolerance')
                self.assertEqual(probe['outcome'], 'rejected')
                if mode == 'exact-in':
                    self.assertEqual(probe['minimumAmountOut'], original['outputMinimum'])
                    self.assertEqual(probe['observedAmountOut'], '1')
                else:
                    self.assertEqual(probe['maximumAmountIn'], original['inputMaximum'])
                    self.assertGreater(int(probe['observedAmountIn']), int(probe['maximumAmountIn']))
                leg, = diagnostics['routeWave']['legs']['rows']
                self.assertEqual((leg['started'], leg['succeeded'], leg['failed']), (2, 2, 0))

    async def test_public_caller_cancellation_remains_cancellation_without_qualifier_rejection(self):
        self.selected_ids = [3]
        self.actions = {3: 'qualification-hold'}
        task = asyncio.create_task(self.quotes.get(self.request))
        await asyncio.wait_for(self.qualifying.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.pending_probe.work.qualifications.counts['rejected'], 0)
        self.assertEqual(self.quotes.semaphore._value, 8)


if __name__ == '__main__':
    unittest.main()
