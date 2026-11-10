"""The owner-authorized physical-pool direction rule, without RPC or pricing."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter, adapt_candidates
from cybergold_candidate.quoter.candidate_hints import normalize_hints
from cybergold_candidate.quoter.dormant_routes import with_dormant_routes
from cybergold_candidate.quoter.evaluate import evaluate_candidate
from cybergold_candidate.quoter.pool_directions import (
    body_directions, branch_directions, conflicting_pool, quote_directions)
from cybergold_candidate.route_search import WETH
from cybergold_candidate.routing_encoding import ZERO
from cybergold_candidate.uniswap_routes import pool_identity

A, B, C, D = WETH, *['0x'+str(index)*40 for index in (6, 7, 8)]


def pool(source, target, *, protocol='v3', fee=500, spacing=10):
    left, right = sorted((source.lower(), target.lower()))
    return {'id': 'unobserved-alias', 'protocol': protocol,
            'token0': {'address': left}, 'token1': {'address': right},
            'feePips': fee, 'tickSpacing': spacing, 'hooks': ZERO}


def hop(source, target, **options):
    value = pool(source, target, **options)
    return {'pool': value, 'zeroForOne': source.lower() == value['token0']['address']}


def branch(amount, currencies):
    return {'amountIn': str(amount), 'hops': [hop(a, b)
        for a, b in zip(currencies, currencies[1:])]}


def route(source, *outputs, share=0):
    return {'inputCurrency': source, 'outputCurrency': outputs[-1] if outputs else source,
            'routes': [{'sharePpm': share, 'steps': [
                {'kind': 1, 'currencyOut': output, 'fee': 500, 'tickSpacing': 10}
                for output in outputs]}] if outputs else []}


def core_body(acquisitions, continuations, *, amount=10):
    return {'branches': [{'kind': 0, 'amountIn': str(amount), 'data': {
        'basketAssets': [row['route']['outputCurrency'] for row in acquisitions],
        'acquisitions': acquisitions,
        'continuations': [{'route': row, 'feeCygld': '0'} for row in continuations]}}]}


def request(intent=0, inputs=None, output=D):
    return {'intent': intent, 'inputs': inputs or [{'currency': A, 'amount': '10'}],
            'outputCurrency': output}


class PoolDirectionPolicyTests(unittest.TestCase):
    def test_direction_projection_does_not_lower_routes_or_checksum_addresses(self):
        branches = [branch(1, (A, B, D)), branch(1_000_000, (A, B, C, D))]
        expected = list(branch_directions(branches))
        with patch('cybergold_candidate.routing_encoding.route_steps',
                   side_effect=AssertionError('A pure direction projection must not encode routes')):
            self.assertEqual(list(branch_directions(branches)), expected)

    def test_same_direction_aliases_and_separate_trades_remain_allowed(self):
        one = branch(10, (A, B))
        alias = deepcopy(one)
        alias['hops'][0]['pool'].update(id='observed-alias', address='0x'+'9'*40)
        self.assertIsNone(conflicting_pool(branch_directions([one, alias])))
        reverse = branch(10, (B, A))
        self.assertIsNone(conflicting_pool(branch_directions([one])))
        self.assertIsNone(conflicting_pool(branch_directions([reverse])))
        self.assertEqual(conflicting_pool(branch_directions([one, reverse])), pool_identity(pool(A, B)))
        # A failed combination cannot poison an independent later nomination.
        self.assertIsNone(conflicting_pool(branch_directions([one, alias])))

    def test_native_wrappers_and_reordered_representatives_keep_physical_direction(self):
        one = branch(10, (A, B))
        native = deepcopy(one)
        native['hops'].insert(0, {'kind': 'wrap', 'currencyOut': A})
        alias = deepcopy(one)
        value = alias['hops'][0]['pool']
        value['token0'], value['token1'] = value['token1'], value['token0']
        alias['hops'][0]['zeroForOne'] = not alias['hops'][0]['zeroForOne']
        self.assertEqual(list(branch_directions([native])), list(branch_directions([alias])))
        native_key = pool_identity(pool(ZERO, B, protocol='v4'))
        wrapped_key = pool_identity(pool(A, B, protocol='v4'))
        self.assertNotEqual(native_key, wrapped_key, 'A native V4 pool is not its WETH counterpart')

    def test_distinct_fee_and_v4_keys_are_different_physical_pools(self):
        for protocol, first, second in (
                ('v3', {'fee': 500}, {'fee': 3000}),
                ('v4', {'spacing': 10}, {'spacing': 60})):
            with self.subTest(protocol=protocol):
                rows = [{'amountIn': '10', 'hops': [hop(A, B, protocol=protocol, **first)]},
                        {'amountIn': '10', 'hops': [hop(B, A, protocol=protocol, **second)]}]
                self.assertIsNone(conflicting_pool(branch_directions(rows)))

    def test_encoded_zero_lots_and_final_remainder_use_actual_funding(self):
        self.assertIsNone(conflicting_pool(branch_directions([
            branch(1, (A, B)), branch(1_000_000, (B, A))])))
        # The final encoded route owns remainder even when its raw weight is0.
        self.assertEqual(conflicting_pool(branch_directions([
            branch(1, (A, B)), branch(2, (A, B)), branch(0, (B, A))])), pool_identity(pool(A, B)))
        self.assertEqual(list(branch_directions([branch(0, (A, B)), branch(0, (B, A))])), [])
        weights = [branch(1, (A, B)), branch(1, (B, A))]
        self.assertIsNone(conflicting_pool(branch_directions(weights, amount=1)))
        self.assertIsNotNone(conflicting_pool(branch_directions(weights, amount=2)))

    def test_acquisitions_residuals_and_market_branches_share_one_rule(self):
        cases = [
            core_body([{'amountIn': '5', 'route': route(A, B, C)},
                       {'amountIn': '5', 'route': route(A, C, B)}], [route(C), route(B)]),
            core_body([{'amountIn': '10', 'route': route(A, B)}], [route(B, A, D)]),
            {'branches': [core_body([{'amountIn': '5', 'route': route(A, B, C)}], [route(C)], amount=5)['branches'][0],
                {'kind': 1, 'amountIn': '5', 'data': {'route': route(A, C, B, D), 'feeCygld': '0'}}]},
        ]
        for body in cases:
            with self.subTest(body=body):
                self.assertIsNotNone(conflicting_pool(body_directions(request(), body)))
        same = core_body([{'amountIn': '5', 'route': route(A, B, C)},
                          {'amountIn': '5', 'route': route(A, B, D)}], [route(C), route(D)])
        self.assertIsNone(conflicting_pool(body_directions(request(), same)))

    def test_unknown_core_lot_is_not_the_nominal_one_unit_split(self):
        continued = route(B, A, D, share=500000)
        continued['routes'].append(route(B, D)['routes'][0])
        body = core_body([{'amountIn': '10', 'route': route(A, B)}], [continued])
        self.assertIsNotNone(conflicting_pool(body_directions(request(), body)))
        self.assertIsNone(conflicting_pool(body_directions(request(), body, [
            {'operation': '0:residual:0', 'fundedInput': '1'}])))
        self.assertIsNotNone(conflicting_pool(body_directions(request(), body, [
            {'operation': '0:residual:0', 'fundedInput': '2'}])))
        full = route(B, D, share=1_000_000)
        full['routes'].append(route(B, A, D)['routes'][0])
        body['branches'][0]['data']['continuations'][0]['route'] = full
        self.assertIsNone(conflicting_pool(body_directions(request(), body)),
                          'One full-share prefix leaves no possible final funding')
        split = route(B, D, share=500000)
        split['routes'].extend([route(B, C, D, share=500000)['routes'][0], route(B, A, D)['routes'][0]])
        body['branches'][0]['data']['continuations'][0]['route'] = split
        self.assertIsNotNone(conflicting_pool(body_directions(request(), body)),
                             'Two fractional prefixes can leave a positive integer remainder')
        self.assertIsNotNone(conflicting_pool(body_directions(request(), body, [
            {'operation': '0:residual:0', 'fundedInput': '1'}])))

    def test_measured_zero_core_residual_needs_no_conversion_metadata_or_row(self):
        body = core_body([{'amountIn': '10', 'route': route(A, B)}], [route(B, A, D)])
        value = {'request': request(), 'plan': {'body': body}, 'context': {'chainId': 1},
                 'conversionObservations': [], 'pricingEvidence': {'stages': [
                    {'fundedInput': '10', 'consumedInput': '10', 'returnedInput': '0', 'amountOut': '10'},
                    {'fundedInput': '10', 'consumedInput': '10', 'returnedInput': '0', 'amountOut': '7'}]}}
        original = deepcopy(value)
        self.assertIsNotNone(conflicting_pool(body_directions(value['request'], body)))
        self.assertIsNone(conflicting_pool(quote_directions(value)))
        self.assertEqual(value, original)
        value['pricingEvidence'] = {}
        self.assertIsNotNone(conflicting_pool(quote_directions(value)))

    def test_zero_direct_basket_input_and_zero_scalar_branch_do_not_claim_pools(self):
        basket = request(2, [{'currency': B, 'amount': '0'}, {'currency': A, 'amount': '10'}])
        body = {'continuations': [{'route': route(B, A, D)}, {'route': route(A, B, D)}]}
        self.assertIsNone(conflicting_pool(body_directions(basket, body)))
        basket['inputs'][0]['amount'] = '1'
        self.assertIsNotNone(conflicting_pool(body_directions(basket, body)))
        body = {'branches': [
            {'kind': 1, 'amountIn': '0', 'data': {'route': route(A, B, C, D), 'feeCygld': '0'}},
            {'kind': 1, 'amountIn': '10', 'data': {'route': route(A, C, B, D), 'feeCygld': '0'}}]}
        self.assertIsNone(conflicting_pool(body_directions(request(), body)))

    def test_sell_fee_funding_and_recorded_zero_redemption_are_respected(self):
        body = {'branches': [
            {'kind': 1, 'amountIn': '10', 'data': {'route': route(D, A, B, C), 'feeCygld': '10'}},
            {'kind': 0, 'amountIn': '10', 'data': {'expectedOutputs': [
                {'kind': 0, 'token': B, 'id': '0', 'amount': '0'}], 'conversions': [route(B, A, C)]}}]}
        req = request(1, [{'currency': D, 'amount': '20'}], C)
        self.assertIsNone(conflicting_pool(body_directions(req, body)))
        body['branches'][0]['data']['feeCygld'] = '0'
        self.assertIsNotNone(conflicting_pool(body_directions(req, body)))
        value = {'request': req, 'plan': {'body': body}, 'pricingEvidence': {'coreOutputAmounts': [
            {'branch': 1, 'index': 0, 'kind': 0, 'amount': '0'}]}}
        self.assertIsNone(conflicting_pool(quote_directions(value)))

    def test_crossed_hint_union_recovers_the_shorter_compatible_paths(self):
        candidate = [branch(50, (A, B, C, D)), branch(50, (A, C, B, D))]
        for source in (A, ZERO):
            with self.subTest(source=source):
                offers = list(normalize_hints([{'branches': candidate, 'origins': ['fixture-provider']}], source, D))
                self.assertTrue(offers)
                recovered = False
                for branches, origins in offers:
                    self.assertIsNone(conflicting_pool(branch_directions(branches)))
                    self.assertEqual(origins, ['fixture-provider'])
                    self.assertEqual(sum(int(row['amountIn']) for row in branches), 100)
                    physical = {tuple(hop['pool']['token1' if hop['zeroForOne'] else 'token0']['address'].lower()
                                      for hop in row['hops'] if 'pool' in hop) for row in branches}
                    recovered |= physical == {(B.lower(), D.lower()), (C.lower(), D.lower())}
                self.assertTrue(recovered, 'The supplied union graph already contains the compatible shorter split')

    def test_compatible_hint_keeps_its_weights_and_bad_sibling_does_not_poison_it(self):
        good = [branch(25, (A, B, D)), branch(75, (A, B, C, D))]
        bad = [branch(50, (A, B, C, D)), branch(50, (A, C, B, D))]
        offers = list(normalize_hints([{'branches': row} for row in (bad, good)], A, D))
        self.assertTrue(any([row['amountIn'] for row in branches] == ['25', '75'] for branches, _ in offers))
        self.assertTrue(all(conflicting_pool(branch_directions(branches)) is None for branches, _ in offers))


class PoolDirectionProducerTests(unittest.IsolatedAsyncioTestCase):
    """Actual producer choices with controlled path outputs, not EVM pricing."""

    def producer(self, *, native=False, no_optional_alternative=False):
        engine = SimpleNamespace(registry=SimpleNamespace(chain=1, seed=pool(B, D)))
        adapter = CyberGoldAmmAdapter(engine, D)
        priced = []
        async def nominations(source, target, amount, block, **options):
            if source.lower() in (A.lower(), ZERO):
                choices = [(A, C, B)] if target == B else [(A, B, C), (A, C)]
            elif source == B:
                choices = [(B, C, D)] + ([] if no_optional_alternative else [(B, D)])
            else:
                choices = [(C, B, D)]
            for currencies in choices:
                row = branch(amount, currencies)
                if source == ZERO:
                    row['hops'].insert(0, {'kind': 'wrap', 'currencyOut': A})
                yield [row], ['fixture-provider']
        adapter.async_nominations = nominations
        async def price(hops, amount, block, bank, canonical):
            priced.append(tuple(row['pool']['token1' if row['zeroForOne'] else 'token0']['address'].lower()
                                for row in hops if 'pool' in row))
            return amount, amount
        async def conversion(*args, **options):
            return await adapter.convert(*args, **options, price_path=price)
        q = SimpleNamespace(core=D, engine=engine, amm=adapter, conversion=conversion)
        req = request(inputs=[{'currency': ZERO if native else A, 'amount': '100'}])
        return q, req, priced

    def test_common_nomination_filter_excludes_an_opposed_split(self):
        crossed = [branch(50, (A, B, C, D)), branch(50, (A, C, B, D))]
        self.assertEqual(list(adapt_candidates([(crossed, [])], A, D)), [])
        self.assertEqual(len(list(adapt_candidates([(crossed, [])], A, D, amount=1))), 1)

    async def test_nominal_and_detailed_choices_keep_compatible_existing_alternatives(self):
        for first in (True, False):
            for native in (False, True):
                with self.subTest(first=first, native=native):
                    q, req, priced = self.producer(native=native)
                    with patch('cybergold_candidate.quoter.evaluate.observed_market_amount', return_value=10):
                        value = await evaluate_candidate(q, req, 100, 'core-first', None,
                                                         [B, C], [500000, 500000], first=first)
                    self.assertIsNone(conflicting_pool(body_directions(req, value['plan']['body'])))
                    data = value['plan']['body']['branches'][0]['data']
                    self.assertEqual(len(data['acquisitions'][1]['route']['routes'][0]['steps']), 1)
                    self.assertEqual(len(data['continuations'][0]['route']['routes'][0]['steps']), 1)
                    self.assertEqual(len(data['continuations'][1]['route']['routes'][0]['steps']), 2)
                    self.assertNotIn((B.lower(), C.lower()), priced)
                    self.assertNotIn((C.lower(), D.lower()), priced)

    async def test_optional_nominal_and_detailed_conflicts_keep_the_retaining_placeholder(self):
        for first in (True, False):
            with self.subTest(first=first):
                q, req, _ = self.producer(no_optional_alternative=True)
                with patch('cybergold_candidate.quoter.evaluate.observed_market_amount', return_value=10):
                    value = await evaluate_candidate(q, req, 100, 'core-first', None,
                                                     [B, C], [500000, 500000], first=first)
                data = value['plan']['body']['branches'][0]['data']
                self.assertEqual(data['continuations'][0]['route'], route(B))
                self.assertIsNone(conflicting_pool(body_directions(req, value['plan']['body'])))

    async def test_unknown_core_split_is_not_admitted_at_its_nominal_one_unit(self):
        for first in (True, False):
            with self.subTest(first=first):
                q, req, _ = self.producer()
                async def nominations(source, target, amount, block, **options):
                    rows = ([branch(amount, (A, B))] if source == A else
                            [branch(1, (B, A, D)), branch(1, (B, D))])
                    yield rows, []
                q.amm.async_nominations = nominations
                with patch('cybergold_candidate.quoter.evaluate.observed_market_amount', return_value=1):
                    value = await evaluate_candidate(q, req, 100, 'core-first', None, [B], [1_000_000], first=first)
                self.assertEqual(value['plan']['body']['branches'][0]['data']['continuations'][0]['route'], route(B))

    def dormant_value(self, extra_paths):
        body = core_body([{'amountIn': '10', 'route': route(A, B)}], [route(B)])
        conversions = {'0:acquire:0': {'inputCurrency': A, 'outputCurrency': B,
            'branches': [{'hops': branch(10, (A, B))['hops']}], 'template': route(A, B)}}
        if extra_paths:
            body['branches'].append({'kind': 1, 'amountIn': '0',
                'data': {'route': route(A, C, B, D), 'feeCygld': '0'}})
            conversions['1:market'] = {'inputCurrency': A, 'outputCurrency': D,
                'branches': [{'hops': branch(0, (A, C, B, D))['hops']}], 'template': route(A, C, B, D)}
        return {'request': request(), 'plan': {'body': body, 'conversions': conversions},
                'context': {'chainId': 1}, 'pricingEvidence': {'stages': [
                    {'fundedInput': '10', 'consumedInput': '10', 'returnedInput': '0', 'amountOut': '10'},
                    {'fundedInput': '10', 'consumedInput': '10', 'returnedInput': '0', 'amountOut': '7'}]}}

    def test_dormant_enrichment_chooses_a_compatible_longer_path_or_leaves_placeholder(self):
        for extra in (False, True):
            with self.subTest(extra_paths=extra):
                value = self.dormant_value(extra)
                original = deepcopy(value)
                result = with_dormant_routes(value, pool(A, D))
                self.assertEqual(value, original)
                selected = result['plan']['body']['branches'][0]['data']['continuations'][0]['route']
                self.assertIsNone(conflicting_pool(body_directions(value['request'], result['plan']['body'])))
                self.assertEqual(len(selected['routes'][0]['steps']) if selected['routes'] else 0, 3 if extra else 0)


if __name__ == '__main__':
    unittest.main()
