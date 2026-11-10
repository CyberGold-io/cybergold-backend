"""Both standard modes share ordinary discovery ownership and execution rules.

Actual factory/providers, HTTP parser, API queue and RouteBootstrap are used.
HTTP responses and prefix arithmetic are controlled; no live API, SDK worker,
Helpers execution or financial result is claimed by these nomination controls.
"""
import asyncio
from copy import deepcopy
import json
import unittest

import httpx

from cybergold_candidate.quoter.amm_adapter import adapt_candidates
from cybergold_candidate.quoter.bootstrap import RouteBootstrap
from cybergold_candidate.quoter.candidate_hints import normalize_hints
from cybergold_candidate.quoter.hosted_routes import UniswapApiProvider
from cybergold_candidate.quoter.providers import route_providers
from cybergold_candidate.route_observations import (
    RouteObservations, project_route_discovery, project_route_origins, route_observation_scope)
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.search_observations import search_observation_scope
from cybergold_candidate.uniswap_api_queue import UniswapApiQueue
from cybergold_candidate.uniswap_v4 import v4_pool_id
from test_hosted_routes import (
    A, B, D, BLOCK, MANAGER, ZERO, FAKE, FixtureTransport, Registry, packed, settings, standard_pool)


FAST, BEST, GUIDE = 'uniroute-api-fastest', 'uniroute-api', 'uniswap-guidestar'


class Clock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    async def sleep(self, delay):
        self.value += delay


class HostedRouteModesTests(unittest.IsolatedAsyncioTestCase):
    def factory(self, *, handlers=None, statuses=None, documents=None, registry=None):
        registry = registry or Registry()
        engine = RouteQuoteEngine(settings(), registry)
        clock = Clock()
        engine.uniswap_api_queue = UniswapApiQueue(now=clock.now, sleep=clock.sleep)
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.pending.close)
        tools = route_providers(settings(), engine)
        for tool in tools:
            self.addAsyncCleanup(tool.close)
        hosted = [tool for tool in tools if isinstance(getattr(tool, 'provider', None), UniswapApiProvider)]
        self.assertEqual(len(tools), 6)
        self.assertEqual([tool.name for tool in hosted], [FAST, BEST, GUIDE])
        transports, clients = {}, {}
        for tool in hosted:
            provider = tool.provider
            self.assertIs(provider.queue, engine.uniswap_api_queue)
            self.assertIsNone(provider.client, 'Factory construction must remain network-free')
            document = {'quote': {'route': [[standard_pool('v3', A, B, fee=3000)]],
                                   'routeCandidates': [{'routeString': 'not-executable'}]}}
            if tool.name == GUIDE:
                document = {'quote': {'route': [], 'swapSteps': [
                    {'type': 'V3_SWAP_EXACT_IN', 'path': packed([A, B], [3000]), 'amountIn': '101'}]}}
            document = deepcopy((documents or {}).get(tool.name, document))
            transport = FixtureTransport(document, (statuses or {}).get(tool.name, 200),
                                         (handlers or {}).get(tool.name))
            transports[tool.name], clients[tool.name] = transport, []
            def create(*, transport=transport, name=tool.name):
                client = httpx.AsyncClient(transport=transport, timeout=None)
                clients[name].append(client)
                return client
            provider.client_factory = create
        return engine, hosted, transports, clients

    @staticmethod
    def offered(session, source=A, target=B, amount=101):
        return list(adapt_candidates(normalize_hints(session.offers(source, target, amount, BLOCK),
                                                     source, target), source, target))

    async def test_actual_factory_sends_distinct_compatible_fast_best_and_guidestar_requests(self):
        engine, hosted, transports, _ = self.factory()
        candidates = await asyncio.gather(*(tool.provider.discover(A, B, 101, BLOCK) for tool in hosted))
        self.assertTrue(all(candidates))
        for name, preference in ((FAST, 'FASTEST'), (BEST, 'BEST_PRICE'), (GUIDE, 'BEST_PRICE')):
            request, = transports[name].requests
            payload = json.loads(request.content)
            self.assertEqual((payload['routingPreference'], payload['amount'], payload['tokenIn'], payload['tokenOut']),
                             (preference, '101', A, B))
            self.assertEqual((payload['tokenInChainId'], payload['tokenOutChainId']), (1, 1))
            self.assertTrue(payload['includeRouteCandidates'])
            if name == FAST:
                self.assertNotIn('protocols', payload)
                self.assertNotIn('hooksOptions', payload)
            else:
                self.assertEqual(payload['protocols'], ['V2', 'V3', 'V4'])
                self.assertEqual(payload['hooksOptions'], 'V4_NO_HOOKS')
            self.assertEqual('x-api-experimental' in request.headers, name == GUIDE)
            self.assertEqual('x-universal-router-swapsteps' in request.headers, name == GUIDE)
        self.assertEqual((engine.registry.calls, engine.registry.metadata_calls), ([], []))
        self.assertFalse(engine.uniswap_api_queue.pending)

    async def test_fast_offer_arrives_while_best_price_http_is_still_pending(self):
        best_entered, release_best, fast_ready = (asyncio.Event() for _ in range(3))
        async def held(_request):
            best_entered.set()
            await release_best.wait()
        _, hosted, transports, _ = self.factory(handlers={BEST: held})
        session = RouteBootstrap(hosted)
        async def ordinary():
            session.offer_feeds(A, B, 101, BLOCK)
        async def receive():
            offered = self.offered(session)
            if not fast_ready.is_set() and any(FAST in origins for _, origins in offered):
                self.assertFalse(release_best.is_set())
                self.assertFalse(any(BEST in origins for _, origins in offered))
                fast_ready.set()
        owner = asyncio.create_task(session.run(ordinary(), receive))
        try:
            await asyncio.wait_for(asyncio.gather(best_entered.wait(), fast_ready.wait()), 2)
            self.assertFalse(owner.done())
            self.assertEqual(session.metrics['providers'][BEST]['pending'], 1)
        finally:
            release_best.set()
            await asyncio.wait_for(owner, 2)
        self.assertTrue(all(len(transport.requests) == 1 for transport in transports.values()))

    async def test_one_failed_standard_mode_preserves_the_other_and_does_not_retry(self):
        for failed in (FAST, BEST):
            with self.subTest(failed=failed):
                _, hosted, transports, _ = self.factory(statuses={failed: 404})
                session = RouteBootstrap(hosted)
                observed = []
                async def ordinary():
                    session.offer_feeds(A, B, 101, BLOCK)
                async def receive():
                    observed.extend(self.offered(session))
                await session.run(ordinary(), receive)
                survivor = BEST if failed == FAST else FAST
                self.assertTrue(any(survivor in origins for _, origins in observed))
                self.assertFalse(any(failed in origins for _, origins in observed))
                self.assertEqual(session.metrics['providers'][failed]['error'], 1)
                self.assertEqual(session.metrics['providers'][survivor]['completed'], 1)
                self.assertTrue(all(len(transport.requests) == 1 for transport in transports.values()))

    async def test_owner_cancellation_drains_all_pending_modes_and_owned_clients(self):
        entered = {name: asyncio.Event() for name in (FAST, BEST, GUIDE)}
        retired, never = set(), asyncio.Event()
        def handler(name):
            async def held(_request):
                entered[name].set()
                try:
                    await never.wait()
                finally:
                    retired.add(name)
            return held
        engine, hosted, transports, clients = self.factory(handlers={name: handler(name) for name in entered})
        session = RouteBootstrap(hosted)
        async def ordinary():
            session.offer_feeds(A, B, 101, BLOCK)
        async def receive():
            pass
        owner = asyncio.create_task(session.run(ordinary(), receive))
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered.values())), 2)
            owner.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await owner
        finally:
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
        self.assertEqual(retired, set(entered))
        self.assertTrue(all(task.done() for task in session._tasks))
        self.assertFalse(engine.uniswap_api_queue.pending)
        for tool in hosted:
            self.assertEqual(tool.provider.clients, set())
            self.assertTrue(transports[tool.name].closed)
            self.assertEqual(len(transports[tool.name].requests), 1)
            self.assertTrue(clients[tool.name] and all(client.is_closed for client in clients[tool.name]))

    async def test_equivalent_routes_merge_both_mode_origins_and_keep_diagnostics(self):
        _, hosted, transports, _ = self.factory()
        session, recorder = RouteBootstrap(hosted), RouteObservations()
        observed = []
        async def ordinary():
            session.offer_feeds(A, B, 101, BLOCK)
        async def receive():
            observed[:] = self.offered(session)
        with route_observation_scope(recorder):
            await session.run(ordinary(), receive)
        self.assertEqual(len(observed), 1, 'Identical API topology must share the ordinary nomination')
        branches, origins = observed[0]
        self.assertEqual(set(origins), {FAST, BEST, GUIDE})
        self.assertEqual([row['amountIn'] for row in branches], ['101'])
        self.assertEqual(session.metrics['providers'][FAST]['completed'], 1)
        self.assertEqual(project_route_discovery(session.metrics)['providers'][FAST]['completed'], 1)
        self.assertEqual(project_route_origins({'discoveryProviders': origins})['discoveryProviders'], sorted(origins))
        self.assertEqual(recorder.api_metrics['requests'], 3)
        self.assertEqual(recorder.api_metrics['origins'][FAST]['requests'], 1)
        self.assertEqual(recorder.api_metrics['retries'], 0)
        self.assertTrue(all(len(transport.requests) == 1 for transport in transports.values()))

    async def test_all_three_hosted_requests_share_one_core_market_prefix_observation(self):
        registry = Registry()
        registry.chain, registry.core = 31338, D
        registry.seed = {'id': v4_pool_id((B, D, 100, 1, ZERO)), 'protocol': 'v4',
            'token0': {'address': B, 'chainId': 31338}, 'token1': {'address': D, 'chainId': 31338},
            'feePips': 100, 'tickSpacing': 1, 'hooks': ZERO, 'poolManager': MANAGER}
        documents = {name: {'quote': {'route': [[standard_pool('v3', B, A, fee=500)]]}}
                     for name in (FAST, BEST)}
        documents[GUIDE] = {'quote': {'route': [], 'swapSteps': [
            {'type': 'V3_SWAP_EXACT_IN', 'path': packed([B, A], [500]), 'amountIn': '67'}]}}
        engine, hosted, transports, _ = self.factory(registry=registry, documents=documents)
        calls = []
        async def prefix(branches, mode, amount, block, **options):
            calls.append((deepcopy(branches), mode, amount, deepcopy(block)))
            return {'amountOut': '67'}
        engine.quote_sdk_branches = prefix
        async with search_observation_scope():
            candidates = await asyncio.gather(*(tool.provider.discover(D, A, 101, BLOCK) for tool in hosted))
        self.assertEqual(len(calls), 1)
        for tool, offers in zip(hosted, candidates, strict=True):
            payload = json.loads(transports[tool.name].requests[0].content)
            self.assertEqual((payload['tokenIn'], payload['amount'], payload['tokenInChainId']), (B, '67', 1))
            self.assertEqual(offers[0][0]['amountIn'], '101')
            self.assertEqual(offers[0][0]['hops'][0]['pool']['id'], registry.seed['id'])
        self.assertEqual((registry.calls, registry.metadata_calls), ([], []))

    async def test_fast_hooked_hint_cannot_discard_an_encodable_sibling(self):
        document = {'quote': {'route': [
            [standard_pool('v4', A, B, fee=500, tickSpacing=10, hooks=FAKE)],
            [standard_pool('v3', A, B, fee=3000)]]}}
        _, hosted, transports, _ = self.factory(documents={FAST: document})
        provider = next(tool.provider for tool in hosted if tool.name == FAST)
        nominees = await provider.discover(A, B, 101, BLOCK)
        offers = [{'branches': branches, 'origins': [FAST]} for branches in nominees]
        actual = list(adapt_candidates(normalize_hints(offers, A, B), A, B))
        self.assertTrue(actual)
        for branches, origins in actual:
            self.assertEqual(origins, [FAST])
            self.assertTrue(all(hop['pool']['protocol'] == 'v3' for row in branches for hop in row['hops']))
        self.assertEqual(len(transports[FAST].requests), 1)


if __name__ == '__main__':
    unittest.main()
