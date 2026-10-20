"""Producer-owned selection stop retains ordinary executable finalization."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, patch

from cybergold_candidate.quote_budget import QuoteBudget, SearchStopped, budget_context
from cybergold_candidate.recovery_rpc import SnapshotChanged
import test_quote_intent as core_fixture
import test_uniswap_market as market_fixture

request = core_fixture.request
POOL, BLOCK = market_fixture.POOL, market_fixture.BLOCK


class CoreBudgetProviders(unittest.IsolatedAsyncioTestCase):
    fixture = core_fixture.EarlyCheckedIssueTests.fixture

    async def ready(self, event):
        await asyncio.wait_for(event.wait(), 1)

    async def run_core(self, intent, value, frames, budget):
        async def publish(frame):
            frames.append(deepcopy(frame))
        with budget_context(budget):
            return await intent.get(value, publish)

    def tracked_fixture(self):
        intent, provider, routes, control = self.fixture()
        control.cancelled = asyncio.Event()
        reserve = routes.engine.search_routes
        async def tracked(*args, **kwargs):
            try:
                return await reserve(*args, **kwargs)
            except asyncio.CancelledError:
                control.cancelled.set()
                raise
        routes.engine.search_routes = tracked
        return intent, provider, routes, control

    async def wait_qualified(self, budget):
        for _ in range(1000):
            if budget.ready:
                return
            await asyncio.sleep(0)
        self.fail('The held search produced no fully checked candidate')

    async def test_core_stop_recovers_checked_tuple_and_drains_owned_tail(self):
        for native in (False, True):
            with self.subTest(native=native):
                intent, provider, routes, control = self.tracked_fixture()
                budget, frames = QuoteBudget(), []
                operation = asyncio.create_task(self.run_core(intent, request('issue-exact-in', native), frames, budget))
                try:
                    await self.wait_qualified(budget)
                    first = next(frame['value'] for frame in frames if frame['type'] == 'qualified')
                    headers = sum(method.startswith('eth_getBlock') for method, _ in provider.calls)
                    budget.finish_selection('best-initial')
                    result = await asyncio.wait_for(operation, 1)
                    self.assertEqual(result['executionAmount'], first['executionAmount'])
                    self.assertEqual(result['quotes'], first['quotes'])
                    self.assertTrue(control.cancelled.is_set())
                    self.assertFalse(control.release.is_set())
                    self.assertGreater(sum(method.startswith('eth_getBlock') for method, _ in provider.calls), headers)
                    self.assertEqual(routes.engine.semaphore._value, 8)
                finally:
                    operation.cancel()
                    await asyncio.gather(operation, return_exceptions=True)

    async def test_core_quiet_reorg_after_qualification_is_rejected_at_stop(self):
        intent, provider, routes, control = self.tracked_fixture()
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_core(intent, request('issue-exact-in'), frames, budget))
        try:
            await self.wait_qualified(budget)
            provider.reorg = True
            budget.finish_selection('best-initial')
            with self.assertRaises(SnapshotChanged):
                await asyncio.wait_for(operation, 1)
            self.assertTrue(control.cancelled.is_set())
            self.assertEqual(routes.engine.semaphore._value, 8)
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_core_caller_cancellation_remains_cancellation(self):
        intent, _provider, _routes, control = self.tracked_fixture()
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_core(intent, request('issue-exact-in'), frames, budget))
        await self.wait_qualified(budget)
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertTrue(control.cancelled.is_set())
        self.assertFalse(budget.stop.is_set())

    async def test_core_unfinished_helpers_does_not_count_as_qualification(self):
        intent, provider, _routes, control = self.tracked_fixture()
        provider.finish_final = asyncio.Event()
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_core(intent, request('issue-exact-in'), frames, budget))
        try:
            await self.ready(provider.final_started)
            self.assertFalse(budget.ready)
            budget.finish_selection('timeout')
            with self.assertRaises(SearchStopped):
                await asyncio.wait_for(operation, 1)
            self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
            self.assertTrue(control.cancelled.is_set())
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_core_snapshot_disproof_during_owned_tail_drain_survives_stop(self):
        intent, _provider, routes, _control = self.fixture()
        reserve = routes.engine.search_routes
        async def changed_during_drain(*args, **kwargs):
            try:
                return await reserve(*args, **kwargs)
            except asyncio.CancelledError:
                raise SnapshotChanged('Disproved while stopping owned search') from None
        routes.engine.search_routes = changed_during_drain
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_core(intent, request('issue-exact-in'), frames, budget))
        try:
            await self.wait_qualified(budget)
            budget.finish_selection('best-initial')
            with self.assertRaises(SnapshotChanged):
                await asyncio.wait_for(operation, 1)
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_core_stop_keeps_final_canonical_read_pending_until_it_completes(self):
        intent, _provider, routes, _control = self.fixture()
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_core(intent, request('issue-exact-in'), frames, budget))
        hold, started = asyncio.Event(), asyncio.Event()
        canonical = routes.rpc.assert_canonical
        async def held(block):
            started.set()
            await hold.wait()
            await canonical(block)
        try:
            await self.wait_qualified(budget)
            routes.rpc.assert_canonical = held
            budget.finish_selection('best-initial')
            await self.ready(started)
            self.assertFalse(operation.done())
            hold.set()
            result = await asyncio.wait_for(operation, 1)
            self.assertEqual(result['executionAmount'], '200')
        finally:
            hold.set()
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_owned_memo_snapshot_disproof_during_stop_retires_incumbent(self):
        intent, provider, _wire, value, _frames, publish, started = core_fixture.ProtectionAwareRedemptionSeedTests.fixture(self, raw_fault='hold')
        read = provider.make_request
        disproved = asyncio.Event()
        async def changed_during_cancel(*args):
            try:
                return await read(*args)
            except asyncio.CancelledError:
                disproved.set()
                raise SnapshotChanged('Disproved during owned memo cancellation') from None
        provider.make_request = changed_during_cancel
        budget = QuoteBudget()
        async def run():
            with budget_context(budget):
                return await intent.get(value, publish)
        operation = asyncio.create_task(run())
        try:
            await self.ready(started)
            self.assertTrue(budget.ready)
            budget.finish_selection('best-initial')
            with self.assertRaises(SnapshotChanged):
                await asyncio.wait_for(operation, 1)
            self.assertTrue(disproved.is_set())
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            await intent.routes.close()

    async def test_redeem_stop_omits_advisory_inversion_without_losing_protection(self):
        intent, _provider, _routes, value, frames, publish, started = core_fixture.ProtectionAwareRedemptionSeedTests.fixture(self, raw_fault='hold')
        budget = QuoteBudget()
        async def run():
            with budget_context(budget):
                return await intent.get(value, publish)
        operation = asyncio.create_task(run())
        try:
            await self.ready(started)
            self.assertTrue(budget.ready)
            budget.finish_selection('best-initial')
            result = await asyncio.wait_for(operation, 1)
            self.assertEqual(result['executionAmount'], '102')
            self.assertEqual(result['preview']['minimumAmountOut'], '200')
            self.assertNotIn('expectedInputAmount', result)
            self.assertTrue(any(frame['type'] == 'qualified' for frame in frames))
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)


class MarketBudgetProviders(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await market_fixture.MarketIntegration.asyncSetUp(self)
        self.release, self.cancelled = asyncio.Event(), asyncio.Event()
        self.canonical_reads, self.reorg = 0, False
        self.tail_error = None
        async def canonical(block):
            self.assertEqual(block, BLOCK)
            self.canonical_reads += 1
            if self.reorg:
                raise SnapshotChanged('Disproved after progressive Market qualification')
        self.rpc.assert_canonical = canonical
        async def branches(_pools, _in, _out, _mode, amount, **_anchor):
            try:
                yield [{'amountIn': str(amount), 'hops': [{'pool': deepcopy(POOL), 'zeroForOne': True}]}]
                await self.release.wait()
                if self.tail_error is not None:
                    raise self.tail_error
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        self.patched = patch('cybergold_candidate.route_quote_engine.candidate_branches', branches)
        self.patched.start()
        self.addCleanup(self.patched.stop)
        async def quote(_branches, _mode, amount, _block):
            if any(hop['pool']['protocol'] == 'v3' for branch in _branches for hop in branch['hops']):
                raise ValueError('Fixture liquidity is V2 only')
            return {'amountIn': str(amount), 'amountOut': str(amount * 2), 'qualification': 'quoter'}
        self.quotes.quote_branches = quote
        self.quotes.get_model = AsyncMock(return_value={})
        self.quotes.estimate = lambda *_: None

    async def asyncTearDown(self):
        await market_fixture.MarketIntegration.asyncTearDown(self)

    async def wait_qualified(self, budget):
        for _ in range(1000):
            if budget.ready:
                return
            await asyncio.sleep(0)
        self.fail('Held Market search produced no canonical qualified candidate')

    async def run_market(self, budget, frames):
        async def publish(frame):
            frames.append(deepcopy(frame))
        with budget_context(budget):
            return await self.quotes._get(self.request, publish, block=BLOCK)

    async def test_market_stop_preserves_checked_best_and_final_canonical_read(self):
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_market(budget, frames))
        try:
            await self.wait_qualified(budget)
            self.assertEqual(self.canonical_reads, 1)
            first = next(frame['value'] for frame in frames if frame['type'] == 'qualified')
            budget.finish_selection('best-initial')
            result = await asyncio.wait_for(operation, 1)
            self.assertTrue(self.cancelled.is_set())
            self.assertEqual(self.canonical_reads, 2)
            self.assertEqual(result['params'], first['params'])
            self.assertEqual(result['adapterData'], first['adapterData'])
            self.assertEqual(self.quotes.semaphore._value, 8)
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_market_quiet_reorg_after_progressive_quote_is_rejected(self):
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_market(budget, frames))
        try:
            await self.wait_qualified(budget)
            self.reorg = True
            budget.finish_selection('best-initial')
            with self.assertRaises(SnapshotChanged):
                await asyncio.wait_for(operation, 1)
            self.assertTrue(self.cancelled.is_set())
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_market_ordinary_tail_error_keeps_incumbent_after_final_validation(self):
        self.tail_error = TimeoutError('Ordinary unfinished route enumeration')
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_market(budget, frames))
        try:
            await self.wait_qualified(budget)
            first = next(frame['value'] for frame in frames if frame['type'] == 'qualified')
            self.release.set()
            result = await asyncio.wait_for(operation, 1)
            self.assertEqual(result['params'], first['params'])
            self.assertEqual(self.canonical_reads, 2)
            self.assertFalse(budget.stop.is_set())
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_market_requires_canonical_check_before_admitting_progress(self):
        started, hold = asyncio.Event(), asyncio.Event()
        canonical = self.rpc.assert_canonical
        async def held(block):
            started.set()
            await hold.wait()
            await canonical(block)
        self.rpc.assert_canonical = held
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_market(budget, frames))
        try:
            await asyncio.wait_for(started.wait(), 1)
            self.assertFalse(budget.ready)
            self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
            budget.finish_selection('timeout')
            with self.assertRaises(SearchStopped):
                await asyncio.wait_for(operation, 1)
            self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
        finally:
            hold.set()
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_market_caller_cancellation_stops_owned_candidates(self):
        budget, frames = QuoteBudget(), []
        operation = asyncio.create_task(self.run_market(budget, frames))
        await self.wait_qualified(budget)
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertTrue(self.cancelled.is_set())
        self.assertFalse(budget.stop.is_set())


if __name__ == '__main__':
    unittest.main()
