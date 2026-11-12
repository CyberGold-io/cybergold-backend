"""The same lazy AMM discovery API for custom and asynchronous route tools."""
import asyncio
from itertools import islice
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter.bootstrap import RouteBootstrap
from cybergold_candidate.quoter import custom_routes
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.cooperative import CHECKPOINT
from cybergold_candidate.quoter.route_tools import (
    CandidateFeed, PendingRouteTool, RouteQuery, RouteTool, round_robin)


BLOCK = {'number': 101, 'hash': '0x' + 'ab'*32}


def pool(source, target, identity):
    return {'id': identity, 'protocol': 'v2', 'feePips': 3000,
            'token0': {'address': source}, 'token1': {'address': target}}


def candidate(amount):
    return [{'amountIn': str(amount), 'hops': [{'pool': pool('a', 'c', 'ac'), 'zeroForOne': True}]}]


class RouteToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_consumer_path_projection_precedes_splits_without_changing_shared_query(self):
        # Twenty direct paths are outside this consuming operation's selected
        # edge; its single useful path needs no split proposals. The producer
        # knows only the caller's opaque projection, not a Core/anchor concept.
        rows = [dict(pool('a', 'c', 'direct-' + str(index)), protocol='v4',
                     feePips=100 + index, tickSpacing=60) for index in range(20)]
        rows.extend((pool('a', 'b', 'ab'), pool('b', 'c', 'bc')))
        registry = SimpleNamespace(inventory={row['id']: row for row in rows})
        session = RouteBootstrap([CustomRoutes(registry)])
        enumerated = []
        ordinary_candidates = custom_routes.route_candidate_steps
        def counted(*args):
            for row in ordinary_candidates(*args):
                if row is not CHECKPOINT:
                    enumerated.append(row)
                yield row
        def selected_edge(routes):
            return [route for route in routes if route[-1]['pool']['id'] == 'bc']
        with patch.object(custom_routes, 'route_candidate_steps', counted):
            selected = list(session.offers('a', 'c', 100, BLOCK, path_projection=selected_edge))
            self.assertEqual(len(selected), 1)
            self.assertEqual(len(enumerated), 1)
            # Same directed pair/amount, same memoized query; another consumer
            # still sees every ordinary path and all its lazy split proposals.
            unprojected = list(session.offers('a', 'c', 100, BLOCK))
            self.assertEqual(len(unprojected), 651)
            self.assertEqual(len(enumerated), 652)
        self.assertEqual(session.metrics['queries'], 1)
        self.assertEqual(session.revision, 0)
        self.assertEqual(len(registry.inventory), 22)
        await session.close()

    async def test_custom_feed_uses_current_inventory_each_time_without_eager_splits(self):
        registry = SimpleNamespace(inventory={'ab': pool('a', 'b', 'ab')})
        query = RouteQuery('a', 'c', 100, BLOCK)
        tool = CustomRoutes(registry)
        feed = tool.discover(query)
        self.assertIsInstance(feed, CandidateFeed)
        self.assertIsNone(feed.pending)
        self.assertEqual(list(feed.available), [])
        registry.inventory['bc'] = pool('b', 'c', 'bc')
        first = next(iter(feed.available))
        self.assertEqual([hop['pool']['id'] for hop in first[0]['hops']], ['ab', 'bc'])
        registry.inventory['ac'] = pool('a', 'c', 'ac')
        self.assertEqual(len(list(feed.available)), 5)  # Two singles and three split shapes.
        self.assertEqual(next(iter(feed.available))[0]['hops'][0]['pool']['id'], 'ac')
        self.assertEqual(query.block, BLOCK)
        await tool.close()

    async def test_session_reuses_repeatable_custom_feed_after_catalog_expands(self):
        registry = SimpleNamespace(inventory={'ab': pool('a', 'b', 'ab')})
        session = RouteBootstrap([CustomRoutes(registry)])
        async def ordinary():
            self.assertEqual(list(session.offers('a', 'c', 100, BLOCK)), [])
            registry.inventory['bc'] = pool('b', 'c', 'bc')
            offered = list(session.offers('a', 'c', 100, BLOCK))
            self.assertEqual(len(offered), 1)
            self.assertEqual(offered[0]['origins'], ['cybergold-custom'])
        async def reevaluate():
            self.fail('Synchronous custom feed reads must not manufacture arrival rounds')
        await session.run(ordinary(), reevaluate)
        metrics = session.metrics['providers']['cybergold-custom']
        self.assertEqual(session.metrics['queries'], 1)
        self.assertEqual(session.revision, 0)
        self.assertEqual(metrics['pending'], 0)
        self.assertEqual(metrics['feedIterations'], 2)
        self.assertEqual(metrics['feedReads'], 1)
        self.assertEqual(metrics['candidates'], 1)
        self.assertGreaterEqual(metrics['feedReadMs'], 0)

    async def test_immediate_stream_stays_lazy_and_fair_to_a_completed_external_source(self):
        read = []
        entered, release = asyncio.Event(), asyncio.Event()
        class Immediate(RouteTool):
            name = 'cybergold-custom'
            def discover(self, query):
                class Available:
                    def __iter__(self):
                        for value in range(1, 1000000):
                            read.append(value)
                            yield candidate(value)
                return CandidateFeed(available=Available())
        class External:
            name = 'external'
            async def discover(self, source, target, amount, block):
                entered.set()
                await release.wait()
                return [candidate(200)]
        session = RouteBootstrap([Immediate(), PendingRouteTool(External())])
        selected = []
        async def ordinary():
            first = next(iter(session.offers('a', 'c', 100, BLOCK)))
            self.assertEqual(first['origins'], ['cybergold-custom'])
            self.assertEqual(read, [1])
        async def reevaluate():
            selected.extend(islice(session.offers('a', 'c', 100, BLOCK), 3))
        task = asyncio.create_task(session.run(ordinary(), reevaluate))
        await entered.wait()
        release.set()
        await task
        self.assertEqual([row['origins'] for row in selected],
                         [['cybergold-custom'], ['external'], ['cybergold-custom']])
        self.assertEqual(read, [1, 1, 2])
        self.assertEqual(session.metrics['providers']['cybergold-custom']['feedReads'], 3)
        self.assertEqual(session.revision, 1)

    async def test_separate_feeds_allow_adapter_priority_without_cross_source_buffering(self):
        class Tool(RouteTool):
            def __init__(self, name, values):
                self.name, self.values = name, values
            def discover(self, query):
                return CandidateFeed(available=self.values)
        session = RouteBootstrap([Tool('custom', [candidate(1), candidate(2)]),
                                  Tool('external', [[*candidate(3), *candidate(4)]])])
        feeds = session.offer_feeds('a', 'c', 100, BLOCK)
        self.assertEqual(len(feeds), 2)
        grouped = [list(feed) for feed in feeds]
        self.assertEqual([len(group) for group in grouped], [2, 1])
        merged = list(round_robin(grouped))
        self.assertEqual([offer['origins'] for offer in merged], [['custom'], ['external'], ['custom']])
        await session.close()

    async def test_unavailable_immediate_source_does_not_remove_another_feed(self):
        class Broken(RouteTool):
            name = 'broken'
            def discover(self, query):
                class Available:
                    def __iter__(self):
                        raise ValueError('private source diagnostic')
                        yield
                return CandidateFeed(available=Available())
        registry = SimpleNamespace(inventory={'ac': pool('a', 'c', 'ac')})
        session = RouteBootstrap([Broken(), CustomRoutes(registry)])
        offered = list(session.offers('a', 'c', 100, BLOCK))
        self.assertEqual(len(offered), 1)
        self.assertEqual(offered[0]['origins'], ['cybergold-custom'])
        self.assertEqual(session.metrics['providers']['broken']['feedErrors'], 1)
        self.assertNotIn('private', repr(session.metrics))
        await session.close()

    async def test_response_engine_attribution_is_diagnostic_and_not_candidate_admission(self):
        class Attributed(list):
            engine_attribution = {'engine': 'uniroute', 'evidence': 'route-candidates'}
        class Raw:
            name = 'uniroute-api'
            async def discover(self, source, target, amount, block):
                return Attributed([candidate(amount)])
        session = RouteBootstrap([PendingRouteTool(Raw())])
        offered = []
        async def ordinary():
            session.offer_feeds('a', 'c', 100, BLOCK)
        async def reevaluate():
            offered.extend(session.offers('a', 'c', 100, BLOCK))
        await session.run(ordinary(), reevaluate)
        self.assertEqual(offered, [{'branches': candidate(100), 'origins': ['uniroute-api']}])
        attribution = session.metrics['providers']['uniroute-api']['engineAttribution']
        self.assertEqual(attribution['engines']['uniroute'], 1)
        self.assertEqual(attribution['evidence']['route-candidates'], 1)


if __name__ == '__main__':
    unittest.main()
