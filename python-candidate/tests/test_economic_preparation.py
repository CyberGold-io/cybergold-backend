"""Economic selection and selected-plan preparation retain different contracts.

The ordered fixture engine uses integer constant-product pool replay. These
controls exercise boundaries/guards; SDK arithmetic has its existing real-worker
suite and is not replaced by the programmable deterioration control below.
"""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.execution_tolerance import floor
from cybergold_candidate.quoter import Quoter
from cybergold_candidate.tx_preparation import TransactionPreparation
from cybergold_candidate.uniswap_routes import pool_identity
from test_universal_quote import (Engine, Quotes, settings, request as legacy_request,
                                  BLOCK, CORE, PAXG, OTHER, USER, WETH)


def economic_request(intent=0):
    original = legacy_request(intent)
    value = {key: deepcopy(original[key]) for key in ('intent', 'inputs', 'outputCurrency')}
    if intent == 2:
        value['inputs'] = [{'currency': PAXG, 'amount': '5000'},
                           {'currency': OTHER, 'amount': '6000'}]
    return value


def quoter():
    engine = Engine()
    fixture = Quotes(engine)
    service = Quoter(settings(), engine, preview=fixture.preview_call,
                     basis_reader=fixture.basis_call, now=lambda: '2026-10-26T12:00:00.000Z')
    service.seed_routes = fixture.seed_routes
    service.discover = fixture.discover
    return service


def preparation(value, **overrides):
    return {'quote': deepcopy(value), 'sender': USER, 'recipient': USER,
            'slippageBps': 100, **overrides}


def assert_no_execution_terms(test, value):
    forbidden = {'recipient', 'deadline', 'slippageBps', 'minimumOutput', 'outputMinimum',
                 'minimumAmount', 'calldata', 'adapterData', 'signature', 'transactionHash'}
    def visit(node):
        if isinstance(node, dict):
            test.assertFalse(forbidden.intersection(node), forbidden.intersection(node))
            for item in node.values():
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)
    visit(value)


class EconomicPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_four_economic_intents_are_wallet_and_execution_guard_free(self):
        for intent in range(4):
            with self.subTest(intent=intent):
                service = quoter()
                value = await service.quote(economic_request(intent))
                self.assertEqual(value['request'], economic_request(intent))
                assert_no_execution_terms(self, value)
                result = await TransactionPreparation(service, now=lambda: 2000).prepare(preparation(value))
                self.assertEqual(result['plan']['deadline'], '2600')
                self.assertEqual(result['plan']['inputs'], value['inputs'])
                self.assertNotIn('transactionHash', result)
                self.assertNotIn('signature', result)

    async def test_same_state_integer_economics_match_legacy_contract_for_all_intents(self):
        fields = ('inputs', 'quotedOutput', 'fees', 'estimatedRetainedInputCharges',
                  'estimatedRecipientOutputs', 'recoveryShares', 'routeFamily')
        for intent in range(4):
            with self.subTest(intent=intent):
                request = economic_request(intent)
                economic = await quoter().quote(request)
                old_request = {**legacy_request(intent), **request}
                old = await Quotes(Engine()).get(old_request)
                self.assertEqual({key: economic[key] for key in fields},
                                 {key: old[key] for key in fields})

    async def test_selected_replay_uses_same_ordered_routes_and_no_discovery(self):
        service = quoter()
        value = await service.quote(economic_request(1))
        service.discover = AsyncMock(side_effect=AssertionError('route discovery during preparation'))
        service.conversion = AsyncMock(side_effect=AssertionError('route search during preparation'))
        service.seed_routes = lambda *_: self.fail('seeding during preparation')
        repeated = await service.evaluate_selected(value['request'], value['plan'])
        self.assertEqual(repeated['plan'], value['plan'])
        for key in ('quotedOutput', 'fees', 'estimatedRetainedInputCharges', 'estimatedRecipientOutputs'):
            self.assertEqual(repeated[key], value[key])
        service.discover.assert_not_called()
        service.conversion.assert_not_called()
        self.assertEqual(service.engine.calls[-1], ('canonical', BLOCK))

    async def test_original_100_minimum_99_cannot_be_relaxed_after_replay_returns_90(self):
        service = quoter()
        gross = 101
        async def amount(_route, funded, *_):
            return funded, gross
        service.price_path = amount
        request = {'intent': 0, 'inputs': [{'currency': PAXG, 'amount': '1000'}], 'outputCurrency': CORE}
        value = await service.candidate(request, 0, 'core-first', BLOCK, [PAXG, OTHER], [500000, 500000])
        self.assertEqual(value['quotedOutput'], '100')
        gross = 91
        current = await service.evaluate_selected(request, value['plan'])
        self.assertEqual(current['quotedOutput'], '90')
        with self.assertRaisesRegex(InvalidPreview, 'Accepted scalar output minimum cannot be met'):
            await TransactionPreparation(service).prepare(preparation(value))
        with self.assertRaisesRegex(InvalidPreview, 'Accepted scalar output minimum cannot be met'):
            await TransactionPreparation(service).prepare(preparation(value, slippageBps=10_000,
                acceptedBounds={'minimumOutput': '99'}))
        self.assertEqual(value['quotedOutput'], '100')

    async def test_selected_replay_reads_changed_pool_state_instead_of_old_embedded_amounts(self):
        service = quoter()
        engine = service.engine
        # Match the production bridge's canonical acquisition boundary while
        # retaining this fixture's independent integer constant-product math.
        async def current_pool(branches, *args, **kwargs):
            known = {pool_identity(pool): pool for pool in engine.registry.inventory.values()}
            branches = deepcopy(branches)
            for branch in branches:
                for hop in branch['hops']:
                    hop['pool'] = deepcopy(known[pool_identity(hop['pool'])])
            return await Engine.quote_sdk_branches(engine, branches, *args, **kwargs)
        engine.quote_sdk_branches = current_pool
        request = {'intent': 0, 'inputs': [{'currency': PAXG, 'amount': '10001'}], 'outputCurrency': CORE}
        value = await service.candidate(request, 0, 'core-first', BLOCK, [PAXG, OTHER], [500000, 500000])
        seed = engine.registry.seed
        reserve = 'reserve0' if seed['token0']['address'].lower() == CORE.lower() else 'reserve1'
        seed[reserve] = str(int(seed[reserve])//2)
        service.conversion = AsyncMock(side_effect=AssertionError('no replacement route search'))
        replayed = await service.evaluate_selected(request, value['plan'])
        self.assertLess(int(replayed['quotedOutput']), int(value['quotedOutput'])//2+1)
        self.assertEqual(replayed['inputs'], value['inputs'])
        self.assertEqual(replayed['plan']['conversions'], value['plan']['conversions'])
        with self.assertRaisesRegex(InvalidPreview, 'Accepted scalar output minimum cannot be met'):
            await TransactionPreparation(service).prepare(preparation(value))
        service.conversion.assert_not_called()

    async def test_basket_redemption_preserves_per_asset_minima_before_repricing(self):
        service = quoter()
        value = await service.quote(economic_request(3))
        original = deepcopy(value['plan']['body']['expectedOutputs'])
        preview = service.preview
        async def deteriorated(mode, payload, block):
            result = await preview(mode, payload, block)
            result['projectedCoreOutputs'][0]['amount'] = str(floor(int(original[0]['amount']), 100)-1)
            return result
        service.preview = deteriorated
        with self.assertRaisesRegex(InvalidPreview, 'Accepted Core output minimum cannot be met'):
            await TransactionPreparation(service).prepare(preparation(value))
        self.assertEqual(value['plan']['body']['expectedOutputs'], original)

    async def test_explicit_legacy_core_minima_survive_preparation_verbatim(self):
        service = quoter()
        value = await service.quote(economic_request(3))
        expected = [{key: row[key] for key in ('kind', 'token', 'id')}
                    | {'minimumAmount': '1'} for row in value['plan']['body']['expectedOutputs']]
        result = await TransactionPreparation(service, now=lambda: 2000).prepare(preparation(value,
            slippageBps=10_000, acceptedBounds={'minimumOutput': '0', 'expectedCoreOutputs': expected}))
        self.assertEqual(result['planDescription']['expectedOutputs'], expected)
        self.assertEqual(result['plan']['minimumOutput'], '0')

    async def test_core_acquisitions_remain_selected_amounts_when_weights_change(self):
        service = quoter()
        request = economic_request()
        request['inputs'][0]['currency'] = WETH
        value = await service.candidate(request, 100, 'core-first', BLOCK,
                                        [PAXG, OTHER], [500000, 500000])
        before = value['plan']['body']['branches'][0]['data']['acquisitions']
        self.assertEqual([row['amountIn'] for row in before], ['5000', '5001'])
        service.basis_reader = AsyncMock(return_value=([PAXG, OTHER], [900000, 100000]))
        replayed = await service.evaluate_selected(request, value['plan'])
        after = replayed['plan']['body']['branches'][0]['data']['acquisitions']
        self.assertEqual(after, before)
        self.assertEqual(replayed['quotedOutput'], value['quotedOutput'])

    async def test_input_maxima_are_preserved_and_cannot_expand_during_replay(self):
        service = quoter()
        value = await service.quote(economic_request())
        accepted = {'inputs': deepcopy(value['inputs']), 'minimumOutput': '0'}
        result = await TransactionPreparation(service).prepare(preparation(value, acceptedBounds=accepted))
        self.assertEqual(result['plan']['inputs'], accepted['inputs'])
        smaller = deepcopy(accepted)
        smaller['inputs'][0]['amount'] = str(int(smaller['inputs'][0]['amount'])-1)
        replay = service.evaluate_selected
        service.evaluate_selected = AsyncMock(wraps=replay)
        with self.assertRaisesRegex(InvalidPreview, 'Accepted input maximum cannot be met'):
            await TransactionPreparation(service).prepare(preparation(value, acceptedBounds=smaller))
        service.evaluate_selected.assert_not_called()

    async def test_preparation_uses_declared_funding_even_when_original_budget_is_larger(self):
        service = quoter()
        request = {'intent': 0, 'inputs': [{'currency': PAXG, 'amount': '1000'}], 'outputCurrency': CORE}
        value = await service.candidate(request, 0, 'core-first', BLOCK, [PAXG, OTHER], [500000, 500000])
        # A future reduced-funding producer may select this evaluated plan under
        # a larger economic budget. Preparation must not restore that budget.
        value['request']['inputs'][0]['amount'] = '2000'
        result = await TransactionPreparation(service).prepare(preparation(value,
            acceptedBounds={'inputs': [{'currency': PAXG, 'amount': '1000'}], 'minimumOutput': '0'}))
        self.assertEqual(result['plan']['inputs'], [{'currency': PAXG, 'amount': '1000'}])
        self.assertEqual(result['economicQuote']['quotedInput'], '1000')

    async def test_execution_lifetime_starts_during_preparation_after_browsing(self):
        service = quoter()
        value = await service.quote(economic_request())
        value['context']['observedAt'] = '2000-01-01T00:00:00.000Z'
        clock = 2000
        replay = service.evaluate_selected
        async def elapsed_during_replay(*args):
            nonlocal clock
            result = await replay(*args)
            clock = 5000
            return result
        service.evaluate_selected = elapsed_during_replay
        result = await TransactionPreparation(service, now=lambda: clock).prepare(preparation(value))
        self.assertEqual(result['plan']['deadline'], '5600')
        self.assertEqual(result['plan']['recipient'], USER)
        self.assertEqual(result['sender'], USER)
        self.assertTrue(result['plan']['body'].startswith('0x'))
        self.assertFalse(any(str(call[0]).startswith(('send', 'eth_send')) for call in service.engine.calls))

    async def test_selected_helpers_or_adapter_change_cannot_retarget_prepared_call(self):
        for field, replacement in (('helpers', '0x'+'f'*40), ('adapter', '0x'+'e'*40)):
            with self.subTest(field=field):
                service = quoter()
                value = await service.quote(economic_request())
                service.evaluate_selected = AsyncMock(side_effect=AssertionError('must not reprice another deployment'))
                setattr(service, field, replacement)
                with self.assertRaisesRegex(InvalidPreview,
                    'Selected Helpers deployment changed' if field == 'helpers' else 'Selected routing adapter changed'):
                    await TransactionPreparation(service).prepare(preparation(value))
                service.evaluate_selected.assert_not_called()

    async def test_deployment_address_case_does_not_change_selected_identity(self):
        service = quoter()
        value = await service.quote(economic_request())
        service.adapter = '0x'+service.adapter[2:].swapcase()
        result = await TransactionPreparation(service).prepare(preparation(value))
        self.assertEqual(result['plan']['inputs'], value['inputs'])

    async def test_conversion_observation_separates_funding_consumption_and_retention(self):
        service = quoter()
        async def partial(_route, funded, *_):
            return funded//2, 101
        service.price_path = partial
        request = {'intent': 0, 'inputs': [{'currency': PAXG, 'amount': '1000'}], 'outputCurrency': CORE}
        value = await service.candidate(request, 0, 'core-first', BLOCK, [PAXG, OTHER], [500000, 500000])
        row, = value['conversionObservations']
        self.assertEqual(row, {'operation': '0:market', 'inputCurrency': PAXG,
            'fundedInput': '1000', 'consumedInput': '500', 'outputCurrency': CORE, 'output': '101'})
        self.assertEqual(value['inputs'], [{'currency': PAXG, 'amount': '1000'}])
        self.assertEqual(value['estimatedRetainedInputCharges'][0]['amount'], '500')
        self.assertNotIn('conversionObservations', value['plan'])
        result = await TransactionPreparation(service).prepare(preparation(value))
        self.assertEqual(result['economicQuote']['conversionObservations'], value['conversionObservations'])
        self.assertEqual(result['plan']['inputs'], value['inputs'])


if __name__ == '__main__':
    unittest.main()
