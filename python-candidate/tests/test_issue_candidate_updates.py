"""Later complete issuance seeds use the existing objective and selection clock."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_quote_intent as fixture
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.quote_errors import QuoteFailure
import cybergold_candidate.quote_intent as coordinator


class IssueCandidateUpdates(unittest.IsolatedAsyncioTestCase):
    def prepare(self, *, factors=(4,), reject_first=False, hold_later=False):
        intent, provider, routes, control = fixture.EarlyCheckedIssueTests.fixture(self, protocol='v2')
        first, rejected, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        later_done, release_later, later_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        trace = SimpleNamespace(first=first, rejected=rejected, delivered=delivered,
            later_done=later_done, release_later=release_later, later_started=later_started, frames=[], factors={})
        original_search, original_sdk = routes.engine.search_routes, routes.engine.quote_sdk_branches
        async def sdk(branches, mode, amount, block, **kwargs):
            pools = [hop['pool'] for branch in branches for hop in branch['hops']]
            if reject_first and mode == 'exactOut' and all(pool['protocol'] == 'v2' for pool in pools):
                rejected.set()
                raise QuoteFailure('quote-contract-reverted')
            factor = trace.factors.get(pools[0]['id'])
            if factor is not None:
                if hold_later:
                    later_started.set()
                    await release_later.wait()
                return {'amountIn': str(amount if mode == 'exactIn' else (amount+factor-1)//factor),
                        'amountOut': str(amount*factor if mode == 'exactIn' else amount),
                        'settled': True, 'fullyFilled': True}
            return await original_sdk(branches, mode, amount, block, **kwargs)
        routes.engine.quote_sdk_branches = sdk
        def changed(rows, factor, sequence):
            rows = deepcopy(rows)
            for index, row in enumerate(rows):
                for branch in row['best']['routePlan']['branches']:
                    for hop in branch['hops']:
                        identity = '0x'+format(1000+sequence*10+index, '040x')
                        hop['pool'].update(protocol='v3', id=identity, address=identity, feePips=500)
                        routes.engine.registry.inventory[identity] = deepcopy(hop['pool'])
                        trace.factors[identity] = factor
                amount, plan = int(row['target']['amount']), row['best']['routePlan']
                row['best']['quote'] = str(amount*factor)
                plan['outputAmount'] = str(amount*factor)
                row.update(attempted=sequence+2, succeeded=sequence+2, total=8)
            return rows
        async def search(value, block, on_update=None):
            async def progress(rows):
                await on_update(rows)
                if value['mode'] == 'exact-in':
                    await asyncio.wait_for((rejected if reject_first else first).wait(), 2)
                    for index, factor in enumerate(factors):
                        await on_update(changed(rows, factor, index))
                        # Each changed vector must reach its own coalescing slot.
                        await asyncio.sleep(0)
                    delivered.set()
            return await original_search(value, block, on_update=progress)
        routes.engine.search_routes = search
        async def emit(frame):
            trace.frames.append(deepcopy(frame))
            if frame['type'] == 'qualified' and frame['value']['executionAmount'] == '200':
                first.set()
        trace.emit = emit
        return intent, routes, control, trace

    async def selected(self, *, factor=4, reject_first=False):
        intent, routes, control, trace = self.prepare(factors=(factor,), reject_first=reject_first)
        expected = str(100*factor)
        finish = coordinator.provider_qualification_finish
        def observed(probe, outcome, error=None):
            finish(probe, outcome, error)
            if probe is not None and probe.row.get('executionAmount') == expected \
                    and probe.row['outcome'] in ('qualified', 'not-improved'):
                trace.later_done.set()
        budget = QuoteBudget()  # Existing 5 + 10 second policy, unchanged.
        async def run():
            with budget_context(budget):
                return await budget.produce(intent.get(fixture.request('issue-exact-in'), trace.emit))
        with patch.object(coordinator, 'provider_qualification_finish', observed):
            operation = asyncio.create_task(run())
            try:
                await asyncio.wait_for(trace.later_done.wait(), 2)
                self.assertFalse(control.release.is_set())
                self.assertFalse(operation.done())
                self.assertLess(budget.elapsed(), 5000)
                budget.finish_selection('best-initial')
                result = await asyncio.wait_for(operation, 2)
            finally:
                control.release.set()
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
        self.assertEqual(routes.engine.semaphore._value, 8)
        return result, trace

    async def test_later_better_complete_seed_replaces_first_before_unrelated_tail_finishes(self):
        result, trace = await self.selected()
        self.assertEqual(result['executionAmount'], '400')
        self.assertEqual(result['maximumInputAmount'], '100')
        amounts = [frame['value']['executionAmount'] for frame in trace.frames if frame['type'] == 'qualified']
        self.assertIn('200', amounts)
        self.assertIn('400', amounts)
        evidence = result['quoteDiagnostics']['providerQualifications']
        self.assertEqual(evidence['selectionReason'], 'best-initial')
        selected = next(row for row in evidence['rows'] if row['attempt'] == evidence['selectedAttempt'])
        self.assertEqual((selected['executionAmount'], selected['quotedOutput'], selected['inputMaximum']),
                         ('400', '400', '100'))
        self.assertEqual(selected['outcome'], 'qualified')
        self.assertLessEqual(selected['startedMs'], selected['completedMs'])
        self.assertTrue(all(pool['protocol'] == 'v3' for pool in selected['pools']))

    async def test_later_checked_seed_can_recover_first_candidate_rejection(self):
        result, _trace = await self.selected(reject_first=True)
        self.assertEqual(result['executionAmount'], '400')
        evidence = result['quoteDiagnostics']['providerQualifications']
        self.assertGreaterEqual(evidence['rejected'], 1)
        self.assertTrue(any(row.get('code') == 'quote-contract-reverted' for row in evidence['rows']))

    async def test_later_worse_complete_seed_does_not_replace_existing_objective_winner(self):
        result, trace = await self.selected(factor=1)
        self.assertEqual(result['executionAmount'], '200')
        self.assertEqual(result['maximumInputAmount'], '100')
        self.assertFalse(any(frame['type'] == 'qualified' and frame['value']['executionAmount'] == '100'
                             for frame in trace.frames))
        self.assertTrue(any(row['outcome'] == 'not-improved' and row.get('executionAmount') == '100'
                            for row in result['quoteDiagnostics']['providerQualifications']['rows']))

    async def test_stop_during_later_candidate_keeps_checked_first_and_drains_pending_work(self):
        intent, routes, control, trace = self.prepare(hold_later=True)
        budget = QuoteBudget()
        async def run():
            with budget_context(budget):
                return await budget.produce(intent.get(fixture.request('issue-exact-in'), trace.emit))
        operation = asyncio.create_task(run())
        try:
            await asyncio.wait_for(trace.later_started.wait(), 2)
            self.assertTrue(trace.first.is_set())
            budget.finish_selection('best-initial')
            result = await asyncio.wait_for(operation, 2)
        finally:
            control.release.set()
            trace.release_later.set()
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        self.assertEqual(result['executionAmount'], '200')
        self.assertFalse(any(frame['type'] == 'qualified' and frame['value']['executionAmount'] == '400'
                             for frame in trace.frames))
        evidence = result['quoteDiagnostics']['providerQualifications']
        self.assertEqual(evidence['pending'], 0)
        self.assertEqual(evidence['cancelled'], 1)
        self.assertFalse(any(row['outcome'] == 'running' for row in evidence['rows']))
        self.assertEqual(routes.engine.semaphore._value, 8)


if __name__ == '__main__':
    unittest.main()
