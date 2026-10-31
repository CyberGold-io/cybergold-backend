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
from cybergold_candidate.quoter.dormant_routes import with_dormant_routes
from cybergold_candidate.quoter.reuse_routes import extract_blueprint, resize_blueprint
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
    async def zero_residual_quote(self):
        service = quoter()
        request = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '1000'},
            {'currency': OTHER, 'amount': '1000'}], 'outputCurrency': CORE}
        value = await service.candidate(request, 100, 'core-first', BLOCK,
                                        [PAXG, OTHER], [500000, 500000])
        return service, value

    async def test_zero_residual_selects_dormant_topology_without_pricing_or_new_economics(self):
        service = quoter()
        service.conversion = AsyncMock(side_effect=AssertionError('No zero-lot route search'))
        service.price_path = AsyncMock(side_effect=AssertionError('No zero-lot pricing'))
        request = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '1000'},
            {'currency': OTHER, 'amount': '1000'}], 'outputCurrency': CORE}
        value = await service.candidate(request, 100, 'core-first', BLOCK, [PAXG, OTHER], [1, 1])
        chosen = value['plan']['conversions']['0:residual:0']
        self.assertEqual(chosen['outputCurrency'], CORE)
        self.assertEqual(value['plan']['body']['continuations'][0]['route'], chosen['template'])
        self.assertEqual(value['plan']['body']['continuations'][0]['feeCygld'], '0')
        self.assertEqual(value['quotedOutput'], '2000')
        self.assertEqual(value['conversionObservations'], [])
        self.assertEqual(value['estimatedRetainedInputCharges'], [])
        service.conversion.assert_not_called()
        service.price_path.assert_not_called()

    async def test_zero_replay_keeps_dormant_route_until_positive_residual_uses_it(self):
        service, value = await self.zero_residual_quote()
        service.conversion = AsyncMock(side_effect=AssertionError('No discovery during replay'))
        same = await service.evaluate_selected(value['request'], value['plan'])
        self.assertEqual(same['plan'], value['plan'])
        preview = service.preview
        async def changed(mode, payload, block):
            result = await preview(mode, payload, block)
            result['amountsInExact'][0] = '999'
            return result
        service.preview = changed
        service.price_path = AsyncMock(return_value=(1, 10))
        prepared = await TransactionPreparation(service).prepare(preparation(same))
        service.price_path.assert_awaited_once()
        self.assertEqual(service.price_path.call_args.args[1], 1)
        self.assertEqual(prepared['economicQuote']['quotedOutput'], '2009')
        self.assertEqual(prepared['outputMinimum'], '1980')
        service.conversion.assert_not_called()

    async def test_dormant_positive_residual_uses_actual_v3_and_v4_sdk(self):
        from quoter_fixture import service as sdk_service, synthetic_pool
        for protocol in ('v3', 'v4'):
            with self.subTest(protocol=protocol):
                changed = False
                async def preview(*_):
                    return {'netCygldOut': '2000', 'amountsInExact': ['900' if changed else '1000', '1000'],
                        'orderedCoreAssets': [PAXG, OTHER],
                        'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
                service = sdk_service(self, [synthetic_pool(PAXG, CORE, 123, protocol)], preview=preview)
                request = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '1000'},
                    {'currency': OTHER, 'amount': '1000'}], 'outputCurrency': CORE}
                value = await service.candidate(request, 100, 'core-first', BLOCK, [PAXG, OTHER], [1, 1])
                service.conversion = AsyncMock(side_effect=AssertionError('No route discovery'))
                changed = True
                result = await TransactionPreparation(service).prepare(preparation(value))
                self.assertGreater(int(result['economicQuote']['quotedOutput']), 2000)
                row, = result['economicQuote']['conversionObservations']
                self.assertEqual(row['operation'], '0:residual:0')
                self.assertEqual(row['fundedInput'], '100')
                self.assertEqual(result['outputMinimum'], '1980')
                service.conversion.assert_not_called()

    async def test_new_positive_residual_does_not_relax_accepted_minimum(self):
        service, value = await self.zero_residual_quote()
        async def changed(*_):
            return {'netCygldOut': '1', 'amountsInExact': ['999', '1000'],
                    'orderedCoreAssets': [PAXG, OTHER],
                    'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
        service.preview = changed
        service.price_path = AsyncMock(return_value=(1, 10))
        with self.assertRaisesRegex(InvalidPreview, 'Accepted scalar output minimum cannot be met'):
            await TransactionPreparation(service).prepare(preparation(value))

    async def test_old_captured_plan_requires_refresh_without_retrofitting_preparation(self):
        service, value = await self.zero_residual_quote()
        del value['plan']['conversions']['0:residual:0']
        value['plan']['body']['continuations'][0]['route'] = {
            'inputCurrency': PAXG, 'outputCurrency': PAXG, 'routes': []}
        captured = deepcopy(value)
        preview = service.preview
        async def changed(mode, payload, block):
            result = await preview(mode, payload, block)
            result['amountsInExact'][0] = '999'
            return result
        service.preview = changed
        service.price_path = AsyncMock(side_effect=AssertionError('No replacement path'))
        with self.assertRaisesRegex(InvalidPreview, 'current Core residual. Refresh the quote'):
            await TransactionPreparation(service).prepare(preparation(value))
        self.assertEqual(value, captured)
        service.price_path.assert_not_called()

    async def test_dormant_completion_is_copied_idempotent_optional_and_protocol_neutral(self):
        from cybergold_candidate.quoter.discovery import market_plan
        from quoter_fixture import synthetic_pool
        for protocol in ('v2', 'v3', 'v4'):
            with self.subTest(protocol=protocol):
                # Reversed B->payment acquisition plus payment->A->Core forms
                # a three-hop dormant path. No inventory enumeration is needed.
                a = synthetic_pool(OTHER, PAXG, 100, protocol)
                b = synthetic_pool(OTHER, WETH, 101, protocol)
                seed = synthetic_pool(PAXG, CORE, 102, protocol)
                def chosen(pool, source, target):
                    hop = {'pool': pool, 'zeroForOne': pool['token0']['address'].lower() == source.lower()}
                    return market_plan(source, target, [hop], 1)['conversions']['0:market']
                value = {'request': {'intent': 0, 'outputCurrency': CORE}, 'plan': {
                    'allocations': [{'kind': 0, 'amountIn': '2'}],
                    'conversions': {'0:acquire:0': chosen(a, OTHER, PAXG),
                                    '0:acquire:1': chosen(b, OTHER, WETH)},
                    'body': {'branches': [{'kind': 0, 'amountIn': '2', 'data': {
                        'basketAssets': [PAXG, WETH],
                        'acquisitions': [{'amountIn': '1'}, {'amountIn': '1'}],
                        'continuations': [{'route': {'inputCurrency': token, 'outputCurrency': token, 'routes': []},
                                           'feeCygld': '0'} for token in (PAXG, WETH)]}}]}}}
                original = deepcopy(value)
                offered = with_dormant_routes(value, seed)
                self.assertEqual(value, original)
                self.assertEqual(with_dormant_routes(offered, seed), offered)
                hops = offered['plan']['conversions']['0:residual:1']['branches'][0]['hops']
                self.assertEqual(len(hops), 3)
                self.assertEqual([pool_identity(h['pool']) for h in hops],
                                 [pool_identity(pool) for pool in (b, a, seed)])
                self.assertTrue(all('sqrtRatioX96' not in h['pool'] for h in hops))
                self.assertEqual(with_dormant_routes(value, None), original)
                blueprint = extract_blueprint({**offered, 'request': {**offered['request'],
                    'inputs': [{'currency': OTHER, 'amount': '2'}]},
                    'inputs': [{'currency': OTHER, 'amount': '2'}]})
                resized = resize_blueprint(blueprint, 4, [WETH, PAXG])
                self.assertEqual(resized['conversions']['0:residual:0'],
                                 offered['plan']['conversions']['0:residual:1'])
                disconnected = deepcopy(value)
                del disconnected['plan']['conversions']['0:acquire:1']
                result = with_dormant_routes(disconnected, seed)
                self.assertNotIn('0:residual:1', result['plan']['conversions'])
                self.assertEqual(result['plan']['body']['branches'][0]['data']['continuations'][1],
                                 value['plan']['body']['branches'][0]['data']['continuations'][1])

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
