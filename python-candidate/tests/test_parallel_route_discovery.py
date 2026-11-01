"""Parallel hint arrivals preserve ordinary selection and request ownership."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from cybergold_candidate.quote_budget import QuoteBudget, SearchStopped, budget_context
from cybergold_candidate.quoter.bootstrap import (
    ProviderUnavailable, RouteBootstrap, bootstrap_scope, current_bootstrap)
from cybergold_candidate.recovery_rpc import SnapshotChanged


BLOCK = {'blockNumber': '101', 'blockHash': '0x' + 'ab'*32, 'chainId': 1}


def candidate(amount):
    return [{'amountIn': str(amount), 'hops': [{'kind': 'wrap', 'currencyOut': 'target'}]}]


class ParallelRouteDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_nominations_retain_independent_origins_without_changing_sharing(self):
        calls, offered = [], []
        async def discover(*args):
            calls.append(args)
            return [candidate(200)]
        session = RouteBootstrap({'tool-one': discover, 'tool-two': discover})
        async def ordinary():
            self.assertEqual(session.offers('source', 'target', 100, BLOCK), [])
            self.assertEqual(session.candidates('SOURCE', 'TARGET', '100', BLOCK), [])
        async def reevaluate():
            offered.extend(session.offers('source', 'target', 100, BLOCK))
            copied = session.offers('source', 'target', 100, BLOCK)
            copied[0]['origins'].append('untrusted-copy')
            copied[0]['branches'][0]['amountIn'] = '1'
            self.assertNotIn('untrusted-copy', repr(session.offers('source', 'target', 100, BLOCK)))
            self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [candidate(200), candidate(200)])
        await session.run(ordinary(), reevaluate)
        self.assertEqual(len(calls), 2)
        self.assertEqual(offered, [{'branches': candidate(200), 'origins': ['tool-one']},
                                  {'branches': candidate(200), 'origins': ['tool-two']}])
        self.assertEqual(session.metrics['queries'], 1)

    async def test_provider_arrival_and_completion_coordinates_use_the_existing_producer_clock(self):
        clock = {'ms': 100.0}
        budget = SimpleNamespace(stop=asyncio.Event(), elapsed=lambda: clock['ms'])
        entered, release = asyncio.Event(), asyncio.Event()
        async def discover(*_):
            entered.set()
            await release.wait()
            return [candidate(200)]
        async def empty(*_):
            return []
        with budget_context(budget):
            session = RouteBootstrap({'tool': discover, 'empty': empty})
            async def ordinary():
                session.offers('private-input', 'private-output', 100, BLOCK)
            async def reevaluate():
                pass
            clock['ms'] = 125.0
            task = asyncio.create_task(session.run(ordinary(), reevaluate))
        await entered.wait()
        self.assertEqual(session.metrics['providers']['tool']['pending'], 1)
        self.assertIsNone(session.timings['tool']['firstCandidateMs'])
        clock['ms'] = 175.0
        release.set()
        await task
        self.assertEqual(session.timings['tool'], {'started': 1, 'pending': 0, 'startedMs': 125.0,
            'firstCandidateMs': 175.0, 'completedMs': 175.0, 'cancelledMs': None, 'durationMs': 50.0})
        self.assertIsNone(session.timings['empty']['firstCandidateMs'])
        self.assertEqual(session.metrics['startedMs'], 100.0)
        self.assertEqual(session.metrics['completedMs'], 175.0)
        self.assertEqual(session.metrics['elapsedMs'], 75.0)
        self.assertEqual(session.metrics['clock'], 'producer')
        self.assertNotIn('private', json.dumps(session.metrics))
        clock['ms'] = 200.0
        self.assertEqual(session.metrics['elapsedMs'], 75.0)

    async def test_cancelled_supplier_timing_is_distinct_from_completion_or_a_nomination(self):
        clock = {'ms': 100.0}
        budget = SimpleNamespace(stop=asyncio.Event(), elapsed=lambda: clock['ms'])
        entered = asyncio.Event()
        async def discover(*_):
            entered.set()
            await asyncio.Event().wait()
        with budget_context(budget):
            session = RouteBootstrap({'tool': discover})
            async def ordinary():
                session.offers('source', 'target', 100, BLOCK)
            async def reevaluate():
                self.fail('Cancelled supplier has offered no candidates')
            clock['ms'] = 150.0
            task = asyncio.create_task(session.run(ordinary(), reevaluate))
        await entered.wait()
        clock['ms'] = 200.0
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        timing = session.timings['tool']
        self.assertEqual(timing['cancelledMs'], 200.0)
        self.assertEqual(timing['durationMs'], 50.0)
        self.assertIsNone(timing['completedMs'])
        self.assertIsNone(timing['firstCandidateMs'])
        self.assertEqual(session.metrics['providers']['tool']['cancelled'], 1)

    async def test_local_first_and_detailed_improvements_precede_blocked_supplier(self):
        release, started, local_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        updates, closed = [], []
        class Provider:
            name = 'external'
            async def discover(self, *_):
                started.set()
                await release.wait()
                return [candidate(200)]
            async def close(self):
                closed.append('provider')
        session = RouteBootstrap([Provider()])
        async def ordinary():
            self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [])
            updates.extend([100, 110])
            local_done.set()
            return 'ordinary-result'
        async def reevaluate():
            rows = session.candidates('source', 'target', 100, BLOCK)
            updates.append(max(int(row[0]['amountIn']) for row in rows))
        task = asyncio.create_task(session.run(ordinary(), reevaluate))
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(local_done.wait(), 1)
        self.assertEqual(updates, [100, 110])
        self.assertFalse(task.done())
        release.set()
        self.assertEqual(await asyncio.wait_for(task, 1), 'ordinary-result')
        self.assertEqual(updates, [100, 110, 200])
        self.assertEqual(closed, ['provider'])
        await session.close()
        self.assertEqual(closed, ['provider'])

    async def test_arrivals_during_a_round_are_coalesced_without_being_lost(self):
        gates = [asyncio.Event(), asyncio.Event(), asyncio.Event()]
        first_round, finish_round = asyncio.Event(), asyncio.Event()
        rounds = []
        async def supplier(index, *_):
            await gates[index].wait()
            return [candidate(index + 1)]
        session = RouteBootstrap({str(index): lambda *args, index=index: supplier(index, *args)
                                  for index in range(3)})
        async def ordinary():
            session.candidates('source', 'target', 100, BLOCK)
        async def reevaluate():
            rounds.append(deepcopy(session.candidates('source', 'target', 100, BLOCK)))
            if len(rounds) == 1:
                first_round.set()
                await finish_round.wait()
        task = asyncio.create_task(session.run(ordinary(), reevaluate))
        gates[0].set()
        await asyncio.wait_for(first_round.wait(), 1)
        gates[1].set()
        gates[2].set()
        while session.revision < 3:
            await asyncio.sleep(0)
        finish_round.set()
        await asyncio.wait_for(task, 1)
        self.assertEqual([len(rows) for rows in rounds], [1, 3])
        self.assertEqual(session.metrics['reevaluations'], 2)

    async def test_reevaluation_can_start_another_coalesced_pair_query(self):
        seen, rounds = [], []
        async def discover(source, target, amount, block):
            seen.append((source, target, amount, block))
            return [candidate(1 if source == 'a' else 2)]
        session = RouteBootstrap({'external': discover})
        async def ordinary():
            session.candidates('A', 'B', '100', BLOCK)
        async def reevaluate():
            rounds.append(session.candidates('a', 'b', 100, BLOCK))
            session.candidates('B', 'C', 50, BLOCK)
        await asyncio.wait_for(session.run(ordinary(), reevaluate), 1)
        self.assertEqual(len(seen), 2)
        self.assertEqual([row[:3] for row in seen], [('a', 'b', 100), ('b', 'c', 50)])
        self.assertEqual(len(rounds), 2)
        self.assertEqual(session.metrics['queries'], 2)

    async def test_supplier_errors_unavailability_and_empty_results_are_independent(self):
        async def unavailable(*_):
            raise ProviderUnavailable('private key-like configuration must not enter metrics')
        async def failed(*_):
            raise RuntimeError('private upstream URL must not enter metrics')
        async def empty(*_):
            return []
        async def useful(*_):
            return [candidate(200)]
        session = RouteBootstrap({'missing': unavailable, 'failed': failed, 'empty': empty, 'useful': useful})
        async def ordinary():
            session.candidates('source', 'target', 100, BLOCK)
        rounds = []
        async def reevaluate():
            rounds.extend(session.candidates('source', 'target', 100, BLOCK))
        await asyncio.wait_for(session.run(ordinary(), reevaluate), 1)
        self.assertEqual(rounds, [candidate(200)])
        for name, status in (('missing', 'unavailable'), ('failed', 'error'), ('empty', 'empty'), ('useful', 'completed')):
            self.assertEqual(session.metrics['providers'][name][status], 1)
        self.assertNotIn('private', repr(session.metrics))

    async def test_query_directions_amounts_and_returned_candidates_are_request_local(self):
        calls = []
        async def discover(*args):
            calls.append(args)
            return [candidate(200)]
        session = RouteBootstrap({'external': discover})
        async def ordinary():
            session.candidates('SOURCE', 'TARGET', '0100', BLOCK)
            session.candidates('source', 'target', 100, BLOCK)
            session.candidates('target', 'source', 100, BLOCK)
            session.candidates('source', 'target', 101, BLOCK)
        async def reevaluate():
            rows = session.candidates('source', 'target', 100, BLOCK)
            rows[0][0]['amountIn'] = '999999'
            self.assertEqual(session.candidates('SOURCE', 'TARGET', 100, BLOCK), [candidate(200)])
        await asyncio.wait_for(session.run(ordinary(), reevaluate), 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [])
        other = RouteBootstrap({'external': discover})
        self.assertEqual(other.candidates('source', 'target', 100, BLOCK), [])
        await other.close()
        self.assertEqual(other.metrics['queries'], 1)

    async def test_context_disproof_cancels_and_drains_ordinary_and_sibling(self):
        started, drained = asyncio.Event(), []
        async def held(*_):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.append('provider')
        async def invalid(*_):
            await started.wait()
            raise SnapshotChanged('pinned context changed')
        session = RouteBootstrap({'held': held, 'invalid': invalid})
        async def ordinary():
            session.candidates('source', 'target', 100, BLOCK)
            try:
                await asyncio.Event().wait()
            finally:
                drained.append('ordinary')
        async def reevaluate():
            self.fail('No candidate was produced')
        with self.assertRaises(SnapshotChanged):
            await asyncio.wait_for(session.run(ordinary(), reevaluate), 1)
        self.assertCountEqual(drained, ['provider', 'ordinary'])

    async def test_caller_cancellation_and_existing_budget_stop_drain_all_work(self):
        for stop in ('caller', 'budget'):
            with self.subTest(stop=stop):
                started, drained = asyncio.Event(), []
                async def discover(*_):
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        drained.append('provider')
                session = RouteBootstrap({'held': discover})
                async def ordinary():
                    session.candidates('source', 'target', 100, BLOCK)
                async def reevaluate():
                    self.fail('No candidate was produced')
                budget = QuoteBudget()
                with budget_context(budget):
                    task = asyncio.create_task(session.run(ordinary(), reevaluate))
                await asyncio.wait_for(started.wait(), 1)
                if stop == 'caller':
                    task.cancel()
                    expected = asyncio.CancelledError
                else:
                    budget.finish_selection('best-initial')
                    expected = SearchStopped
                with self.assertRaises(expected):
                    await asyncio.wait_for(task, 1)
                self.assertEqual(drained, ['provider'])
                self.assertEqual(session.metrics['providers']['held']['pending'], 0)

    async def test_ordinary_error_and_context_disproof_during_cleanup_are_preserved(self):
        for disproof in (False, True):
            with self.subTest(disproof=disproof):
                started, drained = asyncio.Event(), []
                async def discover(*_):
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        drained.append(True)
                        if disproof:
                            raise SnapshotChanged('disproved while draining')
                session = RouteBootstrap({'held': discover})
                async def ordinary():
                    session.candidates('source', 'target', 100, BLOCK)
                    await started.wait()
                    raise ValueError('ordinary failure')
                async def reevaluate():
                    self.fail('No candidate was produced')
                with self.assertRaises(SnapshotChanged if disproof else ValueError):
                    await asyncio.wait_for(session.run(ordinary(), reevaluate), 1)
                self.assertEqual(drained, [True])

    async def test_provider_stop_and_self_cancellation_are_not_optional_errors(self):
        for error in (SearchStopped, asyncio.CancelledError):
            with self.subTest(error=error):
                async def discover(*_):
                    raise error()
                session = RouteBootstrap({'external': discover})
                async def ordinary():
                    session.candidates('source', 'target', 100, BLOCK)
                    await asyncio.Event().wait()
                async def reevaluate():
                    self.fail('No candidate was produced')
                with self.assertRaises(error):
                    await asyncio.wait_for(session.run(ordinary(), reevaluate), 1)

    async def test_scope_restores_the_previous_session(self):
        one, two = RouteBootstrap({}), RouteBootstrap({})
        self.assertIsNone(current_bootstrap())
        with bootstrap_scope(one):
            self.assertIs(current_bootstrap(), one)
            with bootstrap_scope(two):
                self.assertIs(current_bootstrap(), two)
            self.assertIs(current_bootstrap(), one)
        self.assertIsNone(current_bootstrap())
        await one.close()
        await two.close()


if __name__ == '__main__':
    unittest.main()
