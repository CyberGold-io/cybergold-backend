"""Producer deadline behavior through real trade coordination and intent sharing.

Provider I/O is inert: declared completion times represent already checked
executions. Each provider uses the public budget hook, then its own finalizer;
these fixtures do not stand in for Core/market contract or route qualification.
"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.quote_budget import QuoteBudget, SearchStopped, budget_context, current_budget
from cybergold_candidate.quote_errors import QuoteFailure, RpcTimeout
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.trade_quote import TradeQuotes
from test_trade_quote import (ADAPTER, ASSET_A, ASSET_B, BLOCK, SETTINGS,
    core_quote, market_quote, request)


class Providers:
    """Keep discovery, executable readiness, canonicality and cleanup distinct."""
    def __init__(self, *, core=(), market=(), finishes=None, errors=None,
                 resolver_delay=0, head_delay=0, indicative=False, canonical_error=None,
                 preparations=None, canonical_delay=0, cleanup_delay=0):
        self.steps = {'core': core, 'market': market}
        self.finishes, self.errors = finishes or {}, errors or {}
        self.resolver_delay, self.head_delay = resolver_delay, head_delay
        self.indicative, self.canonical_error = indicative, canonical_error
        self.preparations = preparations or {}
        self.canonical_delay, self.cleanup_delay = canonical_delay, cleanup_delay
        self.started = {strategy: asyncio.Event() for strategy in self.steps}
        self.cancelled = {strategy: asyncio.Event() for strategy in self.steps}
        self.drained = {strategy: asyncio.Event() for strategy in self.steps}
        self.finalizing = {strategy: asyncio.Event() for strategy in self.steps}
        self.preparing = {strategy: asyncio.Event() for strategy in self.steps}
        self.context_drained = {strategy: asyncio.Event() for strategy in self.steps}
        self.canonical_hold = None
        self.budgets, self.actions = [], []
        self.head_calls = 0
        self.core = SimpleNamespace(settings=SETTINGS, history=None,
            routes=SimpleNamespace(rpc=object(), rpc_factory=lambda _: object()), get=self.core_get)
        self.market = SimpleNamespace(head=self.head, _get=self.market_get,
            packet=self.packet, get_model=self.get_model,
            estimate=lambda _packet, _request: '999999' if self.indicative else None)
        self.quotes = TradeQuotes(SETTINGS, self.core, self.market,
            request_resolver=self.resolve, basis_reader=self.basis)

    async def resolve(self, value):
        self.actions.append('resolve')
        await asyncio.sleep(self.resolver_delay)
        return {**value, 'adapter': ADAPTER}

    async def head(self):
        self.actions.append('head')
        self.head_calls += 1
        await asyncio.sleep(self.head_delay)
        return deepcopy(BLOCK)

    async def basis(self, block):
        self.actions.append('basis')
        return [ASSET_A, ASSET_B], [500_000, 500_000], 2

    def packet(self, value):
        return {'namespace': 'market', 'intent': value, 'routes': [], 'feeRatePpm': 1000}

    async def get_model(self, value, *, block):
        return self.packet(value)

    async def core_get(self, value, publish, *, block, quoted_ranking):
        return await self.produce('core', publish)

    async def market_get(self, value, publish, *, block):
        return await self.produce('market', publish)

    async def produce(self, strategy, publish):
        budget = current_budget()
        self.budgets.append((strategy, budget))
        self.started[strategy].set()
        selected = None

        async def at(offset):
            await asyncio.sleep(max(0, budget.started + offset - budget.loop.time()))

        async def discover():
            nonlocal selected
            for offset, output in self.steps[strategy]:
                await at(offset)
                value = core_quote(amount_out=output) if strategy == 'core' else market_quote(amount_out=output)
                if budget.qualified():
                    selected = value
                    self.actions.append((strategy, 'qualified', output))
                    await publish({'type': 'qualified', 'value': deepcopy(value)})
            if strategy in self.finishes:
                await at(self.finishes[strategy])
            else:
                await asyncio.Event().wait()

        try:
            try:
                if strategy in self.preparations:
                    async def context():
                        self.preparing[strategy].set()
                        try:
                            await self.preparations[strategy].wait()
                        finally:
                            self.context_drained[strategy].set()
                    await budget.prepare(context())
                await budget.discovery(discover())
            except SearchStopped:
                pass
            self.finalizing[strategy].set()
            if self.canonical_hold:
                await self.canonical_hold.wait()
            await asyncio.sleep(self.canonical_delay)
            if self.canonical_error:
                raise self.canonical_error
            budget.canonical_done()
            if strategy in self.errors:
                raise self.errors[strategy]
            if selected is None:
                raise TimeoutError('No checked execution before discovery ended')
            return deepcopy(selected)
        except asyncio.CancelledError:
            self.cancelled[strategy].set()
            raise
        finally:
            await asyncio.sleep(self.cleanup_delay)
            budget.cleanup_done()
            self.drained[strategy].set()

    async def close(self):
        await self.quotes.close()


class TotalQuoteBudgetTests(unittest.IsolatedAsyncioTestCase):
    def providers(self, **kwargs):
        provider = Providers(**kwargs)
        self.addAsyncCleanup(provider.close)
        return provider

    def operation(self, provider, budget, frames):
        async def publish(frame):
            frames.append(deepcopy(frame))
        with budget_context(budget):
            return asyncio.create_task(provider.quotes.get(request(), publish))

    async def wait_for(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    async def test_resolver_and_head_consume_original_initial_window(self):
        provider = self.providers(core=[(.09, 190)], resolver_delay=.04, head_delay=.04)
        budget, frames = QuoteBudget(.05, .15), []
        result = await self.operation(provider, budget, frames)
        self.assertEqual(result['strategy'], 'core')
        self.assertEqual(budget.reason, 'first-extension')
        self.assertGreaterEqual(budget.first_qualified - budget.started, .08)
        self.assertLess(budget.selected - budget.started, .16)
        self.assertTrue(all(observed is budget for _, observed in provider.budgets))
        self.assertGreaterEqual(result['metrics']['totalMs'], 80)

    async def test_total_deadline_applies_before_producer_start(self):
        for stage in ('resolver', 'head'):
            with self.subTest(stage=stage):
                provider = self.providers(**{stage+'_delay': .2})
                budget = QuoteBudget(.02, .04)
                with self.assertRaises(RpcTimeout if stage == 'head' else TimeoutError):
                    await self.operation(provider, budget, [])
                self.assertFalse(provider.budgets)
                self.assertEqual(provider.quotes.sharing.started, 0)
                self.assertEqual(provider.head_calls, int(stage == 'head'))

    async def test_completed_search_returns_before_initial_cutoff(self):
        provider = self.providers(core=[(.005, 190)], market=[(.01, 180)], finishes={'core': .015, 'market': .02})
        budget = QuoteBudget(.2, .1)
        result = await self.operation(provider, budget, [])
        self.assertEqual(result['strategy'], 'core')
        self.assertEqual(budget.reason, 'complete')
        self.assertLess(budget.finished, budget.initial)
        self.assertTrue(all(event.is_set() for event in provider.drained.values()))

    async def test_best_checked_before_cutoff_wins_and_later_improvements_are_excluded(self):
        provider = self.providers(core=[(.005, 190), (.025, 210), (.09, 260)], market=[(.015, 200), (.08, 240)])
        budget, frames = QuoteBudget(.05, .1), []
        result = await self.operation(provider, budget, frames)
        self.assertEqual((result['strategy'], result['quotedOutput']), ('core', '210'))
        self.assertEqual(budget.reason, 'best-initial')
        self.assertGreaterEqual(budget.selected, budget.initial)
        self.assertFalse(any(frame['type'] == 'qualified' and int(frame['value']['quotedOutput']) > 210 for frame in frames))
        self.assertTrue(all(event.is_set() for event in provider.drained.values()))

    async def test_first_extension_candidate_returns_without_waiting_for_better_one(self):
        provider = self.providers(core=[(.09, 210)], market=[(.07, 180)])
        budget = QuoteBudget(.04, .15)
        result = await self.operation(provider, budget, [])
        self.assertEqual((result['strategy'], result['quotedOutput']), ('market', '180'))
        self.assertEqual(budget.reason, 'first-extension')
        self.assertLess(budget.selected - budget.started, .09)

    async def test_empty_and_late_searches_timeout_without_fabricating_readiness(self):
        for steps in ([], [(.15, 190)]):
            with self.subTest(steps=steps):
                provider = self.providers(core=steps)
                budget, frames = QuoteBudget(.025, .05), []
                with self.assertRaises(TimeoutError):
                    await self.operation(provider, budget, frames)
                self.assertEqual(budget.reason, 'timeout')
                self.assertIsNone(budget.first_qualified)
                self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
                self.assertTrue(all(event.is_set() for event in provider.drained.values()))

    async def test_indicative_estimate_does_not_end_initial_window_or_become_winner(self):
        provider = self.providers(core=[(.08, 190)], indicative=True)
        budget, frames = QuoteBudget(.04, .15), []
        result = await self.operation(provider, budget, frames)
        self.assertTrue(any(frame['type'] == 'estimate' for frame in frames))
        self.assertEqual(result['quotedOutput'], '190')
        self.assertEqual(budget.reason, 'first-extension')
        self.assertGreater(budget.first_qualified, budget.initial)

    async def test_equal_checked_economics_keep_core_preference(self):
        provider = self.providers(core=[(.025, 180)], market=[(.005, 180)])
        budget, frames = QuoteBudget(.05, .1), []
        result = await self.operation(provider, budget, frames)
        self.assertEqual(next(frame for frame in frames if frame['type'] == 'qualified')['value']['strategy'], 'market')
        self.assertEqual(result['strategy'], 'core')

    async def test_progressive_market_candidate_without_terminal_provider_success_is_not_returned(self):
        provider = self.providers(market=[(.01, 260)], finishes={'core': .005},
            errors={'core': QuoteFailure('quote-no-route'), 'market': QuoteFailure('quote-contract-reverted')})
        budget, frames = QuoteBudget(.04, .1), []
        with self.assertRaises(QuoteFailure):
            await self.operation(provider, budget, frames)
        self.assertTrue(any(frame['type'] == 'qualified' for frame in frames))
        self.assertEqual(budget.reason, 'best-initial')
        self.assertFalse(provider.quotes.sharing.pending)

    async def test_overlapping_caller_joins_original_clock_and_first_disconnect_preserves_second(self):
        provider = self.providers(core=[(.005, 190), (.04, 210)])
        first_budget, first_frames = QuoteBudget(.09, .15), []
        original_initial, original_deadline = first_budget.initial, first_budget.deadline
        first = self.operation(provider, first_budget, first_frames)
        await self.wait_for(lambda: any(frame['type'] == 'qualified' for frame in first_frames))
        await asyncio.sleep(.025)
        second_budget, second_frames = QuoteBudget(.09, .15), []
        second = self.operation(provider, second_budget, second_frames)
        await self.wait_for(lambda: provider.quotes.sharing.joined == 1 and any(frame['type'] == 'qualified' for frame in second_frames))
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertFalse(any(event.is_set() for event in provider.cancelled.values()))
        result = await second
        self.assertEqual(result['quotedOutput'], '210')
        self.assertEqual(provider.quotes.sharing.started, 1)
        self.assertEqual(len(provider.budgets), 2)
        self.assertTrue(all(observed is first_budget for _, observed in provider.budgets))
        self.assertEqual((first_budget.initial, first_budget.deadline), (original_initial, original_deadline))
        self.assertEqual(first_budget.reason, 'best-initial')
        self.assertLess(first_budget.selected, second_budget.initial)
        self.assertIsNone(second_budget.selected)
        self.assertFalse(provider.quotes.sharing.pending)

    async def test_last_caller_cancellation_drains_both_owned_discoveries(self):
        provider = self.providers()
        budget = QuoteBudget(.5, .5)
        operation = self.operation(provider, budget, [])
        await asyncio.gather(*(event.wait() for event in provider.started.values()))
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertTrue(all(event.is_set() for event in provider.cancelled.values()))
        self.assertTrue(all(event.is_set() for event in provider.drained.values()))
        self.assertFalse(provider.quotes.sharing.pending)
        self.assertIsNone(current_budget())

    async def test_cutoff_still_requires_provider_finalization_and_disproved_context_fails(self):
        provider = self.providers(core=[(.005, 190)], canonical_error=SnapshotChanged('Changed', retry=1))
        provider.canonical_hold = asyncio.Event()
        budget, frames = QuoteBudget(.03, .1), []
        operation = self.operation(provider, budget, frames)
        await asyncio.gather(*(event.wait() for event in provider.finalizing.values()))
        self.assertTrue(budget.stop.is_set())
        self.assertFalse(operation.done())
        provider.canonical_hold.set()
        with self.assertRaises(SnapshotChanged):
            await operation
        self.assertTrue(any(frame['type'] == 'invalidated' for frame in frames))
        self.assertTrue(all(event.is_set() for event in provider.drained.values()))

    async def test_last_disconnect_during_canonical_finalization_cannot_return_saved_candidate(self):
        provider = self.providers(core=[(.005, 190)])
        provider.canonical_hold = asyncio.Event()
        budget, frames = QuoteBudget(.03, .1), []
        operation = self.operation(provider, budget, frames)
        await asyncio.gather(*(event.wait() for event in provider.finalizing.values()))
        self.assertTrue(any(frame['type'] == 'qualified' for frame in frames))
        self.assertTrue(budget.stop.is_set())
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertTrue(all(event.is_set() for event in provider.cancelled.values()))
        self.assertTrue(all(event.is_set() for event in provider.drained.values()))
        self.assertFalse(provider.quotes.sharing.pending)

    async def test_ready_core_stops_held_market_context_preparation_at_initial_cutoff(self):
        held_context = asyncio.Event()
        provider = self.providers(core=[(.015, 190)], preparations={'market': held_context})
        budget = QuoteBudget(.04, .16)
        operation = self.operation(provider, budget, [])
        await provider.preparing['market'].wait()
        result = await operation
        self.assertEqual(result['strategy'], 'core')
        self.assertEqual(budget.reason, 'best-initial')
        self.assertTrue(provider.context_drained['market'].is_set())
        self.assertFalse(held_context.is_set())
        self.assertLess(budget.finished, budget.deadline - .05)
        self.assertLess(result['metrics']['finalizationMs'], 70)
        self.assertFalse(any(action[0] == 'market' for action in provider.actions if isinstance(action, tuple)))

    async def test_returned_metrics_include_entry_context_and_measure_finalization_overhead(self):
        provider = self.providers(core=[(.05, 190)], resolver_delay=.02, head_delay=.02,
            canonical_delay=.03, cleanup_delay=.015)
        budget = QuoteBudget(.08, .16)
        result = await self.operation(provider, budget, [])
        metrics = result['metrics']
        self.assertTrue({'firstQualifiedMs', 'selectionMs', 'canonicalCompletedMs',
            'cleanupCompletedMs', 'finalizationMs', 'totalMs'} <= metrics.keys())
        self.assertGreaterEqual(metrics['firstQualifiedMs'], 40)
        self.assertGreaterEqual(metrics['selectionMs'], 80)
        ordered = [metrics[name] for name in ('firstQualifiedMs', 'selectionMs', 'canonicalCompletedMs',
            'cleanupCompletedMs', 'totalMs')]
        self.assertEqual(ordered, sorted(ordered))
        self.assertGreaterEqual(metrics['canonicalCompletedMs'] - metrics['selectionMs'], 25)
        self.assertGreaterEqual(metrics['cleanupCompletedMs'] - metrics['canonicalCompletedMs'], 10)
        self.assertGreaterEqual(metrics['finalizationMs'], 40)
        self.assertAlmostEqual(metrics['finalizationMs'], metrics['totalMs'] - metrics['selectionMs'], delta=5)
        self.assertTrue(all(event.is_set() for event in provider.drained.values()))

    async def test_first_extension_terminal_survives_cancelled_slow_progress_delivery(self):
        provider = self.providers(core=[(.06, 190)])
        original_get = provider.core.get
        delivery_entered, delivery_cancelled = asyncio.Event(), asyncio.Event()

        async def delayed_get(value, publish, **options):
            async def slow(frame):
                if frame['type'] == 'qualified' and not delivery_entered.is_set():
                    delivery_entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        delivery_cancelled.set()
                await publish(frame)
            return await original_get(value, slow, **options)

        provider.core.get = delayed_get
        budget, frames = QuoteBudget(.03, .15), []
        result = await self.operation(provider, budget, frames)
        self.assertTrue(delivery_entered.is_set())
        self.assertTrue(delivery_cancelled.is_set())
        self.assertEqual((result['strategy'], result['quotedOutput']), ('core', '190'))
        self.assertEqual(result['evaluation']['core'], 'complete')
        self.assertEqual(len([frame for frame in frames if frame['type'] == 'qualified']), 1)
        self.assertEqual(budget.reason, 'first-extension')
        self.assertTrue(all(event.is_set() for event in provider.drained.values()))
        self.assertFalse(provider.quotes.sharing.pending)


if __name__ == '__main__':
    unittest.main()
