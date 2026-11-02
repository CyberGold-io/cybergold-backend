"""Parallel hint arrivals preserve ordinary selection and request ownership."""
import asyncio
from copy import deepcopy
import json
import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quote_budget import QuoteBudget, SearchStopped, budget_context
from cybergold_candidate.quoter.bootstrap import (
    ProviderUnavailable, RouteBootstrap, bootstrap_scope, current_bootstrap)
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.route_observations import origin_scope, _origin
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.route_tools import CandidateFeed, PendingRouteTool, RouteTool, async_batches


BLOCK = {'blockNumber': '101', 'blockHash': '0x' + 'ab'*32, 'chainId': 1}


def candidate(amount):
    return [{'amountIn': str(amount), 'hops': [{'kind': 'wrap', 'currencyOut': 'target'}]}]


class ParallelRouteDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_quick_pass_does_not_wait_for_older_quick_or_detailed_work(self):
        first_quick, late_quick = asyncio.Event(), asyncio.Event()
        next_batch, release = asyncio.Event(), asyncio.Event()
        drained, rounds, observed = [], [], []
        class Immediate(RouteTool):
            name = 'ordinary-local'
            def discover(_self, query):
                return CandidateFeed(available=[candidate(5)])
        class Stream:
            name = 'arbitrary-tool'
            async def discover_batches(_self, *_):
                yield [candidate(101)]
                await next_batch.wait()
                yield [candidate(202)]
        session = RouteBootstrap([Immediate(), PendingRouteTool(Stream())])
        async def ordinary():
            self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [candidate(5)])
        async def detailed():
            rounds.append(True)
            try:
                await release.wait()
            finally:
                drained.append('detailed')
        async def quick():
            self.assertEqual(_origin.get(), 'cybergold-quoter')
            offers = list(session.offers('source', 'target', 100, BLOCK))
            observed.append(offers)
            amount = offers[0]['branches'][0]['amountIn']
            if amount == '101':
                first_quick.set()
                try:
                    await release.wait()
                finally:
                    drained.append('first-quick')
            else:
                self.assertEqual(amount, '202')
                # All ordinary feeds remain present after the ready prefix.
                self.assertTrue(any(row['branches'] == candidate(5) for row in offers))
                self.assertTrue(any(row['branches'] == candidate(101) for row in offers))
                late_quick.set()
        with origin_scope('cybergold-quoter'):
            task = asyncio.create_task(session.run(ordinary(), detailed, quick=quick))
        try:
            await asyncio.wait_for(first_quick.wait(), 1)
            next_batch.set()
            await asyncio.wait_for(late_quick.wait(), 1)
            self.assertEqual(drained, [])
            self.assertEqual(rounds, [True])
            self.assertEqual(observed[-1][0]['origins'], ['arbitrary-tool'])
            # The driver's normal context never inherits a quick prefix.
            self.assertEqual(next(iter(session.offers('source', 'target', 100, BLOCK)))['branches'], candidate(5))
        finally:
            release.set()
            next_batch.set()
            await asyncio.wait_for(task, 1)
        self.assertCountEqual(drained, ['first-quick', 'detailed', 'detailed'])
        self.assertEqual(session.metrics['quickReevaluations'], 2)

    async def test_later_query_quick_snapshot_retains_ready_choices_for_other_queries(self):
        first_ready, second_ready, next_query, release = (asyncio.Event() for _ in range(4))
        class Immediate(RouteTool):
            name = 'ordinary-local'
            def discover(_self, query):
                return CandidateFeed(available=[candidate(5)])
        class Source:
            name = 'generic-tool'
            async def discover(_self, source, *_):
                if source == 'source':
                    return [candidate(101)]
                await next_query.wait()
                return [candidate(202)]
        session = RouteBootstrap([Immediate(), PendingRouteTool(Source())])
        async def ordinary():
            session.candidates('source', 'target', 100, BLOCK)
            session.candidates('other', 'target', 100, BLOCK)
        async def detailed():
            await release.wait()
        async def quick():
            source = next(iter(session.offers('source', 'target', 100, BLOCK)))
            other = next(iter(session.offers('other', 'target', 100, BLOCK)))
            self.assertEqual(source['branches'], candidate(101))
            if other['branches'] == candidate(5):
                first_ready.set()
            else:
                self.assertEqual(other['branches'], candidate(202))
                second_ready.set()
        task = asyncio.create_task(session.run(ordinary(), detailed, quick=quick))
        try:
            await asyncio.wait_for(first_ready.wait(), 1)
            next_query.set()
            await asyncio.wait_for(second_ready.wait(), 1)
        finally:
            next_query.set()
            release.set()
            await asyncio.wait_for(task, 1)

    async def test_quick_pass_cleanup_obeys_cancellation_budget_and_disproof_priority(self):
        for stop in ('caller', 'budget', 'ordinary-error'):
            for disproof in (False, True):
                with self.subTest(stop=stop, disproof=disproof):
                    entered, drained = asyncio.Event(), []
                    class Source:
                        name = 'generic-tool'
                        async def discover_batches(_self, *_):
                            try:
                                yield [candidate(101)]
                                await asyncio.Event().wait()
                            finally:
                                drained.append('provider')
                    budget = QuoteBudget()
                    with budget_context(budget):
                        session = RouteBootstrap([PendingRouteTool(Source())])
                        async def ordinary():
                            session.candidates('source', 'target', 100, BLOCK)
                            try:
                                await entered.wait()
                                if stop == 'ordinary-error':
                                    raise ValueError('ordinary failure')
                                await asyncio.Event().wait()
                            finally:
                                drained.append('ordinary')
                        async def detailed():
                            try:
                                await asyncio.Event().wait()
                            finally:
                                drained.append('detailed')
                        async def quick():
                            try:
                                entered.set()
                                await asyncio.Event().wait()
                            finally:
                                drained.append('quick')
                                if disproof:
                                    raise SnapshotChanged('quick context disproved during drain')
                        task = asyncio.create_task(session.run(ordinary(), detailed, quick=quick))
                        await asyncio.wait_for(entered.wait(), 1)
                        if stop == 'caller':
                            task.cancel()
                        elif stop == 'budget':
                            budget.finish_selection('best-initial')
                        expected = (SnapshotChanged if disproof else ValueError if stop == 'ordinary-error'
                                    else SearchStopped if stop == 'budget' else asyncio.CancelledError)
                        with self.assertRaises(expected):
                            await asyncio.wait_for(task, 1)
                    self.assertCountEqual(drained, ['ordinary', 'provider', 'quick', 'detailed'])
                    self.assertEqual(session.metrics['providers']['generic-tool']['pending'], 0)

    async def test_incremental_batch_wakes_before_completion_and_survives_ordinary_failure(self):
        release, ready, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Stream:
            name = 'uniroute-local'
            async def discover_batches(_self, *_):
                try:
                    yield [candidate(101)]
                    await release.wait()
                    raise OSError('private supplier failure')
                finally:
                    drained.set()
        session = RouteBootstrap([PendingRouteTool(Stream())])
        async def ordinary():
            self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [])
        async def reevaluate():
            self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [candidate(101)])
            ready.set()
        task = asyncio.create_task(session.run(ordinary(), reevaluate))
        await ready.wait()
        row = session.metrics['providers']['uniroute-local']
        self.assertEqual(row['pending'], 1)
        self.assertEqual(row['batches'], 1)
        self.assertIsNone(row['completedMs'])
        self.assertFalse(task.done())
        release.set()
        await task
        self.assertTrue(drained.is_set())
        row = session.metrics['providers']['uniroute-local']
        self.assertEqual(row['error'], 1)
        self.assertEqual(row['candidates'], 1)
        self.assertNotIn('private', json.dumps(session.metrics))

    async def test_incremental_catalog_refresh_keeps_early_offers_and_coalesces_next_query(self):
        release, ready, calls = asyncio.Event(), asyncio.Event(), []
        catalog = SimpleNamespace(inventory={'one': self.catalog_pool()}, load_task=None)
        class Stream:
            name, catalog_dependent = 'uniroute-local', True
            async def discover_batches(_self, *_):
                count = len(catalog.inventory)
                calls.append(count)
                yield [candidate(100+count)]
                if len(calls) == 1:
                    ready.set()
                    await release.wait()
                yield []
        session = RouteBootstrap([PendingRouteTool(Stream())], catalog=catalog)
        self.addAsyncCleanup(session.close)
        session.candidates('source', 'target', 100, BLOCK)
        await ready.wait()
        self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [candidate(101)])
        catalog.inventory['two'] = self.catalog_pool('other')
        session.refresh_catalog()
        catalog.inventory['three'] = self.catalog_pool('third')
        session.refresh_catalog()
        self.assertEqual(calls, [1])
        release.set()
        await self.settle(session)
        self.assertEqual(calls, [1, 3])
        self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [candidate(101), candidate(103)])

    async def test_incremental_caller_cancel_and_existing_budget_stop_close_stream(self):
        for stop in (False, True):
            ready, drained = asyncio.Event(), asyncio.Event()
            class Stream:
                name = 'uniroute-local'
                async def discover_batches(_self, *_):
                    try:
                        yield [candidate(101)]
                        await asyncio.Event().wait()
                    finally:
                        drained.set()
            budget = QuoteBudget()
            with budget_context(budget):
                session = RouteBootstrap([PendingRouteTool(Stream())])
                async def ordinary():
                    session.candidates('source', 'target', 100, BLOCK)
                async def reevaluate():
                    ready.set()
                task = asyncio.create_task(session.run(ordinary(), reevaluate))
                await ready.wait()
                if stop:
                    budget.finish_selection('best-initial')
                else:
                    task.cancel()
                with self.assertRaises(SearchStopped if stop else asyncio.CancelledError):
                    await task
            self.assertTrue(drained.is_set())
            self.assertEqual(session.metrics['providers']['uniroute-local']['cancelled'], 1)

    async def test_common_async_batch_helper_consumes_both_parts_without_metadata_gate(self):
        async def updates():
            yield [candidate(101)]
        async def pending():
            return [candidate(102)]
        feed = CandidateFeed(updates=updates(), pending=pending())
        self.assertEqual([row async for row in async_batches(feed)], [[candidate(101)], [candidate(102)]])

    async def test_common_batch_cancellation_closes_unconsumed_pending_part(self):
        for as_task in (False, True):
            ready, drained = asyncio.Event(), asyncio.Event()
            async def updates():
                yield [candidate(101)]
                ready.set()
                await asyncio.Event().wait()
            async def pending():
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            operation = asyncio.create_task(pending()) if as_task else pending()
            feed = CandidateFeed(updates=updates(), pending=operation)
            async def consume():
                async for _ in async_batches(feed):
                    pass
            task = asyncio.create_task(consume())
            await ready.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            if as_task:
                self.assertTrue(operation.cancelled())
                self.assertTrue(drained.is_set())
            else:
                self.assertEqual(inspect.getcoroutinestate(operation), inspect.CORO_CLOSED)

    def catalog_pool(self, target='target'):
        return {'id': target, 'protocol': 'v2', 'token0': {'address': 'source'},
                'token1': {'address': target}, 'feePips': 3000}

    async def settle(self, session):
        async with asyncio.timeout(1):
            while any(not task.done() for task in session._tasks):
                await asyncio.gather(*tuple(session._tasks))
                await asyncio.sleep(0)

    async def test_initial_catalog_change_is_consumed_by_first_query_without_reevaluation(self):
        catalog = SimpleNamespace(inventory={'one': self.catalog_pool()}, load_task=None)
        calls = []
        class Local(RouteTool):
            name, catalog_dependent = 'static-local', True
            def discover(_self, query):
                calls.append(tuple(catalog.inventory))
                return CandidateFeed(available=[candidate(query.amount+len(catalog.inventory))])
        session = RouteBootstrap([Local()], catalog=catalog)
        catalog.inventory['two'] = self.catalog_pool('other')
        self.assertTrue(session.refresh_catalog())
        self.assertFalse(session.refresh_catalog())
        async def ordinary():
            self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [candidate(102)])
        async def unnecessary():
            self.fail('Initial graph preparation must not start a whole-plan reevaluation')
        await session.run(ordinary(), unnecessary, quick=unnecessary)
        self.assertEqual(calls, [('one', 'two')])
        self.assertEqual(session.metrics['queries'], 1)
        self.assertEqual(session.metrics['reevaluations'], 0)
        self.assertEqual(session.metrics['quickReevaluations'], 0)

    async def test_changed_catalog_coalesces_inflight_local_inputs_and_preserves_offers(self):
        catalog = SimpleNamespace(inventory={'one': self.catalog_pool()}, load_task=None)
        entered, release, calls, hosted_calls = asyncio.Event(), asyncio.Event(), [], []
        class Local:
            name, catalog_dependent = 'uniroute-local', True
            async def discover(_self, *_):
                count = len(catalog.inventory)
                calls.append(count)
                if len(calls) == 1:
                    entered.set()
                    await release.wait()
                return [candidate(100+count)]
        class Hosted:
            name = 'uniroute-api'
            async def discover(_self, *_):
                hosted_calls.append(True)
                return [candidate(200)]
        session = RouteBootstrap([PendingRouteTool(Local()), PendingRouteTool(Hosted())], catalog=catalog)
        self.addAsyncCleanup(session.close)
        session.candidates('source', 'target', 100, BLOCK)
        await entered.wait()
        catalog.inventory['two'] = self.catalog_pool('other')
        self.assertTrue(session.refresh_catalog())
        catalog.inventory['three'] = self.catalog_pool('third')
        self.assertTrue(session.refresh_catalog())
        self.assertFalse(session.refresh_catalog())
        self.assertEqual(calls, [1])
        release.set()
        await self.settle(session)
        self.assertEqual(calls, [1, 3])
        self.assertEqual(len(hosted_calls), 1)
        self.assertCountEqual(session.candidates('source', 'target', 100, BLOCK),
                              [candidate(101), candidate(103), candidate(200)])
        # Optional display data, scalar observations and a second alias for the
        # same execution key do not change the graph or repeat hosted/local work.
        catalog.inventory['one']['token0']['symbol'] = 'optional'
        catalog.inventory['one']['reserve0'] = '2000'
        catalog.inventory['alias'] = {**deepcopy(catalog.inventory['one']), 'id': 'alias'}
        self.assertFalse(session.refresh_catalog())
        self.assertEqual(calls, [1, 3])
        self.assertEqual(session.metrics['queries'], 1)

    async def test_persisted_catalog_completion_wakes_custom_without_waiting_on_load(self):
        release, started, ordinary_done, refreshed = (asyncio.Event() for _ in range(4))
        catalog = SimpleNamespace(inventory={}, load_task=None)
        async def load():
            await release.wait()
            catalog.inventory['one'] = self.catalog_pool()
        catalog.load_task = asyncio.create_task(load())
        session = RouteBootstrap([CustomRoutes(catalog)], catalog=catalog)
        async def ordinary():
            self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [])
            started.set()
            await ordinary_done.wait()
        async def reevaluate():
            self.assertEqual(len(session.candidates('source', 'target', 100, BLOCK)), 1)
            refreshed.set()
            ordinary_done.set()
        task = asyncio.create_task(session.run(ordinary(), reevaluate))
        await started.wait()
        self.assertFalse(catalog.load_task.done())
        release.set()
        await task
        self.assertTrue(refreshed.is_set())
        self.assertEqual(session.revision, 1)

    async def test_close_detaches_pending_catalog_load_without_waiting_or_cancelling_it(self):
        release = asyncio.Event()
        catalog = SimpleNamespace(inventory={}, load_task=None)
        async def load():
            await release.wait()
            catalog.inventory['one'] = self.catalog_pool()
        catalog.load_task = asyncio.create_task(load())
        session = RouteBootstrap([CustomRoutes(catalog)], catalog=catalog)
        async def ordinary():
            session.candidates('source', 'target', 100, BLOCK)
        async def reevaluate():
            self.fail('Closed sessions cannot consume later DB completions')
        await session.run(ordinary(), reevaluate)
        self.assertFalse(catalog.load_task.done())
        before = session.metrics
        release.set()
        await catalog.load_task
        await asyncio.sleep(0)
        self.assertFalse(session.refresh_catalog())
        self.assertEqual(session.metrics, before)

    async def test_existing_budget_stop_prevents_catalog_followup_before_close(self):
        release, entered, calls = asyncio.Event(), asyncio.Event(), []
        catalog = SimpleNamespace(inventory={'one': self.catalog_pool()}, load_task=None)
        class Local:
            name, catalog_dependent = 'uniroute-local', True
            async def discover(_self, *_):
                calls.append(True)
                entered.set()
                await release.wait()
                return []
        budget = QuoteBudget()
        with budget_context(budget):
            session = RouteBootstrap([PendingRouteTool(Local())], catalog=catalog)
            session.candidates('source', 'target', 100, BLOCK)
            await entered.wait()
            catalog.inventory['two'] = self.catalog_pool('other')
            self.assertTrue(session.refresh_catalog())
            budget.finish_selection('best-initial')
            catalog.inventory['three'] = self.catalog_pool('third')
            self.assertFalse(session.refresh_catalog())
            release.set()
            await self.settle(session)
            self.assertEqual(len(calls), 1)
            await session.close()

    async def test_immediate_static_feed_honors_its_declared_catalog_dependency(self):
        catalog = SimpleNamespace(inventory={'one': self.catalog_pool()}, load_task=None)
        calls = []
        class Static(RouteTool):
            name, catalog_dependent = 'static-local', True
            def discover(_self, query):
                calls.append(True)
                return CandidateFeed(available=[candidate(query.amount+len(catalog.inventory))])
        session = RouteBootstrap([Static()], catalog=catalog)
        self.addAsyncCleanup(session.close)
        self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [candidate(101)])
        catalog.inventory['two'] = self.catalog_pool('other')
        self.assertTrue(session.refresh_catalog())
        self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [candidate(102)])
        self.assertFalse(session.refresh_catalog())
        self.assertEqual(len(calls), 2)

    async def test_completed_catalog_load_is_consumed_before_queued_callback_delivery(self):
        release = asyncio.Event()
        catalog = SimpleNamespace(inventory={}, load_task=None)
        rounds, delivered, closed_when_published = [], [], []
        async def load():
            await release.wait()
            closed_when_published.append(session._closed)
            catalog.inventory['one'] = self.catalog_pool()
        catalog.load_task = asyncio.create_task(load())
        session = RouteBootstrap([CustomRoutes(catalog)], catalog=catalog)
        async def ordinary():
            self.assertEqual(session.candidates('source', 'target', 100, BLOCK), [])
            await asyncio.sleep(0)
        async def reevaluate():
            rounds.append(len(session.candidates('source', 'target', 100, BLOCK)))
            # An unrelated connector update during this pass is not another
            # completion of the already-consumed DB task.
            catalog.inventory['two'] = self.catalog_pool('other')
            await asyncio.sleep(0)
        original = asyncio.gather
        def gather(*arguments, **keywords):
            if (len(arguments) == 1 and isinstance(arguments[0], asyncio.Task)
                    and arguments[0].cancelling() and not delivered):
                delivered.append(True)
                # The load publishes before run resumes from its cancelled
                # change-wait drain, with its callback queued behind run.
                arguments[0].add_done_callback(lambda _: release.set())
            return original(*arguments, **keywords)
        with patch('asyncio.gather', gather):
            await session.run(ordinary(), reevaluate)
        await catalog.load_task
        self.assertEqual(closed_when_published, [False])
        self.assertEqual(rounds, [1])
        self.assertEqual(session.revision, 1)

    async def test_duplicate_nominations_retain_independent_origins_without_changing_sharing(self):
        calls, offered = [], []
        async def discover(*args):
            calls.append(args)
            return [candidate(200)]
        session = RouteBootstrap({'tool-one': discover, 'tool-two': discover})
        async def ordinary():
            self.assertEqual(list(session.offers('source', 'target', 100, BLOCK)), [])
            self.assertEqual(session.candidates('SOURCE', 'TARGET', '100', BLOCK), [])
        async def reevaluate():
            offered.extend(session.offers('source', 'target', 100, BLOCK))
            copied = list(session.offers('source', 'target', 100, BLOCK))
            copied[0]['origins'].append('untrusted-copy')
            copied[0]['branches'][0]['amountIn'] = '1'
            self.assertNotIn('untrusted-copy', repr(list(session.offers('source', 'target', 100, BLOCK))))
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

    async def test_latest_supplier_disproof_keeps_early_hints_and_independent_result(self):
        ready, release, reevaluated = asyncio.Event(), asyncio.Event(), []
        class Source:
            name = 'optional-sdk'
            async def discover_batches(_self, *_):
                yield [candidate(101)]
                ready.set()
                await release.wait()
                raise SnapshotChanged('optional SDK observation changed')
        session = RouteBootstrap([PendingRouteTool(Source())], nomination_only=True)
        async def ordinary():
            session.candidates('source', 'target', 100, BLOCK)
            await ready.wait()
            release.set()
            return 'independent Helpers result'
        async def reevaluate():
            reevaluated.extend(session.candidates('source', 'target', 100, BLOCK))
        self.assertEqual(await asyncio.wait_for(session.run(ordinary(), reevaluate), 1),
                         'independent Helpers result')
        self.assertEqual(reevaluated, [candidate(101)])
        self.assertEqual(session.metrics['providers']['optional-sdk']['invalidated'], 1)
        self.assertEqual(session.metrics['providers']['optional-sdk']['pending'], 0)

    async def test_latest_supplier_cleanup_disproof_does_not_replace_ordinary_error(self):
        started, drained = asyncio.Event(), []
        async def discover(*_):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.append('provider')
                raise SnapshotChanged('optional SDK disproved while draining')
        session = RouteBootstrap({'optional-sdk': discover}, nomination_only=True)
        async def ordinary():
            session.candidates('source', 'target', 100, BLOCK)
            await started.wait()
            raise ValueError('ordinary Helpers failure')
        async def reevaluate():
            self.fail('No candidate was produced')
        with self.assertRaisesRegex(ValueError, 'ordinary Helpers failure'):
            await asyncio.wait_for(session.run(ordinary(), reevaluate), 1)
        self.assertEqual(drained, ['provider'])
        self.assertEqual(session.metrics['providers']['optional-sdk']['pending'], 0)
        self.assertEqual(session.metrics['closeErrors'], 0)

    async def test_latest_supplier_close_disproof_is_observed_without_revoking_result(self):
        class Source:
            name = 'optional-sdk'
            async def discover(_self, *_):
                return []
            async def close(_self):
                raise SnapshotChanged('optional cache context changed at close')
        session = RouteBootstrap([PendingRouteTool(Source())], nomination_only=True)
        async def ordinary():
            session.candidates('source', 'target', 100, BLOCK)
            return 'independent Helpers result'
        async def reevaluate():
            self.fail('No candidate was produced')
        self.assertEqual(await asyncio.wait_for(session.run(ordinary(), reevaluate), 1),
                         'independent Helpers result')
        self.assertEqual(session.metrics['closeErrors'], 1)

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
