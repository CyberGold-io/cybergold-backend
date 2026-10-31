"""Neighbor route resizing through actual SDK, whole plans and preparation."""
from copy import deepcopy
import unittest

from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.reuse_routes import (
    extract_blueprint, neighbor_proposals, resize_blueprint, selected_conversion)
from cybergold_candidate.routing_encoding import ZERO, weighted_routes
from cybergold_candidate.tx_preparation import TransactionPreparation
from quoter_fixture import service, synthetic_pool
from test_universal_quote import BLOCK, CORE, OTHER, PAXG, USER, WETH


def scalar(amount=10001, intent=0, native=False):
    return {'intent': intent, 'inputs': [{'currency': CORE if intent else ZERO if native else WETH,
                                       'amount': str(amount)}],
            'outputCurrency': (ZERO if native else WETH) if intent else CORE}


def topology(test):
    pools = [synthetic_pool(WETH, PAXG, 301, 'v2'),
             synthetic_pool(WETH, OTHER, 302, 'v3', liquidity=10**12),
             synthetic_pool(OTHER, PAXG, 303, 'v2'),
             synthetic_pool(PAXG, CORE, 304, 'v4', liquidity=10**12)]
    q = service(test, pools)
    current_assets = [PAXG, OTHER]
    async def basis(_):
        return list(current_assets), [500000, 500000]
    async def preview(mode, value, _):
        if mode == 'issue-exact-in':
            amounts = list(map(int, value['maximumAmountsIn']))
            matched = min(amounts)
            return {'netCygldOut': str(matched*2), 'amountsInExact': [str(matched)]*2,
                'orderedCoreAssets': list(current_assets),
                'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
        gross = int(value['grossCygldIn']); first = gross//2
        return {'projectedCoreOutputs': [
            {'kind': 0, 'token': current_assets[0], 'id': '0', 'amount': str(first)},
            {'kind': 1, 'token': OTHER, 'id': '7', 'amount': '3'},
            {'kind': 0, 'token': current_assets[1], 'id': '0', 'amount': str(gross-first)}],
            'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
    q.preview, q.basis_reader = preview, basis
    return q, current_assets


async def evaluate(q, request, plan):
    return await q.candidate(request, 100, 'core-first', BLOCK, *await q.basis(BLOCK), selected=plan)


class ReuseRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_sdk_protocols_native_wrap_and_fresh_preparation(self):
        for protocol in ('v2', 'v3', 'v4'):
            for native in (False, True):
                with self.subTest(protocol=protocol, native=native):
                    pool = synthetic_pool(WETH, CORE, 310, protocol, liquidity=10**12)
                    q = service(self, [pool])
                    source = ZERO if native else WETH
                    route = [{'pool': pool, 'zeroForOne': WETH.lower() == pool['token0']['address'].lower()}]
                    if native:
                        route.insert(0, {'kind': 'wrap', 'currencyOut': WETH})
                    previous = await evaluate(q, scalar(native=native), market_plan(source, CORE, route, 10001))
                    previous['quotedOutput'] = '99999999999999999999'
                    previous['fees']['marketFeeCygld'] = '999999999'
                    selected = neighbor_proposals(previous, 9001, (await q.basis(BLOCK))[0])[0]
                    current = scalar(9001, native=native)
                    result = await evaluate(q, current, selected['plan'])
                    direct = await evaluate(q, current, market_plan(source, CORE, route, 9001))
                    self.assertEqual(result['quotedOutput'], direct['quotedOutput'])
                    self.assertEqual(result['fees'], direct['fees'])
                    self.assertEqual(result['inputs'], selected['inputs'])
                    self.assertNotIn('999999999', repr(selected))
                    for chosen in selected['plan']['conversions'].values():
                        for branch in chosen['branches']:
                            for hop in branch['hops']:
                                if 'pool' in hop:
                                    self.assertFalse({'liquidity', 'tick', 'reserve0', 'context', 'ticks'} & hop['pool'].keys())
                    prepared = await TransactionPreparation(q).prepare({'quote': result, 'sender': USER, 'recipient': USER})
                    self.assertEqual(prepared['plan']['inputs'], result['inputs'])
                    self.assertEqual(prepared['economicQuote']['fees'], direct['fees'])

    async def test_core_buy_reordered_assets_both_orders_and_subpercent_lot(self):
        for order in ('core-first', 'market-first'):
            with self.subTest(order=order):
                q, current_assets = topology(self)
                old = await q.candidate(scalar(100000), 1, order, BLOCK, current_assets, [250000, 750000], first=True)
                # The selected ratio is intentionally outside the ordinary
                # 0/25/50/75/100 grid and remains below one percent.
                core_index = next(i for i, row in enumerate(old['plan']['allocations']) if row['kind'] == 0)
                core = old['plan']['body']['branches'][core_index]
                core['amountIn'] = old['plan']['allocations'][core_index]['amountIn'] = '400'
                core['data']['acquisitions'][0]['amountIn'] = '100'
                core['data']['acquisitions'][1]['amountIn'] = '300'
                old['inputs'][0]['amount'] = '99400'
                current_assets.reverse()
                proposal = neighbor_proposals(old, 49700, current_assets)[0]
                plan = proposal['plan']
                self.assertEqual([row['kind'] for row in plan['allocations']], [row['kind'] for row in old['plan']['allocations']])
                self.assertEqual(plan['allocations'][core_index]['amountIn'], '200')
                self.assertEqual([row['amountIn'] for row in plan['body']['branches'][core_index]['data']['acquisitions']], ['150', '50'])
                self.assertEqual(plan['body']['branches'][core_index]['data']['basketAssets'], current_assets)
                result = await evaluate(q, scalar(49700), plan)
                self.assertEqual(result['routeFamily'], 'mixed')
                self.assertEqual(result['inputs'][0]['amount'], '49700')
                self.assertNotIn('assetConversions', result['plan'])
                prepared = await TransactionPreparation(q).prepare({'quote': result, 'sender': USER, 'recipient': USER})
                self.assertEqual(prepared['plan']['inputs'], result['inputs'])

    async def test_rounded_zero_branch_remaps_all_operation_keys(self):
        for order in ('core-first', 'market-first'):
            with self.subTest(order=order):
                q, assets = topology(self)
                previous = await q.candidate(scalar(100000), 1, order, BLOCK, *await q.basis(BLOCK), first=True)
                # Market receives the integer remainder and its old branch
                # index must move when an earlier Core branch becomes zero.
                previous['plan']['allocations'][0]['amountIn'] = '1'
                previous['plan']['allocations'][1]['amountIn'] = '99999'
                previous['plan']['body']['branches'][0]['amountIn'] = '1'
                previous['plan']['body']['branches'][1]['amountIn'] = '99999'
                plan = neighbor_proposals(previous, 100, assets)[0]['plan']
                self.assertEqual(len(plan['allocations']), 1)
                self.assertEqual(plan['allocations'][0]['amountIn'], '100')
                self.assertTrue(all(operation.startswith('0:') for operation in plan['conversions']))
                self.assertEqual(plan['body']['branches'][0]['kind'], plan['allocations'][0]['kind'])
                result = await evaluate(q, scalar(100), plan)
                self.assertGreater(int(result['quotedOutput']), 0)
                prepared = await TransactionPreparation(q).prepare({'quote': result, 'sender': USER, 'recipient': USER})
                self.assertEqual(prepared['plan']['inputs'][0]['amount'], '100')

    async def test_zero_acquisition_slots_and_changed_asset_set(self):
        q, assets = topology(self)
        old = await q.candidate(scalar(100000), 100, 'core-first', BLOCK, *await q.basis(BLOCK), first=True)
        old['plan']['body']['branches'][0]['data']['acquisitions'][0]['amountIn'] = '0'
        old['plan']['body']['branches'][0]['data']['acquisitions'][1]['amountIn'] = '100000'
        resized = resize_blueprint(extract_blueprint(old), 999, assets)
        self.assertEqual([row['amountIn'] for row in resized['body']['branches'][0]['data']['acquisitions']], ['0', '999'])
        with self.assertRaisesRegex(InvalidPreview, 'asset set changed'):
            resize_blueprint(extract_blueprint(old), 999, [PAXG, WETH])

    async def test_core_sale_addresses_survive_interleaved_share_and_order_changes(self):
        q, assets = topology(self)
        old = await q.candidate(scalar(intent=1), 50, 'market-first', BLOCK, *await q.basis(BLOCK), first=True)
        assets.reverse()
        proposal = neighbor_proposals(old, 9000, assets)[0]
        self.assertTrue(proposal['plan']['assetConversions'])
        result = await evaluate(q, scalar(9000, intent=1), proposal['plan'])
        core_index = next(i for i, row in enumerate(result['plan']['allocations']) if row['kind'] == 0)
        for index in (0, 2):
            token = result['plan']['body']['branches'][core_index]['data']['expectedOutputs'][index]['token']
            chosen = result['plan']['conversions'][f'{core_index}:redeem:{index}']
            self.assertEqual(chosen['inputCurrency'].lower(), token.lower())
        self.assertEqual(result['recoveryShares'][0]['kind'], 1)
        self.assertNotIn('assetConversions', result['plan'])
        prepared = await TransactionPreparation(q).prepare({'quote': result, 'sender': USER, 'recipient': USER})
        self.assertEqual(prepared['economicQuote']['quotedOutput'], result['quotedOutput'])

    async def test_split_routes_keep_shares_and_reprice_changed_pool_state(self):
        pools = [synthetic_pool(WETH, CORE, 315 + index, protocol, liquidity=10**12)
                 for index, protocol in enumerate(('v2', 'v3'))]
        q = service(self, pools)
        hops = [[{'pool': pool, 'zeroForOne': WETH.lower() == pool['token0']['address'].lower()}] for pool in pools]
        original_plan = market_plan(WETH, CORE, hops[0], 10000000)
        chosen = original_plan['conversions']['0:market']
        chosen['branches'] = [{'hops': route} for route in hops]
        chosen['template']['routes'] = weighted_routes([
            {'hops': hops[0], 'amountIn': '2500000'}, {'hops': hops[1], 'amountIn': '7500000'}])
        old = await evaluate(q, scalar(10000000), original_plan)
        proposals = neighbor_proposals(old, 20000000, (await q.basis(BLOCK))[0])
        self.assertEqual([int(row['inputs'][0]['amount']) for row in proposals], [10000000, 20000000])
        resized = proposals[1]['plan']
        self.assertEqual(resized['conversions']['0:market']['template']['routes'], chosen['template']['routes'])
        pools[0]['reserve0'] = '2000000000'
        q.engine.registry.observed[pools[0]['id']] = deepcopy(pools[0])
        fresh = await evaluate(q, scalar(20000000), resized)
        self.assertNotEqual(fresh['quotedOutput'], str(int(old['quotedOutput'])*2))
        self.assertEqual(fresh['inputs'][0]['amount'], '20000000')

    def test_sale_alias_absence_does_not_fall_back_to_wrong_historical_ordinal(self):
        selected = {'assetConversions': {'0': {PAXG.lower(): {'inputCurrency': PAXG}}},
                    'conversions': {'0:redeem:0': {'inputCurrency': PAXG}}}
        self.assertIsNone(selected_conversion(selected, '0:redeem:0', OTHER))
        self.assertEqual(selected_conversion(selected, '0:redeem:3', PAXG)['inputCurrency'], PAXG)
        self.assertEqual(selected_conversion({'conversions': selected['conversions']}, '0:redeem:0', PAXG)['inputCurrency'], PAXG)


if __name__ == '__main__':
    unittest.main()
