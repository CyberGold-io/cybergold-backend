"""Budget deadlines retain actual provider diagnostics through intent sharing."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.quote_cache import IntentSharing
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.rpc_diagnostics import rpc_call, rpc_diagnostic_scope
from cybergold_candidate.trade_quote import TradeQuotes
from test_quote_intent import service, request, ADAPTER, ASSET_A, ASSET_B
from test_trade_quote import request as trade_request


class BudgetTimeoutDiagnostics(unittest.IsolatedAsyncioTestCase):
    def fixture(self, *, unified=False, ordinary_deadline=False):
        intent, _provider, routes, _wire = service(31338)
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def blocked(*_args, **_kwargs):
            started.set()
            try:
                with rpc_call('eth_call', stage='route-search'):
                    if ordinary_deadline:
                        async with asyncio.timeout(.05):
                            await asyncio.Event().wait()
                    else:
                        await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        routes.rpc.quote_batch_counted = blocked
        if unified:
            async def head():
                return await routes.rpc.block(None)
            def packet(value):
                return {'namespace': 'market', 'intent': value, 'routes': [], 'feeRatePpm': 1000}
            async def model(value, *, block):
                return packet(value)
            async def impossible_market(*_args, **_kwargs):
                self.fail('Native request unexpectedly dispatched Market')
            market = SimpleNamespace(head=head, packet=packet, get_model=model,
                estimate=lambda *_: None, _get=impossible_market)
            async def resolver(value):
                return {**value, 'adapter': ADAPTER}
            async def basis(_block):
                return [ASSET_A, ASSET_B], [500000, 500000], 2
            quotes = TradeQuotes(intent.settings, intent, market,
                request_resolver=resolver, basis_reader=basis)
            sharing = quotes.sharing
            get = lambda publish: quotes.get(trade_request(native=True), publish)
        else:
            quotes = None
            sharing = IntentSharing(intent)
            get = lambda publish: sharing.get(request('issue-exact-in', True), publish)
        self.addAsyncCleanup(routes.close)
        self.addAsyncCleanup(sharing.close)
        return SimpleNamespace(get=get, sharing=sharing, quotes=quotes,
            started=started, cancelled=cancelled)

    def operation(self, fixture, budget, frames):
        async def publish(frame):
            frames.append(deepcopy(frame))
        async def capture():
            with rpc_diagnostic_scope():
                try:
                    return await fixture.get(publish)
                except Exception as error:
                    return type(error), public_quote_error(error)
        with budget_context(budget):
            return asyncio.create_task(capture())

    def assert_search_timeout(self, outcome):
        error_type, payload = outcome
        self.assertIs(error_type, TimeoutError)
        self.assertEqual(payload['code'], 'quote-timeout')
        self.assertIn('quoteDiagnostics', payload)
        logical = payload['quoteDiagnostics']
        self.assertEqual(logical['phase'], 'initial-search')
        self.assertFalse(logical['qualified'])
        self.assertEqual(logical['inversionIteration'], 0)
        self.assertEqual(logical['routeWave']['mode'], 'exact-in')
        self.assertEqual(logical['routeWave']['subphase'], 'v3-coverage')
        self.assertGreater(logical['routeWave']['legacyCandidates'], 0)
        self.assertEqual(logical['routeWave']['legacyCompleted'], 0)
        self.assertEqual(logical['routeWave']['typedPending'], 0)
        self.assertGreaterEqual(logical['elapsedMs'], logical['routeWave']['elapsedMs'])
        self.assertNotIn('fixture.invalid', repr(payload))
        return payload

    async def test_core_budget_timeout_keeps_route_snapshot_through_intent_sharing(self):
        fixture, frames, budget = self.fixture(), [], QuoteBudget(.2, .8)
        payload = self.assert_search_timeout(await asyncio.wait_for(self.operation(fixture, budget, frames), 5))
        self.assertEqual(payload['diagnostics']['stage'], 'route-search')
        self.assertEqual(payload['diagnostics']['failureType'], 'backend-deadline')
        self.assertTrue(fixture.started.is_set())
        self.assertTrue(fixture.cancelled.is_set())
        self.assertEqual(budget.reason, 'timeout')
        self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
        self.assertFalse(fixture.sharing.pending)

    async def test_unified_budget_timeout_reaches_both_subscribers_without_reclassifying_error(self):
        fixture, first_frames, second_frames = self.fixture(unified=True), [], []
        first_budget, second_budget = QuoteBudget(.2, .8), QuoteBudget(.2, .8)
        first = self.operation(fixture, first_budget, first_frames)
        await asyncio.wait_for(fixture.started.wait(), 5)
        second = self.operation(fixture, second_budget, second_frames)
        outcomes = await asyncio.wait_for(asyncio.gather(first, second), 5)
        payloads = [self.assert_search_timeout(outcome) for outcome in outcomes]
        self.assertEqual(payloads[0]['quoteDiagnostics'], payloads[1]['quoteDiagnostics'])
        self.assertEqual(fixture.sharing.started, 1)
        self.assertEqual(fixture.sharing.joined, 1)
        self.assertEqual(first_budget.reason, 'timeout')
        self.assertIsNone(second_budget.reason)
        self.assertTrue(fixture.cancelled.is_set())
        self.assertFalse(any(frame['type'] == 'qualified' for frame in first_frames + second_frames))
        self.assertFalse(fixture.sharing.pending)

    async def test_unified_context_stop_returns_timeout_without_inventing_route_snapshot(self):
        fixture, frames, budget = self.fixture(unified=True), [], QuoteBudget(.1, .1)
        basis_started = asyncio.Event()
        async def basis(_block):
            basis_started.set()
            await asyncio.Event().wait()
        fixture.quotes.basis_reader = basis
        error_type, payload = await asyncio.wait_for(self.operation(fixture, budget, frames), 5)
        self.assertIs(error_type, TimeoutError)
        self.assertEqual(payload['code'], 'quote-timeout')
        self.assertNotIn('quoteDiagnostics', payload)
        self.assertTrue(basis_started.is_set())
        self.assertFalse(fixture.started.is_set())
        self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
        self.assertFalse(fixture.sharing.pending)

    async def test_last_caller_cancel_remains_cancellation_and_drains_actual_route(self):
        fixture, frames, budget = self.fixture(unified=True), [], QuoteBudget(5, 10)
        operation = self.operation(fixture, budget, frames)
        await asyncio.wait_for(fixture.started.wait(), 5)
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertTrue(fixture.cancelled.is_set())
        self.assertFalse(budget.stop.is_set())
        self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
        self.assertFalse(fixture.sharing.pending)

    async def test_ordinary_provider_deadline_retains_existing_diagnostic_payload(self):
        fixture, frames, budget = self.fixture(unified=True, ordinary_deadline=True), [], QuoteBudget(5, 10)
        payload = self.assert_search_timeout(await asyncio.wait_for(self.operation(fixture, budget, frames), 5))
        self.assertEqual(payload['diagnostics']['stage'], 'route-search')
        self.assertEqual(payload['diagnostics']['failureType'], 'provider-timeout')
        self.assertIsNone(budget.reason)
        self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
        self.assertFalse(fixture.sharing.pending)


if __name__ == '__main__':
    unittest.main()
