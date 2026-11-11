"""Pure encoding reuse cannot share mutable plans, execution state or prices."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from web3 import Web3

from cybergold_candidate.helpers_execution import ABI
from cybergold_candidate.quote_flow import Flow, flow_scope
from cybergold_candidate.quoter import plan_call
from cybergold_candidate.quoter.plan_transport import simulation_scope
from cybergold_candidate.quoter.provenance import attach_origins
from test_quoter_plan_simulation import (
    BLOCK, CORE, HELPERS, OTHER, PAXG, USER, WETH, encoded, fixture, market, measured, stage,
)


class PlanPreparationReuseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.contract = Web3().eth.contract(abi=ABI)

    def compile(self, request, plan, **options):
        return plan_call.compile_call(request, plan, **{
            'chain': 31338, 'helpers': HELPERS, 'core': CORE, 'contract': self.contract, **options})

    async def test_equivalent_wire_inputs_encode_once_with_private_plans_and_params(self):
        request, plan = market(native=True)
        original = deepcopy((request, plan))
        other = deepcopy(plan)
        other['conversions']['0:market']['discoveryOrigins'] = ['uniswap-alpharouter']
        other['body']['branches'][0]['data']['feeCygld'] = '123'
        other['body']['branches'][0]['data']['route']['minimumOutput'] = '777'
        with plan_call.preparation_scope(), patch.object(plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
            first = self.compile(request, plan, block=BLOCK)
            expected = deepcopy(first.params)
            first.plan['conversions']['0:market']['branches'][0]['hops'][0]['pool']['id'] = 'private'
            first.params[0]['data'] = '0xprivate'
            first.params[1]['blockHash'] = 'private'
            first.params[2].clear()
            second = self.compile(request, other, block=BLOCK)
            self.assertEqual(encode.call_count, 1)
            self.assertEqual(second.params, expected)
            self.assertEqual(second.plan, {**other, 'body': {
                'branches': [{**other['body']['branches'][0], 'data': {
                    **other['body']['branches'][0]['data'], 'feeCygld': '0'}}]}})
            self.assertEqual(second.block_tag, expected[1])
            self.assertEqual(second.params[0]['value'], hex(10000))
        self.assertEqual((request, plan), original)

    async def test_simulation_reuses_encoding_without_sharing_origins_or_fee_projection(self):
        request, plan = market()
        response = encoded(measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)]))
        simulation, _, _, provider = fixture(response)
        flow = Flow('/api/economic-quotes/stream')
        other = deepcopy(plan)
        other['conversions']['0:market']['discoveryOrigins'] = ['uniswap-alpharouter']
        with flow_scope(flow), patch.object(plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
            async with simulation_scope():
                with patch('cybergold_candidate.quoter.plan_simulation.get_market_fee_rate', return_value=1000):
                    first = attach_origins(await simulation(request, plan))
                with patch('cybergold_candidate.quoter.plan_simulation.get_market_fee_rate', return_value=2000):
                    second = attach_origins(await simulation(request, other))
        self.assertEqual(encode.call_count, 1)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(first['quotedOutput'], '99900')
        self.assertEqual(second['quotedOutput'], '99800')
        self.assertEqual(second['routeOrigins']['discoveryProviders'], ['uniswap-alpharouter'])
        self.assertEqual(first['plan']['body']['branches'][0]['data']['feeCygld'], '100')
        self.assertEqual(second['plan']['body']['branches'][0]['data']['feeCygld'], '200')
        self.assertEqual(plan['body']['branches'][0]['data']['feeCygld'], '999')
        stages = {row['stage']: row for row in flow.snapshot()['stages']}
        self.assertEqual(stages['plan.compile']['completed'], 2)
        self.assertEqual(stages['plan.encode']['completed'], 1)

    async def test_executable_differences_do_not_reuse_preparation(self):
        request, plan = market()
        cases = []
        changed_request, changed_plan = deepcopy((request, plan))
        changed_request['inputs'][0]['amount'] = '10001'
        changed_plan['body']['branches'][0]['amountIn'] = '10001'
        cases.append(('funding', changed_request, changed_plan, {}))
        changed_request, changed_plan = deepcopy((request, plan))
        changed_request['outputCurrency'] = OTHER
        changed_plan['body']['branches'][0]['data']['route']['outputCurrency'] = OTHER
        changed_plan['body']['branches'][0]['data']['route']['routes'][0]['steps'][0]['currencyOut'] = OTHER
        cases.append(('output', changed_request, changed_plan, {}))
        changed_plan = deepcopy(plan)
        changed_plan['body']['branches'][0]['data']['route']['routes'][0]['steps'][0]['fee'] = 3000
        cases.append(('pool step', request, changed_plan, {}))
        for name, options in (
            ('chain', {'chain': 1}), ('helpers', {'helpers': OTHER}), ('core', {'core': OTHER}),
            ('pricing mode', {'pricing': False}), ('minimum', {'minimum': 2}),
            ('recipient', {'recipient': USER}), ('pinned state', {'block': BLOCK}),
        ):
            cases.append((name, request, plan, options))
        for name, changed_request, changed_plan, options in cases:
            with self.subTest(name=name), plan_call.preparation_scope(), patch.object(
                    plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
                first = self.compile(request, plan)
                second = self.compile(changed_request, changed_plan, **options)
                self.assertEqual(encode.call_count, 2)
                if name not in ('chain', 'core'):
                    self.assertNotEqual(first.params, second.params)

    async def test_ordered_branches_and_ppm_weights_remain_executable_inputs(self):
        request, plan = market()
        a = deepcopy(plan['body']['branches'][0])
        b = deepcopy(a)
        a['amountIn'], b['amountIn'] = '2500', '7500'
        b['data']['route']['routes'][0]['steps'][0]['fee'] = 3000
        plan['body']['branches'] = [a, b]
        reversed_plan = deepcopy(plan)
        reversed_plan['body']['branches'].reverse()
        weighted = deepcopy(plan)
        route = weighted['body']['branches'][0]['data']['route']['routes']
        route[0]['sharePpm'] = 250000
        route.append({'sharePpm': 0, 'steps': deepcopy(route[0]['steps'])})
        changed_weight = deepcopy(weighted)
        changed_weight['body']['branches'][0]['data']['route']['routes'][0]['sharePpm'] = 500000
        with plan_call.preparation_scope(), patch.object(plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
            params = [self.compile(request, value).params for value in (plan, reversed_plan, weighted, changed_weight)]
        self.assertEqual(encode.call_count, 4)
        self.assertEqual(len({value[0]['data'] for value in params}), 4)

    async def test_accepted_core_bounds_and_paid_fees_are_not_discarded(self):
        request = {'intent': 3, 'inputs': [{'currency': CORE, 'amount': '10000'}], 'outputCurrency': CORE}
        descriptor = {'kind': 0, 'token': PAXG, 'id': '0', 'amount': '100'}
        plan = {'allocations': [], 'conversions': {}, 'body': {'expectedOutputs': [descriptor]}}
        accepted = {'kind': 0, 'token': PAXG, 'id': '0', 'minimumAmount': '90'}
        with plan_call.preparation_scope(), patch.object(plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
            first = self.compile(request, plan, pricing=False, accepted_core=[accepted])
            second = self.compile(request, plan, pricing=False, accepted_core=[{**accepted, 'minimumAmount': '91'}])
            self.assertEqual(encode.call_count, 2)
            self.assertNotEqual(first.params, second.params)
        request, plan = market(1)
        changed = deepcopy(plan)
        changed['body']['branches'][0]['data']['feeCygld'] = '998'
        with plan_call.preparation_scope(), patch.object(plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
            first = self.compile(request, plan, pricing=False)
            second = self.compile(request, changed, pricing=False)
            self.assertEqual(encode.call_count, 2)
            self.assertNotEqual(first.params, second.params)

    async def test_sell_policy_is_recomputed_before_lookup_and_paid_replay_stays_fresh(self):
        request, plan = market(1)
        with plan_call.preparation_scope(), patch.object(plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
            with patch.object(plan_call, 'get_market_fee_rate', return_value=1000):
                first = self.compile(request, plan)
            with patch.object(plan_call, 'get_market_fee_rate', return_value=2000):
                second = self.compile(request, plan)
            self.assertEqual(encode.call_count, 2)
            self.assertNotEqual(first.params, second.params)
        request, plan = market()
        plan['body']['branches'][0]['data']['feeCygld'] = '0'
        simulation, _, _, provider = fixture(
            encoded(measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)])),
            encoded(measured(120000, stages=[stage(0, WETH, CORE, 10000, 120000)])))
        with patch.object(plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
            async with simulation_scope():
                quote = await simulation(request, plan)
                paid = await simulation(request, plan, pricing=False)
        self.assertEqual(provider.calls[0], provider.calls[1])
        self.assertEqual(encode.call_count, 2, 'Mode remains a distinct preparation context even for equal bytes')
        self.assertEqual(len(provider.calls), 2, 'Pure preparation cannot reuse quote state for paid execution')
        self.assertEqual(quote['quotedOutput'], '99900')
        self.assertEqual(paid['quotedOutput'], '120000')

    async def test_preparation_does_not_cache_execution_failures(self):
        request, plan = market()
        simulation, _, _, provider = fixture(OSError('fixture transport unavailable'),
            encoded(measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)])))
        with patch.object(plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
            async with simulation_scope():
                with self.assertRaisesRegex(OSError, 'fixture transport unavailable'):
                    await simulation(request, plan)
                value = await simulation(request, plan)
        self.assertEqual(encode.call_count, 1)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(value['quotedOutput'], '99900')

    async def test_scope_lifetime_bounded_lru_and_compile_failure_leave_no_shared_state(self):
        request, plan = market()
        with patch.object(plan_call, 'compile_plan', wraps=plan_call.compile_plan) as encode:
            self.compile(request, plan)
            self.compile(request, plan)
            self.assertEqual(encode.call_count, 2, 'No scope means no completed reuse')
            with patch.object(plan_call, 'MAX_PREPARATIONS', 2), plan_call.preparation_scope() as cache:
                self.compile(request, plan, minimum=1)
                self.compile(request, plan, minimum=2)
                self.compile(request, plan, minimum=1)  # Touch the retained first entry.
                self.compile(request, plan, minimum=3)
                self.assertEqual(len(cache), 2)
                self.compile(request, plan, minimum=2)  # Evicted encoding is rebuilt.
                self.assertEqual(encode.call_count, 6)
                with plan_call.preparation_scope() as inner:
                    self.assertEqual(len(inner), 0)
                    self.compile(request, plan, minimum=2)
                self.assertEqual(len(inner), 0)
                self.compile(request, plan, minimum=2)
                self.assertEqual(encode.call_count, 7, 'Nested scope restores the outer completed encodings')
            self.assertEqual(len(cache), 0)
            with plan_call.preparation_scope():
                self.compile(request, plan)
            self.assertEqual(encode.call_count, 8)
        with plan_call.preparation_scope() as cache, patch.object(
                plan_call, 'compile_plan', side_effect=ValueError('fixture invalid encoding')) as encode:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'fixture invalid encoding'):
                    self.compile(request, plan)
            self.assertEqual(encode.call_count, 2)
            self.assertEqual(len(cache), 0)


if __name__ == '__main__':
    unittest.main()
