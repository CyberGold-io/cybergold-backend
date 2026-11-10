"""Actual-SDK direct/mixed/sale funding and exact execution representation."""
from copy import deepcopy
import unittest

from cybergold_candidate.market_fee import quoted_fee
from cybergold_candidate.quoter.contracts import capture_paths
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.funding import funding_proposal, measured_funding_proposal, direct_basket_funding, supply_funding
from cybergold_candidate.quoter.ranking import prefer_completed
from cybergold_candidate.tx_preparation import TransactionPreparation
from quoter_fixture import historical_service, historical_data, historical_route, expand, service, basis
from test_universal_quote import BLOCK, USER


async def reprice_measured(q, value, block, assets, weights, observations):
    """Consume the active pure funding proposal through ordinary candidate replay."""
    proposal = measured_funding_proposal(value, q.engine.registry.chain)
    if proposal is None:
        return value
    funded, plan = proposal
    result = await q.candidate(funded, 100, 'core-first', block, assets, weights,
                               selected=plan, observations=observations, selection=False)
    result['request'] = deepcopy(value['request'])
    return result if prefer_completed(result, value, scalar=True) else value


class FundingTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_productive_core_branch_stays_mixed_after_selected_funding_changes(self):
        from test_universal_quote import Quotes, Engine, request as fixture_request
        q = Quotes(Engine())
        request = {key: value for key, value in fixture_request().items() if key in ('intent', 'inputs', 'outputCurrency')}
        initial = {**request, 'inputs': [{**request['inputs'][0], 'amount': '400'}]}
        value = await q.candidate(initial, 1, 'core-first', BLOCK, *await basis(BLOCK), first=True)
        selected = deepcopy(value['plan'])
        selected['allocations'][1]['amountIn'] = selected['body']['branches'][1]['amountIn'] = '9997'
        replayed = await q.candidate(request, 100, 'core-first', BLOCK, *await basis(BLOCK), selected=selected)
        self.assertEqual(replayed['routeFamily'], 'mixed')
        self.assertEqual([row['kind'] for row in replayed['plan']['body']['branches']], [0, 1])

    async def test_stopped_selection_still_allows_exact_finalization_replay(self):
        from cybergold_candidate.quote_budget import QuoteBudget, budget_context
        q, case = historical_service(self); block = historical_data()['anchor']
        row = next(row for row in case['routes'] if row['output'] == '1512123003848321271')
        value = await q.candidate(case['request'], 0, 'core-first', block, *case['basis'],
            selected=market_plan(case['request']['inputs'][0]['currency'], q.core, historical_route(q, row), 500000000))
        budget = QuoteBudget(); budget.finish_selection('best-initial')
        with budget_context(budget):
            smaller = await reprice_measured(q, value, block, *case['basis'], {})
        self.assertEqual(smaller['inputs'][0]['amount'], '198627782')
        self.assertEqual(smaller['quotedOutput'], value['quotedOutput'])
        self.assertEqual(smaller['searchCoverage'], value['searchCoverage'])

    async def test_zero_funded_branch_keeps_indices_and_productive_funding(self):
        from cybergold_candidate.quoter.contracts import new_path_trace
        from quoter_fixture import synthetic_pool
        from test_universal_quote import WETH, CORE
        q = service(self, [synthetic_pool(WETH, CORE, 44, 'v4')])
        route = [{'pool': q.engine.registry.seed, 'zeroForOne': False}]
        selected = market_plan(WETH, CORE, route, 100)
        first = selected['body']['branches'][0]
        selected['allocations'] = [{'kind': 1, 'amountIn': '100'}, {'kind': 1, 'amountIn': '200'}]
        selected['body']['branches'] = [first, {**deepcopy(first), 'amountIn': '200'}]
        selected['conversions']['1:market'] = deepcopy(selected['conversions']['0:market'])
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '300'}], 'outputCurrency': CORE}
        async def programmed(route, amount, *_):
            used, output = (0, 0) if amount == 100 else (amount, 778)
            trace = new_path_trace(route, amount)
            if trace is not None:
                trace.consumed, trace.output = used, output
            return used, output
        q.price_path = programmed
        original = await q.candidate(request, 0, 'core-first', BLOCK, *await basis(BLOCK), selected=selected)
        before = deepcopy(original)
        proposal = measured_funding_proposal(original, q.engine.registry.chain)
        self.assertIsNotNone(proposal)
        funded, plan = proposal
        self.assertEqual(funded['inputs'][0]['amount'], '200')
        self.assertEqual([row['amountIn'] for row in plan['body']['branches']], ['0', '200'])
        self.assertEqual([row['amountIn'] for row in plan['allocations']], ['0', '200'])
        self.assertEqual(plan['conversions'], original['plan']['conversions'])
        self.assertEqual([row['data'] for row in plan['body']['branches']],
                         [row['data'] for row in original['plan']['body']['branches']])
        # This component oracle compacts zero branches on replay. Exact Helpers
        # wire controls separately cover the preserved leading-zero index.
        self.assertEqual(original['quotedOutput'], '777')
        self.assertEqual(original, before)

    @staticmethod
    def measured_branches(intent, rows):
        """Build measured branch facts around the normal Market plan builder."""
        from cybergold_candidate.market_fee import routed_sell_budget
        from quoter_fixture import synthetic_pool
        from test_universal_quote import WETH, CORE, PAXG
        source, target = (CORE, WETH) if intent == 1 else (WETH, CORE)
        pool = synthetic_pool(source, target, 45, 'v2')
        hop = {'pool': pool, 'zeroForOne': source.lower() == pool['token0']['address'].lower()}
        plan = {'allocations': [], 'conversions': {}, 'body': {'branches': []}}
        observations = []
        for index, (kind, amount, used) in enumerate(rows):
            if kind == 0:
                # A sale Core lot is opaque to input-consumption funding. Its
                # output descriptors/routes must stay attached to this index.
                branch = {'kind': 0, 'amountIn': str(amount), 'data': {
                    'expectedOutputs': [{'kind': 0, 'token': PAXG, 'id': '0', 'amount': '123'}],
                    'conversions': [{'inputCurrency': PAXG, 'outputCurrency': target, 'routes': []}]}}
                plan['conversions'][f'{index}:redeem:0'] = {
                    'inputCurrency': PAXG, 'outputCurrency': target, 'branches': []}
            else:
                market = market_plan(source, target, [hop], amount, origins=['cybergold-custom'])
                branch = market['body']['branches'][0]
                if intent == 1:
                    branch['data']['feeCygld'] = str(routed_sell_budget(amount, 1000)[1])
                plan['conversions'][f'{index}:market'] = market['conversions']['0:market']
                if used is not None:
                    observations.append({'operation': f'{index}:market', 'inputCurrency': source,
                        'consumedInput': str(used), 'outputCurrency': target, 'output': '777' if used else '0'})
            plan['allocations'].append({'kind': kind, 'amountIn': str(amount)})
            plan['body']['branches'].append(branch)
        amount = str(sum(row[1] for row in rows))
        request = {'intent': intent, 'inputs': [{'currency': source, 'amount': amount}], 'outputCurrency': target}
        return {'request': request, 'inputs': deepcopy(request['inputs']), 'plan': plan,
                'conversionObservations': observations, 'quotedOutput': '777'}

    def test_unused_market_branches_preserve_buy_and_mixed_sale_indices(self):
        for intent in (0, 1):
            for unused_first in (True, False):
                with self.subTest(intent=intent, unused_first=unused_first):
                    markets = [(1, 100, 0), (1, 300, 200)]
                    if not unused_first:
                        markets.reverse()
                    rows = ([markets[0], (0, 500, None), markets[1]] if intent == 1 else markets)
                    value = self.measured_branches(intent, rows)
                    before = deepcopy(value)
                    proposal = measured_funding_proposal(value, 1)
                    self.assertIsNotNone(proposal)
                    funded, plan = proposal
                    expected = [0, 201 if intent else 200] if unused_first else [201 if intent else 200, 0]
                    if intent == 1:
                        expected.insert(1, 500)
                    self.assertEqual(funded['inputs'][0]['amount'], str(sum(expected)))
                    self.assertEqual([int(row['amountIn']) for row in plan['body']['branches']], expected)
                    self.assertEqual([int(row['amountIn']) for row in plan['allocations']], expected)
                    self.assertEqual(plan['conversions'], before['plan']['conversions'])
                    self.assertEqual([row['data'] for row in plan['body']['branches']],
                                     [row['data'] for row in before['plan']['body']['branches']])
                    self.assertEqual(len(plan['body']['branches']), len(rows))
                    self.assertEqual(value, before)
                    plan['body']['branches'][0]['data']['owned-test-edit'] = True
                    plan['conversions'][next(iter(plan['conversions']))]['owned-test-edit'] = True
                    self.assertEqual(value, before)

    def test_positive_core_sale_stays_nominal_with_fee_inclusive_partial_market_in_both_orders(self):
        for core_first in (True, False):
            with self.subTest(core_first=core_first):
                rows = [(0, 500, None), (1, 300, 200)]
                if not core_first:
                    rows.reverse()
                value = self.measured_branches(1, rows)
                before = deepcopy(value)
                proposal = measured_funding_proposal(value, 1)
                self.assertIsNotNone(proposal)
                funded, plan = proposal
                self.assertEqual(funded['inputs'][0]['amount'], '701')
                core_index, market_index = (0, 1) if core_first else (1, 0)
                self.assertEqual(plan['body']['branches'][core_index], before['plan']['body']['branches'][core_index])
                self.assertEqual(plan['body']['branches'][market_index]['amountIn'], str(200 + quoted_fee(200, 1000)))
                self.assertEqual(plan['body']['branches'][market_index]['data'],
                                 before['plan']['body']['branches'][market_index]['data'])
                self.assertEqual(plan['conversions'], before['plan']['conversions'])
                self.assertEqual(value, before)

    def test_zero_aggregate_and_unknown_market_measurements_keep_nominal_funding(self):
        for intent in (0, 1):
            with self.subTest(intent=intent, measurement='zero-aggregate'):
                value = self.measured_branches(intent, [(1, 100, 0), (1, 300, 0)])
                before = deepcopy(value)
                self.assertIsNone(measured_funding_proposal(value, 1))
                self.assertEqual(value, before)
            for unknown in ('missing-observation', 'missing-conversion', 'other-payment'):
                with self.subTest(intent=intent, measurement=unknown):
                    rows = [(1, 100, 0), (1, 300, 200)]
                    if intent == 1:
                        rows.insert(0, (0, 500, None))
                    value = self.measured_branches(intent, rows)
                    market_index = len(rows)-1
                    operation = f'{market_index}:market'
                    if unknown == 'missing-observation':
                        value['conversionObservations'] = [row for row in value['conversionObservations']
                                                           if row['operation'] != operation]
                    elif unknown == 'missing-conversion':
                        del value['plan']['conversions'][operation]
                    else:
                        value['plan']['conversions'][operation]['inputCurrency'] = value['request']['outputCurrency']
                    before = deepcopy(value)
                    proposal = measured_funding_proposal(value, 1)
                    self.assertIsNotNone(proposal)
                    funded, plan = proposal
                    self.assertEqual(funded['inputs'][0]['amount'], '800' if intent else '300')
                    self.assertEqual(plan['body']['branches'][market_index],
                                     before['plan']['body']['branches'][market_index])
                    self.assertEqual(value, before)

    def test_whole_plan_builder_keeps_zero_acquisitions_and_owns_route_edits(self):
        from test_universal_quote import WETH, CORE, PAXG, OTHER
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '300'}], 'outputCurrency': CORE}
        route = {'inputCurrency': WETH, 'outputCurrency': PAXG, 'routes': []}
        plan = {'allocations': [{'kind': 0, 'amountIn': '300'}], 'conversions': {}, 'body': {'branches': [
            {'kind': 0, 'amountIn': '300', 'data': {'basketAssets': [PAXG, OTHER],
                'acquisitions': [{'amountIn': '100', 'route': deepcopy(route)},
                                 {'amountIn': '200', 'route': deepcopy(route)}]}}]}}
        before = deepcopy(plan)
        chosen = {'inputCurrency': WETH, 'outputCurrency': PAXG, 'branches': [], 'template': route}
        proposal = funding_proposal(request, plan, {'0:acquire:0': 0, '0:acquire:1': 70},
                                    {'0:acquire:0': chosen})
        self.assertEqual(proposal['inputs'][0]['amount'], '70')
        self.assertEqual(proposal['plan']['allocations'][0]['amountIn'], '70')
        self.assertEqual(proposal['plan']['body']['branches'][0]['data']['acquisitions'][0]['amountIn'], '0')
        proposal['plan']['conversions']['0:acquire:0']['template']['routes'].append({})
        self.assertEqual(plan, before)
        self.assertEqual(chosen['template']['routes'], [])

    async def test_real_direct_and_both_mixed_orders_preserve_output(self):
        q, case = historical_service(self)
        block = historical_data()['anchor']
        direct = next(row for row in case['routes'] if row['output'] == '1512123003848321271')
        value = await q.candidate(case['request'], 0, 'core-first', block, *case['basis'],
            selected=market_plan(case['request']['inputs'][0]['currency'], q.core, historical_route(q, direct), 500000000))
        self.assertEqual(value['quotedOutput'], '1512123003848321271')
        old_observed = deepcopy(q.engine.registry.observed)
        smaller = await reprice_measured(q, value, block, *case['basis'], {})
        self.assertEqual(smaller['inputs'][0]['amount'], '198627782')
        self.assertEqual(smaller['quotedOutput'], value['quotedOutput'])
        self.assertEqual(smaller['estimatedRetainedInputCharges'], [])
        for row in historical_data()['mixed']:
            with self.subTest(order=row['order']):
                original = row['original']
                with capture_paths() as traces:
                    value = await q.candidate(original['request'], 100, 'core-first', block,
                        *case['basis'], selected=original['plan'])
                # The later path must see an earlier operation's actual mutation.
                self.assertTrue(any(hop.pre_state is not None and any(
                    hop.pre_state.get(field) != q.engine.registry.observation(hop.hop['pool']).get(field)
                    for field in ('reserve0', 'reserve1', 'sqrtRatioX96', 'liquidity'))
                    for trace in traces for hop in trace.hops))
                smaller = await reprice_measured(q, value, block, *case['basis'], {})
                self.assertEqual(smaller['inputs'][0]['amount'], '473627782')
                self.assertEqual(smaller['quotedOutput'], original['quotedOutput'])
                self.assertEqual(smaller['fees'], original['fees'])
                self.assertEqual(smaller['request']['inputs'][0]['amount'], '500000000')
                self.assertEqual(smaller['estimatedRetainedInputCharges'], [])
                prepared = await TransactionPreparation(q).prepare({'quote': smaller, 'sender': USER, 'recipient': USER})
                self.assertEqual(prepared['plan']['inputs'], smaller['inputs'])
                self.assertEqual(prepared['economicQuote']['quotedOutput'], smaller['quotedOutput'])
        self.assertEqual(q.engine.registry.observed, old_observed)

    def test_direct_basket_vector_and_redemption_supply_share_proposal_math(self):
        from test_universal_quote import CORE, PAXG, OTHER
        request = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '90'},
                                         {'currency': OTHER, 'amount': '6000000'}], 'outputCurrency': CORE}
        state = {'conversions': [10**18, 10**30], 'weights': [600000, 400000],
                 'supply': 20, 'maxSupply': 120, 'effectiveCap': 100}
        vector = direct_basket_funding(request, state)
        self.assertEqual(vector, [{'currency': PAXG, 'amount': '48'}, {'currency': OTHER, 'amount': '1'}])
        plan = {'allocations': [], 'conversions': {}, 'body': {'continuations': []}}
        proposal = funding_proposal(request, plan, inputs=vector)
        self.assertEqual(proposal['inputs'], vector)
        proposal['inputs'][0]['amount'] = '1'
        self.assertEqual(request['inputs'][0]['amount'], '90')
        self.assertEqual(vector[0]['amount'], '48')
        for intent in (1, 3):
            sale = {'intent': intent, 'inputs': [{'currency': CORE, 'amount': '200'}], 'outputCurrency': PAXG}
            self.assertEqual(supply_funding(sale, state), [{'currency': CORE, 'amount': '20'}])
            if intent == 3:
                self.assertEqual(direct_basket_funding(sale, state), supply_funding(sale, state))

    async def test_recovered_e13_sale_fee_and_changed_minimum(self):
        data = historical_data()
        for name in ['original', 'after']:
            with self.subTest(state=name):
                pool = expand(data['e13'][name])
                source = pool['token1']['address']; target = pool['token0']['address']
                q = service(self, [pool]); q.core = source
                q.engine.registry.core = source
                q.engine.registry.at = {'number': int(pool['context']['blockNumber']), 'hash': pool['context']['blockHash']}
                block = q.engine.registry.at
                request = {'intent': 1, 'inputs': [{'currency': source, 'amount': '77599013858487449084'}], 'outputCurrency': target}
                route = [{'pool': pool, 'zeroForOne': False}]
                value = await q.candidate(request, 0, 'core-first', block, *await basis(block),
                    selected=market_plan(source, target, route, int(request['inputs'][0]['amount'])))
                smaller = await reprice_measured(q, value, block, *await basis(block), {})
                self.assertEqual(smaller['quotedOutput'], value['quotedOutput'])
                self.assertLess(int(smaller['inputs'][0]['amount']), int(value['inputs'][0]['amount']))
                self.assertLess(int(smaller['fees']['marketFeeCygld']), int(value['fees']['marketFeeCygld']))
                self.assertEqual(smaller['estimatedRetainedInputCharges'], [])
                used = int(smaller['conversionObservations'][0]['consumedInput'])
                self.assertEqual(int(smaller['inputs'][0]['amount']), used + quoted_fee(used, 1000))
                if name == 'original':
                    self.assertEqual(value['quotedOutput'], '206997918024914661')
                    original_quote = deepcopy(smaller)
                else:
                    from cybergold_candidate.tx_preparation import compile_execution
                    with self.assertRaisesRegex(Exception, 'Accepted scalar output minimum'):
                        compile_execution(smaller, recipient=USER, deadline=2000000000, minimum=204927938844665514)
                    q.seed_routes = lambda *_: None
                    async def discovered(*_):
                        pass
                    q.discover = discovered
                    refreshed = await q.get(request, seed=original_quote)
                    self.assertIsNone(refreshed['context']['blockHash'])
                    self.assertEqual(refreshed['context']['blockTag'], 'latest')
                    self.assertLess(int(refreshed['quotedOutput']), int(original_quote['quotedOutput']))


if __name__ == '__main__':
    unittest.main()
