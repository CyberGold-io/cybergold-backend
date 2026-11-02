"""Helpers ABI simulation is the economic authority for nominated plans."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from web3 import Web3

from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.exact_input_plan import CORE_BUY, CORE_SELL, MARKET, SCALAR_BODY, CORE_OUTPUT, CONTINUATION
from cybergold_candidate.helpers_execution import ABI
from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.plan_simulation import HelpersPlanSimulation, simulation_scope
from cybergold_candidate.quoter.provenance import attach_origins
from cybergold_candidate.quoter.simulation_funding import SIMULATION_SENDER
from cybergold_candidate.quoter.types import EconomicQuote
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.route_work_slots import PricingSlots
from cybergold_candidate.routing_encoding import ZERO
from cybergold_candidate.tx_preparation import TransactionPreparation
from test_universal_quote import BLOCK, CORE, HELPERS, ADAPTER, USER, WETH, PAXG, OTHER, settings


# Independent ITradeExactInput.TradeResult wire shape, not the implementation's
# projection helper. These bytes must decode through the shipped Helpers ABI.
TRADE_RESULT = ('((address,uint256)[],(uint256,uint256,address,address,uint256,uint256,uint256,uint256,uint256)[],'
                '(uint8,address,uint256,uint256)[],(uint8,address,uint256,uint256)[],'
                '(uint256,uint256,address,uint256)[],uint256,uint256,uint256,address,address)')
NOW = '2026-11-02T12:00:00.000Z'
CODEC = Web3().codec


def stage(index, source, target, funded, output, *, consumed=None, returned=0, branch=0):
    return (branch, index, source, target, funded, returned,
            funded-returned if consumed is None else consumed, 0, output)


def measured(output, *, stages=(), currency=CORE, fees=(0, 0, 0), retained=(), recovery=(), recipients=None):
    return ([], list(stages), [(0, currency, 0, output)] if recipients is None else list(recipients),
            list(recovery), list(retained), *fees, HELPERS, USER)


def encoded(value):
    return {'result': Web3.to_hex(CODEC.encode([TRADE_RESULT], [value]))}


def route(source, target, *, split=False):
    rows = [] if source.lower() == target.lower() else [
        {'sharePpm': 250000 if split else 0,
         'steps': [{'kind': 1, 'currencyOut': target, 'fee': 500, 'tickSpacing': 10}]}]
    if split:
        rows.append({'sharePpm': 0, 'steps': [{'kind': 2, 'currencyOut': target, 'fee': 100, 'tickSpacing': 1}]})
    return {'inputCurrency': source, 'outputCurrency': target, 'routes': rows}


def market(intent=0, *, native=False):
    source = ZERO if native else WETH if intent == 0 else CORE
    target = CORE if intent == 0 else PAXG
    template = route(WETH if native else source, target)
    request = {'intent': intent, 'inputs': [{'currency': source, 'amount': '10000'}], 'outputCurrency': target}
    a, b = sorted((template['inputCurrency'], target), key=str.lower)
    physical = {'pool': {'id': '0x'+'17'*20, 'address': '0x'+'17'*20, 'protocol': 'v3',
        'feePips': 500, 'tickSpacing': 10, 'token0': {'address': a}, 'token1': {'address': b}},
        'zeroForOne': template['inputCurrency'].lower() == a.lower()}
    plan = {'allocations': [{'kind': 1, 'amountIn': '10000'}],
        'conversions': {'0:market': {'inputCurrency': source, 'outputCurrency': target,
            'branches': [{'hops': [physical]}], 'template': deepcopy(template), 'discoveryOrigins': ['cybergold-custom', 'uniroute-local']}},
        'body': {'branches': [{'kind': 1, 'amountIn': '10000',
                              'data': {'route': template, 'feeCygld': '999'}}]}}
    return request, plan


class Provider:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.entered, self.release, self.drained = asyncio.Event(), None, asyncio.Event()

    async def make_request(self, method, params):
        self.calls.append((method, deepcopy(params)))
        self.entered.set()
        try:
            if self.release is not None:
                await self.release.wait()
            response = self.responses.pop(0)
            if callable(response):
                response = response(method, params)
            if isinstance(response, BaseException):
                raise response
            return deepcopy(response)
        finally:
            self.drained.set()


class Rpc:
    def __init__(self, provider):
        self.w3 = SimpleNamespace(codec=CODEC, provider=provider)
        self.heads, self.verifications = [], []
        self.disproof = False

    async def block(self, value):
        self.heads.append(value)
        return deepcopy(BLOCK)

    async def assert_canonical(self, block):
        self.verifications.append(deepcopy(block))
        if self.disproof:
            raise SnapshotChanged('Pinned preparation head changed')

    async def read_function(self, *_):
        raise AssertionError('Helpers simulation must not read SDK/Core getters')


def fixture(*responses):
    provider = Provider(*responses)
    rpc = Rpc(provider)
    registry = SimpleNamespace(chain=31338, core=CORE, seed=None, inventory={}, get_rpc=lambda: rpc,
                               ensure_loaded=AsyncMock())
    simulation = HelpersPlanSimulation(settings(), registry, helpers=HELPERS, adapter=ADAPTER, core=CORE,
                                       now=lambda: NOW)
    engine = SimpleNamespace(registry=registry, semaphore=PricingSlots(8), quote_sdk_branches=AsyncMock(
        side_effect=AssertionError('Helpers simulation must not invoke SDK pricing')))
    q = Quoter(settings(), engine, now=lambda: NOW)
    return simulation, q, rpc, provider


def decode(provider, index=0):
    method, arguments = provider.calls[index]
    transaction, block_tag, overrides = arguments
    function, values = Web3().eth.contract(abi=ABI).decode_function_input(transaction['data'])
    return method, transaction, block_tag, overrides, function, values


def branches(values):
    return CODEC.decode([f'({SCALAR_BODY})'], values['plan']['body'])[0][0]


class HelpersPlanSimulationTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_sale_projects_actual_amounts_and_preparation_binds_actual_recovery(self):
        request = {'intent': 1, 'inputs': [{'currency': CORE, 'amount': '10000'}], 'outputCurrency': WETH}
        outputs = [{'kind': 0, 'token': PAXG, 'id': '0', 'amount': '1'},
                   {'kind': 1, 'token': OTHER, 'id': '7', 'amount': '1'},
                   {'kind': 0, 'token': WETH, 'id': '0', 'amount': '999'}]
        plan = {'allocations': [{'kind': 0, 'amountIn': '10000'}], 'conversions': {},
                'body': {'branches': [{'kind': 0, 'amountIn': '10000', 'data': {
                    'expectedOutputs': outputs,
                    'conversions': [route(PAXG, WETH), route(OTHER, OTHER), route(WETH, WETH)]}}]}}
        saved = deepcopy(plan)
        raw = encoded(measured(200, currency=WETH, stages=[stage(0, PAXG, WETH, 321, 123)],
                               recovery=[(1, OTHER, 7, 45)], fees=(3, 4, 0)))
        simulation, q, rpc, provider = fixture(raw, raw)
        quote = await simulation(request, plan)
        actual = quote['plan']['body']['branches'][0]['data']['expectedOutputs']
        self.assertEqual([row['amount'] for row in actual], ['321', '45', '77'])
        self.assertEqual([row['source'] for row in quote['pricingEvidence']['coreOutputAmounts']],
                         ['conversion-funding', 'scalar-remainder', 'recovery-shares'])
        self.assertEqual(quote['conversionObservations'][0]['fundedInput'], '321')
        self.assertEqual(len(provider.calls), 1)
        prepared = await TransactionPreparation(q).prepare({'quote': quote, 'sender': USER, 'recipient': USER})
        self.assertEqual(prepared['economicQuote']['recoveryShares'][0]['amount'], '45')
        encoded_core = CODEC.decode([CORE_SELL], branches(decode(provider, 1)[-1])[0][2])[0]
        self.assertEqual([row[3] for row in encoded_core[0]], [317, 44, 76])
        self.assertEqual(len(provider.calls), 2)  # One quote, one fresh preparation.
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))
        self.assertEqual(plan, saved)

    async def test_mixed_native_sale_uses_branch_and_wrapper_stages_for_core_amounts(self):
        request = {'intent': 1, 'inputs': [{'currency': CORE, 'amount': '10000'}], 'outputCurrency': ZERO}
        plan = {'allocations': [{'kind': 1, 'amountIn': '4000'}, {'kind': 0, 'amountIn': '6000'}],
            'conversions': {}, 'body': {'branches': [
                {'kind': 1, 'amountIn': '4000', 'data': {'route': route(CORE, WETH), 'feeCygld': '4'}},
                {'kind': 0, 'amountIn': '6000', 'data': {'expectedOutputs': [
                    {'kind': 0, 'token': PAXG, 'id': '0', 'amount': '1'},
                    {'kind': 1, 'token': OTHER, 'id': '7', 'amount': '1'},
                    {'kind': 0, 'token': WETH, 'id': '0', 'amount': '1'}],
                    'conversions': [route(PAXG, WETH), route(OTHER, OTHER), route(WETH, WETH)]}}]}}
        stages = [stage(0, CORE, WETH, 3996, 50), stage(1, WETH, ZERO, 50, 50),
                  stage(2, PAXG, WETH, 100, 200, branch=1), stage(3, WETH, ZERO, 200, 200, branch=1),
                  stage(4, WETH, ZERO, 70, 70, branch=1)]
        simulation, _, _, provider = fixture(encoded(measured(320, currency=ZERO, stages=stages,
                                                            recovery=[(1, OTHER, 7, 9)], fees=(3, 4, 4))))
        quote = await simulation(request, plan)
        actual = quote['plan']['body']['branches'][1]['data']['expectedOutputs']
        self.assertEqual([row['amount'] for row in actual], ['100', '9', '70'])
        self.assertEqual([row['operation'] for row in quote['conversionObservations']],
                         ['0:market', '1:redeem:0', '1:redeem:2'])
        self.assertEqual(quote['quotedOutput'], '320')
        self.assertEqual(len(provider.calls), 1)

    async def test_repeated_recovery_identity_is_projected_only_when_branch_order_is_known(self):
        request = {'intent': 1, 'inputs': [{'currency': CORE, 'amount': '10000'}], 'outputCurrency': PAXG}
        plan = {'allocations': [{'kind': 0, 'amountIn': '4000'}, {'kind': 0, 'amountIn': '6000'}],
            'conversions': {}, 'body': {'branches': [{'kind': 0, 'amountIn': str(amount), 'data': {
                'expectedOutputs': [{'kind': 1, 'token': OTHER, 'id': '7', 'amount': str(nominal)}],
                'conversions': [route(OTHER, OTHER)]}} for amount, nominal in [(4000, 5), (6000, 9)]]}}
        for recovery, expected in [([(1, OTHER, 7, 10), (1, OTHER, 7, 20)], ['10', '20']),
                                   ([], ['0', '0']), ([(1, OTHER, 7, 20)], ['5', '9'])]:
            with self.subTest(recovery=recovery):
                simulation, _, _, provider = fixture(encoded(measured(0, currency=PAXG, recovery=recovery)))
                quote = await simulation(request, plan)
                self.assertEqual([branch['data']['expectedOutputs'][0]['amount']
                                  for branch in quote['plan']['body']['branches']], expected)
                if len(recovery) == 1:
                    self.assertNotIn('coreOutputAmounts', quote['pricingEvidence'])
                self.assertEqual(len(provider.calls), 1)

    async def test_scalar_funding_remainder_is_reported_by_helpers_without_local_equality_gate(self):
        request, plan = market()
        plan['allocations'][0]['amountIn'] = plan['body']['branches'][0]['amountIn'] = '2000'
        simulation, _, _, provider = fixture(encoded(measured(100000,
            stages=[stage(0, WETH, CORE, 2000, 100000)], retained=[(1, 1, WETH, 8000)])))
        value = await simulation(request, plan)
        self.assertEqual(value['inputs'][0]['amount'], '10000')
        self.assertEqual(value['estimatedRetainedInputCharges'][0]['amount'], '8000')
        self.assertEqual(value['quotedOutput'], '99900')
        self.assertEqual(branches(decode(provider)[-1])[0][1], 2000)
        self.assertEqual(len(provider.calls), 1)

    async def test_successful_zero_scalar_receipt_is_not_rejected_after_contract_execution(self):
        request = {'intent': 1, 'inputs': [{'currency': CORE, 'amount': '10000'}], 'outputCurrency': PAXG}
        plan = {'allocations': [{'kind': 0, 'amountIn': '10000'}], 'conversions': {},
            'body': {'branches': [{'kind': 0, 'amountIn': '10000', 'data': {
                'expectedOutputs': [{'kind': 0, 'token': PAXG, 'id': '0', 'amount': '0'}],
                'conversions': [route(PAXG, PAXG)]}}]}}
        simulation, _, _, provider = fixture(encoded(measured(0, currency=PAXG)))
        quote = await simulation(request, plan)
        self.assertEqual(quote['quotedOutput'], '0')
        self.assertEqual(quote['recoveryShares'], [])
        self.assertEqual(decode(provider)[-1]['plan']['minimumOutput'], 0)
        self.assertEqual(len(provider.calls), 1)

    async def test_market_buy_is_one_latest_helpers_call_and_projects_output_fee_only(self):
        request, plan = market()
        saved = deepcopy(plan)
        raw = measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)])
        simulation, q, rpc, provider = fixture(encoded(raw))
        value = await simulation(request, plan)
        self.assertEqual(len(provider.calls), 1)
        method, tx, tag, overrides, function, values = decode(provider)
        self.assertEqual((method, function.fn_name, tag), ('eth_call', 'executeExactInput', 'latest'))
        self.assertEqual((tx['from'], tx['to'], tx['gasPrice']), (SIMULATION_SENDER, HELPERS, '0x0'))
        self.assertNotIn('value', tx)
        self.assertEqual(set(overrides), {SIMULATION_SENDER, WETH})
        self.assertEqual((values['plan']['deadline'], values['plan']['minimumOutput']), (0, 1))
        self.assertEqual(values['plan']['recipient'], SIMULATION_SENDER)
        body = branches(values)
        encoded_market = CODEC.decode([MARKET], body[0][2])[0]
        self.assertEqual((body[0][0], body[0][1], encoded_market[1]), (1, 10000, 0))
        self.assertEqual(encoded_market[0][2], 0)  # No fabricated per-AMM bound.
        self.assertEqual(values['funding']['authorizations'][0]['kind'], 0)
        self.assertEqual(values['funding']['permit2']['permit']['permitted'], [])
        self.assertEqual(value['quotedOutput'], '99900')
        self.assertEqual(value['fees'], {'coreProtocolFeeCygld': '0', 'coreHelpersFeeCygld': '0', 'marketFeeCygld': '100'})
        self.assertEqual(value['plan']['body']['branches'][0]['data']['feeCygld'], '100')
        self.assertEqual(value['pricingEvidence']['stages'][0]['amountOut'], '100000')
        self.assertEqual(value['pricingEvidence']['feeTreatment'], 'policy-output-arithmetic')
        self.assertEqual(value['conversionObservations'][0]['output'], '100000')
        self.assertEqual(value['context'], {'chainId': 31338, 'blockNumber': None, 'blockHash': None,
            'blockTag': 'latest', 'verification': 'quote-observation', 'observedAt': NOW})
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))
        q.engine.quote_sdk_branches.assert_not_called()
        self.assertEqual(plan, saved)

    async def test_core_sale_zero_minimum_is_limited_by_actual_helpers_outputs(self):
        for nominated, actual, minimum, succeeds in ((0, 0, 0, True), (500, 500, 1, True), (0, 500, 0, False)):
            with self.subTest(nominated=nominated, actual=actual):
                request = {'intent': 1, 'inputs': [{'currency': CORE, 'amount': '10000'}], 'outputCurrency': PAXG}
                plan = {'allocations': [{'kind': 0, 'amountIn': '10000'}], 'conversions': {},
                    'body': {'branches': [{'kind': 0, 'amountIn': '10000', 'data': {
                        'expectedOutputs': [{'kind': 1, 'token': OTHER, 'id': '7', 'amount': '3'},
                                            {'kind': 0, 'token': PAXG, 'id': '0', 'amount': str(nominated)}],
                        'conversions': [route(OTHER, OTHER), route(PAXG, PAXG)]}}]}}
                result = encoded(measured(actual, currency=PAXG, recovery=[(1, OTHER, 7, 3)], fees=(7, 11, 0)))
                def oracle(_method, params):
                    _, decoded = Web3().eth.contract(abi=ABI).decode_function_input(params[0]['data'])
                    bound = decoded['plan']['minimumOutput']
                    # Helpers permits min=0 for share-only Core redemption,
                    # rejects it if fresh ERC20 outputs have become positive,
                    # and enforces nonzero minima against the final scalar.
                    if bound == 0 and actual:
                        data = Web3.to_hex(Web3.keccak(text='ZeroFinalMinimum()')[:4])
                        return {'error': {'code': 3, 'data': data, 'message': 'execution reverted'}}
                    if bound > actual:
                        data = Web3.to_hex(Web3.keccak(text='InsufficientOutput(uint256,uint256)')[:4]
                            + CODEC.encode(['uint256', 'uint256'], [bound, actual]))
                        return {'error': {'code': 3, 'data': data, 'message': 'execution reverted'}}
                    return result
                simulation, _, rpc, provider = fixture(oracle)
                if succeeds:
                    value = await simulation(request, plan)
                    self.assertEqual(value['quotedOutput'], str(actual))
                    self.assertEqual(value['recoveryShares'][0]['amount'], '3')
                    self.assertEqual(value['routeFamily'], 'core')
                    self.assertEqual(value['fees']['coreHelpersFeeCygld'], '11')
                else:
                    with self.assertRaises(QuoteFailure) as caught:
                        await simulation(request, plan)
                    self.assertEqual(caught.exception.code, 'quote-contract-reverted')
                self.assertEqual(decode(provider)[-1]['plan']['minimumOutput'], minimum)
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual((rpc.heads, rpc.verifications), ([], []))

    async def test_raw_trade_result_remains_distinct_from_policy_normalized_quote(self):
        request, plan = market()
        raw_return = measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)])
        simulation, _, _, _ = fixture(encoded(raw_return))
        value = await simulation(request, plan)
        evidence = value['pricingEvidence']['rawTradeResult']
        self.assertEqual(evidence['recipientOutputs'], [{'kind': '0', 'token': CORE, 'id': '0', 'amount': '100000'}])
        self.assertEqual(evidence['marketFeeCygld'], '0')
        self.assertEqual(evidence['feeBeneficiaryAtSettlement'], USER)
        self.assertEqual(evidence['retainedCustodian'], HELPERS)
        self.assertEqual(evidence['stages'][0]['amountOut'], '100000')
        self.assertEqual(value['estimatedRecipientOutputs'][0]['amount'], '99900')
        self.assertEqual(value['fees']['marketFeeCygld'], '100')
        self.assertEqual(value['plan']['body']['branches'][0]['data']['feeCygld'], '100')
        value['estimatedRecipientOutputs'][0]['amount'] = 'mutated-normalized-copy'
        self.assertEqual(evidence['recipientOutputs'][0]['amount'], '100000')
        normalized = EconomicQuote.model_validate({**value,
            'estimatedRecipientOutputs': [{'kind': 0, 'token': CORE, 'id': '0', 'amount': '99900'}]}).model_dump()
        self.assertEqual(normalized['pricingEvidence']['rawTradeResult'], evidence)

    async def test_native_sale_zero_output_branch_has_no_unwrap_stage_before_positive_sibling(self):
        request, plan = market(1)
        request['outputCurrency'] = ZERO
        template = route(CORE, WETH)
        plan['allocations'] = [{'kind': 1, 'amountIn': '3000'}, {'kind': 1, 'amountIn': '7000'}]
        plan['conversions'] = {}
        plan['body']['branches'] = [{'kind': 1, 'amountIn': str(amount),
            'data': {'route': deepcopy(template), 'feeCygld': '999'}} for amount in (3000, 7000)]
        # Helpers skips the trailing unwrap when the first AMM output is zero.
        # There is no omitted-placeholder stage between these two branches.
        raw_stages = [stage(0, CORE, WETH, 2997, 0),
                      stage(1, CORE, WETH, 6993, 14000, branch=1),
                      stage(2, WETH, ZERO, 14000, 14000, branch=1)]
        simulation, _, _, provider = fixture(encoded(measured(14000, currency=ZERO,
            stages=raw_stages, fees=(0, 0, 10))))
        value = await simulation(request, plan)
        self.assertEqual(value['quotedOutput'], '14000')
        self.assertEqual(value['fees']['marketFeeCygld'], '10')
        self.assertEqual([row['operation'] for row in value['conversionObservations']], ['0:market', '1:market'])
        self.assertEqual([row['output'] for row in value['conversionObservations']], ['0', '14000'])
        self.assertEqual([row['fundedInput'] for row in value['conversionObservations']], ['2997', '6993'])
        self.assertEqual([row['stage'] for row in value['pricingEvidence']['rawTradeResult']['stages']], ['0', '1', '2'])
        encoded_branches = branches(decode(provider)[-1])
        self.assertEqual([CODEC.decode([MARKET], row[2])[0][1] for row in encoded_branches], [3, 7])
        self.assertEqual(len(provider.calls), 1)

    async def test_market_sell_fee_is_in_input_funding_and_is_not_deducted_from_output(self):
        request, plan = market(1)
        raw = measured(50000, currency=PAXG, fees=(0, 0, 10),
            stages=[stage(0, CORE, PAXG, 9990, 50000, consumed=9980, returned=10)],
            retained=[(0, 0, CORE, 10)])
        simulation, _, rpc, provider = fixture(encoded(raw))
        value = await simulation(request, plan)
        encoded_market = CODEC.decode([MARKET], branches(decode(provider)[-1])[0][2])[0]
        self.assertEqual(encoded_market[1], 10)
        self.assertEqual(value['quotedOutput'], '50000')
        self.assertEqual(value['fees']['marketFeeCygld'], '10')
        self.assertEqual(value['quotedInput'], '10000')
        self.assertEqual(value['conversionObservations'][0]['fundedInput'], '9990')
        self.assertEqual(value['conversionObservations'][0]['consumedInput'], '9980')
        self.assertEqual(value['estimatedRetainedInputCharges'], [{'branch': 0, 'stage': 0, 'currency': CORE, 'amount': '10'}])
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))

    async def test_mixed_core_buy_residual_wrappers_and_split_are_one_ordered_execution(self):
        request, plan = market(native=True)
        acquire = route(WETH, PAXG, split=True)
        continuation = route(PAXG, CORE)
        plan['allocations'] = [{'kind': 0, 'amountIn': '6000'}, {'kind': 1, 'amountIn': '4000'}]
        plan['body']['branches'] = [
            {'kind': 0, 'amountIn': '6000', 'data': {'basketAssets': [PAXG, WETH],
                'acquisitions': [{'amountIn': '4000', 'route': acquire}, {'amountIn': '2000', 'route': route(WETH, WETH)}],
                'continuations': [{'route': continuation, 'feeCygld': '777'},
                                  {'route': route(WETH, CORE), 'feeCygld': '888'}]}},
            {'kind': 1, 'amountIn': '4000', 'data': {'route': route(WETH, CORE, split=True), 'feeCygld': '999'}}]
        original_market = deepcopy(plan['conversions']['0:market'])
        plan['conversions'] = {
            operation: {**deepcopy(original_market), 'inputCurrency': source, 'outputCurrency': target,
                        'template': deepcopy(template)}
            for operation, source, target, template in (
                ('0:acquire:0', ZERO, PAXG, acquire), ('0:acquire:1', ZERO, WETH, route(WETH, WETH)),
                ('0:residual:0', PAXG, CORE, continuation), ('1:market', ZERO, CORE, route(WETH, CORE, split=True)))}
        raw_stages = [stage(0, ZERO, WETH, 4000, 4000),
            stage(1, WETH, PAXG, 4000, 8000, consumed=3900, returned=100),
            stage(2, ZERO, WETH, 2000, 2000), stage(3, PAXG, CORE, 8000, 20000, consumed=7000, returned=1000),
            stage(4, PAXG, CORE, 1000, 3000), stage(5, WETH, CORE, 2000, 0),
            stage(6, ZERO, WETH, 4000, 4000, branch=1), stage(7, WETH, CORE, 4000, 10000, branch=1)]
        simulation, _, rpc, provider = fixture(encoded(measured(33000, stages=raw_stages,
            fees=(7, 11, 0), retained=[(0, 1, WETH, 100)])))
        value = await simulation(request, plan)
        _, tx, tag, overrides, _, values = decode(provider)
        self.assertEqual((tag, tx['value'], overrides), ('latest', '0x2710', {SIMULATION_SENDER: {'balance': '0x2710'}}))
        core_branch, market_branch = branches(values)
        core = CODEC.decode([CORE_BUY], core_branch[2])[0]
        self.assertEqual(list(core[0]), [PAXG.lower(), WETH.lower()])
        self.assertEqual([row[0] for row in core[1]], [4000, 2000])
        self.assertEqual([row[0] for row in core[1][0][1][3]], [250000, 0])
        self.assertEqual([row[1] for row in core[2]], [0, 0])
        self.assertEqual(CODEC.decode([MARKET], market_branch[2])[0][1], 0)
        self.assertEqual(value['quotedOutput'], '32987')
        self.assertEqual(value['fees'], {'coreProtocolFeeCygld': '7', 'coreHelpersFeeCygld': '11', 'marketFeeCygld': '13'})
        self.assertEqual(value['routeFamily'], 'mixed')
        self.assertEqual(value['plan']['body']['branches'][0]['data']['continuations'][0]['feeCygld'], '3')
        self.assertEqual(value['plan']['body']['branches'][0]['data']['continuations'][1]['feeCygld'], '0')
        self.assertEqual([row['operation'] for row in value['conversionObservations']],
                         ['0:acquire:0', '0:acquire:1', '0:residual:0', '1:market'])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))

    async def test_direct_basket_issue_encodes_vector_and_projects_only_actual_residual_fee(self):
        request = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '8000'},
            {'currency': WETH, 'amount': '2000'}], 'outputCurrency': CORE}
        plan = {'allocations': [], 'conversions': {}, 'body': {'continuations': [
            {'route': route(PAXG, CORE), 'feeCygld': '999'},
            {'route': route(WETH, CORE), 'feeCygld': '999'}]}}
        stages = [stage(0, PAXG, CORE, 8000, 20000, consumed=7000, returned=1000),
                  stage(1, PAXG, CORE, 1000, 3000), stage(2, WETH, CORE, 2000, 0)]
        simulation, _, rpc, provider = fixture(encoded(measured(23000, stages=stages, fees=(7, 11, 0))))
        value = await simulation(request, plan)
        _, _, tag, overrides, _, values = decode(provider)
        continuations = CODEC.decode([f'({CONTINUATION}[])'], values['plan']['body'])[0][0]
        self.assertEqual([row[1] for row in continuations], [0, 0])
        self.assertEqual([row['amount'] for row in values['plan']['inputs']], [8000, 2000])
        self.assertEqual(len(values['funding']['authorizations']), 2)
        self.assertEqual(set(overrides), {SIMULATION_SENDER, PAXG, WETH})
        self.assertEqual(value['quotedOutput'], '22997')
        self.assertEqual(value['fees']['marketFeeCygld'], '3')
        self.assertEqual([row['feeCygld'] for row in value['plan']['body']['continuations']], ['3', '0'])
        self.assertNotIn('quotedInput', value)
        self.assertEqual(tag, 'latest')
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))

    async def test_schema_provenance_and_stored_observation_preserve_helpers_evidence(self):
        request, plan = market()
        simulation, q, rpc, provider = fixture(encoded(measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)])))
        quote = attach_origins(await simulation(request, plan))
        normalized = EconomicQuote.model_validate(quote).model_dump(exclude_none=True)
        self.assertEqual(normalized['pricingEvidence'], quote['pricingEvidence'])
        self.assertEqual(normalized['routeOrigins']['pricing'], 'helpers-execution-with-policy-fees')
        self.assertEqual(normalized['routeOrigins']['discoveryProviders'], ['cybergold-custom', 'uniroute-local'])
        class Store:
            def capture_scope(self, request):
                return 'same-scope'
            async def lookup(self, request, *, scope):
                return deepcopy(normalized)
            async def neighbors(self, request, *, scope):
                return {}
        q.quote = AsyncMock(side_effect=AssertionError('Stored quote must not reprice'))
        value = await EconomicQuotes(q, Store()).get(request)
        self.assertEqual(value['observation'], {'source': 'stored', 'refresh': False})
        self.assertEqual(value['pricingEvidence'], quote['pricingEvidence'])
        self.assertEqual(value['context'], quote['context'])
        self.assertEqual(value['routeOrigins'], quote['routeOrigins'])
        self.assertEqual(value['plan'], quote['plan'])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))
        q.quote.assert_not_called()

    async def test_simulation_reuse_is_request_local_and_never_reuses_nomination_origins(self):
        request, plan = market()
        first = measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)])
        later = measured(200000, stages=[stage(0, WETH, CORE, 10000, 200000)])
        simulation, _, _, provider = fixture(encoded(first), encoded(later))
        alternative = deepcopy(plan)
        alternative['conversions']['0:market']['discoveryOrigins'] = ['uniswap-alpharouter']
        async with simulation_scope():
            initial = attach_origins(await simulation(request, plan))
            repeated = attach_origins(await simulation(request, alternative))
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(repeated['quotedOutput'], initial['quotedOutput'])
            self.assertEqual(repeated['context']['observedAt'], initial['context']['observedAt'])
            self.assertEqual(initial['pricingEvidence']['rpcCalls'], 1)
            self.assertEqual(repeated['pricingEvidence']['rpcCalls'], 0)
            self.assertEqual(repeated['pricingEvidence']['reused'], 1)
            self.assertEqual(repeated['routeOrigins']['discoveryProviders'], ['uniswap-alpharouter'])
        async with simulation_scope():
            fresh = await simulation(request, plan)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(fresh['quotedOutput'], '199800')
        self.assertEqual(fresh['pricingEvidence']['rpcCalls'], 1)

    async def test_overlapping_simulation_subscribers_coalesce_and_cancel_independently(self):
        for ending in ('one-caller', 'all-callers', 'scope-owner'):
            with self.subTest(ending=ending):
                request, plan = market()
                alternative = deepcopy(plan)
                alternative['conversions']['0:market']['discoveryOrigins'] = ['uniswap-alpharouter']
                simulation, _, _, provider = fixture(encoded(measured(100000,
                    stages=[stage(0, WETH, CORE, 10000, 100000)])))
                provider.release = asyncio.Event()
                joined, subscriptions = asyncio.Event(), 0
                original = SharedReads.many
                async def subscribe(reads, *args, **kwargs):
                    nonlocal subscriptions
                    subscriptions += 1
                    if subscriptions == 2:
                        joined.set()
                    return await original(reads, *args, **kwargs)
                async with asyncio.timeout(1):
                    with patch.object(SharedReads, 'many', subscribe):
                        async with simulation_scope():
                            first = asyncio.create_task(simulation(request, plan))
                            await provider.entered.wait()
                            second = asyncio.create_task(simulation(request, alternative))
                            await joined.wait()
                            self.assertEqual(len(provider.calls), 1)
                            if ending == 'one-caller':
                                first.cancel()
                                with self.assertRaises(asyncio.CancelledError):
                                    await first
                                self.assertFalse(provider.drained.is_set())
                                provider.release.set()
                                surviving = attach_origins(await second)
                                self.assertEqual(surviving['quotedOutput'], '99900')
                                self.assertEqual(surviving['pricingEvidence']['coalesced'], 1)
                                self.assertEqual(surviving['pricingEvidence']['rpcCalls'], 0)
                                self.assertEqual(surviving['routeOrigins']['discoveryProviders'], ['uniswap-alpharouter'])
                            elif ending == 'all-callers':
                                first.cancel()
                                second.cancel()
                                outcomes = await asyncio.gather(first, second, return_exceptions=True)
                                self.assertTrue(all(isinstance(error, asyncio.CancelledError) for error in outcomes))
                        # Closing the request owner also cancels a still-needed
                        # producer; its subscribers receive cancellation, not a
                        # price fabricated from an abandoned RPC request.
                        if ending == 'scope-owner':
                            outcomes = await asyncio.gather(first, second, return_exceptions=True)
                            self.assertTrue(all(isinstance(error, asyncio.CancelledError) for error in outcomes))
                self.assertTrue(provider.drained.is_set())
                self.assertEqual(len(provider.calls), 1)

    async def test_rpc_rate_limit_and_transport_failure_are_not_retried(self):
        request, plan = market()
        simulation, _, _, provider = fixture({'error': {'code': -32005, 'message': 'opaque upstream detail'}})
        with self.assertRaises(Exception) as caught:
            await simulation(request, plan)
        self.assertEqual(caught.exception.code, 'rpc-rate-limit')
        self.assertNotIn('opaque upstream detail', str(caught.exception))
        self.assertEqual(len(provider.calls), 1)
        simulation, _, _, provider = fixture(OSError('transport unavailable'))
        with self.assertRaisesRegex(OSError, 'transport unavailable'):
            await simulation(request, plan)
        self.assertEqual(len(provider.calls), 1)

    async def test_preparation_inside_quote_scope_always_executes_fresh_identical_calldata(self):
        request, plan = market()
        # An explicitly selected zero-fee plan produces identical calldata to
        # neutral quote pricing. Mode alone must prevent preparation reuse.
        plan['body']['branches'][0]['data']['feeCygld'] = '0'
        first = measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)])
        latest = measured(120000, stages=[stage(0, WETH, CORE, 10000, 120000)])
        simulation, q, rpc, provider = fixture(encoded(first), encoded(latest))
        async with simulation_scope():
            quote = await simulation(request, plan)
            prepared = await q.evaluate_selected(request, plan)
        self.assertEqual(provider.calls[0], provider.calls[1])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(quote['quotedOutput'], '99900')
        self.assertEqual(prepared['quotedOutput'], '120000')
        self.assertEqual(prepared['fees']['marketFeeCygld'], '0')
        self.assertEqual(prepared['pricingEvidence']['rpcCalls'], 1)
        self.assertEqual(prepared['pricingEvidence']['reused'], 0)
        self.assertEqual(prepared['context']['verification'], 'execution-simulation')
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))

    async def test_preparation_uses_actual_fees_latest_state_and_original_accepted_bound(self):
        request, plan = market()
        neutral = measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)])
        actual = measured(99900, stages=[stage(0, WETH, CORE, 10000, 100000)], fees=(0, 0, 100))
        simulation, q, rpc, provider = fixture(encoded(neutral), encoded(actual))
        quote = attach_origins(await simulation(request, plan))
        value = await TransactionPreparation(q, now=lambda: 1000).prepare({'quote': quote, 'sender': USER,
            'recipient': USER, 'acceptedBounds': {'minimumOutput': '99800'}})
        _, tx, tag, _, _, values = decode(provider, 1)
        self.assertEqual(tag, 'latest')
        self.assertEqual((values['plan']['recipient'], values['plan']['minimumOutput']), (USER, 99800))
        self.assertEqual(CODEC.decode([MARKET], branches(values)[0][2])[0][1], 100)
        self.assertEqual(values['plan']['deadline'], 0)
        self.assertEqual(value['plan']['deadline'], '1600')
        self.assertEqual(value['outputMinimum'], '99800')
        self.assertEqual(value['economicQuote']['quotedOutput'], '99900')
        self.assertEqual(value['economicQuote']['fees']['marketFeeCygld'], '100')
        self.assertEqual(value['economicQuote']['context']['verification'], 'execution-simulation')
        self.assertIsNone(value['economicQuote']['context']['blockNumber'])
        self.assertIsNone(value['economicQuote']['context']['blockHash'])
        self.assertEqual(value['economicQuote']['routeOrigins']['discoveryProviders'], ['cybergold-custom', 'uniroute-local'])
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))
        self.assertEqual(tx['from'], SIMULATION_SENDER)
        q.engine.quote_sdk_branches.assert_not_called()

    async def test_preparation_keeps_accepted_minimum_when_helpers_reverts(self):
        request, plan = market()
        selector = Web3.keccak(text='InsufficientOutput(uint256,uint256)')[:4]
        revert = Web3.to_hex(selector+CODEC.encode(['uint256', 'uint256'], [99800, 99700]))
        simulation, q, rpc, provider = fixture(
            encoded(measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)])),
            {'error': {'code': 3, 'data': revert, 'message': 'execution reverted'}})
        quote = attach_origins(await simulation(request, plan))
        with self.assertRaises(QuoteFailure) as caught:
            await TransactionPreparation(q).prepare({'quote': quote, 'sender': USER, 'recipient': USER,
                'acceptedBounds': {'minimumOutput': '99800'}})
        self.assertEqual(caught.exception.code, 'quote-contract-reverted')
        decoded = decode(provider, 1)
        self.assertEqual(decoded[-1]['plan']['minimumOutput'], 99800)
        self.assertEqual(decoded[2], 'latest')
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))

    async def test_preparation_preserves_accepted_core_output_vector_in_real_abi(self):
        request = {'intent': 3, 'inputs': [{'currency': CORE, 'amount': '10000'}], 'outputCurrency': ZERO}
        outputs = [{'kind': 0, 'token': PAXG, 'id': '0', 'amount': '500'},
                   {'kind': 1, 'token': OTHER, 'id': '7', 'amount': '3'}]
        plan = {'allocations': [], 'conversions': {}, 'body': {'expectedOutputs': outputs}}
        vector = measured(0, recipients=[(0, PAXG, 0, 500), (1, OTHER, 7, 3)],
                          recovery=[(1, OTHER, 7, 3)], fees=(7, 11, 0))
        fresh = measured(0, recipients=[(0, PAXG, 0, 600), (1, OTHER, 7, 4)],
                         recovery=[(1, OTHER, 7, 4)], fees=(7, 11, 0))
        simulation, q, rpc, provider = fixture(encoded(vector), encoded(fresh))
        quote = attach_origins(await simulation(request, plan))
        accepted = [{'kind': 0, 'token': PAXG, 'id': '0', 'minimumAmount': '490'},
                    {'kind': 1, 'token': OTHER, 'id': '7', 'minimumAmount': '2'}]
        value = await TransactionPreparation(q).prepare({'quote': quote, 'sender': USER, 'recipient': USER,
            'acceptedBounds': {'expectedCoreOutputs': accepted}})
        values = decode(provider, 1)[-1]
        actual = CODEC.decode([f'({CORE_OUTPUT}[])'], values['plan']['body'])[0][0]
        self.assertEqual([row[3] for row in actual], [490, 2])
        self.assertEqual(values['plan']['minimumOutput'], 0)
        self.assertEqual(value['economicQuote']['fees']['coreProtocolFeeCygld'], '7')
        self.assertEqual(value['economicQuote']['recoveryShares'][0]['id'], '7')
        self.assertEqual([row['amount'] for row in value['economicQuote']['plan']['body']['expectedOutputs']], ['600', '4'])
        self.assertEqual([row['amount'] for row in quote['plan']['body']['expectedOutputs']], ['500', '3'])
        self.assertEqual([row['amount'] for row in value['economicQuote']['estimatedRecipientOutputs']], ['600', '4'])
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))

    async def test_explicit_component_snapshot_tag_adds_no_head_or_verification_reads(self):
        request, plan = market()
        plan['body']['branches'][0]['data']['feeCygld'] = '100'
        simulation, _, rpc, provider = fixture(encoded(measured(99900, fees=(0, 0, 100),
            stages=[stage(0, WETH, CORE, 10000, 100000)])))
        value = await simulation(request, plan, block=BLOCK, pricing=False)
        self.assertEqual(decode(provider)[2], {'blockHash': BLOCK['hash'], 'requireCanonical': True})
        self.assertEqual(value['context']['blockHash'], BLOCK['hash'])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))

    async def test_errors_and_malformed_return_are_ordinary_single_call_failures(self):
        request, plan = market()
        selector = Web3.to_hex(Web3.keccak(text='InsufficientReserveBalance()'))[:10]
        simulation, _, rpc, provider = fixture({'error': {'code': 3, 'data': selector, 'message': 'opaque'}})
        with self.assertRaises(Exception) as caught:
            await simulation(request, plan)
        self.assertEqual(caught.exception.code, 'insufficient-reserve-balance')
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))
        simulation, _, _, provider = fixture({'result': '0x01'})
        with self.assertRaises(Exception):
            await simulation(request, plan)
        self.assertEqual(len(provider.calls), 1)

    async def test_cancellation_drains_the_one_owned_execution_request(self):
        request, plan = market()
        simulation, _, rpc, provider = fixture(encoded(measured(100000)))
        provider.release = asyncio.Event()
        async with asyncio.timeout(1):
            task = asyncio.create_task(simulation(request, plan))
            await provider.entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(provider.drained.is_set())
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))


if __name__ == '__main__':
    unittest.main()
