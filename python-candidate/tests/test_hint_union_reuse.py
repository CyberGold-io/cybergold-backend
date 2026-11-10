"""Local union expansion reuse keeps current topology, funding and origins.

These are pure nomination controls: no SDK, RPC, pricing or route admission
limit. The canonical graph/candidate producers supply the expected order.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter.amm_adapter import adapt_candidates
from cybergold_candidate.quoter.candidate_hints import normalize_hints
from cybergold_candidate.quoter.discovery import paths, route_candidates, route_identity
from cybergold_candidate.quoter.pool_directions import branch_directions, conflicting_pool
from cybergold_candidate.routing_encoding import ZERO
from cybergold_candidate.route_search import WETH


A = WETH.lower()
B, C, D = ('0x' + str(value) * 40 for value in (6, 7, 8))


def crossed(amounts=(50, 50), *, origin='first', epoch='old'):
    pools = {}
    for index, (source, target) in enumerate(((A, B), (B, C), (C, D), (A, C), (B, D))):
        left, right = sorted((source, target))
        pools[frozenset((left, right))] = {
            'id': '0x' + format(index + 100, '040x'), 'protocol': 'v3',
            'token0': {'address': left, 'decimals': 18, 'symbol': epoch},
            'token1': {'address': right, 'decimals': 18},
            'feePips': 500, 'tickSpacing': 10, 'hooks': ZERO,
            'liquidity': '1000' if epoch == 'old' else '2000',
            'sqrtRatioX96': str(2**96), 'observationEpoch': epoch}
    def hop(source, target):
        pool = pools[frozenset((source, target))]
        return {'pool': pool, 'zeroForOne': pool['token0']['address'] == source}
    return {'branches': [{'amountIn': str(amount), 'hops': [hop(a, b)
        for a, b in zip(route, route[1:])]} for amount, route in zip(
            amounts, ((A, B, C, D), (A, C, B, D)), strict=True)], 'origins': [origin]}


def signature(branches):
    return tuple((row['amountIn'], route_identity(row['hops'])) for row in branches)


def expected_union(offer, source=A):
    inventory = [hop['pool'] for row in offer['branches'] for hop in row['hops']]
    routes = paths(inventory, source, D)
    amount = sum(int(row['amountIn']) for row in offer['branches'])
    return [signature(rows) for rows in route_candidates(routes, amount)
            if conflicting_pool(branch_directions(rows)) is None]


class HintUnionReuseTests(unittest.TestCase):
    def test_different_weights_reuse_expansion_and_preserve_native_order(self):
        for source in (A, ZERO):
            with self.subTest(source=source):
                first, second = crossed(), crossed((33, 67), origin='second')
                original = deepcopy((first, second))
                expected = expected_union(first, source)
                with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                           wraps=route_candidates) as enumerate_candidates:
                    offered = list(normalize_hints([first, second], source, D))
                self.assertEqual(enumerate_candidates.call_count, 1)
                self.assertEqual([signature(rows) for rows, origins in offered if origins == ['first']], expected)
                self.assertEqual([signature(rows) for rows, origins in offered if origins == ['second']], expected)
                self.assertEqual((first, second), original)

    def test_distinct_union_or_total_input_rebuilds_without_losing_candidates(self):
        first = crossed()
        changed_union = crossed(origin='different-pool')
        for row in changed_union['branches']:
            for hop in row['hops']:
                if {hop['pool']['token0']['address'], hop['pool']['token1']['address']} == {B, D}:
                    hop['pool']['feePips'] = 3000
        changed_total = crossed((34, 67), origin='different-total')
        offers = [first, changed_union, changed_total]
        expected = {offer['origins'][0]: expected_union(offer) for offer in offers}
        with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                   wraps=route_candidates) as enumerate_candidates:
            actual = list(normalize_hints(offers, A, D))
        self.assertEqual(enumerate_candidates.call_count, 3)
        for origin, nominations in expected.items():
            self.assertEqual([signature(rows) for rows, origins in actual if origins == [origin]], nominations)

    def test_late_metadata_and_state_bind_current_pool_representatives(self):
        first, current = crossed(), crossed((33, 67), origin='current', epoch='new')
        self.assertEqual(expected_union(first), expected_union(current))
        with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                   wraps=route_candidates) as enumerate_candidates:
            actual = list(normalize_hints([first, current], A, D))
        self.assertEqual(enumerate_candidates.call_count, 1)
        for branches, origins in actual:
            epoch = 'new' if origins == ['current'] else 'old'
            for row in branches:
                for hop in row['hops']:
                    pool = hop['pool']
                    self.assertEqual(pool['observationEpoch'], epoch)
                    self.assertEqual(pool['token0']['symbol'], epoch)
                    self.assertEqual(pool['liquidity'], '2000' if epoch == 'new' else '1000')

    def test_metadata_that_changes_route_order_rebuilds_the_ordered_patterns(self):
        first, reordered = crossed(), crossed(origin='reordered')
        for row in reordered['branches']:
            for hop in row['hops']:
                pool = hop['pool']
                pool['id'] = '0x' + format(1000-int(pool['id'], 16), '040x')
        self.assertNotEqual(expected_union(first), expected_union(reordered))
        with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                   wraps=route_candidates) as enumerate_candidates:
            actual = list(normalize_hints([first, reordered], A, D))
        self.assertEqual(enumerate_candidates.call_count, 2)
        self.assertEqual([signature(rows) for rows, origins in actual if origins == ['reordered']],
                         expected_union(reordered))

    def test_compatible_original_weights_are_not_replaced_by_cached_union_weights(self):
        bad = crossed()
        pool_by_pair = {frozenset((hop['pool']['token0']['address'], hop['pool']['token1']['address'])): hop['pool']
                        for row in bad['branches'] for hop in row['hops']}
        def compatible(weights, origin):
            rows = []
            for amount, currencies in zip(weights, ((A, B, D), (A, C, D)), strict=True):
                hops = []
                for source, target in zip(currencies, currencies[1:]):
                    pool = pool_by_pair[frozenset((source, target))]
                    hops.append({'pool': pool, 'zeroForOne': pool['token0']['address'] == source})
                rows.append({'amountIn': str(amount), 'hops': hops})
            return {'branches': rows, 'origins': [origin]}
        good = [compatible((19, 81), 'nineteen'), compatible((61, 39), 'sixty-one')]
        with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                   wraps=route_candidates) as enumerate_candidates:
            actual = list(normalize_hints([bad, *good, crossed((33, 67), origin='last')], A, D))
        self.assertEqual(enumerate_candidates.call_count, 1)
        for offered in good:
            self.assertEqual([signature(rows) for rows, origins in actual if origins == offered['origins']],
                             [signature(offered['branches'])])

    def test_replayed_candidates_still_merge_origins_in_the_shared_adapter(self):
        first, second = crossed(origin='provider-a'), crossed((33, 67), origin='provider-b')
        with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                   wraps=route_candidates) as enumerate_candidates:
            actual = list(adapt_candidates(normalize_hints([first, second], A, D), A, D))
        self.assertEqual(enumerate_candidates.call_count, 1)
        self.assertEqual([signature(rows) for rows, _ in actual], expected_union(first))
        self.assertTrue(all(origins == ['provider-a', 'provider-b'] for _, origins in actual))

    def test_last_completed_memo_does_not_accumulate_earlier_union_keys(self):
        first, other = crossed(), crossed((34, 67), origin='different-total')
        with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                   wraps=route_candidates) as enumerate_candidates:
            offered = list(normalize_hints([first, other, crossed(origin='again')], A, D))
        self.assertEqual(enumerate_candidates.call_count, 3)
        self.assertEqual([signature(rows) for rows, origins in offered if origins == ['again']], expected_union(first))

    def test_emitted_mutations_and_another_iterator_do_not_poison_reuse(self):
        original = crossed()
        with patch('cybergold_candidate.quoter.candidate_hints.route_candidates',
                   wraps=route_candidates) as enumerate_candidates:
            iterator = iter(normalize_hints([original, crossed((33, 67), origin='second')], A, D))
            branches, _ = next(iterator)
            branches[0]['amountIn'] = '999999'
            branches[0]['hops'][0]['zeroForOne'] = not branches[0]['hops'][0]['zeroForOne']
            remainder = list(iterator)
            again = list(normalize_hints([crossed(origin='another-iterator')], A, D))
        self.assertEqual(enumerate_candidates.call_count, 2)
        self.assertEqual([signature(rows) for rows, origins in remainder if origins == ['second']], expected_union(original))
        self.assertEqual([signature(rows) for rows, _ in again], expected_union(original))


if __name__ == '__main__':
    unittest.main()
