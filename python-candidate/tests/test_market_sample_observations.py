"""Exact route observations retain their own state and raw fee coordinates."""
from collections import OrderedDict
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.market_swap import MarketQuotes, market_family
from cybergold_candidate.quote_models import PoolBaseline


CORE, COUNTER, ADAPTER, POOL = ('0x'+str(index)*40 for index in range(1, 5))
CONTEXT = {'chainId': 1, 'blockNumber': '123', 'blockHash': '0x'+'ab'*32,
           'observedAt': '2026-10-26T12:00:00.000Z'}


def fixture(side='buy', mode='exact-in'):
    request = {'side': side, 'mode': mode, 'counterToken': COUNTER, 'adapter': ADAPTER,
               'amount': '1000' if side == 'buy' and mode == 'exact-out' else '1002'}
    pool = {'id': POOL, 'address': POOL, 'protocol': 'v2', 'feePips': 3000,
            'token0': {'address': CORE, 'decimals': 18, 'chainId': 1},
            'token1': {'address': COUNTER, 'decimals': 6, 'chainId': 1}}
    raw_target = 1000 if side == 'sell' and mode == 'exact-in' else 1002
    raw_input = raw_target if mode == 'exact-in' else 333
    raw_output = 777 if mode == 'exact-in' else raw_target+1
    route = {'mode': 'exactIn' if mode == 'exact-in' else 'exactOut',
             'branches': [{'amountIn': str(raw_input) if mode == 'exact-in' else '0',
                           'hops': [{'pool': pool, 'zeroForOne': side == 'sell'}]}]}
    service = MarketQuotes.__new__(MarketQuotes)
    service.registry = SimpleNamespace(chain=1, core=CORE)
    service.generation = 'fork-a'
    family = market_family(request, 1, CORE)
    row = {'route': deepcopy(route), 'points': [], 'amountIn': '0', 'amountOut': '0',
           'exchangeRate': {'numerator': '2', 'denominator': '1'},
           'feeRetention': {'numerator': '1', 'denominator': '1'},
           'localImpact': {'numerator': '0', 'denominator': '1'}}
    service.models = OrderedDict({family: {'namespace': 'market', 'family': family,
        'intent': {name: request[name] for name in ('side', 'mode', 'counterToken', 'adapter')},
        'cygld': CORE, 'context': deepcopy(CONTEXT), 'routes': [row]}})
    result = {'amountIn': str(raw_input), 'amountOut': str(raw_output),
              'totalInput': '9999', 'netOutput': '1',
              'plan': {'route': deepcopy(route)}, 'context': deepcopy(CONTEXT)}
    service.remember_model_quote(request, result, 1000, raw_target, service.generation)
    return service, request, result, raw_target


class MarketSampleObservationTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_observations_apply_existing_fees_once_in_all_four_modes(self):
        expected = {('buy', 'exact-in'): '776', ('sell', 'exact-in'): '777',
                    ('buy', 'exact-out'): '333', ('sell', 'exact-out'): '334'}
        for (side, mode), output in expected.items():
            with self.subTest(side=side, mode=mode):
                service, request, result, raw_target = fixture(side, mode)
                packet = service.packet(request)
                self.assertEqual(service.estimate(packet, request), output)
                point = packet['routes'][0]['points'][0]
                self.assertEqual(point['amountIn'], result['amountIn'])
                self.assertEqual(point['amountOut'], result['amountOut'])
                self.assertEqual(point['requestedAmount'], str(raw_target))
                # Deliberately different total/net fields are not raw-route samples.
                self.assertNotEqual(point['amountIn'], result['totalInput'])
                self.assertNotEqual(point['amountOut'], result['netOutput'])

    def test_exact_output_matches_requested_target_not_rounded_excess(self):
        service, request, _, _ = fixture('sell', 'exact-out')
        packet = service.packet(request)
        self.assertEqual(packet['routes'][0]['points'][0]['amountOut'], '1003')
        self.assertEqual(service.estimate(packet, request), '334')
        # A request for 1003 has not been observed merely because the previous
        # 1002-target operation rounded up to 1003 output.
        without_points = deepcopy(packet)
        without_points['routes'][0]['points'] = []
        changed = {**request, 'amount': '1003'}
        self.assertEqual(service.estimate(packet, changed), service.estimate(without_points, changed))

    def test_sample_state_identity_ignores_observation_wall_clock(self):
        service, request, _, _ = fixture()
        packet = service.packet(request)
        packet['context']['observedAt'] = '2026-10-26T15:00:00.000Z'
        self.assertEqual(service.estimate(packet, request), '776')

    def test_legacy_or_incomplete_points_do_not_become_exact(self):
        service, request, _, _ = fixture()
        packet = service.packet(request)
        without_points = deepcopy(packet)
        without_points['routes'][0]['points'] = []
        baseline = service.estimate(without_points, request)
        point = packet['routes'][0]['points'][0]
        for missing in ('context', 'family', 'feeRatePpm', 'routeIdentity', 'requestedAmount'):
            with self.subTest(missing=missing):
                changed = deepcopy(packet)
                del changed['routes'][0]['points'][0][missing]
                self.assertEqual(service.estimate(changed, request), baseline)
        packet['routes'][0]['points'] = [{key: point[key] for key in ('amountIn', 'amountOut')}]
        self.assertEqual(service.estimate(packet, request), baseline)

    def test_other_state_route_fee_or_trade_family_uses_existing_baseline(self):
        service, request, _, _ = fixture()
        packet = service.packet(request)
        for field in ('state', 'chain', 'route', 'fee', 'family', 'amount'):
            with self.subTest(field=field):
                changed = deepcopy(packet)
                changed_request = deepcopy(request)
                if field == 'state':
                    changed['context']['blockHash'] = '0x'+'cd'*32
                elif field == 'chain':
                    changed['context']['chainId'] = 2
                    changed['routes'][0]['points'][0]['context']['chainId'] = 2
                elif field == 'route':
                    hop = changed['routes'][0]['route']['branches'][0]['hops'][0]
                    hop['zeroForOne'] = not hop['zeroForOne']
                elif field == 'fee':
                    changed['feeRatePpm'] = 2500
                elif field == 'family':
                    changed['routes'][0]['points'][0]['family'] = 'another-family'
                else:
                    changed_request['amount'] = '1003'
                without_points = deepcopy(changed)
                without_points['routes'][0]['points'] = []
                self.assertEqual(service.estimate(changed, changed_request),
                                 service.estimate(without_points, changed_request))

    def test_pool_address_enrichment_does_not_discard_an_identical_route_observation(self):
        service, request, _, _ = fixture()
        packet = service.packet(request)
        pool = packet['routes'][0]['route']['branches'][0]['hops'][0]['pool']
        pool['id'] = 'another-alias'
        pool['token0']['decimals'] = 6
        self.assertEqual(service.estimate(packet, request), '776')

    def test_matching_observation_works_without_approximate_baseline_parameters(self):
        service, request, _, _ = fixture()
        packet = service.packet(request)
        for name in ('exchangeRate', 'feeRetention', 'localImpact'):
            packet['routes'][0].pop(name)
        self.assertEqual(service.estimate(packet, request), '776')
        packet['routes'][0]['points'] = []
        self.assertIsNone(service.estimate(packet, request))

    def test_baseline_only_call_does_not_require_a_service_or_route_identity(self):
        service, request, _, _ = fixture()
        packet = service.packet(request)
        packet['routes'][0]['points'] = []
        del packet['routes'][0]['route']
        # Existing pure callers supply None instead of an instantiated service.
        self.assertEqual(MarketQuotes.estimate(None, packet, request), '2001')
        # A live service without samples also uses the cheap baseline path.
        self.assertEqual(service.estimate(packet, request), '2001')
        packet['routes'][0]['points'] = [{'amountIn': '1002', 'amountOut': '777'}]
        self.assertEqual(MarketQuotes.estimate(None, packet, request), '2001')

    async def test_refreshing_packet_context_does_not_relabel_retained_points(self):
        service, request, _, _ = fixture()
        pool = service.packet(request)['routes'][0]['route']['branches'][0]['hops'][0]['pool']
        service.registry.inventory = {pool['id']: pool}
        service.registry.seed = pool
        service.registry.ensure_loaded = AsyncMock()
        service.registry.get_rpc = lambda: SimpleNamespace()
        service.request_resolver = None
        service.now = lambda: '2026-10-26T15:00:00.000Z'
        service.route_baseline = AsyncMock(return_value=PoolBaseline(Fraction(2), Fraction(1), Fraction(0)))
        packet = await service.get_model(request, block={'number': 124, 'hash': '0x'+'cd'*32})
        self.assertEqual(packet['context']['blockHash'], '0x'+'cd'*32)
        self.assertEqual(packet['routes'][0]['points'][0]['context'], CONTEXT)
        without_points = deepcopy(packet)
        without_points['routes'][0]['points'] = []
        self.assertEqual(service.estimate(packet, request), service.estimate(without_points, request))

    async def test_sandbox_same_header_state_change_keeps_points_advisory(self):
        service, request, result, target = fixture()
        service.registry.chain = 31338
        result['context']['chainId'] = 31338
        service.remember_model_quote(request, result, 1000, target, service.generation)
        pool = result['plan']['route']['branches'][0]['hops'][0]['pool']
        service.registry.inventory = {pool['id']: pool}
        service.registry.seed = pool
        service.registry.ensure_loaded = AsyncMock()
        service.registry.get_rpc = lambda: SimpleNamespace()
        service.request_resolver = None
        service.now = lambda: '2026-10-26T15:00:00.000Z'
        service.route_baseline = AsyncMock(return_value=PoolBaseline(Fraction(3), Fraction(1), Fraction(0)))
        packet = await service.get_model(request, block={'number': 123, 'hash': CONTEXT['blockHash']})
        point = packet['routes'][0]['points'][-1]
        self.assertEqual(point['context']['chainId'], 31338)
        self.assertEqual(point['context']['blockHash'], packet['context']['blockHash'])
        self.assertEqual(point['amountOut'], '777')
        # The newly observed fork state prices 1002 -> 3006 gross, less fee 4.
        # Its unchanged header must not turn the older 777 observation exact.
        self.assertEqual(service.estimate(packet, request), '3002')

    def test_writer_keeps_same_amount_at_distinct_states_and_copies_context(self):
        service, request, result, target = fixture()
        result['context']['blockHash'] = '0x'+'cd'*32
        result['context']['blockNumber'] = '124'
        result['amountOut'] = '800'
        service.remember_model_quote(request, result, 1000, target, service.generation)
        result['context']['blockHash'] = 'mutated-after-save'
        points = service.packet(request)['routes'][0]['points']
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]['context'], CONTEXT)
        self.assertEqual(points[1]['context']['blockHash'], '0x'+'cd'*32)
        self.assertEqual(service.estimate(service.packet(request), request), '799')

    def test_writer_deduplicates_same_observation_and_preserves_legacy_coordinates(self):
        service, request, result, target = fixture()
        packet = service.models[market_family(request, 1, CORE)]
        packet['routes'][0]['points'].insert(0, {'amountIn': '5', 'amountOut': '10'})
        result['context']['observedAt'] = '2026-10-26T15:00:00.000Z'
        service.remember_model_quote(request, result, 1000, target, service.generation)
        points = service.packet(request)['routes'][0]['points']
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0], {'amountIn': '5', 'amountOut': '10'})
        self.assertEqual(points[1]['context']['observedAt'], result['context']['observedAt'])

    def test_capacity_sample_uses_recorded_funding_not_unspent_budget(self):
        service, request, result, target = fixture()
        result['amountIn'] = '500'
        result['plan']['route']['branches'][0]['amountIn'] = '500'
        service.remember_model_quote(request, result, 1000, target, service.generation)
        packet = service.packet(request)
        self.assertEqual(packet['routes'][0]['points'][-1]['requestedAmount'], '500')
        without_points = deepcopy(packet)
        without_points['routes'][0]['points'] = []
        # The full budget still matches the previously completed full-size
        # observation, not the smaller capacity sample's output.
        self.assertEqual(service.estimate(packet, request), '776')
        self.assertEqual(service.estimate(packet, {**request, 'amount': '500'}), '776')
        self.assertNotEqual(service.estimate(without_points, request), '776')

    def test_writer_keeps_existing_bounds_and_rejects_late_old_generation_publication(self):
        service, request, result, target = fixture()
        for number in range(124, 165):
            result['context'] = {**CONTEXT, 'blockNumber': str(number), 'blockHash': f'0x{number:064x}'}
            service.remember_model_quote(request, result, 1000, target, service.generation)
        self.assertEqual(len(service.packet(request)['routes'][0]['points']), 32)
        before = deepcopy(service.models)
        service.generation = 'fork-b'
        service.remember_model_quote(request, result, 1000, target, 'fork-a')
        self.assertEqual(service.models, before)


if __name__ == '__main__':
    unittest.main()
