"""Backend-owned quote handoff, private repricing, and whole-tuple selection."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.preview_errors import KnownPreviewError
from cybergold_candidate.progressive_quotes import CanonicalPublication
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.quoter.provenance import attach_origins
from cybergold_candidate.quoter.reuse_estimate import CachedEconomicEstimates
from cybergold_candidate.quoter.reuse_routes import funded_route_identity, neighbor_proposals
from cybergold_candidate.quoter.store import EconomicQuoteStore
from test_progressive_economic_quotes import ScriptedQuoter, economic_request
from test_universal_quote import CORE, PAXG, OTHER, Engine, Quotes, BLOCK, settings


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


class RetainedEconomicRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.quoter = Quotes(Engine())
        self.quoter.engine.registry.ensure_loaded = AsyncMock()
        self.addAsyncCleanup(self.quoter.close)
        self.request = economic_request()
        self.base = await self.quoter.candidate(self.request, 0, 'core-first', BLOCK, [], [])
        self.core = await self.quoter.candidate(self.request, 100, 'core-first', BLOCK,
                                               [PAXG, OTHER], [500000, 500000])
        self.amount = int(self.request['inputs'][0]['amount'])
        self.store = EconomicQuoteStore(settings(), self.quoter.engine.registry)
        self.addAsyncCleanup(self.store.close)

    def value(self, output, label, *, base=None, request=None, proposal=None):
        value = deepcopy(base or self.base)
        if proposal:
            value.update(deepcopy(proposal))
        value['request'] = deepcopy(request or self.request)
        value['quotedOutput'] = str(output)
        value['estimatedRecipientOutputs'][0]['amount'] = str(output)
        value['context']['observedAt'] = label
        value['fees']['coreProtocolFeeCygld'] = str(output % 7)
        for selected in value['plan']['conversions'].values():
            selected['discoveryOrigins'] = [label]
        return attach_origins(value)

    def frame(self, value, *, identity=None, replaces=None):
        return {'type': 'candidate-repriced', 'value': deepcopy(value),
                '_candidateIdentity': identity or funded_route_identity(value),
                **({'_replacesIdentity': replaces} if replaces is not None else {})}

    async def test_book_keeps_independent_winner_and_replaces_same_funded_body_in_both_directions(self):
        frames = []
        async def publish(frame): frames.append(deepcopy(frame))
        publication = CanonicalPublication(None, self.request, publish)
        original = self.value(100, 'old-market')
        other = self.value(90, 'core-fallback', base=self.core)
        publication.queue.put_nowait(('stored', original))
        consumer = asyncio.create_task(publication.run())
        await until(lambda: len(frames) == 1)
        await publication.enqueue(self.frame(other))
        await asyncio.sleep(0)
        self.assertEqual(len(frames), 1, 'an independent weaker quote must not downgrade the selected quote')
        for output, label, expected in ((80, 'down', '90'), (120, 'up', '120'), (120, 'equal-new-context', '120')):
            value = self.value(output, label)
            before = len(frames)
            await publication.enqueue(self.frame(value))
            await until(lambda: len(frames) > before)
            self.assertEqual(frames[-1]['value']['quotedOutput'], expected)
            if expected == '120':
                for field in ('inputs', 'plan', 'context', 'fees', 'routeOrigins'):
                    self.assertEqual(frames[-1]['value'][field], value[field])
        await publication.enqueue(self.frame(None, identity=funded_route_identity(original)))
        await until(lambda: frames[-1]['value']['quotedOutput'] == '90')
        publication.queue.put_nowait(('stored', self.value(999, 'late-sql')))
        publication.queue.put_nowait(('terminal', self.value(999, 'stale-greedy-terminal')))
        publication.queue.put_nowait(None)
        await consumer
        self.assertEqual([frame['value']['quotedOutput'] for frame in frames], ['100', '90', '120', '120', '90'])
        self.assertEqual(publication.best['plan'], other['plan'])
        self.assertFalse(any(frame['type'] == 'candidate-repriced' for frame in frames))

    async def test_backend_l1_is_shared_between_http_clients_before_first_drain_and_sql_finish(self):
        old = self.value(100, 'old-client')
        maximum = {**self.request, 'inputs': [{**self.request['inputs'][0], 'amount': str(self.amount * 2)}]}
        priced, draining, drain_release, sql_release, sql_entered, history_seen = (asyncio.Event() for _ in range(6))
        calls = []
        async def sql_read(*_, **__):
            await sql_release.wait()
            return None
        async def sql_neighbors(*_, **__):
            await sql_release.wait()
            return []
        async def sql_write(*_, **__):
            sql_entered.set(); await sql_release.wait(); return True
        self.store.load_lookup = AsyncMock(side_effect=sql_read)
        self.store.load_neighbors = AsyncMock(side_effect=sql_neighbors)
        self.store.persist = AsyncMock(side_effect=sql_write)
        async def script(request, callback=None, **options):
            calls.append(deepcopy(options.get('route_seeds')))
            if len(calls) == 1:
                await options['on_candidate'](self.frame(old))
                priced.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    draining.set(); await drain_release.wait()
            await history_seen.wait()
            self.assertEqual(calls[-1][0]['inputs'], old['inputs'])
            self.assertEqual(calls[-1][0]['plan'], old['plan'])
            fitting = self.value(105, 'second-fit', request=request)
            await options['on_candidate'](self.frame(fitting))
            expanded = self.value(180, 'second-expanded', request=request,
                proposal=neighbor_proposals(fitting, int(request['inputs'][0]['amount']), [PAXG, OTHER])[-1])
            await options['on_candidate'](self.frame(expanded))
            return old  # The old greedy inner return must not defeat the book.
        service = EconomicQuotes(ScriptedQuoter(script), self.store)
        self.addAsyncCleanup(service.close)
        progressive = service.progressive
        async def observed(request, publish, **options):
            async def deliver(frame):
                await publish(frame)
                if frame['type'] == 'qualified' and frame['value']['observation']['source'] == 'stored':
                    history_seen.set()
            return await progressive(request, deliver, **options)
        service.progressive = observed
        estimates = CachedEconomicEstimates(self.store, CORE)
        app = create_app(economic_quotes=service, trade_quotes=estimates)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://browser-a') as one, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://browser-b') as two:
            first = asyncio.create_task(one.post('/api/economic-quotes/stream', json=self.request))
            try:
                await asyncio.wait_for(asyncio.gather(priced.wait(), sql_entered.wait()), 3)
                first.cancel()
                await asyncio.wait_for(draining.wait(), 3)
                self.assertFalse(first.done())
                estimate = await asyncio.wait_for(two.post('/api/economic-estimates', json={
                    'side': 'buy', 'mode': 'exact-in', 'counterToken': PAXG, 'native': True,
                    'amount': str(self.amount * 2)}), 3)
                self.assertEqual(estimate.status_code, 200, estimate.text)
                self.assertEqual(estimate.json()['estimate']['amount'], '200')
                self.assertFalse(sql_release.is_set())
                second = await asyncio.wait_for(two.post('/api/economic-quotes/stream', json=maximum), 3)
                self.assertEqual(second.status_code, 200, second.text)
                frames = [json.loads(line) for line in second.text.splitlines()]
                qualified = [frame['value'] for frame in frames if frame['type'] == 'qualified']
                self.assertEqual(qualified[0]['inputs'], old['inputs'])
                self.assertEqual(qualified[0]['observation']['source'], 'stored')
                self.assertEqual(frames[-1]['value']['inputs'], maximum['inputs'])
                self.assertEqual(frames[-1]['value']['quotedOutput'], '180')
                self.assertEqual(frames[-1]['value'], qualified[-1])
                self.assertFalse(any(frame['type'] == 'candidate-repriced' for frame in frames))
                self.assertFalse(first.done())
            finally:
                drain_release.set(); sql_release.set()
                await asyncio.gather(first, return_exceptions=True)

    async def test_scalar_json_uses_same_book_instead_of_stale_greedy_return(self):
        old, other, down = self.value(100, 'old'), self.value(90, 'fallback', base=self.core), self.value(80, 'repriced')
        self.store.remember(self.request, old)
        async def script(request, callback=None, **options):
            await options['on_candidate'](self.frame(other))
            await options['on_candidate'](self.frame(down))
            return old
        service = EconomicQuotes(ScriptedQuoter(script), self.store)
        self.addAsyncCleanup(service.close)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app(economic_quotes=service)),
                                     base_url='http://test') as client:
            response = await client.post('/api/economic-quotes', json=self.request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['quotedOutput'], '90')
        self.assertEqual(response.json()['plan'], other['plan'])

    async def test_active_http_clients_share_paid_downward_observations_and_disproof_without_terminal_resurrection(self):
        for output in (80, None):
            with self.subTest(output=output):
                store = EconomicQuoteStore(settings(), self.quoter.engine.registry)
                old, fallback = self.value(100, 'old'), self.value(90, 'fallback', base=self.core)
                later = self.value(95, 'independent-later', proposal=
                    neighbor_proposals(self.base, self.amount // 2, [PAXG, OTHER])[-1])
                started, observed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
                frames, calls = [], []
                async def script(request, callback=None, **options):
                    number = len(calls); calls.append(options)
                    if number == 0:
                        await options['on_candidate'](self.frame(old))
                        await options['on_candidate'](self.frame(fallback))
                        started.set()
                        await observed.wait()
                        await options['on_candidate'](self.frame(later))
                        release.set()
                    else:
                        await options['on_candidate'](self.frame(
                            self.value(output, 'other-client-new-price') if output is not None else None,
                            identity=funded_route_identity(old)))
                        observed.set()
                        await release.wait()
                    terminal = deepcopy(old); terminal['metrics'] = {'late': number}
                    return terminal
                service = EconomicQuotes(ScriptedQuoter(script), store)
                self.addAsyncCleanup(service.close)
                progressive = service.progressive
                async def observed_progressive(request, publish, **options):
                    history = []; frames.append(history)
                    async def delivery(frame):
                        history.append(deepcopy(frame)); await publish(frame)
                    return await progressive(request, delivery, **options)
                service.progressive = observed_progressive
                app = create_app(economic_quotes=service)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://a') as one, \
                        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://b') as two:
                    first = asyncio.create_task(one.post('/api/economic-quotes/stream', json=self.request))
                    await asyncio.wait_for(started.wait(), 3)
                    second = asyncio.create_task(two.post('/api/economic-quotes/stream', json=self.request))
                    responses = await asyncio.wait_for(asyncio.gather(first, second), 3)
                self.assertTrue(all(response.status_code == 200 for response in responses))
                final = [json.loads(response.text.splitlines()[-1]) for response in responses]
                self.assertEqual([frame['value']['quotedOutput'] for frame in final], ['95', '90'])
                self.assertEqual(store.memory_lookup(self.request)['quotedOutput'], '95')
                self.assertTrue(all(frame['value']['quotedOutput'] != '100' for history in frames
                    for frame in history if frame['type'] == 'qualified' and
                    frame['value']['context']['observedAt'] != 'old'))

    async def test_paid_null_empty_book_is_ordinary_no_route_and_late_sql_cannot_restore_it(self):
        old = self.value(100, 'old')
        async def script(request, callback=None, **options):
            await options['on_candidate'](self.frame(old))
            await options['on_candidate'](self.frame(None, identity=funded_route_identity(old)))
            return old
        service = EconomicQuotes(ScriptedQuoter(script), self.store)
        self.addAsyncCleanup(service.close)
        app = create_app(economic_quotes=service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            response = await client.post('/api/economic-quotes', json=self.request)
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()['code'], 'quote-no-route')
            response = await client.post('/api/economic-quotes/stream', json=self.request)
        frames = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(frames[-1]['type'], 'error')
        self.assertEqual(frames[-1]['code'], 'quote-no-route')
        self.assertTrue(any(frame['type'] == 'invalidated' for frame in frames))
        self.assertIsNone(self.store.memory_lookup(self.request))

    async def test_historical_alias_sequence_replaces_whole_tuple_and_notifies_active_books(self):
        old = self.value(100, 'sql-old')
        maximum = {**self.request, 'inputs': [{**self.request['inputs'][0], 'amount': str(self.amount * 2)}]}
        new = self.value(80, 'sql-new', request=maximum)
        async def script(*_, **__): pass
        service = EconomicQuotes(ScriptedQuoter(script), self.store)
        self.addAsyncCleanup(service.close)
        feed = service.cache_feed(self.request)
        self.addAsyncCleanup(feed.close)
        frames = []
        async def publish(frame): frames.append(deepcopy(frame))
        publication = CanonicalPublication(self.quoter, self.request, publish, cache=feed)
        self.store.remember(self.request, old, current=False, sequence=1, row_identity='old:market')
        publication._historical(old)
        publication.queue.put_nowait(('changed', None))
        consumer = asyncio.create_task(publication.run())
        await until(lambda: bool(frames))
        self.store.remember(maximum, new, current=False, sequence=2, row_identity='new:market')
        await until(lambda: frames[-1]['value']['quotedOutput'] == '80')
        publication.queue.put_nowait(('stored', old))
        publication.queue.put_nowait(None); await consumer
        self.assertIsNone(self.store.memory_lookup(self.request))
        self.assertEqual(self.store.memory_neighbors(self.request)[0]['quote'], new)
        self.assertEqual(publication.best['context'], new['context'])
        await publication.enqueue(self.frame(self.value(70, 'paid')))
        self.store.remember(maximum, self.value(999, 'sql-too-late', request=maximum),
                            current=False, sequence=99, row_identity='late:market')
        self.assertEqual(publication.book.winner()['quotedOutput'], '70')

    async def test_independent_snapshot_error_keeps_completed_helpers_tuple_and_error_diagnostics(self):
        from cybergold_candidate.recovery_rpc import SnapshotChanged
        value = self.value(100, 'helpers-completed')
        async def script(request, callback=None, **options):
            await options['on_candidate'](self.frame(value))
            raise SnapshotChanged('independent SDK snapshot error')
        service = EconomicQuotes(ScriptedQuoter(script), self.store)
        self.addAsyncCleanup(service.close)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app(economic_quotes=service)),
                                     base_url='http://test') as client:
            response = await client.post('/api/economic-quotes/stream', json=self.request)
        frames = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual([frame['type'] for frame in frames], ['qualified', 'error'])
        self.assertEqual(frames[0]['value']['context'], value['context'])
        self.assertEqual(self.store.memory_lookup(self.request), value)
        self.assertNotIn('independent SDK snapshot error', response.text)

    async def test_rejected_independent_historical_loser_does_not_retain_orphan_sql_metadata(self):
        best = self.value(100, 'current')
        lower = self.value(90, 'stored-loser', proposal=
            neighbor_proposals(self.base, self.amount // 2, [PAXG, OTHER])[-1])
        self.store.remember(self.request, best)
        self.assertFalse(self.store.remember(self.request, lower, current=False,
                                             sequence=1, row_identity='loser:market'))
        self.assertFalse(self.store.known_rows)
        self.assertEqual(self.store.memory_lookup(self.request), best)

    async def test_identical_paid_callback_does_not_revoke_its_already_pending_writer_version(self):
        async def script(*_, **__): pass
        service = EconomicQuotes(ScriptedQuoter(script), self.store)
        self.addAsyncCleanup(service.close)
        feed = service.cache_feed(self.request)
        self.addAsyncCleanup(feed.close)
        async def publish(_): pass
        publication = CanonicalPublication(self.quoter, self.request, publish, cache=feed)
        value = self.value(100, 'same-completed-observation')
        await publication.enqueue(self.frame(value))
        first = publication.book.versions[funded_route_identity(value)]
        await publication.enqueue(self.frame(value))
        self.assertEqual(publication.book.versions[funded_route_identity(value)], first)
        self.assertEqual(self.store.latest_version(self.store.capture_scope(self.request),
                                                 funded_route_identity(value)), first)

    async def test_http_does_not_accept_browser_seeds_or_expose_private_reprice_events(self):
        options_seen = []
        async def script(request, callback=None, **options):
            options_seen.append(options)
            await options['on_candidate'](self.frame(self.base))
            return self.base
        service = EconomicQuotes(ScriptedQuoter(script), self.store)
        self.addAsyncCleanup(service.close)
        app = create_app(economic_quotes=service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            response = await client.post('/api/economic-quotes/stream', json={**self.request,
                'routeSeeds': [{'inputs': self.base['inputs'], 'plan': self.base['plan'], 'quotedOutput': str(2**255)}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('route_seeds', options_seen[0])
        frames = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(frames[-1]['type'], 'complete')
        self.assertFalse(any(frame['type'] == 'candidate-repriced' for frame in frames))
        self.assertNotIn('_candidateIdentity', response.text)

    async def test_private_quoter_replays_original_and_expands_budget_without_sql_handoff(self):
        fitting = neighbor_proposals(self.base, self.amount // 2, [PAXG, OTHER])[-1]
        historical = self.value(40, 'earlier', proposal=fitting)
        self.store.remember(self.request, historical)
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        self.quoter.route_provider_factory = lambda: []
        async def candidate(request, *_args, selected=None, **_):
            if selected is None:
                await asyncio.Event().wait()
            calls.append(deepcopy(request['inputs']))
            if len(calls) == 2: started.set()
            try:
                await release.wait()
            finally:
                pass
            return self.value(100, 'paid', request=request,
                              proposal={'inputs': request['inputs'], 'plan': selected})
        self.quoter.candidate = candidate
        held = asyncio.Event()
        async def observe_scope(): await held.wait()
        service = EconomicQuotes(self.quoter, self.store, observe_scope=observe_scope)
        self.addAsyncCleanup(service.close)
        task = asyncio.create_task(service.get(self.request))
        try:
            await asyncio.wait_for(started.wait(), 3)
            self.assertEqual({int(row[0]['amount']) for row in calls}, {self.amount // 2, self.amount})
            self.assertFalse(held.is_set())
        finally:
            task.cancel(); release.set(); held.set()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
