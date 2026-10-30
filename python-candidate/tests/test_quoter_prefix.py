"""Actual SDK inverse/forward agreement and unsigned execution preparation."""
from copy import deepcopy
import unittest

from cybergold_candidate.quoter.amm import PartialPath
from cybergold_candidate.quoter.contracts import capture_paths
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.prefix import repair_prefix
from cybergold_candidate.tx_preparation import TransactionPreparation
from quoter_fixture import service, synthetic_pool, basis
from test_universal_quote import BLOCK, CORE, PAXG, OTHER, WETH, USER


class PrefixTests(unittest.IsolatedAsyncioTestCase):
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
                        proposal = await repair_prefix(q, request, trace, BLOCK)
                        funding, plan = proposal
                        self.assertIn(int(funding[0]['amount']), [3025, 3035])
                        value = await q.candidate({**request, 'inputs': funding}, 0, 'core-first',
                            BLOCK, *await basis(BLOCK), selected=plan)
                        value['request'] = deepcopy(request)
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


if __name__ == '__main__':
    unittest.main()
