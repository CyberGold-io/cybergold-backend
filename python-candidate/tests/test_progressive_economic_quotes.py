"""Ready publication, owned cancellation and actual incremental ASGI transport."""
import asyncio
from copy import deepcopy
import json
import io
import logging
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.telemetry import configure_logging, getter_reads, rpc_exchange
from cybergold_candidate.tx_preparation import TransactionPreparation
from test_economic_quote_api import SharedStore
from test_universal_quote import Quotes, Engine, request, PAXG, OTHER, CORE, USER


def economic_request(intent=0):
    value = {key: request(intent)[key] for key in ('intent', 'inputs', 'outputCurrency')}
    if intent == 2:
        value['inputs'] = [{'currency': PAXG, 'amount': '100'}, {'currency': OTHER, 'amount': '100'}]
    return value


class ScriptedQuoter:
    def __init__(self, script, canonical=None):
        self.script, self.canonical = script, canonical
        self.canonical_calls = []
        self.engine = SimpleNamespace(registry=SimpleNamespace(ensure_loaded=AsyncMock(), get_rpc=lambda: self))
    async def quote(self, *args, **kwargs):
        return await self.script(*args, **kwargs)
    async def assert_canonical(self, block):
        self.canonical_calls.append(deepcopy(block))
        if self.canonical:
            await self.canonical(block)


class ProgressiveFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.base = await Quotes(Engine()).quote(economic_request())

    def value(self, output, **changes):
        return {**deepcopy(self.base), 'quotedOutput': str(output), **changes}

    def service(self, script, canonical=None, store=None):
        return EconomicQuotes(ScriptedQuoter(script, canonical), store or SharedStore())


class ProgressiveTests(ProgressiveFixture):
    async def test_first_ready_does_not_wait_for_search_and_tuples_improve_atomically(self):
        release, ready, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
        first, better = self.value(100), self.value(200)
        better['fees']['marketFeeCygld'] = '12'
        better['plan']['body']['marker'] = 'better'
        async def script(value, callback, **_):
            try:
                await callback({'type': 'qualified', 'value': first})
                await release.wait()
                await callback({'type': 'qualified', 'value': better})
                await callback({'type': 'qualified', 'value': self.value(90)})
                return better
            finally:
                drained.set()
        frames = []
        async def publish(frame):
            frames.append(deepcopy(frame)); ready.set()
        service = self.service(script)
        task = asyncio.create_task(service.progressive(economic_request(), publish))
        await asyncio.wait_for(ready.wait(), 1)
        self.assertFalse(task.done())
        self.assertEqual(frames[0]['value']['quotedOutput'], '100')
        release.set(); result = await asyncio.wait_for(task, 1)
        self.assertTrue(drained.is_set())
        self.assertEqual([f['value']['quotedOutput'] for f in frames], ['100', '200'])
        self.assertEqual(result['fees']['marketFeeCygld'], '12')
        self.assertEqual(result['plan']['body']['marker'], 'better')
        self.assertIn('reuseSample', result)
        self.assertEqual((await service.store.lookup(economic_request(), scope=str(economic_request())))['quotedOutput'], '200')

    async def test_candidate_callback_does_not_wait_for_canonical_or_transport(self):
        canonical_started, release_canonical, search_done = (asyncio.Event() for _ in range(3))
        async def canonical(_):
            canonical_started.set(); await release_canonical.wait()
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            search_done.set()
            await canonical_started.wait()
            return self.value(200)
        frames = []
        service = self.service(script, canonical)
        task = asyncio.create_task(service.progressive(economic_request(), lambda frame: asyncio.sleep(0, result=frames.append(frame))))
        await asyncio.wait_for(canonical_started.wait(), 1)
        self.assertTrue(search_done.is_set())
        self.assertFalse(frames)
        release_canonical.set()
        result = await task
        self.assertEqual(result['quotedOutput'], '200')
        # Only the queued intermediate needed a publication assertion; the
        # normal terminal producer result already has its own canonical check.
        self.assertEqual(len(service.quoter.canonical_calls), 1)

    async def test_serial_confirmation_cannot_publish_a_worse_older_tuple(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def canonical(_):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set(); await release.wait()
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            await started.wait()
            await callback({'type': 'qualified', 'value': self.value(300)})
            await callback({'type': 'qualified', 'value': self.value(200)})
            release.set()
            return self.value(250)
        frames = []
        service = self.service(script, canonical)
        result = await service.progressive(economic_request(), lambda frame: asyncio.sleep(0, result=frames.append(frame)))
        self.assertEqual([f['value']['quotedOutput'] for f in frames], ['100', '300'])
        self.assertEqual(result['quotedOutput'], '300')

    async def test_provider_failure_leaves_candidate_unconfirmed_and_terminal_continues(self):
        attempted = asyncio.Event()
        async def canonical(_):
            attempted.set(); raise QuoteFailure('rpc-unavailable')
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            await attempted.wait()
            return self.value(200)
        frames = []
        service = self.service(script, canonical)
        result = await service.progressive(economic_request(), lambda frame: asyncio.sleep(0, result=frames.append(frame)))
        self.assertEqual([f['value']['quotedOutput'] for f in frames], ['200'])
        self.assertEqual(result['quotedOutput'], '200')

    async def test_disproof_in_publisher_cancels_search_and_prevents_save(self):
        drained = asyncio.Event()
        async def canonical(_):
            raise SnapshotChanged('existing disproof')
        async def script(value, callback, **_):
            try:
                await callback({'type': 'qualified', 'value': self.value(100)})
                await asyncio.Event().wait()
            finally:
                drained.set()
        store = SharedStore(); store.save = AsyncMock(wraps=store.save)
        service = self.service(script, canonical, store)
        with self.assertRaises(SnapshotChanged) as failure:
            await asyncio.wait_for(service.progressive(economic_request(), AsyncMock()), 1)
        self.assertEqual(failure.exception.economic_context, self.base['context'])
        self.assertTrue(drained.is_set())
        store.save.assert_not_called()

    async def test_racing_terminal_does_not_outrun_publisher_disproof(self):
        checking, release = asyncio.Event(), asyncio.Event()
        async def canonical(_):
            checking.set(); await release.wait(); raise SnapshotChanged('late canonical disproof')
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            await checking.wait(); release.set()
            return self.value(200)
        store = SharedStore(); store.save = AsyncMock(wraps=store.save)
        with self.assertRaises(SnapshotChanged):
            await self.service(script, canonical, store).progressive(economic_request(), AsyncMock())
        store.save.assert_not_called()

    async def test_stop_drains_search_then_saves_the_confirmed_snapshot_once(self):
        ready, search_drained = asyncio.Event(), asyncio.Event()
        async def script(value, callback, **_):
            try:
                await callback({'type': 'qualified', 'value': self.value(100)})
                await asyncio.Event().wait()
            finally:
                search_drained.set()
        store = SharedStore(); saving = store.save
        async def save(*args, **kwargs):
            self.assertTrue(search_drained.is_set())
            await asyncio.sleep(.01)
            return await saving(*args, **kwargs)
        store.save = AsyncMock(side_effect=save)
        service = self.service(script, store=store)
        task = asyncio.create_task(service.progressive(economic_request(), lambda frame: asyncio.sleep(0, result=ready.set())))
        await asyncio.wait_for(ready.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        store.save.assert_awaited_once()
        self.assertEqual(next(iter(store.rows.values()))['quotedOutput'], '100')

    async def test_disproof_during_cancel_drain_prevents_persisting_older_incumbent(self):
        ready = asyncio.Event()
        async def script(value, callback, **_):
            try:
                await callback({'type': 'qualified', 'value': self.value(100)})
                await asyncio.Event().wait()
            finally:
                raise SnapshotChanged('disproof observed while draining producer')
        store = SharedStore(); store.save = AsyncMock(wraps=store.save)
        task = asyncio.create_task(self.service(script, store=store).progressive(economic_request(),
            lambda frame: asyncio.sleep(0, result=ready.set())))
        await ready.wait(); task.cancel()
        with self.assertRaises(SnapshotChanged): await task
        store.save.assert_not_called()

    async def test_publisher_disproof_while_draining_also_prevents_save(self):
        ready, checking = asyncio.Event(), asyncio.Event()
        calls = 0
        async def canonical(_):
            nonlocal calls
            calls += 1
            if calls == 2:
                try:
                    checking.set(); await asyncio.Event().wait()
                finally:
                    raise SnapshotChanged('publisher disproof during cancellation')
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            await ready.wait()
            await callback({'type': 'qualified', 'value': self.value(200)})
            await asyncio.Event().wait()
        store = SharedStore(); store.save = AsyncMock(wraps=store.save)
        task = asyncio.create_task(self.service(script, canonical, store).progressive(economic_request(),
            lambda frame: asyncio.sleep(0, result=ready.set())))
        await checking.wait(); task.cancel()
        with self.assertRaises(SnapshotChanged): await task
        store.save.assert_not_called()

    async def test_cancel_during_optional_save_drains_that_write_without_retry(self):
        saving, drained = asyncio.Event(), asyncio.Event()
        async def script(*_, **__): return self.value(100)
        async def save(*_, **__):
            try:
                saving.set(); await asyncio.Event().wait()
            finally:
                drained.set()
        store = SharedStore(); store.save = AsyncMock(side_effect=save)
        task = asyncio.create_task(self.service(script, store=store).progressive(economic_request(), AsyncMock()))
        await saving.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(drained.is_set()); store.save.assert_awaited_once()

    async def test_stop_before_confirmation_does_not_save_or_publish(self):
        checking, canonical_drained, search_drained = (asyncio.Event() for _ in range(3))
        async def canonical(_):
            try:
                checking.set(); await asyncio.Event().wait()
            finally: canonical_drained.set()
        async def script(value, callback, **_):
            try:
                await callback({'type': 'qualified', 'value': self.value(100)})
                await asyncio.Event().wait()
            finally: search_drained.set()
        store = SharedStore(); store.save = AsyncMock(wraps=store.save); publish = AsyncMock()
        task = asyncio.create_task(self.service(script, canonical, store).progressive(economic_request(), publish))
        await checking.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(canonical_drained.is_set() and search_drained.is_set())
        publish.assert_not_called(); store.save.assert_not_called()

    async def test_ordinary_refinement_failure_preserves_and_saves_ready_quote(self):
        ready = asyncio.Event()
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            await ready.wait()
            raise QuoteFailure('rpc-rate-limit')
        store = SharedStore(); store.save = AsyncMock(wraps=store.save)
        service = self.service(script, store=store)
        with self.assertRaises(QuoteFailure) as failure:
            await service.progressive(economic_request(), lambda frame: asyncio.sleep(0, result=ready.set()))
        self.assertEqual(failure.exception.code, 'rpc-rate-limit')
        store.save.assert_awaited_once()
        self.assertEqual(next(iter(store.rows.values()))['quotedOutput'], '100')

    async def test_optional_write_error_cannot_retract_ready_quote(self):
        async def script(*_, **__): return self.value(100)
        store = SharedStore(); store.save = AsyncMock(side_effect=RuntimeError('private SQL failure'))
        frames = []
        result = await self.service(script, store=store).progressive(economic_request(),
            lambda frame: asyncio.sleep(0, result=frames.append(frame)))
        self.assertEqual(result['quotedOutput'], '100'); self.assertEqual(len(frames), 1)

    async def test_historical_hit_needs_no_new_head_or_confirmation(self):
        store = SharedStore()
        await store.save(economic_request(), self.base, scope=str(economic_request()))
        service = self.service(AsyncMock(side_effect=AssertionError('no search')), store=store)
        service.quoter.canonical = AsyncMock(side_effect=AssertionError('no new canonical check'))
        frames = []
        result = await service.progressive(economic_request(), lambda frame: asyncio.sleep(0, result=frames.append(frame)))
        self.assertEqual(result['observation']['source'], 'stored')
        self.assertEqual(result['context'], self.base['context']); self.assertEqual(len(frames), 1)
        self.assertEqual(service.quoter.canonical_calls, [])

    async def test_failed_explicit_refresh_keeps_the_previous_historical_observation(self):
        store = SharedStore()
        await store.save(economic_request(), self.base, scope=str(economic_request()))
        async def script(*_, **__): raise QuoteFailure('quote-no-route')
        service = self.service(script, store=store); publish = AsyncMock()
        with self.assertRaises(QuoteFailure):
            await service.progressive(economic_request(), publish, refresh=True)
        publish.assert_not_called()
        self.assertEqual(next(iter(store.rows.values())), self.base)

    async def test_real_quoter_all_four_intents_and_unsigned_preparation(self):
        for intent in range(4):
            with self.subTest(intent):
                quoter = Quotes(Engine()); quoter.engine.registry.ensure_loaded = AsyncMock()
                service = EconomicQuotes(quoter, SharedStore()); frames = []
                value = await service.progressive(economic_request(intent),
                    lambda frame: asyncio.sleep(0, result=frames.append(deepcopy(frame))))
                self.assertTrue(frames)
                self.assertEqual(value['request']['intent'], intent)
                self.assertEqual(value['observation']['source'], 'search')
                prepared = await TransactionPreparation(quoter, now=lambda: 2000).prepare({
                    'quote': value, 'sender': USER, 'recipient': USER, 'slippageBps': 100})
                self.assertEqual(prepared['economicQuote']['inputs'], value['inputs'])
                self.assertEqual(quoter.engine.semaphore._value, 8)

    async def test_cancelled_subscriber_keeps_another_shared_read_alive(self):
        bank = SharedReads(); entered, release, ready = (asyncio.Event() for _ in range(3))
        async def read(): entered.set(); await release.wait(); return 7
        survivor = asyncio.create_task(bank.one('same', read)); await entered.wait()
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            return await bank.one('same', read)
        service = self.service(script)
        task = asyncio.create_task(service.progressive(economic_request(), lambda frame: asyncio.sleep(0, result=ready.set())))
        await ready.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(survivor.done())
        release.set(); self.assertEqual(await survivor, 7); await bank.close()


class StreamTransportTests(ProgressiveFixture):
    async def asgi_stream(self, service, *, spec='2.4', refresh=False):
        inbox = asyncio.Queue(); frames, headers = [], {}
        ready, terminal = asyncio.Event(), asyncio.Event()
        body = json.dumps({**economic_request(), 'refresh': refresh}).encode()
        inbox.put_nowait({'type': 'http.request', 'body': body, 'more_body': False})
        async def receive(): return await inbox.get()
        async def send(message):
            if message['type'] == 'http.response.start': headers.update(dict(message['headers']))
            if message['type'] == 'http.response.body' and message.get('body'):
                for line in message['body'].splitlines():
                    frame = json.loads(line); frames.append(frame)
                    if frame['type'] == 'qualified': ready.set()
                    if frame['type'] in ('complete', 'error'): terminal.set()
        app = create_app(economic_quotes=service)
        self.stream_app = app
        scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': spec},
            'http_version': '1.1', 'method': 'POST', 'scheme': 'http', 'path': '/api/economic-quotes/stream',
            'raw_path': b'/api/economic-quotes/stream', 'query_string': b'', 'root_path': '',
            'headers': [(b'content-type', b'application/json')], 'server': ('test', 80), 'client': ('127.0.0.1', 1)}
        task = asyncio.create_task(app(scope, receive, send))
        self.addAsyncCleanup(self.drain, task)
        return task, inbox, frames, headers, ready, terminal

    async def drain(self, task):
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_asgi_23_and_24_stream_ready_before_complete_and_disconnect_drains(self):
        for spec in ('2.3', '2.4'):
            with self.subTest(spec):
                drained = asyncio.Event()
                async def script(value, callback, **_):
                    try:
                        await callback({'type': 'qualified', 'value': self.value(100)})
                        await asyncio.Event().wait()
                    finally: drained.set()
                service = self.service(script)
                task, inbox, frames, headers, ready, terminal = await self.asgi_stream(service, spec=spec)
                await asyncio.wait_for(ready.wait(), 1)
                self.assertFalse(task.done() or terminal.is_set())
                self.assertEqual(headers[b'x-accel-buffering'], b'no')
                self.assertTrue(headers[b'content-type'].startswith(b'application/x-ndjson'))
                self.assertEqual(headers[b'cache-control'], b'no-store')
                inbox.put_nowait({'type': 'http.disconnect'})
                await asyncio.wait_for(task, 1)
                self.assertTrue(drained.is_set())
                self.assertEqual([frame['type'] for frame in frames], ['qualified'])
                self.assertEqual(next(iter(service.store.rows.values()))['quotedOutput'], '100')

    async def test_stream_exactly_one_complete_and_full_terminal_improvement(self):
        ready = asyncio.Event()
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            await ready.wait()
            return self.value(200)
        service = self.service(script)
        task, _, frames, _, published, terminal = await self.asgi_stream(service)
        await published.wait(); ready.set(); await asyncio.wait_for(task, 1)
        self.assertEqual([frame['type'] for frame in frames], ['qualified', 'qualified', 'complete'])
        self.assertTrue(terminal.is_set())
        self.assertEqual(frames[-1]['value']['quotedOutput'], '200')
        self.assertTrue(all('requestId' in frame for frame in frames))

    async def test_stream_disproof_invalidates_then_ends_with_one_safe_error(self):
        ready = asyncio.Event()
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            await ready.wait(); raise SnapshotChanged('private context text')
        service = self.service(script)
        task, _, frames, _, published, _ = await self.asgi_stream(service)
        await published.wait(); ready.set(); await asyncio.wait_for(task, 1)
        self.assertEqual([frame['type'] for frame in frames], ['qualified', 'invalidated', 'error'])
        self.assertEqual(frames[-2]['context'], self.base['context'])
        self.assertNotIn('private context text', json.dumps(frames))
        self.assertFalse(service.store.rows)
        stages = [sample for family in self.stream_app.state.metrics.quote_stages.collect()
                  for sample in family.samples if sample.name.endswith('_total')]
        self.assertEqual({sample.labels['strategy'] for sample in stages
                          if sample.labels['stage'] in ('invalidated', 'error')}, {'universal'})

    async def test_ordinary_error_after_ready_preserves_incumbent_and_exact_failure_code(self):
        release = asyncio.Event()
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            await release.wait(); raise QuoteFailure('rpc-rate-limit')
        service = self.service(script)
        task, _, frames, _, ready, _ = await self.asgi_stream(service)
        await ready.wait(); release.set(); await asyncio.wait_for(task, 1)
        self.assertEqual([frame['type'] for frame in frames], ['qualified', 'error'])
        self.assertEqual(frames[-1]['code'], 'rpc-rate-limit')
        self.assertTrue(service.store.rows)

    async def test_before_ready_error_and_invalid_input_preserve_identified_errors(self):
        async def script(*_, **__): raise QuoteFailure('quote-no-route')
        service = self.service(script)
        task, _, frames, _, _, _ = await self.asgi_stream(service)
        await asyncio.wait_for(task, 1)
        self.assertEqual([frame['type'] for frame in frames], ['error'])
        self.assertEqual(frames[0]['code'], 'quote-no-route')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app(economic_quotes=service)), base_url='http://test') as client:
            response = await client.post('/api/economic-quotes/stream', json={**economic_request(), 'refresh': 'no'})
        self.assertEqual(response.status_code, 400)

    async def test_stream_outcomes_retain_existing_economic_classification_and_rpc_counts(self):
        logger = logging.getLogger('cybergold.candidate')
        previous = (list(logger.handlers), logger.level, logger.propagate)
        stream = io.StringIO()
        configure_logging(stream)
        try:
            for outcome in ('succeeded', 'cancelled', 'stored', 'refresh'):
                with self.subTest(outcome):
                    async def script(value, callback, **_):
                        getter_reads({'requested': 3, 'issued': 2, 'coalesced': 1, 'reused': 0})
                        with rpc_exchange(2):
                            await asyncio.sleep(0)
                        await callback({'type': 'qualified', 'value': self.value(100)})
                        if outcome == 'cancelled':
                            await asyncio.Event().wait()
                        return self.value(100)
                    service = self.service(script)
                    if outcome == 'stored':
                        await service.store.save(economic_request(), self.base, scope=str(economic_request()))
                    task, inbox, _, _, ready, _ = await self.asgi_stream(service, refresh=outcome == 'refresh')
                    await asyncio.wait_for(ready.wait(), 1)
                    if outcome == 'cancelled':
                        inbox.put_nowait({'type': 'http.disconnect'})
                    await asyncio.wait_for(task, 1)
                    rows = [row for row in map(json.loads, stream.getvalue().splitlines())
                            if row.get('event') == 'quote_outcome']
                    row = rows[-1]
                    self.assertEqual(row['operation'], '/api/economic-quotes/stream')
                    self.assertEqual(row['operationKind'], 'quoter')
                    self.assertEqual(row['outcome'], 'cancelled' if outcome == 'cancelled' else 'succeeded')
                    self.assertEqual(row['resultSource'], 'stored-quote' if outcome == 'stored'
                                     else 'refresh' if outcome == 'refresh' else 'search')
                    self.assertEqual(row['operationPhase'], 'lookup' if outcome == 'stored' else 'current-state-search')
                    expected = (0, 0, 0, 0) if outcome == 'stored' else (3, 2, 1, 0)
                    self.assertEqual(tuple(row['rpc']['getterReads'][key]
                        for key in ('requested', 'issued', 'coalesced', 'reused')), expected)
                    self.assertEqual(row['rpc']['transport']['started'], int(outcome != 'stored'))
                    self.assertEqual(row['rpc']['transport']['completed'], int(outcome != 'stored'))
                    self.assertEqual(row['rpc']['transport']['rpcCallsStarted'], 0 if outcome == 'stored' else 2)
                    self.assertTrue(row['requestId'])
            self.assertEqual(len(rows), 4)
        finally:
            logger.handlers, logger.level, logger.propagate = previous

    async def test_pre_ready_failure_cancel_and_disproof_retain_complete_outcome_evidence(self):
        logger = logging.getLogger('cybergold.candidate')
        previous = (list(logger.handlers), logger.level, logger.propagate)
        stream = io.StringIO()
        configure_logging(stream)
        try:
            for scenario in ('pre-ready-failure', 'pre-ready-cancel', 'disproof'):
                with self.subTest(scenario):
                    entered, release = asyncio.Event(), asyncio.Event()
                    async def script(value, callback, **_):
                        getter_reads({'requested': 3, 'issued': 2, 'coalesced': 1, 'reused': 0})
                        with rpc_exchange(2):
                            await asyncio.sleep(0)
                        entered.set()
                        if scenario == 'pre-ready-failure':
                            error = QuoteFailure('quote-no-route')
                            error.quoter_metrics = {'totalMs': 5028.494, 'searchMs': 5000.69,
                                'finalizationMs': 27.804, 'selectionReason': 'best-initial'}
                            raise error
                        if scenario == 'pre-ready-cancel':
                            await asyncio.Event().wait()
                        await callback({'type': 'qualified', 'value': self.value(100)})
                        await release.wait()
                        raise SnapshotChanged('private disproof detail')
                    service = self.service(script)
                    task, inbox, frames, _, ready, _ = await self.asgi_stream(service)
                    await asyncio.wait_for(entered.wait(), 1)
                    if scenario == 'pre-ready-cancel':
                        inbox.put_nowait({'type': 'http.disconnect'})
                    if scenario == 'disproof':
                        await asyncio.wait_for(ready.wait(), 1)
                        release.set()
                    await asyncio.wait_for(task, 1)
                    rows = [row for row in map(json.loads, stream.getvalue().splitlines())
                            if row.get('event') == 'quote_outcome']
                    self.assertEqual(len(rows), ('pre-ready-failure', 'pre-ready-cancel', 'disproof').index(scenario)+1)
                    row = rows[-1]
                    self.assertEqual(row['operation'], '/api/economic-quotes/stream')
                    self.assertEqual(row['operationKind'], 'quoter')
                    self.assertEqual(row['resultSource'], 'search')
                    self.assertEqual(row['operationPhase'], 'current-state-search')
                    self.assertEqual(row['outcome'], 'cancelled' if scenario == 'pre-ready-cancel' else 'failed')
                    self.assertEqual(row['inputBudget'], economic_request()['inputs'])
                    self.assertEqual(row['rpc']['getterReads']['requested'], 3)
                    self.assertEqual(row['rpc']['transport']['rpcCallsStarted'], 2)
                    self.assertEqual(row['rpc']['transport']['completed'], 1)
                    self.assertNotIn('funding', row)
                    self.assertFalse(service.store.rows)
                    self.assertNotIn('private disproof detail', json.dumps(frames))
                    if scenario == 'pre-ready-failure':
                        self.assertEqual(row['producerMetrics'], {'totalMs': 5028.494, 'searchMs': 5000.69,
                            'finalizationMs': 27.804, 'selectionReason': 'best-initial'})
                    if scenario != 'pre-ready-cancel':
                        self.assertEqual(frames[-1]['type'], 'error')
                    if scenario == 'disproof':
                        self.assertEqual(frames[-2]['type'], 'invalidated')
        finally:
            logger.handlers, logger.level, logger.propagate = previous


if __name__ == '__main__':
    unittest.main()
