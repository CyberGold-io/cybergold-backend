"""Ready-first publication, bounded topology prefix and private state copies."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.pool_snapshot import copy_pool_bank
from cybergold_candidate.quote_flow import Flow, flow_scope, milestone
from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.route_tools import RouteQuery
from cybergold_candidate.quoter.discovery import seeded_path_steps, paths, route_identity
from cybergold_candidate.quoter.cooperative import values
from cybergold_candidate.route_search import WETH
from cybergold_candidate.routing_encoding import ZERO
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.app import create_app
import json
from test_progressive_economic_quotes import ProgressiveFixture, economic_request
from test_quoter_topology_reuse import pool, A, B, C, D, BLOCK


class ReadyFirstTests(ProgressiveFixture):
    async def test_initial_seed_is_in_supplier_first_candidate_accounting(self):
        rows = [pool(A, B, 10, 'v3'), pool(B, C, 11, 'v3')]
        registry = SimpleNamespace(inventory={row['id']: row for row in rows}, seed=rows[1])
        adapter = CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)
        session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        session._elapsed_ms = lambda: 12.5
        try:
            with bootstrap_scope(session):
                nominations = adapter.nominations(A, C, 100, BLOCK, market=True, first=True)
                first = next(nominations)
                metrics = session.metrics['providers']['cybergold-custom']
                self.assertEqual(first[1], ['cybergold-custom'])
                self.assertEqual(metrics['candidates'], 1)
                self.assertEqual(metrics['firstCandidateMs'], 12.5)
                self.assertEqual(metrics['feedReads'], 0)
                self.assertEqual(session.revision, 0)
                session._elapsed_ms = lambda: 30
                self.assertEqual(list(nominations), [])
                metrics = session.metrics['providers']['cybergold-custom']
                self.assertEqual(metrics['candidates'], 2)
                self.assertEqual(metrics['firstCandidateMs'], 12.5)
                self.assertEqual(metrics['feedReads'], 1)
                self.assertEqual(session.revision, 0)
        finally:
            await session.close()

    async def test_selected_send_disconnect_and_owned_cleanup_have_separate_milestones(self):
        started, disconnected = asyncio.Event(), asyncio.Event()
        now, records = [0.0], []
        async def script(*_args, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                now[0] = 4
        service = self.service(script)
        service.store.memory_lookup = lambda *_args, **_kwargs: deepcopy(self.base)
        app = create_app(economic_quotes=service)
        body = json.dumps(economic_request()).encode()
        sent_request = False
        async def receive():
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                now[0] = 1
                return {'type': 'http.request', 'body': body, 'more_body': False}
            await disconnected.wait()
            now[0] = 3
            return {'type': 'http.disconnect'}
        async def send(message):
            if message['type'] == 'http.response.body' and message.get('body'):
                self.assertEqual(json.loads(message['body'])['type'], 'qualified')
                await started.wait()
                now[0] = 2
                disconnected.set()
        scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                 'http_version': '1.1', 'method': 'POST', 'scheme': 'http', 'path': '/api/economic-quotes/stream',
                 'raw_path': b'/api/economic-quotes/stream', 'query_string': b'', 'headers': [],
                 'server': ('fixture', 80), 'client': ('fixture', 1)}
        with patch('cybergold_candidate.telemetry.Flow', side_effect=lambda *args, **kwargs:
                   Flow(*args, **kwargs, clock=lambda: now[0], sink=records.append)):
            await asyncio.wait_for(app(scope, receive, send), 5)
        marks = next(row for row in records if row['flowKind'] == 'request')['milestonesMs']
        self.assertEqual(marks['publication.first_selected.ready'], 1000)
        self.assertEqual(marks['publication.first_selected.sent'], 2000)
        self.assertEqual(marks['http.disconnect'], 3000)
        self.assertEqual(marks['http.cleanup.finished'], 4000)

    async def test_initial_seed_does_not_cover_a_later_ready_better_topology(self):
        old, seed = pool(A, B, 10, 'v3'), pool(B, C, 11, 'v3')
        registry = SimpleNamespace(inventory={row['id']: row for row in (old, seed)}, seed=seed)
        adapter = CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)
        session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
        try:
            with bootstrap_scope(session):
                initial = adapter.nominations(A, C, 100, BLOCK, market=True, first=True)
                self.assertEqual(next(initial)[0][0]['hops'][0]['pool']['feePips'], 3000)
                initial.close()
                better = pool(A, B, 12, 'v3', fee=100)
                route = [{'pool': better, 'zeroForOne': True}, {'pool': seed, 'zeroForOne': True}]
                session.publish_completed(RouteQuery(A, C, 100, BLOCK), route, ['uniroute-local'])
                async def quick():
                    feed = adapter.nominations(A, C, 100, BLOCK, market=True, first=True)
                    try:
                        first = next(feed)
                        self.assertEqual(first[0][0]['hops'][0]['pool']['feePips'], 100)
                        self.assertIn('uniroute-local', first[1])
                    finally:
                        feed.close()
                await session._arrival_pass(quick, None, session._ready_offers())
        finally:
            await session.close()

    async def test_retained_single_read_does_not_create_a_task_or_await_a_timer(self):
        reads = SharedReads()
        async def produce(_keys):
            return [{'value': 7}]
        await reads.many(['known'], produce, retain=True)
        await asyncio.sleep(0)  # Let the completed producer's bookkeeping drain.
        with patch('asyncio.create_task', side_effect=AssertionError('duplicate task')):
            values, counts = await reads.many(['known'], produce, retain=True)
        self.assertEqual(values, [{'value': 7}])
        self.assertEqual(counts['reused'], 1)
        await reads.close()

    async def test_memory_selection_is_published_before_search_starts(self):
        order = []
        async def script(_request, _callback, **_options):
            order.append('search')
            self.assertEqual(order[0], 'stored')
            return self.value(200)
        service = self.service(script)
        service.store.memory_lookup = lambda *_args, **_kwargs: deepcopy(self.base)
        async def publish(frame):
            if frame['type'] == 'qualified':
                order.append(frame['value']['observation']['source'])
        result = await service.progressive(economic_request(), publish)
        self.assertEqual(order[:2], ['stored', 'search'])
        self.assertEqual(result['quotedOutput'], '200')

    async def test_initial_publication_failure_starts_no_search_and_closes_cache(self):
        async def script(*_args, **_kwargs):
            self.fail('search must not start after delivery has already failed')
        service = self.service(script)
        service.store.memory_lookup = lambda *_args, **_kwargs: deepcopy(self.base)
        async def publish(_frame):
            raise OSError('caller left')
        with self.assertRaisesRegex(OSError, 'caller left'):
            await service.progressive(economic_request(), publish)
        await asyncio.gather(*tuple(service.background))


class InitialTopologyTests(unittest.TestCase):
    def test_short_prefix_matches_ordinary_paths_both_directions_and_native(self):
        rows = [pool(WETH, B, 10), pool(B, C, 11), pool(B, D, 12), pool(D, C, 13)]
        for source, target in [(ZERO, C), (C, ZERO), (WETH, C), (C, WETH), (B, C)]:
            with self.subTest(source=source, target=target):
                prefix = list(values(seeded_path_steps(rows, rows[1], source, target)))
                normal = {route_identity(route) for route in paths(rows, source, target)}
                self.assertTrue(prefix)
                self.assertTrue(all(route_identity(route) in normal for route in prefix))

    def test_first_nomination_does_not_walk_full_graph_and_later_coverage_remains(self):
        rows = [pool(A, B, 10), pool(B, C, 11), pool(A, D, 12), pool(D, C, 13)]
        registry = SimpleNamespace(inventory={row['id']: row for row in rows}, seed=rows[1])
        adapter = CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)
        expected = list(adapter.nominations(A, C, 101, BLOCK, market=True))
        with patch('cybergold_candidate.quoter.custom_routes.path_steps', side_effect=AssertionError('full walk')):
            first = adapter.nominations(A, C, 101, BLOCK, market=True, first=True)
            candidate = next(first)
            self.assertEqual([hop['pool']['id'] for hop in candidate[0][0]['hops']], [rows[0]['id'], rows[1]['id']])
            first.close()
        actual = list(adapter.nominations(A, C, 101, BLOCK, market=True, first=True))
        self.assertEqual({repr(value) for value in actual}, {repr(value) for value in expected})

    def test_hooked_or_absent_anchor_is_not_added_to_prefix(self):
        rows = [pool(A, B, 10), {**pool(B, C, 11), 'hooks': D}]
        self.assertEqual(list(values(seeded_path_steps(rows, rows[1], A, C))), [])
        self.assertEqual(list(values(seeded_path_steps(rows[:1], rows[1], A, C))), [])


class TimingAndCopies(unittest.TestCase):
    def test_milestones_keep_their_first_clock_and_never_change_quote_work(self):
        now = 0
        flow = Flow('quote', clock=lambda: now)
        with flow_scope(flow):
            now = 1
            milestone('publication.first_selected')
            now = 3
            milestone('publication.first_selected')
            milestone('unbounded-name')
            flow.clock = lambda: (_ for _ in ()).throw(ValueError('clock unavailable'))
            milestone('http.disconnect')
        flow.clock = lambda: now
        self.assertEqual(flow.snapshot()['milestonesMs'], {'publication.first_selected': 1000})

    def test_candidate_banks_keep_nested_metadata_and_coverage_private(self):
        original = {'pool': {'ticks': [{'index': 0, 'liquidityNet': '4'}],
            'bitmapWords': [{'wordPosition': 0, 'bitmap': '1'}], 'metadata': {'nested': [1]}}}
        one, two = copy_pool_bank(original), copy_pool_bank(original)
        self.assertEqual(one, deepcopy(original))
        one['pool']['ticks'][0]['liquidityNet'] = '8'
        one['pool']['bitmapWords'].clear()
        one['pool']['metadata']['nested'].append(2)
        self.assertEqual(two, original)


if __name__ == '__main__':
    unittest.main()
