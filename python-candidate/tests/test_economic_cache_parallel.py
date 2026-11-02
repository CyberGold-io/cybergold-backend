"""Optional SQL inputs/writes cannot hold fresh Helpers qualification hostage."""
import asyncio
from copy import deepcopy
import gc
import unittest
from unittest.mock import AsyncMock
import weakref

from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.quote_budget import QuoteBudget, SearchStopped, budget_context
from cybergold_candidate.quoter.provenance import attach_origins
from cybergold_candidate.recovery_rpc import SnapshotChanged
from test_economic_quote_api import SharedStore
from test_progressive_economic_quotes import economic_request, ScriptedQuoter
from test_universal_quote import Quotes, Engine, BLOCK


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

    async def test_json_and_stream_refresh_start_before_optional_scope_and_return_before_it(self):
        for streamed in (False, True):
            with self.subTest(streamed=streamed):
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
                operation = (service.progressive(self.request, publish, refresh=True) if streamed
                             else service.get(self.request, refresh=True))
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
                    return {'lower': {'quote': deepcopy(self.value)}, 'upper': None}
                store.lookup, store.neighbors = lookup, neighbors
                async def script(_request, **kwargs):
                    seed, nearby = await asyncio.gather(kwargs['seed_lookup'](), kwargs['neighbors']())
                    self.assertIsNone(seed)
                    self.assertEqual(nearby['lower']['quote']['plan'], self.value['plan'])
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
        service.store.neighbors = AsyncMock(return_value={'lower': {'quote': self.value}, 'upper': None})
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
            self.assertEqual((await asyncio.wait_for(two, 1))['lower']['quote'], self.value)
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
