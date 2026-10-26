"""Warm indicative models follow shared facts without discovery or RPC."""
from copy import deepcopy
from unittest.mock import Mock, AsyncMock
import unittest

from cybergold_candidate.market_swap import market_route_observation_identity
from cybergold_candidate.market_fee import quoted_fee
from cybergold_candidate.quote_models import LegModel
from test_market_sample_observations import fixture, CONTEXT, POOL


def observation(pool, *, output=30_000_000, block=124, hash_part='cd'):
    return {**deepcopy(pool), 'reserve0': str(output), 'reserve1': '10000000',
        'context': {**CONTEXT, 'blockNumber': str(block), 'blockHash': '0x'+hash_part*32,
                    'observedAt': '2026-10-26T13:00:00.000Z'}}


class MarketModelRefreshTests(unittest.TestCase):
    def test_changed_shared_facts_refresh_prediction_and_unchanged_facts_reuse_parameters(self):
        service, request, _, _ = fixture()
        pool = service.packet(request)['routes'][0]['route']['branches'][0]['hops'][0]['pool']
        state = observation(pool)
        service.registry.observed = {POOL: state}
        service.route_baseline = AsyncMock(side_effect=AssertionError('must not acquire state'))
        service.baseline_from_states = Mock(wraps=service.baseline_from_states)
        service.now = Mock(side_effect=AssertionError('no newly observed market time'))
        refreshed = service.packet(request)
        row = refreshed['routes'][0]
        self.assertEqual(row['exchangeRate'], {'numerator': '3', 'denominator': '1'})
        self.assertEqual(row['sourceContext'], state['context'])
        self.assertEqual(row['sourceObservations'], [{'poolId': POOL, 'context': state['context']}])
        self.assertEqual(refreshed['context'], CONTEXT)
        self.assertEqual(row['points'][0]['context'], CONTEXT)
        self.assertNotEqual(service.estimate(refreshed, request), '776')
        expected = LegModel(baseline=service.baseline(state, False)).predict(1002, 'local')
        self.assertEqual(service.estimate(refreshed, request), str(expected - quoted_fee(expected, 1000)))
        again = service.packet(request)
        self.assertEqual(again, refreshed)
        self.assertEqual(service.baseline_from_states.call_count, 1)
        service.route_baseline.assert_not_called()
        changed = observation(pool, output=40_000_000, block=125, hash_part='ef')
        service.registry.observed[POOL] = changed
        later = service.packet(request)
        self.assertEqual(later['routes'][0]['exchangeRate'], {'numerator': '4', 'denominator': '1'})
        self.assertNotEqual(service.estimate(later, request), service.estimate(refreshed, request))
        self.assertEqual(service.baseline_from_states.call_count, 2)

    def test_missing_shared_hop_keeps_last_advisory_parameters(self):
        service, request, _, _ = fixture()
        before = service.packet(request)
        service.registry.observed = {}
        self.assertEqual(service.packet(request), before)

    def test_mixed_source_hashes_cannot_reuse_packet_hash_for_exact_sample(self):
        service, request, result, _ = fixture()
        family = service.packet(request)['family']
        row = service.models[family]['routes'][0]
        first = row['route']['branches'][0]['hops'][0]
        middle = '0x'+'8'*40
        first['pool']['token0']['address'] = middle
        second = deepcopy(first)
        second['pool']['id'] = second['pool']['address'] = '0x'+'9'*40
        second['pool']['token1']['address'] = middle
        second['pool']['token0']['address'] = service.registry.core
        row['route']['branches'][0]['hops'].append(second)
        row['points'][0]['routeIdentity'] = market_route_observation_identity(row['route'])
        left = observation(first['pool'])
        right = observation(second['pool'], block=125, hash_part='ef')
        service.registry.observed = {left['id']: left, right['id']: right}
        packet = service.packet(request)
        self.assertIsNone(packet['routes'][0]['sourceContext'])
        self.assertEqual(len(packet['routes'][0]['sourceObservations']), 2)
        without = deepcopy(packet)
        without['routes'][0]['points'] = []
        self.assertEqual(service.estimate(packet, request), service.estimate(without, request))
        self.assertNotEqual(service.estimate(packet, request), '776')

    def test_observation_wall_clock_change_is_not_a_changed_immutable_fact(self):
        service, request, _, _ = fixture()
        pool = service.packet(request)['routes'][0]['route']['branches'][0]['hops'][0]['pool']
        state = observation(pool)
        service.registry.observed = {POOL: state}
        service.baseline_from_states = Mock(wraps=service.baseline_from_states)
        service.packet(request)
        state['context']['observedAt'] = '2026-10-26T14:00:00.000Z'
        again = service.packet(request)
        self.assertEqual(service.baseline_from_states.call_count, 1)
        self.assertEqual(again['routes'][0]['sourceContext']['observedAt'], '2026-10-26T13:00:00.000Z')


if __name__ == '__main__':
    unittest.main()
