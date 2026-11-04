"""Optional SQL inputs/writes cannot hold fresh Helpers qualification hostage."""
import asyncio
from copy import deepcopy
import gc
import unittest
from unittest.mock import AsyncMock
import weakref

from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.quote_publication import CanonicalPublication
from cybergold_candidate.quoter.reuse_estimate import attach_reuse_sample
from cybergold_candidate.quoter.reuse_routes import neighbor_proposals
from cybergold_candidate.quote_budget import QuoteBudget, SearchStopped, budget_context
from cybergold_candidate.quoter.provenance import attach_origins
from cybergold_candidate.recovery_rpc import SnapshotChanged
from test_economic_quote_api import SharedStore
from test_progressive_economic_quotes import economic_request, ScriptedQuoter
from test_universal_quote import Quotes, Engine, BLOCK, PAXG, OTHER


class ParallelCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.request = economic_request()
        self.value = await Quotes(Engine()).candidate(self.request, 0, 'core-first', BLOCK, [], [])
        for route in self.value['plan']['conversions'].values():
            route['discoveryOrigins'] = ['cybergold-custom', 'uniroute-api']
        attach_origins(self.value)

    def service(self, script, *, store=None, observe_scope=None):
        service = EconomicQuotes(ScriptedQuoter(script), store or SharedStore(), observe_scope=observe_scope)
        self.addAsyncCleanup(service.close)
        return service

    async def test_json_and_stream_search_start_before_optional_scope_and_return_before_it(self):
        for streamed, refresh in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(streamed=streamed, refresh=refresh):
                held, drained, quoted = asyncio.Event(), asyncio.Event(), asyncio.Event()
                async def observe():
                    try:
                        held.set()
                        await asyncio.Event().wait()
                    finally:
                        drained.set()
                async def script(_request, callback=None, **kwargs):
                    quoted.set()
                    readers = [asyncio.create_task(kwargs[name]()) for name in ('seed_lookup', 'neighbors')]
                    try:
                        await held.wait()
                        if callback:
                            await callback({'type': 'qualified', 'value': self.value})
                        return deepcopy(self.value)
                    finally:
                        for reader in readers:
                            reader.cancel()
                        await asyncio.gather(*readers, return_exceptions=True)
                service = self.service(script, observe_scope=observe)
                service.store.lookup = AsyncMock(side_effect=AssertionError('scope is still held'))
                service.store.save = AsyncMock(side_effect=AssertionError('scope is still held'))
                frames = []
                async def publish(frame):
                    frames.append(deepcopy(frame))
                operation = (service.progressive(self.request, publish, refresh=refresh) if streamed
                             else service.get(self.request, refresh=refresh))
                result = await asyncio.wait_for(operation, 1)
                self.assertTrue(quoted.is_set())
                self.assertFalse(drained.is_set())
                self.assertEqual(result['quotedOutput'], self.value['quotedOutput'])
                self.assertEqual(result['routeOrigins'], self.value['routeOrigins'])
                if streamed:
                    self.assertEqual(frames[0]['type'], 'qualified')
                service.store.lookup.assert_not_awaited()
                service.store.save.assert_not_awaited()
                await service.close()
                self.assertTrue(drained.is_set())
                self.assertFalse(service.background)

    async def test_feed_coalesces_both_sql_reads_and_cancelling_one_reader_preserves_its_sibling(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def observe():
            entered.set(); await release.wait()
        service = self.service(AsyncMock(), observe_scope=observe)
        service.store.lookup = AsyncMock(return_value=self.value)
        service.store.neighbors = AsyncMock(return_value=[{'family': 'market', 'side': 'lower', 'quote': self.value}])
        feed = service.cache_feed(self.request)
        one, two, three = (asyncio.create_task(read()) for read in (feed.neighbors, feed.neighbors, feed.lookup))
        try:
            await entered.wait(); one.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await one
            release.set()
            neighbors, value = await asyncio.gather(two, three)
            self.assertEqual(neighbors[0]['quote'], self.value)
            self.assertEqual(value, self.value)
            neighbors[0]['quote']['quotedOutput'] = 'different-caller-copy'
            self.assertEqual((await feed.neighbors())[0]['quote'], self.value)
            self.assertEqual(await feed.lookup(), self.value)
            service.store.lookup.assert_awaited_once()
            service.store.neighbors.assert_awaited_once()
        finally:
            for task in (one, two, three):
                task.cancel()
            await asyncio.gather(one, two, three, return_exceptions=True)
            await feed.close()
        self.assertTrue(all(task.done() for task in feed.reads.values()))

    async def test_independently_cancelled_sql_producers_are_misses_but_caller_cancel_still_drains(self):
        service = self.service(AsyncMock())
        service.store.lookup = AsyncMock(side_effect=asyncio.CancelledError())
        service.store.neighbors = AsyncMock(side_effect=asyncio.CancelledError())
        feed = service.cache_feed(self.request)
        self.assertIsNone(await feed.lookup())
        self.assertEqual(await feed.neighbors(), [])
        # A sibling joins the same completed optional miss, without retrying.
        self.assertIsNone(await feed.lookup())
        self.assertEqual(await feed.neighbors(), [])
        service.store.lookup.assert_awaited_once()
        service.store.neighbors.assert_awaited_once()
        await feed.close()
        entered, drained = asyncio.Event(), asyncio.Event()
        async def held(*_, **__):
            try:
                entered.set(); await asyncio.Event().wait()
            finally:
                drained.set()
        service.store.lookup = AsyncMock(side_effect=held)
        feed = service.cache_feed(self.request)
        caller = asyncio.create_task(feed.lookup())
        await entered.wait(); caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertFalse(drained.is_set(), 'the feed still owns its memoized SQL producer')
        await feed.close()
        self.assertTrue(drained.is_set())
        self.assertTrue(all(task.done() for task in feed.reads.values()))

    async def test_late_historical_offer_cannot_replace_an_already_published_current_quote(self):
        ready, release, offered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        old, fresh = deepcopy(self.value), deepcopy(self.value)
        old['quotedOutput'], fresh['quotedOutput'] = '900', '100'
        async def script(request, callback, **options):
            await callback({'type': 'qualified', 'value': fresh})
            await ready.wait(); release.set()
            await offered.wait()
            return deepcopy(fresh)
        service = self.service(script)
        async def lookup(*_, **__):
            await release.wait()
            offered.set()
            return deepcopy(old)
        service.store.lookup = AsyncMock(side_effect=lookup)
        service.store.neighbors = AsyncMock(return_value=[])
        frames = []
        async def publish(frame):
            frames.append(deepcopy(frame)); ready.set()
        result = await asyncio.wait_for(service.progressive(self.request, publish), 1)
        self.assertTrue(offered.is_set())
        self.assertEqual([frame['value']['quotedOutput'] for frame in frames], ['100'])
        self.assertEqual(result['quotedOutput'], '100')
        service.store.lookup.assert_awaited_once()
        service.store.neighbors.assert_awaited_once()

    async def test_each_historical_source_can_publish_before_its_held_sibling(self):
        for early, exact_missing in (('lookup', False), ('neighbors', False), ('neighbors', True)):
            with self.subTest(early=early, exact_missing=exact_missing):
                entered = {name: asyncio.Event() for name in ('lookup', 'neighbors')}
                release = {name: asyncio.Event() for name in entered}
                drained = {name: asyncio.Event() for name in entered}
                fresh_release, delivered = asyncio.Event(), asyncio.Queue()
                exact, lower, core, fresh = (deepcopy(self.value) for _ in range(4))
                lower.update(neighbor_proposals(lower, int(lower['inputs'][0]['amount'])-1, [PAXG, OTHER])[-1])
                core = await Quotes(Engine()).candidate(self.request, 100, 'core-first', BLOCK,
                                                       [PAXG, OTHER], [500000, 500000])
                attach_origins(core)
                for quote, output, observation in ((exact, '100', 'exact'), (lower, '110', 'lower'),
                                                   (core, '120', 'core'), (fresh, '130', 'current')):
                    quote['quotedOutput'] = output
                    quote['context']['observedAt'] = observation
                    quote['fees']['coreProtocolFeeCygld'] = output
                rows = [{'family': 'market', 'side': 'lower', 'quote': lower},
                        {'family': 'core', 'side': 'lower', 'quote': core}]
                async def lookup(*_, **__):
                    try:
                        entered['lookup'].set(); await release['lookup'].wait()
                        return None if exact_missing else deepcopy(exact)
                    finally:
                        drained['lookup'].set()
                async def neighbors(*_, **__):
                    try:
                        entered['neighbors'].set(); await release['neighbors'].wait()
                        return deepcopy(rows)
                    finally:
                        drained['neighbors'].set()
                store = SharedStore()
                store.lookup, store.neighbors = AsyncMock(side_effect=lookup), AsyncMock(side_effect=neighbors)
                async def script(_request, callback, **options):
                    readers = [asyncio.create_task(options[name]()) for name in ('seed_lookup', 'neighbors')]
                    try:
                        await fresh_release.wait()
                        await callback({'type': 'qualified', 'value': deepcopy(fresh)})
                        return deepcopy(fresh)
                    finally:
                        for reader in readers: reader.cancel()
                        await asyncio.gather(*readers, return_exceptions=True)
                service, frames = self.service(script, store=store), []
                async def publish(frame):
                    frames.append(deepcopy(frame)); delivered.put_nowait(frame)
                operation = asyncio.create_task(service.progressive(self.request, publish))
                try:
                    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered.values())), 1)
                    release[early].set()
                    first = await asyncio.wait_for(delivered.get(), 1)
                    expected = exact if early == 'lookup' else core
                    self.assertEqual(first['value']['observation']['source'], 'stored')
                    for field in ('inputs', 'plan', 'context', 'quotedOutput', 'fees', 'routeOrigins'):
                        self.assertEqual(first['value'][field], expected[field])
                    other = 'neighbors' if early == 'lookup' else 'lookup'
                    self.assertFalse(drained[other].is_set())
                    release[other].set()
                    await drained[other].wait()
                    if early == 'lookup':
                        second = await asyncio.wait_for(delivered.get(), 1)
                        self.assertEqual(second['value']['quotedOutput'], '120')
                    fresh_release.set()
                    result = await asyncio.wait_for(operation, 1)
                    historical = [int(frame['value']['quotedOutput']) for frame in frames
                                  if frame['value']['observation']['source'] == 'stored']
                    self.assertEqual(historical, [100, 120] if early == 'lookup' else [120])
                    self.assertEqual(result['quotedOutput'], '130')
                    store.lookup.assert_awaited_once(); store.neighbors.assert_awaited_once()
                finally:
                    fresh_release.set()
                    for event in release.values(): event.set()
                    if not operation.done(): operation.cancel()
                    await asyncio.gather(operation, return_exceptions=True)

    async def test_historical_ties_enrich_limitation_once_and_current_pricing_takes_precedence(self):
        first, limited, fresh, later = (deepcopy(self.value) for _ in range(4))
        first['quotedOutput'] = limited['quotedOutput'] = '100'
        limited['searchCoverage']['inputLimitObserved'] = True
        for chosen in limited['plan']['conversions'].values():
            chosen['discoveryOrigins'].append('uniswap-alpharouter')
        fresh['quotedOutput'], later['quotedOutput'] = '90', '999'
        frames = []
        async def publish(frame): frames.append(deepcopy(frame))
        publication = CanonicalPublication(None, self.request, publish)
        for value in (first, limited, limited):
            value['observation'] = {'source': 'stored', 'refresh': False}
            publication.queue.put_nowait(('stored', attach_reuse_sample(value)))
        publication.queue.put_nowait(('candidate', fresh))
        publication.queue.put_nowait(('stored', later))
        publication.queue.put_nowait(None)
        await publication.run()
        self.assertEqual([frame['value']['quotedOutput'] for frame in frames], ['100', '100', '90'])
        self.assertNotIn('inputLimitObserved', frames[0]['value']['reuseSample'])
        self.assertTrue(frames[1]['value']['reuseSample']['inputLimitObserved'])
        self.assertIn('uniswap-alpharouter', frames[1]['value']['routeOrigins']['discoveryProviders'])
        for field in ('inputs', 'context', 'fees'):
            self.assertEqual(frames[1]['value'][field], first[field])
        self.assertEqual(frames[-1]['value']['observation']['source'], 'search')
        self.assertEqual(publication.best['quotedOutput'], '90')

    async def test_disconnect_after_early_history_drains_both_readers_and_current_producer(self):
        neighbor_started, neighbor_drained, producer_drained, ready = (asyncio.Event() for _ in range(4))
        store = SharedStore()
        store.lookup = AsyncMock(return_value=deepcopy(self.value))
        async def neighbors(*_, **__):
            try:
                neighbor_started.set(); await asyncio.Event().wait()
            finally:
                neighbor_drained.set()
        store.neighbors = AsyncMock(side_effect=neighbors)
        async def script(_request, callback, **options):
            readers = [asyncio.create_task(options[name]()) for name in ('seed_lookup', 'neighbors')]
            try:
                await asyncio.Event().wait()
            finally:
                for reader in readers: reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                producer_drained.set()
        service = self.service(script, store=store)
        async def publish(frame):
            self.assertEqual(frame['value']['observation']['source'], 'stored')
            ready.set()
        operation = asyncio.create_task(service.progressive(self.request, publish))
        await asyncio.wait_for(asyncio.gather(ready.wait(), neighbor_started.wait()), 1)
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError): await operation
        self.assertTrue(neighbor_drained.is_set())
        self.assertTrue(producer_drained.is_set())
        store.lookup.assert_awaited_once(); store.neighbors.assert_awaited_once()
        await service.close()
        self.assertFalse(service.background)

    async def test_optional_exact_lookup_and_neighbors_are_independent_and_errors_are_misses(self):
        for error in (OSError('optional SQL failure'), SnapshotChanged('optional cache context changed')):
            with self.subTest(error=type(error).__name__):
                exact_started, neighbors_done = asyncio.Event(), asyncio.Event()
                store = SharedStore()
                async def lookup(*_, **__):
                    exact_started.set()
                    await neighbors_done.wait()
                    raise error
                async def neighbors(*_, **__):
                    await exact_started.wait()
                    neighbors_done.set()
                    return [{'family': 'market', 'side': 'lower', 'quote': deepcopy(self.value)}]
                store.lookup, store.neighbors = lookup, neighbors
                async def script(_request, callback=None, **kwargs):
                    seed, nearby = await asyncio.gather(kwargs['seed_lookup'](), kwargs['neighbors']())
                    self.assertIsNone(seed)
                    self.assertEqual(nearby[0]['quote']['plan'], self.value['plan'])
                    return deepcopy(self.value)
                result = await asyncio.wait_for(self.service(script, store=store).get(self.request, refresh=True), 1)
                self.assertEqual(result['quotedOutput'], self.value['quotedOutput'])

    async def test_cancelled_cache_reader_does_not_cancel_shared_scope_or_its_sibling(self):
        entered, release, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def observe():
            try:
                entered.set()
                await release.wait()
            finally:
                drained.set()
        service = self.service(AsyncMock(), observe_scope=observe)
        service.store.neighbors = AsyncMock(return_value=[{'family': 'market', 'side': 'lower', 'quote': self.value}])
        feed = service.cache_feed(self.request)
        one, two = asyncio.create_task(feed.lookup()), asyncio.create_task(feed.neighbors())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            one.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await one
            self.assertFalse(drained.is_set())
            self.assertFalse(two.done())
            release.set()
            self.assertEqual((await asyncio.wait_for(two, 1))[0]['quote'], self.value)
            self.assertTrue(drained.is_set())
            service.quoter.engine.registry.ensure_loaded.assert_awaited_once()
        finally:
            for task in (one, two):
                task.cancel()
            await asyncio.gather(one, two, return_exceptions=True)
            await feed.close()

    async def test_real_quoter_qualifies_while_exact_and_neighbor_sql_reads_are_held(self):
        quoter = Quotes(Engine())
        quoter.engine.registry.ensure_loaded = AsyncMock()
        store = SharedStore()
        started = {name: asyncio.Event() for name in ('lookup', 'neighbors')}
        drained = {name: asyncio.Event() for name in started}
        def held(name):
            async def read(*_, **__):
                try:
                    started[name].set()
                    await asyncio.Event().wait()
                finally:
                    drained[name].set()
            return read
        store.lookup, store.neighbors = held('lookup'), held('neighbors')
        service = EconomicQuotes(quoter, store)
        self.addAsyncCleanup(service.close)
        budget, frames = QuoteBudget(), []
        async def publish(frame):
            frames.append(deepcopy(frame))
            if frame['type'] == 'qualified':
                await asyncio.gather(*(event.wait() for event in started.values()))
                self.assertFalse(any(event.is_set() for event in drained.values()))
                budget.finish_selection('best-initial')
        with budget_context(budget):
            result = await asyncio.wait_for(service.progressive(self.request, publish, refresh=True), 1)
        self.assertTrue(any(frame['type'] == 'qualified' for frame in frames))
        self.assertGreater(int(result['quotedOutput']), 0)
        self.assertTrue(all(event.is_set() for event in drained.values()))

    async def test_json_returns_before_held_write_and_owner_close_drains_it_once(self):
        saving, drained = asyncio.Event(), asyncio.Event()
        async def script(*_, **__):
            return deepcopy(self.value)
        store = SharedStore()
        async def save(*_, **__):
            try:
                saving.set()
                await asyncio.Event().wait()
            finally:
                drained.set()
        store.save = AsyncMock(side_effect=save)
        service = self.service(script, store=store)
        result = await asyncio.wait_for(service.get(self.request, refresh=True), 1)
        await asyncio.wait_for(saving.wait(), 1)
        self.assertEqual(result['quotedOutput'], self.value['quotedOutput'])
        self.assertFalse(drained.is_set())
        await service.close()
        self.assertTrue(drained.is_set())
        self.assertFalse(service.background)
        store.save.assert_awaited_once()

    async def test_stream_transport_failure_is_preserved_while_optional_scope_is_held(self):
        entered, drained, search_drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def observe():
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                drained.set()
        async def script(_request, callback, **_):
            try:
                await callback({'type': 'qualified', 'value': self.value})
                await asyncio.Event().wait()
            finally:
                search_drained.set()
        async def publish(_frame):
            await entered.wait()
            raise OSError('consumer transport failed')
        service = self.service(script, observe_scope=observe)
        with self.assertRaisesRegex(OSError, 'consumer transport failed'):
            await asyncio.wait_for(service.progressive(self.request, publish, refresh=True), 1)
        self.assertTrue(search_drained.is_set())
        self.assertFalse(drained.is_set())
        await service.close()
        self.assertTrue(drained.is_set())

    async def test_unobserved_scope_control_failure_is_retrieved_and_active_waiter_still_receives_it(self):
        async def observe():
            raise SearchStopped()
        service = self.service(AsyncMock(), observe_scope=observe)
        loop = asyncio.get_running_loop()
        original, warnings = loop.get_exception_handler(), []
        loop.set_exception_handler(lambda _loop, context: warnings.append(context))
        try:
            async def orphaned_scope():
                return weakref.ref(service.cache_feed(self.request).preparing)
            retired = await orphaned_scope()
            for _ in range(3):
                await asyncio.sleep(0)
            gc.collect()
            self.assertIsNone(retired())
            self.assertEqual(warnings, [])
            active = service.cache_feed(self.request)
            try:
                with self.assertRaises(SearchStopped):
                    await active.lookup()
            finally:
                await active.close()
            self.assertEqual(warnings, [])
        finally:
            loop.set_exception_handler(original)


if __name__ == '__main__':
    unittest.main()
