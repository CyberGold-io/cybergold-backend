"""Actual-SDK direct/mixed/sale funding and exact execution representation."""
from copy import deepcopy
import unittest

from cybergold_candidate.market_fee import quoted_fee
from cybergold_candidate.quoter.contracts import capture_paths
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.funding import exact_ppm_routes, reconstruct
from cybergold_candidate.routing_encoding import split_runtime
from cybergold_candidate.tx_preparation import TransactionPreparation
from quoter_fixture import historical_service, historical_data, historical_route, expand, service, basis
from test_universal_quote import BLOCK, USER


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
            smaller = await reconstruct(q, value, block, *case['basis'], {})
        self.assertEqual(smaller['inputs'][0]['amount'], '198627782')
        self.assertEqual(smaller['quotedOutput'], value['quotedOutput'])
        self.assertEqual(smaller['searchCoverage'], value['searchCoverage'])

    async def test_any_zero_funded_branch_retains_original_representation(self):
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
            used, output = (0, 0) if amount == 100 else (amount, 777)
            trace = new_path_trace(route, amount)
            if trace is not None:
                trace.consumed, trace.output = used, output
            return used, output
        q.price_path = programmed
        original = await q.candidate(request, 0, 'core-first', BLOCK, *await basis(BLOCK), selected=selected)
        self.assertIs(await reconstruct(q, original, BLOCK, *await basis(BLOCK), {}), original)
        self.assertEqual(len(original['plan']['body']['branches']), 2)

    def test_exact_ppm_intervals_and_unrepresentable_vector(self):
        routes = [{'sharePpm': 600000, 'steps': []}, {'sharePpm': 0, 'steps': []}]
        for desired in [[123456000, 876544000], [1, 2], [999999, 1]]:
            result = exact_ppm_routes(routes, desired)
            self.assertEqual(split_runtime(sum(desired), result), desired)
        self.assertIsNone(exact_ppm_routes(routes, [198627782, 125000000]))
        self.assertIsNone(exact_ppm_routes(routes, [0, 0]))

    async def test_real_direct_and_both_mixed_orders_preserve_output(self):
        q, case = historical_service(self)
        block = historical_data()['anchor']
        direct = next(row for row in case['routes'] if row['output'] == '1512123003848321271')
        value = await q.candidate(case['request'], 0, 'core-first', block, *case['basis'],
            selected=market_plan(case['request']['inputs'][0]['currency'], q.core, historical_route(q, direct), 500000000))
        self.assertEqual(value['quotedOutput'], '1512123003848321271')
        old_observed = deepcopy(q.engine.registry.observed)
        smaller = await reconstruct(q, value, block, *case['basis'], {})
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
                smaller = await reconstruct(q, value, block, *case['basis'], {})
                self.assertEqual(smaller['inputs'][0]['amount'], '473627782')
                self.assertEqual(smaller['quotedOutput'], original['quotedOutput'])
                self.assertEqual(smaller['fees'], original['fees'])
                self.assertEqual(smaller['request']['inputs'][0]['amount'], '500000000')
                self.assertEqual(smaller['estimatedRetainedInputCharges'], [])
                prepared = await TransactionPreparation(q).prepare({'quote': smaller, 'sender': USER, 'recipient': USER})
                self.assertEqual(prepared['plan']['inputs'], smaller['inputs'])
                self.assertEqual(prepared['economicQuote']['quotedOutput'], smaller['quotedOutput'])
        self.assertEqual(q.engine.registry.observed, old_observed)

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
                smaller = await reconstruct(q, value, block, *await basis(block), {})
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
                    self.assertEqual(refreshed['context']['blockHash'], pool['context']['blockHash'])
                    self.assertLess(int(refreshed['quotedOutput']), int(original_quote['quotedOutput']))


if __name__ == '__main__':
    unittest.main()
