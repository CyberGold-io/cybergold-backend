"""Complete candidate proposals reach the real Helpers ABI without Core repricing."""
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.exact_input_plan import compile_plan, CORE_BUY, CORE_SELL, MARKET, SCALAR_BODY
from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.evaluate import evaluate_candidate
from cybergold_candidate.quoter.funding import cached_core_funding, measured_funding_proposal
from cybergold_candidate.quoter.plan_call import executable_body
from cybergold_candidate.quoter.reuse_routes import neighbor_proposals
from cybergold_candidate.routing_encoding import ZERO
from test_quoter_plan_simulation import Provider, Rpc, encoded, measured, stage, CODEC
from test_universal_quote import BLOCK, CORE, PAXG, OTHER, WETH, USER, Engine, settings


ASSETS = [PAXG, OTHER]
OUTPUTS = [{'kind': 0, 'token': PAXG, 'id': '0', 'amount': '100'},
           {'kind': 1, 'token': OTHER, 'id': '7', 'amount': '3'},
           {'kind': 0, 'token': OTHER, 'id': '0', 'amount': '100'}]


def request(intent=0, amount=10000, native=False):
    return {'intent': intent, 'inputs': ([{'currency': PAXG, 'amount': '100'},
        {'currency': OTHER, 'amount': '100'}] if intent == 2 else
        [{'currency': ZERO if native else WETH if intent == 0 else CORE, 'amount': str(amount)}]),
        'outputCurrency': CORE if intent in (0, 2) else WETH if intent == 1 else ZERO}


def service(*responses):
    provider = Provider(*responses)
    rpc, engine = Rpc(provider), Engine()
    engine.registry.get_rpc = lambda: rpc
    engine.quote_sdk_branches = AsyncMock(side_effect=AssertionError('First body construction must not price SDK pools'))
    q = Quoter(settings(), engine)
    q.preview = AsyncMock(side_effect=AssertionError('Proposal construction must not preview Core amounts'))
    q.core_outputs = AsyncMock(return_value=deepcopy(OUTPUTS))
    return q, provider


def encode(req, plan):
    return compile_plan({**req, 'recipient': USER, 'deadline': '0'}, executable_body(plan['body']), 1)


class CandidateBodyTests(unittest.IsolatedAsyncioTestCase):
    async def proposal(self, q, req, share=100, order='core-first'):
        return (await evaluate_candidate(q, req, share, order, BLOCK, ASSETS, [500000, 500000], first=True))['plan']

    async def test_all_intents_and_mixed_orders_encode_without_sdk_or_core_preview(self):
        q, provider = service()
        for intent, share, order in [(0, 0, 'core-first'), (0, 100, 'core-first'),
                (0, 50, 'market-first'), (0, 50, 'core-first'), (1, 0, 'core-first'),
                (1, 100, 'core-first'), (1, 50, 'market-first'), (2, 100, 'core-first'),
                (3, 100, 'core-first')]:
            with self.subTest(intent=intent, share=share, order=order):
                req = request(intent)
                plan = await self.proposal(q, req, share, order)
                self.assertTrue(encode(req, plan)['body'].startswith('0x'))
                if intent < 2:
                    self.assertEqual(sum(int(x['amountIn']) for x in plan['allocations']), 10000)
        self.assertEqual(provider.calls, [])
        q.preview.assert_not_awaited()
        q.engine.quote_sdk_branches.assert_not_awaited()

    async def test_first_core_body_gets_one_real_helpers_result(self):
        receipt = encoded(measured(190, fees=(2, 0, 0), stages=[
            stage(0, WETH, PAXG, 5000, 100), stage(1, WETH, OTHER, 5000, 100),
            stage(2, PAXG, CORE, 100, 190), stage(3, OTHER, CORE, 100, 0)]))
        q, provider = service(receipt)
        value = await q.candidate(request(), 100, 'core-first', BLOCK, ASSETS, [500000, 500000], first=True)
        self.assertEqual(value['quotedOutput'], '190')
        self.assertEqual(value['fees']['coreProtocolFeeCygld'], '2')
        self.assertEqual(value['pricingEvidence']['engine'], 'helpers-execution')
        self.assertEqual([(method, params[1]) for method, params in provider.calls], [('eth_call', 'latest')])
        q.preview.assert_not_awaited()
        q.engine.quote_sdk_branches.assert_not_awaited()

    async def test_core_sale_and_basket_intents_take_actual_receipt_in_one_call(self):
        cases = [
            (1, measured(77, currency=WETH, fees=(4, 5, 0), recovery=[(1, OTHER, 7, 2)], stages=[
                stage(0, PAXG, WETH, 100, 40), stage(1, OTHER, WETH, 100, 37)])),
            (2, measured(190, fees=(2, 0, 0), stages=[stage(0, PAXG, CORE, 100, 190)])),
            (3, measured(0, recipients=[(0, PAXG, 0, 31), (1, OTHER, 7, 2), (0, OTHER, 0, 47)],
                         recovery=[(1, OTHER, 7, 2)], fees=(4, 5, 0))),
        ]
        for intent, receipt in cases:
            with self.subTest(intent=intent):
                q, provider = service(encoded(receipt))
                req, assets, weights = request(intent), ASSETS, [500000, 500000]
                if intent == 2:
                    # The funding override uses a real configured input token;
                    # OTHER is only a synthetic intermediate/output identity.
                    req['inputs'], assets, weights = [req['inputs'][0]], [PAXG], [1000000]
                value = await q.candidate(req, 100, 'core-first', BLOCK, assets, weights, first=True)
                self.assertEqual(value['quotedOutput'], str(receipt[2][0][3]) if intent != 3 else '0')
                self.assertEqual(value['fees']['coreProtocolFeeCygld'], str(receipt[5]))
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(provider.calls[0][1][1], 'latest')
                if intent == 3:
                    self.assertEqual([row['amount'] for row in value['plan']['body']['expectedOutputs']], ['31', '2', '47'])
                q.preview.assert_not_awaited()
                q.engine.quote_sdk_branches.assert_not_awaited()

    async def test_original_and_resized_nearby_core_market_bodies_encode(self):
        q, provider = service()
        for intent in (0, 1):
            for share in (0, 50, 100):
                with self.subTest(intent=intent, share=share):
                    req = request(intent)
                    old = {'request': req, 'inputs': deepcopy(req['inputs']),
                           'plan': await self.proposal(q, req, share), 'quotedOutput': '999999'}
                    proposals = neighbor_proposals(old, 20000, [])
                    self.assertEqual([p['inputs'][0]['amount'] for p in proposals], ['10000', '20000'])
                    for proposal in proposals:
                        funded = {**req, 'inputs': proposal['inputs']}
                        compiled = encode(funded, proposal['plan'])
                        decoded = CODEC.decode([f'({SCALAR_BODY})'], bytes.fromhex(compiled['body'][2:]))[0][0]
                        self.assertEqual(len(decoded), len(proposal['plan']['allocations']))
                        for branch, wire in zip(proposal['plan']['body']['branches'], decoded, strict=True):
                            schema = MARKET if branch['kind'] == 1 else CORE_BUY if intent == 0 else CORE_SELL
                            self.assertTrue(CODEC.decode([schema], wire[2]))
        self.assertEqual(provider.calls, [])
        q.preview.assert_not_awaited()
        q.engine.quote_sdk_branches.assert_not_awaited()

    async def test_nearby_market_and_native_templates_reach_one_helpers_call(self):
        for native in (False, True):
            with self.subTest(native=native):
                stages = ([stage(0, ZERO, WETH, 20000, 20000)] if native else [])
                stages.append(stage(len(stages), WETH, CORE, 20000, 77))
                q, provider = service(encoded(measured(77, stages=stages)))
                req = request(native=native)
                old = {'request': req, 'inputs': deepcopy(req['inputs']),
                       'plan': await self.proposal(q, req, 0)}
                proposal = neighbor_proposals(old, 20000, [])[1]
                result = await q.candidate({**req, 'inputs': proposal['inputs']}, 0, 'core-first',
                    BLOCK, [], [], selected=proposal['plan'])
                self.assertEqual(result['quotedOutput'], '76')
                self.assertEqual(result['fees']['marketFeeCygld'], '1')
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(provider.calls[0][1][1], 'latest')
                self.assertEqual(result['inputs'][0]['amount'], '20000')
                self.assertEqual(bool(provider.calls[0][1][0].get('value')), native)

    async def test_changed_funding_is_a_pure_complete_proposal(self):
        q, provider = service()
        req = request()
        value = {'request': req, 'inputs': deepcopy(req['inputs']), 'plan': await self.proposal(q, req, 0),
                 'conversionObservations': [{'operation': '0:market', 'inputCurrency': WETH,
                    'consumedInput': '7000'}]}
        funded, plan = measured_funding_proposal(value, 1)
        self.assertEqual(funded['inputs'][0]['amount'], '7000')
        self.assertEqual(plan['body']['branches'][0]['amountIn'], '7000')
        self.assertTrue(encode(funded, plan)['body'].startswith('0x'))
        self.assertEqual(value['inputs'][0]['amount'], '10000')
        self.assertEqual(provider.calls, [])

    async def test_native_split_consumption_nominates_funding_without_promising_output(self):
        q, provider = service()
        req = request(native=True)
        plan = await self.proposal(q, req, 0)
        chosen = plan['conversions']['0:market']
        chosen['branches'] *= 2
        selected = chosen['template']['routes'][0]
        chosen['template']['routes'] = [{**deepcopy(selected), 'sharePpm': 500000},
                                       {**deepcopy(selected), 'sharePpm': 0}]
        plan['body']['branches'][0]['data']['route'] = deepcopy(chosen['template'])
        value = {'request': req, 'inputs': deepcopy(req['inputs']), 'plan': plan,
                 'conversionObservations': [{'operation': '0:market', 'inputCurrency': WETH,
                                            'consumedInput': '7000'}]}
        funded, proposal = measured_funding_proposal(value, 1)
        self.assertEqual(funded['inputs'], [{'currency': ZERO, 'amount': '7000'}])
        self.assertEqual(proposal['body']['branches'][0]['data']['route']['routes'], chosen['template']['routes'])
        self.assertTrue(encode(funded, proposal)['body'].startswith('0x'))
        self.assertNotIn('quotedOutput', proposal)
        self.assertEqual(provider.calls, [])

    async def test_cached_core_supply_constructs_smaller_funding_and_recomputes_sell_fee(self):
        q, provider = service(encoded(measured(77, currency=WETH, fees=(0, 0, 7),
                                              stages=[stage(0, CORE, WETH, 6993, 77)])))
        req = request(1)
        plan = await self.proposal(q, req, 0)
        plan['body']['branches'][0]['data']['feeCygld'] = '999'
        saved = deepcopy(plan)
        unchanged, retained = cached_core_funding(req, {}, plan)
        self.assertEqual((unchanged, retained), (req, plan))
        funded, selected = cached_core_funding(req, {'supply': 7000}, plan)
        self.assertEqual(funded['inputs'][0]['amount'], '7000')
        self.assertEqual(selected['body']['branches'][0]['amountIn'], '7000')
        self.assertEqual(selected['body']['branches'][0]['data']['feeCygld'], '0')
        result = await q.candidate(funded, 0, 'core-first', BLOCK, [], [], selected=selected)
        self.assertEqual(result['fees']['marketFeeCygld'], '7')
        self.assertEqual(result['plan']['body']['branches'][0]['data']['feeCygld'], '7')
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(plan, saved)
        self.assertEqual(req['inputs'][0]['amount'], '10000')

    async def test_cached_supply_preserves_unallocated_input_proportion_in_selected_body(self):
        q, provider = service()
        req = request(1)
        plan = await self.proposal(q, req, 0)
        plan['allocations'][0]['amountIn'] = plan['body']['branches'][0]['amountIn'] = '2000'
        funded, selected = cached_core_funding(req, {'supply': 7000}, plan)
        self.assertEqual(funded['inputs'][0]['amount'], '7000')
        self.assertEqual(selected['allocations'][0]['amountIn'], '1400')
        self.assertTrue(encode(funded, selected)['body'].startswith('0x'))
        self.assertEqual(provider.calls, [])


if __name__ == '__main__':
    unittest.main()
