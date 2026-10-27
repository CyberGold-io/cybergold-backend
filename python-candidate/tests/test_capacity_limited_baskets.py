"""State-derived direct basket funding, ordered economics and preparation.

The Core fixture uses the existing integer translation of its proportional
reserve/recovery arithmetic; AMM continuations use the ordered constant-product
fixture. These are producer/compiler controls, not live-chain measurements.
"""
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.basket_arithmetic import BasketArithmetic
from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.preview_errors import KnownPreviewError
from cybergold_candidate.quoter.ranking import prefer_completed
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.tx_preparation import TransactionPreparation
from test_economic_preparation import quoter, preparation
from test_economic_quote_api import SharedStore
from test_universal_quote import BLOCK, CORE, PAXG, OTHER


def state():
    return {'assets': [PAXG, OTHER], 'weights': [500000, 500000], 'conversions': [10**18, 10**18],
        'supply': 1000000, 'maxSupply': 1500000, 'effectiveCap': 1400000,
        'issueFee': 10000, 'helperFee': 2000, 'redeemFee': 10000,
        'available': [120000, 300000], 'recoveryValues': [200000], 'recoveryShares': [250],
        'descriptors': [{'kind': 0, 'token': PAXG, 'id': '0'}, {'kind': 0, 'token': OTHER, 'id': '0'},
                        {'kind': 1, 'token': CORE, 'id': '7'}]}


def request(intent=2):
    return {'intent': intent, 'inputs': ([{'currency': PAXG, 'amount': '500000'},
        {'currency': OTHER, 'amount': '500000'}] if intent == 2 else [{'currency': CORE, 'amount': '2000000'}]),
        'outputCurrency': CORE if intent == 2 else '0x'+'0'*40}


def service(current=None, *, markets=False):
    current = current if current is not None else state()
    value = quoter()
    previews, reads = [], []
    async def preview(mode, arguments, block):
        previews.append((mode, deepcopy(arguments), deepcopy(block)))
        arithmetic = BasketArithmetic(current)
        if mode == 'issue-exact-in':
            result = (arithmetic.issue_in(list(map(int, arguments['maximumAmountsIn'])))
                if min(current['maxSupply'], current['effectiveCap']) > current['supply'] else {
                    'netCygldOut': 0, 'amountsInExact': [0, 0], 'orderedCoreAssets': [PAXG, OTHER],
                    'fees': {'protocolFeeCygld': 0, 'helperFeeCygld': 0}})
        else:
            gross = int(arguments['grossCygldIn'])
            if gross - gross*current['helperFee']//1000000 > current['supply']:
                raise KnownPreviewError('redemption-supply-exceeded', 'The input exceeds supply.')
            result = arithmetic.redeem_in(gross)
            if not any(int(row['amount']) for row in result['projectedCoreOutputs']):
                raise InvalidPreview('No positive Core redemption output.')
        def wire(node):
            if isinstance(node, dict):
                return {key: item if key == 'kind' else wire(item) for key, item in node.items()}
            if isinstance(node, list):
                return [wire(item) for item in node]
            return str(node) if type(node) is int else node
        return wire(result)
    async def read(target, signature, types, arguments, outputs, block):
        reads.append((target, signature, types, arguments, outputs, deepcopy(block)))
        if signature != 'totalSupply()':
            raise AssertionError('Unexpected capacity read.')
        return [current['supply']]
    value.preview = preview
    value.engine.read_function = read
    value.engine.registry.ensure_loaded = AsyncMock()
    if not markets:
        value.engine.registry.inventory = {}
    return value, previews, reads


class CapacityLimitedBasketTests(unittest.IsolatedAsyncioTestCase):
    async def test_issuance_cap_uses_exact_required_vector_without_acquiring_unused_budget(self):
        quoter, previews, reads = service()
        budget = request()
        original = deepcopy(budget)
        quote = await quoter.quote(budget)
        self.assertEqual(budget, original)
        self.assertEqual(quote['request'], original)
        self.assertEqual(quote['inputs'], [{'currency': PAXG, 'amount': '200000'},
                                         {'currency': OTHER, 'amount': '200000'}])
        self.assertEqual(quote['quotedOutput'], '395208')
        self.assertEqual(quote['fees'], {'coreProtocolFeeCygld': '3999',
            'coreHelpersFeeCygld': '792', 'marketFeeCygld': '0'})
        self.assertEqual(quote['estimatedRetainedInputCharges'], [])
        self.assertEqual(quote['searchCoverage']['selectedPhase'], 'capacity-limited')
        self.assertTrue(any(row[1]['maximumAmountsIn'] == ['200000', '200000'] for row in previews))
        self.assertTrue(all(row[2] == BLOCK for row in previews))
        self.assertEqual(reads, [])
        prepared = await TransactionPreparation(quoter).prepare(preparation(quote))
        self.assertEqual(prepared['plan']['inputs'], quote['inputs'])
        self.assertEqual(prepared['economicQuote']['fees'], quote['fees'])

    async def test_redemption_supply_uses_actual_funding_and_fee_adjusted_reserve_recovery_outputs(self):
        quoter, previews, reads = service()
        budget = request(3)
        original = deepcopy(budget)
        quote = await quoter.quote(budget)
        self.assertEqual(budget, original)
        self.assertEqual(quote['request'], original)
        self.assertEqual(quote['inputs'], [{'currency': CORE, 'amount': '1000000'}])
        self.assertEqual(quote['quotedInput'], '1000000')
        self.assertEqual(quote['inputMaximum'], '1000000')
        self.assertEqual(quote['fees'], {'coreProtocolFeeCygld': '9980',
            'coreHelpersFeeCygld': '2000', 'marketFeeCygld': '0'})
        self.assertEqual([row['amount'] for row in quote['estimatedRecipientOutputs']], ['118562', '296406', '247'])
        self.assertEqual(quote['estimatedRecipientOutputs'][-1], {'kind': 1, 'token': CORE, 'id': '7', 'amount': '247'})
        self.assertEqual(quote['estimatedRetainedInputCharges'], [])
        self.assertEqual(reads, [(CORE, 'totalSupply()', [], [], ['uint256'], BLOCK)])
        self.assertIn(('redeem-exact-in', {'grossCygldIn': '1000000'}, BLOCK), previews)
        prepared = await TransactionPreparation(quoter).prepare(preparation(quote))
        self.assertEqual(prepared['plan']['inputs'], quote['inputs'])
        self.assertEqual(prepared['economicQuote']['inputs'], quote['inputs'])
        self.assertEqual(prepared['economicQuote']['estimatedRecipientOutputs'], quote['estimatedRecipientOutputs'])

    async def test_productive_full_budget_continuations_win_when_they_produce_more_output(self):
        quoter, _, _ = service(markets=True)
        quote = await quoter.quote(request())
        self.assertGreater(int(quote['quotedOutput']), 395208)
        self.assertEqual(quote['inputs'], request()['inputs'])
        self.assertEqual(quote['routeFamily'], 'mixed')

    async def test_equal_output_prefers_smaller_real_funding_over_retained_surplus(self):
        quoter, _, _ = service(markets=True)
        quoter.engine.cap = 1
        quote = await quoter.quote(request())
        self.assertEqual(quote['quotedOutput'], '395208')
        self.assertEqual([row['amount'] for row in quote['inputs']], ['200000', '200000'])
        self.assertEqual(quote['estimatedRetainedInputCharges'], [])

    async def test_saved_quote_lookup_and_refresh_keep_smaller_funding_under_original_budget(self):
        for intent in (2, 3):
            with self.subTest(intent=intent):
                quoter, _, _ = service()
                quotes = EconomicQuotes(quoter, SharedStore())
                budget = request(intent)
                first = await quotes.get(budget)
                head = quoter.engine.block
                quoter.engine.block = AsyncMock(side_effect=AssertionError('Stored quote must not read head.'))
                cached = await quotes.get(budget)
                self.assertEqual(cached['inputs'], first['inputs'])
                self.assertEqual(cached['request'], budget)
                self.assertEqual(cached['observation']['source'], 'stored')
                quoter.engine.block.assert_not_called()
                quoter.engine.block = head
                # Only saved-plan replay can produce the reduced quote here:
                # ordinary full-budget issuance has no continuation route, and
                # full-budget redemption exceeds the same supply.
                quoter.direct_basket_funding = AsyncMock(return_value=None)
                refreshed = await quotes.get(budget, refresh=True)
                self.assertEqual(refreshed['inputs'], first['inputs'])
                self.assertEqual(refreshed['request'], budget)
                self.assertEqual(refreshed['searchCoverage']['selectedPhase'], 'saved-plan')

    async def test_saved_funding_above_a_new_smaller_budget_cannot_win(self):
        quoter, _, _ = service()
        previous = await quoter.quote(request(3))
        smaller = request(3)
        smaller['inputs'][0]['amount'] = '500000'
        quote = await quoter.quote(smaller, seed=previous)
        self.assertEqual(quote['request'], smaller)
        self.assertEqual(quote['inputs'], smaller['inputs'])
        self.assertNotEqual(quote['searchCoverage']['selectedPhase'], 'saved-plan')

    async def test_redemption_capacity_read_failure_retains_its_ordinary_rpc_error(self):
        quoter, _, _ = service()
        quoter.engine.read_function = AsyncMock(side_effect=QuoteFailure('rpc-unavailable'))
        budget = request(3)
        budget['inputs'][0]['amount'] = '500000'
        with self.assertRaises(QuoteFailure) as failed:
            await quoter.quote(budget)
        self.assertEqual(failed.exception.code, 'rpc-unavailable')

    async def test_helpers_fee_cannot_make_funding_above_the_entire_supply_win(self):
        quoter, previews, _ = service()
        budget = request(3)
        # Helpers would send only 998998 to Core, which is below supply. The
        # outer 1001000 could nevertheless never be acquired from any payer.
        budget['inputs'][0]['amount'] = '1001000'
        quote = await quoter.quote(budget)
        self.assertEqual(quote['request'], budget)
        self.assertEqual(quote['inputs'][0]['amount'], '1000000')
        self.assertTrue(all(row[1]['grossCygldIn'] == '1000000' for row in previews))

    async def test_saved_redemption_funding_cannot_exceed_the_newly_observed_supply(self):
        current = state()
        quoter, _, _ = service(current)
        budget = request(3)
        previous = await quoter.quote(budget)
        current['supply'] = 500000
        updates = []
        async def update(frame):
            updates.append(deepcopy(frame['value']))
        quote = await quoter.quote(budget, update, seed=previous)
        self.assertEqual(quote['request'], budget)
        self.assertEqual(quote['inputs'][0]['amount'], '500000')
        self.assertTrue(updates)
        self.assertTrue(all(int(row['inputs'][0]['amount']) <= 500000 for row in updates))

    async def test_zero_supply_preserves_the_identified_rejection_without_inventing_a_quote(self):
        current = state()
        current['supply'] = 0
        quoter, _, _ = service(current)
        with self.assertRaises(KnownPreviewError) as failed:
            await quoter.quote(request(3))
        self.assertEqual(failed.exception.code, 'redemption-supply-exceeded')

    async def test_exhausted_issuance_with_no_market_route_preserves_an_ordinary_failure(self):
        current = state()
        current['effectiveCap'] = current['supply']
        quoter, _, _ = service(current)
        with self.assertRaises(QuoteFailure):
            await quoter.quote(request())

    def test_basket_comparison_uses_output_descriptors_and_componentwise_funding(self):
        def quote(inputs, outputs):
            return {'quotedOutput': '0', 'inputs': [{'currency': token, 'amount': str(amount)}
                for token, amount in zip((PAXG, OTHER), inputs, strict=True)],
                'estimatedRecipientOutputs': [{'kind': 0, 'token': token, 'id': '0', 'amount': str(amount)}
                    for token, amount in zip((PAXG, OTHER), outputs, strict=True)]}
        incumbent = quote([1000, 10], [20, 30])
        self.assertTrue(prefer_completed(quote([900, 10], [20, 30]), incumbent, scalar=False, basket=True))
        self.assertFalse(prefer_completed(quote([1, 11], [20, 30]), incumbent, scalar=False, basket=True))
        self.assertTrue(prefer_completed(quote([1000, 10], [21, 30]), incumbent, scalar=False, basket=True))
        self.assertFalse(prefer_completed(quote([1, 1], [21, 29]), incumbent, scalar=False, basket=True))
        changed = quote([1, 1], [21, 31])
        changed['estimatedRecipientOutputs'][1]['id'] = '7'
        self.assertFalse(prefer_completed(changed, incumbent, scalar=False, basket=True))


if __name__ == '__main__':
    unittest.main()
