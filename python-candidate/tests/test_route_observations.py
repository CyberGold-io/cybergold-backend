"""Physical RPC/API work counts and closed source evidence projection."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import ClientResponseError, web
import httpx

from cybergold_candidate.quoter.hosted_routes import HostedRouteError, UniswapApiProvider
from cybergold_candidate.uniswap_api_queue import UniswapApiQueue
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.route_tools import PendingRouteTool
from cybergold_candidate.route_observations import (
    RouteObservations, api_exchange, origin_scope, route_observation_scope)
from cybergold_candidate.rpc_transport import rpc_provider
from cybergold_candidate.trade_observation import economic_evidence


HASH = '0x' + 'a' * 64
PINNED = [{'to': '0x' + '1' * 40, 'data': '0x1234'}, {'blockHash': HASH, 'requireCanonical': True}]


class PhysicalTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()
        self.status = 200
        async def receive(request):
            body = await request.json()
            self.requests.append(body)
            self.entered.set()
            await self.release.wait()
            if self.status != 200:
                return web.Response(status=self.status, text='private provider failure detail')
            def result(row):
                return {'jsonrpc': '2.0', 'id': row['id'], 'result': '0x01'}
            return web.json_response([result(row) for row in body] if isinstance(body, list) else result(body))
        app = web.Application()
        app.router.add_post('/', receive)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.provider = rpc_provider(f'http://127.0.0.1:{port}/', 'Bearer private-fixture')

    async def asyncTearDown(self):
        self.release.set()
        await self.provider.disconnect()
        await self.runner.cleanup()

    async def test_coalesced_read_counts_one_post_for_first_issuing_owner_only(self):
        self.release.clear()
        first, second = RouteObservations(), RouteObservations()
        with route_observation_scope(first):
            left = asyncio.create_task(self.provider.make_request('eth_call', deepcopy(PINNED)))
        await asyncio.wait_for(self.entered.wait(), 1)
        with route_observation_scope(second), origin_scope('uniswap-alpharouter'):
            right = asyncio.create_task(self.provider.make_request('eth_call', deepcopy(PINNED)))
        async with asyncio.timeout(1):
            while next(iter(self.provider.reads.pending.values())).users != 2:
                await asyncio.sleep(0)
        self.assertEqual(first.metrics['requests'], 1)
        self.assertEqual(first.metrics['inFlight'], 1)
        self.assertEqual(second.metrics['requests'], 0)
        self.release.set()
        await asyncio.gather(left, right)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(first.metrics['jsonRpcMembers'], 1)
        self.assertEqual(first.metrics['methods'], {'eth_call': 1})
        self.assertEqual(first.metrics['origins']['cybergold-quoter']['requests'], 1)
        self.assertNotIn('cybergold-custom', first.metrics['origins'])
        self.assertEqual(first.metrics['completed'], 1)
        self.assertEqual(second.metrics['origins'], {})

    async def test_batch_bypassing_single_request_path_counts_one_envelope_two_members(self):
        recorder = RouteObservations()
        with route_observation_scope(recorder), origin_scope('uniswap-alpharouter'):
            result = await self.provider.make_batch_request([
                ('eth_chainId', []), ('eth_getBlockByNumber', ['latest', False])])
        self.assertEqual(len(result), 2)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(recorder.metrics['requests'], 1)
        self.assertEqual(recorder.metrics['jsonRpcMembers'], 2)
        self.assertEqual(recorder.metrics['batchRequests'], 1)
        self.assertEqual(recorder.metrics['batchMembers'], 2)
        self.assertEqual(recorder.metrics['methods'], {'eth_chainId': 1, 'eth_getBlockByNumber': 1})
        self.assertEqual(recorder.metrics['origins']['uniswap-alpharouter']['batchMembers'], 2)

    async def test_concurrent_independent_recorders_preserve_method_and_origin_counts(self):
        one, two = RouteObservations(), RouteObservations()
        with route_observation_scope(one):
            first = asyncio.create_task(self.provider.make_request('eth_chainId', []))
        with route_observation_scope(two), origin_scope('uniswap-guidestar'):
            second = asyncio.create_task(self.provider.make_request('eth_getCode', [PINNED[0]['to'], 'latest']))
        await asyncio.gather(first, second)
        self.assertEqual((one.metrics['requests'], two.metrics['requests']), (1, 1))
        self.assertEqual(one.metrics['methods'], {'eth_chainId': 1})
        self.assertEqual(two.metrics['methods'], {'eth_getCode': 1})
        self.assertEqual(set(one.metrics['origins']), {'cybergold-quoter'})
        self.assertEqual(set(two.metrics['origins']), {'uniswap-guidestar'})

    async def test_external_only_factory_keeps_common_replay_reads_on_quoter_origin(self):
        provider, recorder = self.provider, RouteObservations()
        class External:
            name = 'uniswap-alpharouter'
            async def discover(self, *_):
                await provider.make_request('eth_getCode', [PINNED[0]['to'], 'latest'])
                return []
        session = RouteBootstrap([PendingRouteTool(External())])
        async def ordinary():
            session.offers('source', 'target', 100, {'number': 1, 'hash': HASH})
            await provider.make_request('eth_call', deepcopy(PINNED))
        async def reevaluate():
            self.fail('The external source returned no nominations')
        with route_observation_scope(recorder), bootstrap_scope(session):
            await session.run(ordinary(), reevaluate)
        self.assertEqual(recorder.metrics['requests'], 2)
        self.assertEqual(recorder.metrics['origins']['cybergold-quoter']['requests'], 1)
        self.assertEqual(recorder.metrics['origins']['uniswap-alpharouter']['requests'], 1)
        self.assertNotIn('cybergold-custom', recorder.metrics['origins'])
        projected = economic_evidence({'metrics': {'routeDiscovery': {'physicalRpc': recorder.metrics}}},
                                     {'operationKind': 'quoter', 'resultSource': 'search'})
        origins = projected['producerMetrics']['routeDiscovery']['physicalRpc']['origins']
        self.assertEqual(set(origins), {'cybergold-quoter', 'uniswap-alpharouter'})

    async def test_http_failure_and_inflight_cancellation_are_counted_attempts(self):
        failed, cancelled = RouteObservations(), RouteObservations()
        self.status = 503
        with route_observation_scope(failed):
            with self.assertRaises(ClientResponseError):
                await self.provider.make_request('eth_chainId', [])
        self.assertEqual((failed.metrics['requests'], failed.metrics['errors']), (1, 1))
        self.status = 200
        self.entered.clear()
        self.release.clear()
        with route_observation_scope(cancelled):
            task = asyncio.create_task(self.provider.make_request('eth_chainId', []))
        await asyncio.wait_for(self.entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((cancelled.metrics['requests'], cancelled.metrics['cancelled']), (1, 1))
        self.assertEqual(cancelled.metrics['inFlight'], 0)
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn('private', json.dumps(failed.metrics))

    async def test_cancellation_while_acquiring_cached_session_is_not_a_post_attempt(self):
        entered = asyncio.Event()
        async def blocked(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        recorder = RouteObservations()
        with patch.object(self.provider._request_session_manager, 'async_cache_and_return_session', blocked):
            with route_observation_scope(recorder):
                task = asyncio.create_task(self.provider.make_request('eth_chainId', []))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(recorder.metrics['requests'], 0)
        self.assertEqual(self.requests, [])


class ObservationProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_hosted_http_count_is_separate_from_rpc_and_has_actual_provider_origin(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(404, json={'error': 'private API detail'})
        config = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS='0x'+'1'*40,
            CYBERGOLD_UNISWAP_API_KEY='private-api-credential')
        engine = SimpleNamespace(registry=SimpleNamespace(chain=1), uniswap_api_queue=UniswapApiQueue())
        provider = UniswapApiProvider(engine, config, guidestar=True,
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=None))
        recorder = RouteObservations()
        with route_observation_scope(recorder):
            with self.assertRaises(HostedRouteError):
                await provider.discover('0x'+'1'*40, '0x'+'2'*40, 100, {'number': 1, 'hash': HASH})
        self.assertEqual(recorder.metrics['requests'], 0)
        self.assertEqual((recorder.api_metrics['requests'], recorder.api_metrics['errors']), (1, 1))
        self.assertEqual(recorder.api_metrics['httpStatuses'], {'404': 1})
        self.assertEqual(set(recorder.api_metrics['origins']), {'uniswap-guidestar'})
        self.assertEqual(len(requests), 1)
        self.assertNotIn('private', json.dumps(recorder.api_metrics))
        await provider.close()

    def test_counter_ignores_parameters_private_method_names_and_unknown_origin_names(self):
        recorder = RouteObservations()
        with route_observation_scope(recorder), origin_scope('private account identifier'):
            with recorder.record_http(json.dumps([
                    {'method': 'eth_call', 'params': ['private params']},
                    {'method': 'private-method', 'params': ['private body']}])):
                pass
            with api_exchange():
                pass
        self.assertEqual(recorder.metrics['methods'], {'eth_call': 1, 'other': 1})
        self.assertEqual(set(recorder.metrics['origins']), {'other'})
        self.assertNotIn('private', json.dumps(recorder.metrics))

    def test_evidence_retains_bounded_quote_origins_and_full_discovery_timing(self):
        recorder = RouteObservations()
        with route_observation_scope(recorder), origin_scope('uniswap-alpharouter'):
            with recorder.record_http({'method': 'eth_call', 'params': ['private']}):
                pass
        discovery = {'clock': 'producer', 'startedMs': 2.1, 'elapsedMs': 100.5, 'completedMs': 102.6,
            'queries': 1, 'reevaluations': 1, 'quickReevaluations': 2, 'private': 'secret', 'physicalRpc': recorder.metrics,
            'apiRequests': recorder.api_metrics, 'providers': {'uniswap-alpharouter': {
                'started': 1, 'completed': 1, 'startedMs': 5.0, 'firstCandidateMs': 15.0,
                'completedMs': 20.0, 'durationMs': 15.0, 'url': 'private'}, 'private label': {'started': 1}}}
        origins = {'economicEvaluator': 'cybergold-quoter', 'pricing': 'canonical-sdk-and-core-previews',
            'discoveryProviders': ['uniswap-alpharouter', 'cybergold-custom', 'private label'],
            'conversions': {'0:market': ['uniswap-alpharouter'], 'private address': ['cybergold-custom']},
            'private': 'wallet signature'}
        value = {'routeOrigins': origins, 'metrics': {'totalMs': 110, 'routeDiscovery': discovery},
                 'searchCoverage': {'selectedPhase': 'provider-arrival-quick'}}
        projected = economic_evidence(value, {'operationKind': 'quoter', 'resultSource': 'search'})
        self.assertEqual(projected['routeOrigins']['discoveryProviders'], ['cybergold-custom', 'uniswap-alpharouter'])
        self.assertEqual(projected['routeOrigins']['pricing'], 'canonical-sdk-and-core-previews')
        self.assertEqual(projected['routeOrigins']['conversions'], {'0:market': ['uniswap-alpharouter']})
        self.assertEqual(projected['routePhase'], 'provider-arrival-quick')
        performance = projected['producerMetrics']['routeDiscovery']
        self.assertEqual(performance['quickReevaluations'], 2)
        self.assertEqual(performance['physicalRpc']['requests'], 1)
        self.assertEqual(performance['providers']['uniswap-alpharouter']['firstCandidateMs'], 15)
        self.assertEqual(performance['clock'], 'producer')
        self.assertNotIn('private', json.dumps(projected))
        self.assertNotIn('secret', json.dumps(projected))
        # Stored observations preserve the old producer's evidence without
        # claiming those RPC attempts belong to today's cache lookup.
        stored = economic_evidence(value, {'operationKind': 'quoter', 'resultSource': 'stored-quote'})
        self.assertIn('observedQuoteMetrics', stored)
        self.assertNotIn('producerMetrics', stored)

    def test_failure_metrics_projection_uses_retained_route_performance(self):
        result = economic_evidence({}, {'operationKind': 'quoter', 'resultSource': 'search',
            'producerMetrics': {'routeDiscovery': {'clock': 'producer', 'elapsedMs': 5000,
                'providers': {'uniswap-guidestar': {'started': 1, 'cancelled': 1, 'cancelledMs': 5000}}}}})
        self.assertEqual(result['producerMetrics']['routeDiscovery']['elapsedMs'], 5000)
        self.assertEqual(result['producerMetrics']['routeDiscovery']['providers']['uniswap-guidestar']['cancelled'], 1)

    def test_shared_tool_feed_work_and_api_engine_evidence_have_closed_log_projection(self):
        value = {'routeOrigins': {'economicEvaluator': 'cybergold-quoter',
            'pricing': 'canonical-sdk-and-core-previews',
            'discoveryProviders': ['uniroute-api', 'uniroute-local', 'cybergold-custom']},
            'metrics': {'routeDiscovery': {'providers': {
                'cybergold-custom': {'started': 1, 'available': 1, 'feedReads': 4,
                    'feedIterations': 2, 'feedReadMs': 0.5, 'feedErrors': 0},
                'uniroute-local': {'started': 1, 'completed': 1, 'candidates': 1},
                'uniroute-api': {'started': 3, 'completed': 3, 'engineAttribution': {
                    'engines': {'uniroute': 1, 'guidestar': 0, 'unverified': 2, 'private': 50},
                    'evidence': {'route-candidates': 1, 'not-disclosed': 1, 'ambiguous': 1,
                                 'private': 20}, 'private': 'secret'}}}}}}
        projected = economic_evidence(value, {'operationKind': 'quoter', 'resultSource': 'search'})
        self.assertEqual(projected['routeOrigins']['discoveryProviders'],
                         ['cybergold-custom', 'uniroute-api', 'uniroute-local'])
        providers = projected['producerMetrics']['routeDiscovery']['providers']
        self.assertEqual(providers['cybergold-custom']['feedReadMs'], 0.5)
        self.assertEqual(providers['cybergold-custom']['available'], 1)
        self.assertEqual(providers['uniroute-api']['engineAttribution'], {
            'engines': {'uniroute': 1, 'guidestar': 0, 'unverified': 2},
            'evidence': {'route-candidates': 1, 'not-disclosed': 1, 'ambiguous': 1}})
        self.assertNotIn('private', json.dumps(projected))
        self.assertNotIn('secret', json.dumps(projected))


if __name__ == '__main__':
    unittest.main()
