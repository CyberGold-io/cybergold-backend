"""Ready-view reuse preserves publication order, origins and private consumers.

Canonical producer methods publish controlled nominations; no supplier, pricing,
chain IO, elapsed-time assertion or amount-search loop is involved.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter import bootstrap
from cybergold_candidate.quoter.discovery import route_available
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteQuery, RouteTool


A, B, C = ('0x' + f'{n:040x}' for n in (1, 2, 3))
BLOCK = {'number': 123, 'hash': '0x' + 'ab' * 32}


def candidate(index, *, native=False, split=False):
    def route(offset):
        hops = [{'pool': {'id': '0x' + f'{index + offset:040x}',
            'address': '0x' + f'{index + offset:040x}', 'protocol': 'v3',
            'feePips': (100, 500, 3000, 10000)[(index // 10 + offset) % 4],
            'token0': {'address': A, 'decimals': 18, 'chainId': 31338},
            'token1': {'address': B, 'decimals': 6, 'chainId': 31338}},
            'zeroForOne': True}]
        return ([{'kind': 'wrap', 'currencyOut': A}] if native else []) + hops
    return ([{'amountIn': '60', 'hops': route(0)}, {'amountIn': '40', 'hops': route(1)}]
            if split else [{'amountIn': '100', 'hops': route(0)}])


class Immediate(RouteTool):
    def __init__(self, name):
        self.name = name
        self.queries = []

    def discover(self, query):
        self.queries.append(query)
        return CandidateFeed()


class ObservedOrigins(list):
    """Count actual snapshot reads without changing values or sorting policy."""
    def __init__(self, names):
        super().__init__(names)
        self.reads = 0

    def __iter__(self):
        self.reads += 1
        return super().__iter__()


class ReadyOfferSnapshots(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.providers = [Immediate('first'), Immediate('second')]
        self.session = bootstrap.RouteBootstrap(self.providers)
        self.addAsyncCleanup(self.session.close)

    def query(self, amount=100, *, source=A, target=B):
        key = source.lower(), target.lower(), amount
        self.session.offer_feeds(*key, BLOCK)
        return key

    def publish(self, key, values, provider=0):
        entry = self.session._queries[key][provider]
        self.session._publish_batch(values, entry, entry['attempt'])
        return entry

    async def test_unchanged_query_reuses_view_and_each_pass_keeps_its_own_map(self):
        key, other, empty = self.query(), self.query(200), self.query(300)
        entry = self.publish(key, [candidate(10)])
        self.publish(other, [candidate(20)])
        origins = ObservedOrigins(entry['offers'][0]['origins'])
        entry['offers'][0]['origins'] = origins
        first = self.session._ready_offers()
        self.assertEqual(origins.reads, 1)
        second = self.session._ready_offers()
        self.assertEqual(origins.reads, 1, 'An unchanged ready row must not be rematerialized')
        self.assertIsNot(first, second)
        for query in (key, other, empty):
            self.assertIs(first[query], second[query])
        first.pop(other)
        self.assertEqual(list(self.session._ready_offers()), [key, other, empty])

    async def test_new_batch_rebuilds_only_its_query_and_keeps_prior_pass_unchanged(self):
        key, other = self.query(), self.query(200)
        self.publish(key, [candidate(10)])
        self.publish(other, [candidate(20)])
        first = self.session._ready_offers()
        original = deepcopy(first)
        self.publish(key, [candidate(30)])
        second = self.session._ready_offers()
        self.assertEqual(first, original)
        self.assertIsNot(first[key], second[key])
        self.assertIs(first[other], second[other])
        self.assertEqual([row['branches'] for row in second[key]], [candidate(30), candidate(10)])

    async def test_duplicate_batch_invalidates_without_an_economic_revision(self):
        key = self.query()
        self.publish(key, [candidate(10)])
        first = self.session._ready_offers()
        original, revision = deepcopy(first), self.session.revision
        self.publish(key, [candidate(10), candidate(10)], provider=1)
        self.assertEqual(self.session.revision, revision)
        second = self.session._ready_offers()
        self.assertEqual(first, original)
        self.assertIsNot(first[key], second[key])
        self.assertEqual(second[key], [
            {'branches': candidate(10), 'origins': ['second']},
            {'branches': candidate(10), 'origins': ['second']},
            {'branches': candidate(10), 'origins': ['first']}])

    async def test_completed_insert_refreshes_unqueried_prefix_without_starting_suppliers(self):
        query = RouteQuery(A, B, 100, BLOCK)
        self.assertTrue(self.session.publish_completed(query, candidate(10)[0]['hops'], ['first']))
        first = self.session._ready_offers()
        self.assertTrue(self.session.publish_completed(query, candidate(20)[0]['hops'], ['second']))
        second = self.session._ready_offers()
        key = A, B, 100
        self.assertEqual((self.session.revision, self.session.metrics['queries']), (0, 0))
        self.assertTrue(all(not provider.queries for provider in self.providers))
        self.assertEqual(first[key], [{'branches': candidate(10), 'origins': ['first']}])
        self.assertEqual(second[key], [
            {'branches': candidate(20), 'origins': ['second']},
            {'branches': candidate(10), 'origins': ['first']}])

    async def test_origin_extension_refreshes_without_mutating_prior_origin_lists(self):
        query, key = RouteQuery(A, B, 100, BLOCK), (A, B, 100)
        route = candidate(10)[0]['hops']
        self.session.publish_completed(query, route, ['first'])
        first = self.session._ready_offers()
        self.assertFalse(self.session.publish_completed(query, route, ['second', 'first']))
        second = self.session._ready_offers()
        self.assertEqual(self.session.revision, 0)
        self.assertIsNot(first[key], second[key])
        self.assertEqual(first[key][0]['origins'], ['first'])
        self.assertEqual(second[key][0]['origins'], ['first', 'second'])
        self.assertIsNot(first[key][0]['origins'], second[key][0]['origins'])
        self.assertFalse(self.session.publish_completed(query, route, ['second', 'first', 'second']))
        third = self.session._ready_offers()
        self.assertIs(third[key], second[key], 'An identical origin set is not a stored mutation')

    async def test_tied_rows_all_keys_native_paths_and_split_multiplicity_keep_literal_order(self):
        key, other, empty = self.query(), self.query(200), self.query(300)
        old = candidate(10, native=True)
        split, duplicate = candidate(20, split=True), candidate(30)
        self.publish(key, [old])
        self.publish(other, [candidate(40)])
        self.publish(key, [split, duplicate, duplicate], provider=1)
        completed_only = RouteQuery(B, C, 400, BLOCK)
        self.session.publish_completed(completed_only, candidate(50)[0]['hops'], ['completed'])
        expected = {
            key: [{'branches': value, 'origins': ['second']} for value in (split, duplicate, duplicate)]
                 + [{'branches': old, 'origins': ['first']}],
            other: [{'branches': candidate(40), 'origins': ['first']}],
            empty: [],
            (B, C, 400): [{'branches': [{'amountIn': '400', 'hops': candidate(50)[0]['hops']}],
                          'origins': ['completed']}]}
        first, second = self.session._ready_offers(), self.session._ready_offers()
        self.assertEqual(list(first), list(expected))
        self.assertEqual(list(second), list(expected))
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)

    async def test_empty_batch_is_not_a_stored_mutation(self):
        key = self.query()
        self.publish(key, [candidate(10)])
        first, revision = self.session._ready_offers(), self.session.revision
        self.publish(key, [])
        second = self.session._ready_offers()
        self.assertEqual(self.session.revision, revision)
        self.assertIs(first[key], second[key])

    async def test_cached_quick_prefix_copies_only_consumed_body_and_keeps_private_mutations(self):
        key = self.query()
        entry = self.publish(key, [candidate(10), candidate(20), candidate(30)])
        ready = self.session._ready_offers()
        original = deepcopy((ready, entry['offers']))
        async def consume():
            with patch.object(bootstrap, 'deepcopy', wraps=deepcopy) as copies:
                feeds = self.session.offer_feeds(*key, BLOCK)
                self.assertEqual(copies.call_count, 0)
                chosen = next(feeds[0])
                self.assertEqual(copies.call_count, 1)
                self.assertEqual(chosen, ready[key][0])
                chosen['origins'].append('private-consumer')
                chosen['branches'][0]['hops'][0]['pool']['feePips'] = 42
                for iterator in feeds:
                    close = getattr(iterator, 'close', None)
                    if close is not None:
                        close()
                self.assertEqual(copies.call_count, 1, 'An unused prefix still must not be copied')
        await self.session._arrival_pass(consume, {key}, ready)
        self.assertEqual((ready, entry['offers']), original)

    async def test_reused_topology_does_not_freeze_current_pool_availability(self):
        key = self.query()
        self.publish(key, [candidate(10)])
        ready = self.session._ready_offers()
        available = True
        self.session.topology.pool_available = lambda pool: available
        with bootstrap.bootstrap_scope(self.session):
            self.assertTrue(route_available(ready[key][0]['branches'][0]['hops']))
            available = False
            current = self.session._ready_offers()
            self.assertIs(current[key], ready[key])
            self.assertFalse(route_available(current[key][0]['branches'][0]['hops']))
            available = True
            self.assertTrue(route_available(current[key][0]['branches'][0]['hops']))

    async def test_close_clears_request_owned_snapshots_without_changing_old_pass(self):
        key = self.query()
        self.publish(key, [candidate(10)])
        ready = self.session._ready_offers()
        original = deepcopy(ready)
        self.assertTrue(self.session._ready_offer_snapshots)
        await self.session.close()
        self.assertFalse(self.session._ready_offer_snapshots)
        self.assertEqual(ready, original)


if __name__ == '__main__':
    unittest.main()
