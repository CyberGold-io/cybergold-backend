"""Actual SDK inverse/forward agreement and unsigned execution preparation."""
from copy import deepcopy
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.quoter.amm import PartialPath
from cybergold_candidate.quoter.contracts import capture_paths
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.prefix import repair_prefix
from cybergold_candidate.quoter.capacity_recovery import recover_selected
from cybergold_candidate.quoter.evaluate import encode_nomination, replay_conversion
from cybergold_candidate.quoter.inverse import inverse_conversion
from cybergold_candidate.routing_encoding import split_runtime
from cybergold_candidate.tx_preparation import TransactionPreparation
from quoter_fixture import service, synthetic_pool, basis
from test_universal_quote import BLOCK, CORE, PAXG, OTHER, WETH, USER


class PrefixTests(unittest.IsolatedAsyncioTestCase):
    async def test_paid_remainder_uses_real_sdk_prefix_without_reading_downstream_pool(self):
        from cybergold_candidate.routing_encoding import ZERO
        pools = [synthetic_pool(WETH, PAXG, 590, 'v2'), synthetic_pool(PAXG, CORE, 591, 'v4')]
        route = [{'pool': pool, 'zeroForOne': source.lower() == pool['token0']['address'].lower()}
                 for source, pool in zip([WETH, PAXG], pools)]
        q = service(self, pools)
        request = {'intent': 0, 'inputs': [{'currency': ZERO, 'amount': '10000'}], 'outputCurrency': CORE}
        selected = market_plan(ZERO, CORE, [{'kind': 'wrap', 'currencyOut': WETH}] + route,
                               10000, origins=['uniroute-local'])
        with capture_paths(), self.assertRaises(PartialPath) as caught:
            await q.price_path(route, 10000, BLOCK, {}, {})
        partial = caught.exception.trace.hops[-1]
        remainder = {'currency': PAXG, 'amount': str(partial.funded-partial.consumed)}
        original, observed = q.engine.registry.snapshot, []
        async def only_prefix(pool, block):
            observed.append(pool['id'])
            if pool['id'] == pools[1]['id']:
                raise AssertionError('Paid remainder must not scan the downstream pool')
            return await original(pool, block)
        q.engine.registry.snapshot = only_prefix
        repaired, = await recover_selected(q, request, selected, BLOCK, {}, unsettled=remainder)
        self.assertEqual(repaired['inputs'][0]['amount'], '3025')
        self.assertEqual(observed, [pools[0]['id']])
        self.assertEqual(repaired['plan']['conversions'], selected['conversions'])
        q.engine.registry.snapshot = original
        value = await q.candidate({**request, 'inputs': repaired['inputs']}, 0, 'core-first',
            BLOCK, *await basis(BLOCK), selected=repaired['plan'])
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(value['estimatedRetainedInputCharges'], [])

    async def test_ambiguous_paid_remainder_retains_ordinary_forward_diagnostic(self):
        pools = [synthetic_pool(WETH, PAXG, 595, 'v2'), synthetic_pool(PAXG, CORE, 596, 'v4')]
        route = [{'pool': pool, 'zeroForOne': source.lower() == pool['token0']['address'].lower()}
                 for source, pool in zip([WETH, PAXG], pools)]
        q = service(self, pools)
        selected = market_plan(WETH, CORE, route, 10000)
        selected['conversions']['unused-matching-path'] = deepcopy(selected['conversions']['0:market'])
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        original, observed = q.engine.registry.snapshot, []
        async def snapshot(pool, block):
            observed.append(pool['id'])
            return await original(pool, block)
        q.engine.registry.snapshot = snapshot
        repaired, = await recover_selected(q, request, selected, BLOCK, {},
                                          unsettled={'currency': PAXG, 'amount': '1'})
        self.assertIn(pools[1]['id'], observed)
        self.assertEqual(repaired['inputs'][0]['amount'], '3025')

    async def test_actual_sdk_failed_native_market_plan_reuses_prefix_without_losing_topology(self):
        from cybergold_candidate.routing_encoding import ZERO
        pools = [synthetic_pool(WETH, PAXG, 601, 'v2'), synthetic_pool(PAXG, CORE, 602, 'v4')]
        hops = [{'pool': pool, 'zeroForOne': source.lower() == pool['token0']['address'].lower()}
                for source, pool in zip([WETH, PAXG], pools)]
        route = [{'kind': 'wrap', 'currencyOut': WETH}] + hops
        q = service(self, pools)
        request = {'intent': 0, 'inputs': [{'currency': ZERO, 'amount': '10000'}], 'outputCurrency': CORE}
        selected = market_plan(ZERO, CORE, route, 10000, origins=['uniroute-local'])
        before, canonical = deepcopy(selected), {}
        proposals = await recover_selected(q, request, selected, BLOCK, canonical)
        self.assertEqual(len(proposals), 1)
        repaired = proposals[0]
        self.assertEqual(repaired['inputs'][0]['amount'], '3025')
        self.assertEqual(repaired['inputs'][0]['currency'], ZERO)
        chosen = repaired['plan']['conversions']['0:market']
        self.assertEqual(chosen, selected['conversions']['0:market'])
        self.assertEqual(chosen['template']['inputCurrency'].lower(), WETH.lower())
        value = await q.candidate({**request, 'inputs': repaired['inputs']}, 0, 'core-first',
            BLOCK, *await basis(BLOCK), selected=repaired['plan'])
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(value['estimatedRetainedInputCharges'], [])
        self.assertEqual(selected, before)
        self.assertTrue(canonical)
        self.assertEqual(q.engine.registry.observed, q.engine.registry.inventory)

    async def test_actual_sdk_split_repair_preserves_weights_and_forward_branch_order(self):
        from cybergold_candidate.routing_encoding import weighted_routes
        pools = [synthetic_pool(WETH, CORE, 610, 'v2'), synthetic_pool(WETH, PAXG, 611, 'v2'),
                 synthetic_pool(PAXG, CORE, 612, 'v4')]
        def hop(pool, source):
            return {'pool': pool, 'zeroForOne': source.lower() == pool['token0']['address'].lower()}
        branches = [{'amountIn': '5000', 'hops': [hop(pools[0], WETH)]},
                    {'amountIn': '5001', 'hops': [hop(pools[1], WETH), hop(pools[2], PAXG)]}]
        selected = market_plan(WETH, CORE, branches[1]['hops'], 10001, origins=['uniswap-alpharouter'])
        chosen = selected['conversions']['0:market']
        chosen['branches'] = [{'hops': row['hops']} for row in branches]
        chosen['template']['routes'] = weighted_routes(branches)
        selected['body']['branches'][0]['data']['route'] = deepcopy(chosen['template'])
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10001'}], 'outputCurrency': CORE}
        q = service(self, pools)
        repaired, = await recover_selected(q, request, selected, BLOCK, {})
        # The original template's rounded preceding share funds 4999/5002;
        # retaining those exact weights yields a conservative 6048 proposal.
        self.assertEqual(repaired['inputs'][0]['amount'], '6048')
        self.assertEqual(repaired['plan']['conversions'], selected['conversions'])
        value = await q.candidate({**request, 'inputs': repaired['inputs']}, 0, 'core-first',
            BLOCK, *await basis(BLOCK), selected=repaired['plan'])
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(value['estimatedRetainedInputCharges'], [])

    async def test_actual_sdk_core_acquisition_repair_keeps_containing_plan_and_shared_prefix_state(self):
        from cybergold_candidate.routing_encoding import weighted_routes
        pools = [synthetic_pool(WETH, OTHER, 620, 'v2'), synthetic_pool(OTHER, PAXG, 621, 'v4')]
        def hop(pool, source):
            return {'pool': pool, 'zeroForOne': source.lower() == pool['token0']['address'].lower()}
        first, second = [hop(pools[0], WETH)], [hop(pools[0], WETH), hop(pools[1], OTHER)]
        def conversion(route, target):
            template = {'inputCurrency': WETH, 'outputCurrency': target,
                        'routes': weighted_routes([{'amountIn': '1', 'hops': route}])}
            return {'inputCurrency': WETH, 'outputCurrency': target,
                    'branches': [{'hops': route}], 'template': template, 'discoveryOrigins': ['uniroute-local']}
        a, b = conversion(first, OTHER), conversion(second, PAXG)
        selected = {'allocations': [{'kind': 0, 'amountIn': '20000'}],
            'conversions': {'0:acquire:0': a, '0:acquire:1': b},
            'body': {'branches': [{'kind': 0, 'amountIn': '20000', 'data': {
                'basketAssets': [OTHER, PAXG],
                'acquisitions': [{'amountIn': '10000', 'route': deepcopy(a['template'])},
                                 {'amountIn': '10000', 'route': deepcopy(b['template'])}],
                'continuations': [{'route': {'inputCurrency': asset, 'outputCurrency': asset, 'routes': []},
                                   'feeCygld': '0'} for asset in [OTHER, PAXG]]}}]}}
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '20000'}], 'outputCurrency': CORE}
        q = service(self, pools)
        calls, original = [], q.engine.sdk.request
        async def observed(payload, *args, **kwargs):
            if payload.get('operation') == 'quote' and payload.get('mode') == 'exactOut':
                calls.append(deepcopy(payload))
            return await original(payload, *args, **kwargs)
        q.engine.sdk.request = observed
        repaired, = await recover_selected(q, request, selected, BLOCK, {})
        self.assertEqual(len(calls), 1)
        inverse_pool = calls[0]['pools'][0]
        self.assertNotEqual((inverse_pool['reserve0'], inverse_pool['reserve1']),
                            (pools[0]['reserve0'], pools[0]['reserve1']))
        self.assertEqual(repaired['plan']['conversions'], selected['conversions'])
        data = repaired['plan']['body']['branches'][0]['data']
        self.assertEqual(data['acquisitions'][0]['amountIn'], '10000')
        self.assertLess(int(data['acquisitions'][1]['amountIn']), 10000)
        self.assertEqual(repaired['inputs'][0]['amount'], str(sum(int(row['amountIn']) for row in data['acquisitions'])))
        self.assertEqual(repaired['plan']['allocations'][0]['amountIn'], repaired['inputs'][0]['amount'])
        self.assertEqual(q.engine.registry.observed, q.engine.registry.inventory)

    async def test_unknown_core_generated_lots_do_not_invent_later_pool_state(self):
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10'}], 'outputCurrency': CORE}
        selected = {'allocations': [{'kind': 0, 'amountIn': '5'}, {'kind': 1, 'amountIn': '5'}],
            'conversions': {}, 'body': {'branches': [
                {'kind': 0, 'amountIn': '5', 'data': {'basketAssets': [PAXG, WETH],
                    'acquisitions': [{'amountIn': '0'}, {'amountIn': '5'}], 'continuations': [
                    {'route': {'inputCurrency': PAXG, 'outputCurrency': CORE, 'routes': [{'sharePpm': 0, 'steps': []}]}}]}},
                {'kind': 1, 'amountIn': '5', 'data': {}}]}}
        q = SimpleNamespace(price_path=AsyncMock(side_effect=AssertionError('Unknown residual cannot be replayed')))
        self.assertEqual(await recover_selected(q, request, selected, BLOCK, {}), [])
        q.price_path.assert_not_awaited()

    async def test_native_prefix_amount_is_proposed_without_sdk_fill_certification(self):
        from cybergold_candidate.exact_input_plan import compile_plan
        from cybergold_candidate.quoter.contracts import PathTrace, HopTrace
        from cybergold_candidate.quoter.plan_call import executable_body
        from cybergold_candidate.routing_encoding import ZERO
        pools = [synthetic_pool(WETH, PAXG, 501, 'v2'), synthetic_pool(PAXG, CORE, 502, 'v2')]
        hops = [{'pool': pool, 'zeroForOne': source.lower() == pool['token0']['address'].lower()}
                for source, pool in zip([WETH, PAXG], pools)]
        trace = PathTrace(hops, 1000, '0:market', 0, 0, [
            HopTrace(hops[0], 1000, 1000, 100, deepcopy(pools[0])),
            HopTrace(hops[1], 100, 80, 10, deepcopy(pools[1]))])
        sdk = SimpleNamespace(request=AsyncMock(return_value={
            'amountIn': '40', 'amountOut': '81', 'fullyFilled': False}))
        q = SimpleNamespace(engine=SimpleNamespace(sdk=sdk, semaphore=asyncio.Semaphore(8),
                                                   registry=SimpleNamespace(chain=1)))
        request = {'intent': 0, 'inputs': [{'currency': ZERO, 'amount': '1000'}], 'outputCurrency': CORE}
        funding, plan = await repair_prefix(q, request, trace, BLOCK)
        self.assertEqual(funding[0]['amount'], '40')
        self.assertEqual(plan['body']['branches'][0]['data']['route']['inputCurrency'].lower(), WETH.lower())
        compiled = compile_plan({**request, 'inputs': funding, 'recipient': USER, 'deadline': '0'},
                                executable_body(plan['body']), 1)
        self.assertTrue(compiled['body'].startswith('0x'))
        sdk.request.assert_awaited_once()

    async def test_twelve_actual_sdk_repairs_and_rounding_neighbors(self):
        for shape in ['two-last', 'three-last', 'three-middle']:
            for v4 in [False, True]:
                for liquidity in [10**6, 1000003]:
                    with self.subTest(shape=shape, v4=v4, liquidity=liquidity):
                        currencies = [WETH, PAXG, CORE] if shape == 'two-last' else [WETH, OTHER, PAXG, CORE]
                        partial = len(currencies)-2 if shape.endswith('last') else 1
                        pools = [synthetic_pool(a, b, 101+i,
                            'v4' if v4 and i == len(currencies)-2 else 'v3' if i == partial else 'v2',
                            liquidity if i == partial else 10**12)
                            for i, (a, b) in enumerate(zip(currencies, currencies[1:]))]
                        route = [{'pool': pool, 'zeroForOne': source.lower() == pool['token0']['address'].lower()}
                                 for source, pool in zip(currencies, pools)]
                        q = service(self, pools)
                        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
                        original = market_plan(WETH, CORE, route, 10000)
                        with capture_paths(), self.assertRaises(PartialPath) as caught:
                            await q.candidate(request, 0, 'core-first', BLOCK, *await basis(BLOCK), selected=original)
                        trace = caught.exception.trace
                        self.assertTrue(all(row.pre_state is not None for row in trace.hops))
                        proposal = await repair_prefix(q, request, trace, BLOCK, origins=['uniroute-local'])
                        funding, plan = proposal
                        self.assertIn(int(funding[0]['amount']), [3025, 3035])
                        value = await q.candidate({**request, 'inputs': funding}, 0, 'core-first',
                            BLOCK, *await basis(BLOCK), selected=plan)
                        value['request'] = deepcopy(request)
                        self.assertEqual(value['plan']['conversions']['0:market']['discoveryOrigins'], ['uniroute-local'])
                        self.assertEqual(value['estimatedRetainedInputCharges'], [])
                        prepared = await TransactionPreparation(q).prepare({'quote': value, 'sender': USER, 'recipient': USER})
                        self.assertEqual(prepared['plan']['inputs'], funding)
                        self.assertEqual(prepared['economicQuote']['quotedOutput'], value['quotedOutput'])
                        self.assertEqual(value['request']['inputs'][0]['amount'], '10000')
                        less = int(funding[0]['amount']) - 1
                        neighboring = await q.candidate({**request, 'inputs': [{**funding[0], 'amount': str(less)}]},
                            0, 'core-first', BLOCK, *await basis(BLOCK), selected=market_plan(WETH, CORE, route, less))
                        self.assertEqual(neighboring['quotedOutput'], value['quotedOutput'])
                        extra = int(funding[0]['amount']) + 1
                        with self.assertRaisesRegex(Exception, 'Unsettled current-operation'):
                            await q.candidate({**request, 'inputs': [{**funding[0], 'amount': str(extra)}]},
                                0, 'core-first', BLOCK, *await basis(BLOCK), selected=market_plan(WETH, CORE, route, extra))

    async def test_acquired_zero_consumption_paths_do_not_invent_a_repair(self):
        from quoter_fixture import historical_service, historical_data, historical_route
        q, case = historical_service(self)
        block = historical_data()['anchor']
        for row in case['partialRoutes']:
            route = historical_route(q, row)
            with capture_paths(), self.assertRaises(PartialPath) as caught:
                await q.candidate(case['request'], 0, 'core-first', block, *case['basis'],
                    selected=market_plan(case['request']['inputs'][0]['currency'], q.core, route, 500000000))
            self.assertEqual(caught.exception.trace.hops[-1].consumed, 0)
            self.assertIsNone(await repair_prefix(q, case['request'], caught.exception.trace, block))

    async def test_native_and_repeated_pool_traces_decline(self):
        from cybergold_candidate.quoter.contracts import PathTrace
        pool = synthetic_pool(WETH, CORE, 1, 'v2'); q = service(self, [pool])
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        for route in [[{'kind': 'wrap', 'currencyOut': WETH}], [{'pool': pool, 'zeroForOne': True}]*2]:
            trace = PathTrace(route, 10000, '0:market', 0, 0)
            self.assertIsNone(await repair_prefix(q, request, trace, BLOCK))
        native = {**request, 'inputs': [{'currency': '0x' + '00'*20, 'amount': '10000'}]}
        trace = PathTrace([{'pool': pool, 'zeroForOne': True}], 10000, '0:market', 0, 0)
        self.assertIsNone(await repair_prefix(q, native, trace, BLOCK))


class InverseConversionTests(unittest.IsolatedAsyncioTestCase):
    def chosen(self, routes, source=WETH, target=CORE):
        return encode_nomination(source, target, (routes, ['uniroute-local']))[1]

    async def test_native_single_path_target_and_private_state_are_forward_replayed(self):
        from cybergold_candidate.routing_encoding import ZERO
        pool = synthetic_pool(WETH, CORE, 701, 'v2')
        hop = {'pool': pool, 'zeroForOne': pool['token0']['address'].lower() == WETH.lower()}
        chosen = self.chosen([{'amountIn': '10000', 'hops': [{'kind': 'wrap', 'currencyOut': WETH}, hop]}],
                             source=ZERO)
        original = deepcopy(chosen)
        q = service(self, [pool])
        bank, canonical = {}, {}
        amount, resized = await inverse_conversion(q, chosen, ZERO, CORE, 10000, 5000, BLOCK, bank, canonical)
        self.assertLess(amount, 10000)
        self.assertEqual(resized['inputCurrency'], ZERO)
        self.assertEqual(resized['template']['inputCurrency'].lower(), WETH.lower())
        independent = {}
        _, output, retained = await replay_conversion(q, deepcopy(resized), ZERO, CORE, amount,
                                                       BLOCK, independent, canonical)
        self.assertEqual(output, 5000)
        self.assertEqual(retained, [])
        self.assertEqual(bank, independent)
        self.assertEqual(chosen, original)
        self.assertEqual(q.engine.registry.observed, q.engine.registry.inventory)

    async def test_split_shared_pool_uses_actual_ppm_lots_and_changed_forward_state(self):
        pool = synthetic_pool(WETH, CORE, 702, 'v2')
        hop = {'pool': pool, 'zeroForOne': pool['token0']['address'].lower() == WETH.lower()}
        chosen = self.chosen([{'amountIn': '50000000', 'hops': [hop]},
                              {'amountIn': '50000000', 'hops': [hop]}])
        original = deepcopy(chosen)
        q = service(self, [pool])
        bank, canonical = {}, {}
        amount, resized = await inverse_conversion(q, chosen, WETH, CORE, 100000000, 45000001,
                                                    BLOCK, bank, canonical)
        self.assertLess(amount, 100000000)
        lots = split_runtime(amount, resized['template']['routes'])
        self.assertEqual(sum(lots), amount)
        # An independent constant-product calculation observes each split's
        # updated reserve, rather than treating both paths as independent pools.
        x = y = 10**9
        expected = 0
        for lot in lots:
            received = lot * 997 * y // (x * 1000 + lot * 997)
            expected += received
            x, y = x + lot, y - received
        independent = {}
        _, output, retained = await replay_conversion(q, deepcopy(resized), WETH, CORE, amount,
                                                       BLOCK, independent, canonical)
        self.assertEqual(output, expected)
        self.assertEqual(retained, [])
        self.assertEqual(bank, independent)
        self.assertEqual(chosen, original)
        self.assertEqual(q.engine.registry.observed, q.engine.registry.inventory)

    async def test_inverse_failure_keeps_preceding_bank_and_original_topology(self):
        pool = synthetic_pool(WETH, CORE, 703, 'v2')
        hop = {'pool': pool, 'zeroForOne': pool['token0']['address'].lower() == WETH.lower()}
        chosen = self.chosen([{'amountIn': '10000', 'hops': [hop]}])
        q = service(self, [pool])
        bank = {pool['id']: deepcopy(pool)}
        bank[pool['id']]['reserve0'] = '1000000001'
        original, before = deepcopy(chosen), deepcopy(bank)
        request = q.engine.sdk.request
        async def unavailable(value, *args, **kwargs):
            if value.get('mode') == 'exactOut':
                raise ValueError('ordinary inverse failure')
            return await request(value, *args, **kwargs)
        q.engine.sdk.request = unavailable
        with self.assertRaisesRegex(ValueError, 'ordinary inverse failure'):
            await inverse_conversion(q, chosen, WETH, CORE, 10000, 5000, BLOCK, bank, {})
        self.assertEqual(bank, before)
        self.assertEqual(chosen, original)

    async def test_one_unit_split_target_keeps_zero_lot_topology_and_rounds_at_execution(self):
        pools = [synthetic_pool(WETH, CORE, number, 'v2') for number in (704, 705)]
        branches = [{'amountIn': '5000', 'hops': [{'pool': pool,
            'zeroForOne': pool['token0']['address'].lower() == WETH.lower()}]} for pool in pools]
        chosen = self.chosen(branches)
        q = service(self, pools)
        bank, canonical = {}, {}
        amount, resized = await inverse_conversion(q, chosen, WETH, CORE, 10000, 1, BLOCK, bank, canonical)
        self.assertEqual(split_runtime(amount, resized['template']['routes']), [0, amount])
        self.assertEqual(len(resized['branches']), 2)
        _, output, retained = await replay_conversion(q, deepcopy(resized), WETH, CORE, amount,
                                                       BLOCK, {}, canonical)
        self.assertEqual(output, 1)
        self.assertEqual(retained, [])

    async def test_repeated_pool_occurrences_advance_the_changed_plan_once(self):
        pool = synthetic_pool(WETH, PAXG, 706, 'v2')
        finish = synthetic_pool(WETH, CORE, 707, 'v2')
        first = {'pool': pool, 'zeroForOne': pool['token0']['address'].lower() == WETH.lower()}
        route = [first, {**deepcopy(first), 'zeroForOne': not first['zeroForOne']},
                 {'pool': finish, 'zeroForOne': finish['token0']['address'].lower() == WETH.lower()}]
        chosen = self.chosen([{'amountIn': '100000000', 'hops': route}])
        q = service(self, [pool, finish])
        bank, canonical = {}, {}
        amount, resized = await inverse_conversion(q, chosen, WETH, CORE, 100000000, 25000000,
                                                    BLOCK, bank, canonical)
        self.assertLess(amount, 100000000)
        expected, states = amount, {p['id']: [10**9, 10**9] for p in (pool, finish)}
        for hop in route:
            reserves = states[hop['pool']['id']]
            left, right = (0, 1) if hop['zeroForOne'] else (1, 0)
            received = expected * 997 * reserves[right] // (reserves[left] * 1000 + expected * 997)
            reserves[left] += expected
            reserves[right] -= received
            expected = received
        independent = {}
        _, output, retained = await replay_conversion(q, deepcopy(resized), WETH, CORE, amount,
                                                       BLOCK, independent, canonical)
        self.assertEqual(output, expected)
        self.assertEqual(retained, [])
        self.assertEqual(bank, independent)
        self.assertEqual(q.engine.registry.observed, q.engine.registry.inventory)

    async def test_identity_and_zero_targets_need_no_sdk_or_route_metadata(self):
        chosen = {'logical': 'identity'}
        q = SimpleNamespace()
        for source, target, desired in [(WETH, WETH, 7), (WETH, CORE, 0)]:
            amount, resized = await inverse_conversion(q, chosen, source, target, 10000, desired,
                                                        BLOCK, {}, {})
            self.assertEqual(amount, desired)
            self.assertEqual(resized, chosen)
            self.assertIsNot(resized, chosen)


if __name__ == '__main__':
    unittest.main()
