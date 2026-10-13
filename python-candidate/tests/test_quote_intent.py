"""Actual ABI, route producer and whole-intent invariants; no live transactions."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider
from eth_utils.abi import collapse_if_tuple

from cybergold_candidate.app import create_app
from cybergold_candidate.basket_preview import ABI as BASKET_ABI
from cybergold_candidate.token_preview import TokenPreviewRpc
from cybergold_candidate.quote_intent import QuoteIntent, REQUEST, issue_input_bounds, ceil
from cybergold_candidate.issuance_capacity import ABI as CAPACITY_ABI, READS as CAPACITY_READS, capacity_amounts
from cybergold_candidate.quote_errors import QuoteFailure, RpcTimeout, public_quote_error
from cybergold_candidate.route_search import RouteSearch, RouteSearchRpc, WETH, candidates
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.rpc_diagnostics import rpc_call, rpc_diagnostic_scope, error_diagnostics, quote_sdk_request
from test_route_search import ASSET_A, ASSET_B, ASSET_C, HASH, Wire, wire_result

CORE = '0x' + '4' * 40
ADAPTER = '0x' + '5' * 40
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS=ASSET_C,
    NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=ASSET_C, NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
    RPC_URL='http://fixture.invalid', RPC_AUTHORIZATION=None)


class Provider(AsyncBaseProvider):
    def __init__(self):
        super().__init__()
        self.calls, self.contract_calls = [], []
        self.reorg, self.wrong_chain, self.fail_final = False, False, False
        self.block_hash = HASH
        self.chain_id = 1
        self.issue_fees, self.issue_cap = (0, 0), None
        self.hold_chain, self.hold_header = None, None
        self.contract = Web3().eth.contract(abi=BASKET_ABI + TokenPreviewRpc.abi)
        self.final_started, self.finish_final = asyncio.Event(), None

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            if self.hold_chain:
                await self.hold_chain.wait()
            result = '0x2' if self.wrong_chain else hex(self.chain_id)
        elif method.startswith('eth_getBlock'):
            if self.hold_header:
                await self.hold_header.wait()
            result = {'number': '0x65', 'hash': '0x'+'b'*64 if self.reorg and params[0] != 'latest' else self.block_hash}
        elif params[0]['to'].lower() == CORE.lower():
            result = '0x' + Web3().codec.encode(['address[]'], [[ASSET_C]]).hex()
        else:
            function, args = self.contract.decode_function_input(params[0]['data'])
            name = function.fn_name
            self.contract_calls.append((name, args, params[1]))
            fees, assets = (0, 0), [ASSET_A, ASSET_B]
            if name == 'previewIssueFromBasketExactOut':
                fees = self.issue_fees
                raw = args['netCygldOut'] + sum(fees)
                value = (assets, [raw//2, raw-raw//2], fees)
            elif name in ('previewIssueFromTokenExactIn', 'previewIssueFromNativeExactIn'):
                legs = list(args.values())[1]
                fees = self.issue_fees
                net = sum(row['minimumAmountOut'] for row in legs) - sum(fees)
                value = (assets, min(net, self.issue_cap) if self.issue_cap is not None else net, fees)
            elif name in ('previewIssueFromTokenExactOut', 'previewIssueFromNativeExactOut'):
                self.final_started.set()
                if self.finish_final:
                    await self.finish_final.wait()
                if self.fail_final:
                    return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'message': 'private supplier failure'}}
                legs = list(args.values())[1]
                params = args['params']
                maximum = params.get('maximumInputAmount', params.get('maximumNativeIn'))
                if sum(row['amountIn'] for row in legs) > maximum:
                    return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'message': 'execution reverted: InsufficientInput'}}
                fees = self.issue_fees
                value = (assets, fees)
            elif name == 'previewRedeemToBasketExactIn':
                gross = args['grossCygldIn']
                value = ([(0, ASSET_A, 0, gross//2), (0, ASSET_B, 0, gross-gross//2),
                          (1, CORE, int(ASSET_C, 16), gross)], fees)
            elif name == 'previewRedeemToBasketExactOut':
                outputs = args['minimumOutputs']
                value = (sum(row['minimumAmount'] for row in outputs),
                         [(row['kind'], row['token'], row['id'], row['minimumAmount']) for row in outputs], fees)
            else:
                gross = list(args.values())[0]
                gross = gross if isinstance(gross, int) else gross['grossCygldIn']
                legs = list(args.values())[1]
                value = (sum(row['minimumAmountOut'] for row in legs),
                         [(0, ASSET_A, 0, gross//2), (0, ASSET_B, 0, gross-gross//2),
                          (1, CORE, int(ASSET_C, 16), gross)], fees)
            output = function.abi['outputs'][0]
            # Result tuple order comes from the shipped Helpers ABI, not a
            # mirror of the orchestration implementation.
            values = dict(zip(['orderedCoreAssets','amountsInExact','fees'] if name == 'previewIssueFromBasketExactOut'
                else ['orderedCoreAssets','netCygldOut','fees'] if name.endswith('ExactIn') and name.startswith('previewIssue')
                else ['orderedCoreAssets','fees'] if name.startswith('previewIssue')
                else ['grossCygldIn','projectedCoreOutputs','fees'] if name == 'previewRedeemToBasketExactOut'
                else ['projectedCoreOutputs','fees'] if name == 'previewRedeemToBasketExactIn'
                else ['minimumAmountOut','projectedCoreOutputs','fees'], value, strict=True))
            ordered = tuple(values[part['name']] for part in output['components'])
            result = '0x' + Web3().codec.encode([collapse_if_tuple(output)], [ordered]).hex()
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


class QuoteWire(Wire):
    def __init__(self):
        super().__init__()
        self.provider = None
        self.capacity_batches = []

    async def send(self, request):
        payload = json.loads(request.content)
        selector = payload[0]['params'][0]['data'][:10]
        contract = Web3().eth.contract(abi=CAPACITY_ABI)
        reads = {contract.encode_abi(name)[:10]: (name, output) for name, output in CAPACITY_READS}
        if selector in reads:
            self.capacity_batches.append(payload)
            provider = self.provider
            cap = provider.issue_cap if provider and provider.issue_cap is not None else 10**30
            direct = isinstance(provider, DirectProvider)
            state = {'basketTargetsPpm': [1_000_000] if direct else [500_000, 500_000],
                     'basketCygldPerUnitFp18': [10**18] if direct else [10**18, 10**18],
                     'issuanceFeePpm': 0, 'helperFeePpm': 0, 'totalSupply': 0,
                     'maxTotalSupply': cap, 'effectiveCygldSupplyCap': cap}
            rows = []
            for row in payload:
                name, output = reads[row['params'][0]['data'][:10]]
                rows.append({'jsonrpc': '2.0', 'id': row['id'],
                             'result': '0x' + Web3().codec.encode([output], [state[name]]).hex()})
            return httpx.Response(200, json=rows)
        if selector in ('0x1698ee82', '0x1a686502'):
            return await super().send(request)
        self.batches.append(payload)
        mode_in = selector == '0x' + Web3.keccak(text='quoteExactInput(bytes,uint256)')[:4].hex()
        rows = []
        for row in payload:
            path, amount = Web3().codec.decode(['bytes', 'uint256'], bytes.fromhex(row['params'][0]['data'][2:])[4:])
            quoted = await self.on_quote(path, amount) if self.on_quote else amount*2 if mode_in else (amount+1)//2
            rows.append({'jsonrpc':'2.0','id':row['id'],'result':wire_result(quoted)})
        return httpx.Response(200, json=list(reversed(rows)))


class DirectProvider(Provider):
    async def make_request(self, method, params):
        if method != 'eth_call' or params[0]['to'].lower() == CORE.lower():
            return await super().make_request(method, params)
        self.calls.append((method, params))
        function, args = self.contract.decode_function_input(params[0]['data'])
        self.contract_calls.append((function.fn_name, args, params[1]))
        fees = (0, 0)
        if function.fn_name == 'previewIssueFromBasketExactOut':
            value = {'orderedCoreAssets': [WETH], 'amountsInExact': [args['netCygldOut']], 'fees': fees}
        elif function.fn_name == 'previewIssueFromTokenExactIn':
            self.assert_no_legs(args)
            value = {'orderedCoreAssets': [WETH], 'netCygldOut': args['params']['inputAmount'], 'fees': fees}
        elif function.fn_name == 'previewIssueFromTokenExactOut':
            self.assert_no_legs(args)
            value = {'orderedCoreAssets': [WETH], 'fees': fees}
        else:
            gross = args['grossCygldIn'] if function.fn_name == 'previewRedeemToBasketExactIn' else args['params']['grossCygldIn']
            outputs = [(0, WETH, 0, gross), (1, CORE, int(ASSET_C, 16), gross)]
            value = {'projectedCoreOutputs': outputs, 'fees': fees, 'minimumAmountOut': gross}
        output = function.abi['outputs'][0]
        ordered = tuple(value[part['name']] for part in output['components'])
        return {'jsonrpc': '2.0', 'id': 1, 'result': '0x' + Web3().codec.encode([collapse_if_tuple(output)], [ordered]).hex()}

    @staticmethod
    def assert_no_legs(args):
        if list(args.values())[1]:
            raise AssertionError('Direct preview received swap legs')


def service(chain_id=1):
    provider, wire = Provider(), QuoteWire()
    wire.provider = provider
    provider.chain_id = chain_id
    settings = SimpleNamespace(**{**vars(SETTINGS), 'NEXT_PUBLIC_CHAIN_ID': str(chain_id)})
    route = RouteSearch(settings, RouteSearchRpc(settings, AsyncWeb3(provider),
                        httpx.AsyncClient(transport=httpx.MockTransport(wire.send))))
    return QuoteIntent(settings, route), provider, route, wire


def request(mode, native=False):
    targets = [{'inputAsset': WETH if mode == 'issue-exact-in' else asset,
                'outputAsset': asset if mode == 'issue-exact-in' else WETH,
                'amount': '50' if mode == 'issue-exact-in' else '100'} for asset in (ASSET_A, ASSET_B)]
    return {'mode':mode,'token': '0x'+'0'*40 if native else WETH,'quoteToken':WETH,'native':native,
            'amount':'200' if mode == 'redeem-exact-out' else '100','adapter':ADAPTER,
            'deadline':'1792000000','orderedAssets':[ASSET_A,ASSET_B],
            'targets':targets if mode in ('issue-exact-in','redeem-exact-out') else []}


def retained_plan(result):
    return {key: deepcopy(result[key]) for key in ('executionAmount', 'maximumInputAmount', 'quotes')} | {
        'minimumAmountOut': result['preview'].get('minimumAmountOut', '0'),
        'expectedCoreOutputs': deepcopy(result.get('expectedCoreOutputs', [])),
        'slippageBps': result.get('slippageBps', 100),
        **({'expectedInputAmount': result['expectedInputAmount']} if 'expectedInputAmount' in result else {}),
    }


class IssueInputBoundsTests(unittest.TestCase):
    def test_custom_cushions_and_zero_tolerance_respect_the_same_budget(self):
        quotes = [{'amountIn': '1000'}, {'amountIn': '2000'}]
        self.assertEqual(issue_input_bounds(quotes, 5000, 0, 0), quotes)
        self.assertEqual([row['amountIn'] for row in issue_input_bounds(quotes, 5000, 0, 300)], ['1030', '2060'])
        self.assertEqual(sum(int(row['amountIn']) for row in issue_input_bounds(quotes, 3020, 0, 300)), 3020)

    def test_api_tolerance_defaults_and_integer_percentage_domain(self):
        self.assertEqual(REQUEST.validate_python(request('issue-exact-in')).slippageBps, 100)
        for value in (0, 50, 300, 10_000):
            self.assertEqual(REQUEST.validate_python({**request('issue-exact-in'), 'slippageBps': value}).slippageBps, value)
        for value in (-1, 10_001, 0.5, '100', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                REQUEST.validate_python({**request('issue-exact-in'), 'slippageBps': value})

    def test_unclipped_capacity_matches_integer_core_math_and_includes_both_fees(self):
        value = {**request('issue-exact-in'), 'amount': '100000',
                 'targets': [{'inputAsset': WETH, 'outputAsset': ASSET_A, 'amount': '40000'}],
                 'orderedAssets': [ASSET_A, WETH]}
        state = ([400_000, 600_000], [10**18, 10**18], 10_000, 200_000, 250_000, 240_000, 5_000)
        result = capacity_amounts(value, [40_000], state)
        self.assertEqual(result, {'requestedGrossCygldOut': '99998', 'requestedNetCygldOut': '98505',
                                  'remainingGrossCapacity': '40000', 'remainingNetCapacity': '39402'})

    def test_one_unit_budget_fee_plateau_does_not_reject_a_canonical_mint_that_fits(self):
        value = {**request('issue-exact-in'), 'amount': '100', 'targets': [], 'orderedAssets': [WETH]}
        state = ([1_000_000], [10**18], 10_000, 0, 99, 99, 10_000)
        result = capacity_amounts(value, [], state)
        self.assertGreater(int(value['amount']), int(result['remainingGrossCapacity']))
        self.assertEqual(result['requestedNetCygldOut'], '99')
        self.assertEqual(result['requestedGrossCygldOut'], '99')
        self.assertLessEqual(int(result['requestedGrossCygldOut']), int(result['remainingGrossCapacity']))
        self.assertEqual(result['requestedNetCygldOut'], result['remainingNetCapacity'])

    def test_route_cushions_fit_input_ceiling_including_direct_reserves_and_tiny_integers(self):
        cases = [([50, 50], 100, 0), ([49, 49], 100, 0), ([30, 40], 101, 30),
                 ([1000, 2000, 3000], 6031, 0), ([1, 1, 1], 4, 0),
                 ([], 100, 100), ([2**180, 2**181], 3 * 2**180 + 13, 0)]
        for amounts, maximum, direct in cases:
            with self.subTest(amounts=amounts, maximum=maximum, direct=direct):
                quotes = [{'amountIn': str(amount), 'minimumAmountOut': '123', 'data': '0xab'} for amount in amounts]
                bounded = issue_input_bounds(quotes, maximum, direct)
                totals = sum(int(row['amountIn']) for row in bounded)
                self.assertLessEqual(totals + direct, maximum)
                self.assertEqual(totals, sum(amounts) + min(maximum-direct-sum(amounts), sum(ceil(a)-a for a in amounts)))
                for old, new in zip(quotes, bounded, strict=True):
                    self.assertLessEqual(int(old['amountIn']), int(new['amountIn']))
                    self.assertLessEqual(int(new['amountIn']), ceil(int(old['amountIn'])))
                    self.assertEqual(new['minimumAmountOut'], old['minimumAmountOut'])
                    self.assertEqual(new['data'], old['data'])


class IntentTests(unittest.IsolatedAsyncioTestCase):
    def fail_quote_calls(self, route, wire, error_for_call):
        self.addAsyncCleanup(route.rpc.client.aclose)
        calls = []
        selectors = {'0x' + Web3.keccak(text=f'{name}(bytes,uint256)')[:4].hex(): mode
                     for name, mode in [('quoteExactInput', 'exact-in'), ('quoteExactOutput', 'exact-out')]}

        async def send(request):
            batch = json.loads(request.content)
            mode = selectors.get(batch[0]['params'][0]['data'][:10])
            if mode is None:
                return await wire.send(request)
            errors = [error_for_call(mode, row) for row in batch]
            if not any(errors):
                return await wire.send(request)
            calls.extend(batch)
            return httpx.Response(200, json=[{'jsonrpc': '2.0', 'id': row['id'], 'error': error}
                                            for row, error in zip(batch, errors, strict=True)])

        route.rpc.client = httpx.AsyncClient(transport=httpx.MockTransport(send))
        return calls

    async def stream_error(self, intent, value):
        app = create_app(quote_intent=intent)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('cybergold.candidate', level='ERROR') as logs:
                response = await client.post('/api/quotes/intent/stream', json=value)
        payload = json.loads(response.text.splitlines()[-1])
        record = json.loads(logs.records[-1].getMessage())
        self.assertEqual(payload['type'], 'error')
        self.assertNotIn('"type":"complete"', response.text)
        self.assertEqual(record['correlationId'], payload['correlationId'])
        self.assertEqual(record['errorClassification'], payload['code'])
        self.assertEqual(record.get('diagnostics'), payload.get('diagnostics'))
        self.assertEqual(response.headers['cache-control'], 'no-store')
        for secret in ('fixture-secret-key', 'private-call-data', 'fixture.invalid'):
            self.assertNotIn(secret, response.text + repr(record))
        return payload

    async def test_all_failed_routes_keep_selected_rpc_diagnostics_in_terminal_stream_and_log(self):
        for mode in ('issue-exact-in', 'issue-exact-out', 'redeem-exact-in', 'redeem-exact-out'):
            for mixed_errors in (True, False):
                with self.subTest(mode=mode, mixed_errors=mixed_errors):
                    intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
                    intent.qualification = False

                    def error_for_call(_mode, row):
                        path, _ = route.rpc.w3.codec.decode(['bytes', 'uint256'],
                            bytes.fromhex(row['params'][0]['data'][2:])[4:])
                        fee = int.from_bytes(path[20:23])
                        if mixed_errors and fee != 100:
                            return {'code': -32005, 'message':
                                    'Request quota reached; api_key=fixture-secret-key; params: [private-call-data]'}
                        return {'code': 3, 'message': 'execution reverted: route rejected; api_key=fixture-secret-key'}

                    calls = self.fail_quote_calls(route, wire, error_for_call)
                    payload = await self.stream_error(intent, request(mode))
                    expected_code = 'rpc-rate-limit' if mixed_errors else \
                        'quote-unavailable' if mode == 'redeem-exact-out' else 'quote-no-route'
                    self.assertEqual(payload['code'], expected_code)
                    diagnostics = payload['diagnostics']
                    self.assertEqual(diagnostics['rpcMethod'], 'eth_call')
                    self.assertEqual(diagnostics['stage'], 'route-search')
                    self.assertEqual(diagnostics['failureType'], 'rpc-error')
                    self.assertEqual(diagnostics['upstreamErrorCode'], -32005 if mixed_errors else 3)
                    self.assertIn('Request quota reached' if mixed_errors else 'route rejected',
                                  diagnostics['providerMessage'])
                    self.assertGreaterEqual(diagnostics['elapsedMs'], 0)
                    # Each of the four candidates for both assets is submitted once.
                    self.assertEqual(len(calls), 8)
                    self.assertEqual(len({row['params'][0]['data'] for row in calls}), 8)

    async def test_zero_quote_amounts_do_not_invent_upstream_failure_diagnostics(self):
        for mode in ('issue-exact-in', 'issue-exact-out', 'redeem-exact-in', 'redeem-exact-out'):
            with self.subTest(mode=mode):
                intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
                intent.qualification = False

                async def zero_quote(path, amount):
                    return 0

                wire.on_quote = zero_quote
                payload = await self.stream_error(intent, request(mode))
                self.assertEqual(payload['code'], 'quote-unavailable' if mode == 'redeem-exact-out' else 'quote-no-route')
                self.assertNotIn('diagnostics', payload)

    async def test_selected_plan_and_capacity_batch_failures_keep_rpc_diagnostics_without_research(self):
        for mode, failing_mode, expected_calls in [('redeem-exact-in', 'exact-in', 2),
                                                    ('issue-exact-in', 'exact-in', 2)]:
            with self.subTest(mode=mode):
                intent, provider, route, wire = service(31338); self.addAsyncCleanup(route.close)
                intent.qualification = False
                intent.retain_plans = True
                first = await intent.get(request(mode), lambda frame: asyncio.sleep(0))
                provider.block_hash = '0x' + 'c' * 64
                wire.batches.clear()
                calls = self.fail_quote_calls(route, wire, lambda candidate_mode, _row:
                    {'code': -32005, 'message': 'Request quota reached; api_key=fixture-secret-key'}
                    if candidate_mode == failing_mode else None)
                payload = await self.stream_error(intent, {**request(mode), 'retainedPlan': retained_plan(first)})
                self.assertEqual(payload['code'], 'rpc-rate-limit')
                self.assertEqual(payload['diagnostics']['rpcMethod'], 'eth_call')
                self.assertEqual(payload['diagnostics']['upstreamErrorCode'], -32005)
                self.assertIn('Request quota reached', payload['diagnostics']['providerMessage'])
                self.assertEqual(len(calls), expected_calls)
                # Issuance revalidates its two selected exact-out calls before
                # the failed two-call capacity observation; no routes are enumerated.
                successful_quote_calls = sum(len(batch) for batch in wire.batches)
                self.assertEqual(successful_quote_calls, 2 if mode == 'issue-exact-in' else 0)

    async def test_custom_tolerance_changes_execution_limits_without_changing_expected_quotes(self):
        for mode in ('issue-exact-in', 'issue-exact-out', 'redeem-exact-in', 'redeem-exact-out'):
            for native in (False, True):
                expected = []
                limits = []
                for bps in (0, 50, 300):
                    with self.subTest(mode=mode, native=native, bps=bps):
                        intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
                        value = request(mode, native)
                        value.update(amount='20000' if mode == 'redeem-exact-out' else '10000', slippageBps=bps)
                        if mode == 'issue-exact-in':
                            for target in value['targets']:
                                target['amount'] = '5000'
                        result = await intent.get(value, lambda frame: asyncio.sleep(0))
                        self.assertEqual(result['slippageBps'], bps)
                        expected.append(result['expectedInputAmount'] if mode.endswith('exact-out') else result['displayAmount'])
                        limits.append(int(result['maximumInputAmount']) if mode == 'issue-exact-out'
                                      else int(result['preview']['minimumAmountOut']) if mode == 'redeem-exact-in'
                                      else int(result['executionAmount']))
                        if mode == 'redeem-exact-in':
                            self.assertEqual([row['minimumAmount'] for row in result['expectedCoreOutputs'][:2]],
                                             [str(5000 * (10000-bps)//10000)] * 2)
                self.assertEqual(len(set(expected)), 1)
                if mode != 'issue-exact-in':
                    self.assertNotEqual(limits[0], limits[-1])

    async def test_changed_tolerance_recalculates_a_browser_plan_and_matching_tolerance_reuses_it(self):
        intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
        intent.retain_plans = True
        value = {**request('redeem-exact-in'), 'amount': '10000', 'slippageBps': 300}
        first = await intent.get(value, lambda frame: asyncio.sleep(0))
        same = await intent.get({**value, 'retainedPlan': retained_plan(first)}, lambda frame: asyncio.sleep(0))
        self.assertEqual(same['metrics']['candidateCalls'], 2)
        self.assertEqual(same['preview']['minimumAmountOut'], '19400')
        events = []
        tighter = await intent.get({**value, 'slippageBps': 50, 'retainedPlan': retained_plan(first)},
                                   lambda frame: asyncio.sleep(0, result=events.append(frame)))
        self.assertEqual(events[0]['type'], 'invalidated')
        self.assertEqual(tighter['preview']['minimumAmountOut'], '19900')
        self.assertEqual(tighter['displayAmount'], first['displayAmount'])

    async def test_cap_metadata_preserves_requested_output_on_capped_and_retained_quotes(self):
        intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
        intent.retain_plans = True
        provider.issue_cap = 150
        value = request('issue-exact-in')
        for result in (await intent.get(value, lambda frame: asyncio.sleep(0)),
                       await intent.get(value, lambda frame: asyncio.sleep(0))):
            self.assertEqual(result['executionAmount'], '150')
            self.assertEqual(result['requestedGrossCygldOut'], '200')
            self.assertEqual(result['requestedNetCygldOut'], '200')
            self.assertEqual(result['remainingGrossCapacity'], '150')
            self.assertEqual(result['remainingNetCapacity'], '150')
            self.assertTrue(all(params[1] == {'blockHash': HASH, 'requireCanonical': True}
                                for batch in wire.batches + wire.capacity_batches for row in batch for params in [row['params']]))

    async def test_redemption_displays_expected_output_and_keeps_the_protected_minimum(self):
        for native in (False, True):
            intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
            intent.retain_plans = True
            value = request('redeem-exact-in', native)
            result = await intent.get(value, lambda frame: asyncio.sleep(0))
            self.assertEqual(result['displayAmount'], '200')
            self.assertEqual(result['preview']['minimumAmountOut'], '198')
            self.assertEqual(result['executionAmount'], '100')
            provider.block_hash = '0x'+'c'*64
            fresh = await intent.get(value, lambda frame: asyncio.sleep(0))
            self.assertEqual(fresh['metrics']['candidateCalls'], 2)
            self.assertEqual(fresh['displayAmount'], '200')
            self.assertEqual(fresh['preview']['minimumAmountOut'], '198')
            self.assertEqual(fresh['expectedCoreOutputs'], result['expectedCoreOutputs'])

    async def test_purchase_targets_full_output_after_fees_including_a_supply_cap(self):
        for native in (False, True):
            for cap in (None, 150):
                with self.subTest(native=native, cap=cap):
                    intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
                    provider.issue_fees, provider.issue_cap = (1, 2), cap
                    result = await intent.get(request('issue-exact-in', native), lambda frame: asyncio.sleep(0))
                    expected = cap or 197
                    self.assertEqual(int(result['displayAmount']), expected)
                    self.assertEqual(int(result['executionAmount']), expected)
                    self.assertEqual(result['preview']['fees'], {'protocolFeeCygld': '1', 'helperFeeCygld': '2'})
                    self.assertEqual(result['maximumInputAmount'], '100')
                    name, args, _ = next(row for row in reversed(provider.contract_calls)
                        if row[0] in ('previewIssueFromTokenExactOut', 'previewIssueFromNativeExactOut'))
                    self.assertEqual(args['params']['netCygldOut'], expected)
                    self.assertLessEqual(sum(int(row['amountIn']) for row in result['quotes']), 100)

    async def test_browser_limits_override_a_weaker_shared_plan_and_never_replace_that_bank(self):
        intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
        intent.retain_plans = True
        value = request('redeem-exact-in')
        first = await intent.get(value, lambda frame: asyncio.sleep(0))
        key = json.dumps({k:v for k,v in value.items() if k not in ('deadline','retainedPlan')},sort_keys=True)
        weak = deepcopy(first)
        weak['preview']['minimumAmountOut'] = '100'
        for leg in weak['quotes']:
            path,_,deadline,mode = route.rpc.w3.codec.decode(['bytes','uint256','uint256','bool'],bytes.fromhex(leg['data'][2:]))
            leg.update(minimumAmountOut='50', data='0x'+route.rpc.w3.codec.encode(['bytes','uint256','uint256','bool'],[path,50,deadline,mode]).hex())
        intent.retained[key] = (intent.retained[key][0],weak)
        provider.block_hash = '0x'+'c'*64
        async def changed(path, amount):return amount*8//5
        wire.on_quote = changed
        plan = {k:deepcopy(first[k]) for k in ('executionAmount','maximumInputAmount','quotes','expectedCoreOutputs')}
        plan['minimumAmountOut'] = first['preview']['minimumAmountOut']
        events = []
        result = await intent.get({**value,'retainedPlan':plan},lambda frame:asyncio.sleep(0,result=events.append(frame)))
        self.assertEqual(events[0]['type'],'invalidated')
        self.assertLess(int(result['preview']['minimumAmountOut']),int(plan['minimumAmountOut']))
        self.assertEqual(intent.retained[key][1],weak)

    async def test_retained_plan_from_another_input_is_recalculated_for_the_current_intent(self):
        intent, provider, route, wire = service();self.addAsyncCleanup(route.close)
        intent.retain_plans = True
        first = await intent.get(request('redeem-exact-in'),lambda frame:asyncio.sleep(0))
        plan = {k:deepcopy(first[k]) for k in ('executionAmount','maximumInputAmount','quotes','expectedCoreOutputs')}
        plan.update(executionAmount='99',minimumAmountOut=first['preview']['minimumAmountOut'])
        result = await intent.get({**request('redeem-exact-in'),'retainedPlan':plan},lambda frame:asyncio.sleep(0))
        self.assertEqual(result['executionAmount'],'100')
        self.assertEqual(result['metrics']['candidateCalls'],8)

    async def test_new_head_revalidates_selected_routes_and_current_expected_amounts(self):
        for mode in ('issue-exact-in','issue-exact-out','redeem-exact-in','redeem-exact-out'):
            for native in (False, True):
                with self.subTest(mode=mode, native=native):
                    intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
                    intent.retain_plans = True
                    first = await intent.get(request(mode,native), lambda frame: asyncio.sleep(0))
                    original_bounds = first.get('expectedCoreOutputs')
                    for index in (1, 1, 2): # A second browser/deadline also reuses the selected plan.
                        provider.block_hash = '0x'+str(index)*64
                        next_request = {**request(mode,native), 'deadline': str(1792000000+index)}
                        current = await intent.get(next_request, lambda frame: asyncio.sleep(0))
                        self.assertEqual(current['context']['blockHash'], provider.block_hash)
                        self.assertEqual(current['metrics']['candidateCalls'], 4 if mode in ('issue-exact-in', 'redeem-exact-out') else 2)
                        self.assertEqual(current['metrics']['iterations'], 0)
                        self.assertEqual(current['executionAmount'], first['executionAmount'])
                        self.assertLessEqual(int(current['maximumInputAmount']), int(first['maximumInputAmount']))
                        for leg in current['quotes']:
                            _,_,deadline,_ = route.rpc.w3.codec.decode(['bytes','uint256','uint256','bool'],bytes.fromhex(leg['data'][2:]))
                            self.assertEqual(deadline, int(next_request['deadline']))
                        if original_bounds:
                            self.assertEqual(current['expectedCoreOutputs'], original_bounds)
                            self.assertEqual(current['preview']['minimumAmountOut'], first['preview']['minimumAmountOut'])

    async def test_changed_price_invalidates_retained_execution_then_falls_back_to_complete_search(self):
        intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
        intent.retain_plans = True
        first = await intent.get(request('redeem-exact-in'), lambda frame: asyncio.sleep(0))
        provider.block_hash = '0x'+'c'*64
        async def changed(path, amount): return amount
        wire.on_quote = changed
        events = []
        fresh = await intent.get(request('redeem-exact-in'), lambda frame: asyncio.sleep(0,result=events.append(frame)))
        self.assertEqual(events[0]['type'], 'invalidated')
        self.assertLess(int(fresh['preview']['minimumAmountOut']), int(first['preview']['minimumAmountOut']))
        self.assertEqual(fresh['metrics']['candidateCalls'], 10) # 2 checked + all 8 candidates.

    async def test_sandbox_new_heads_check_browser_selected_routes_in_all_eight_modes(self):
        for mode in ('issue-exact-in', 'issue-exact-out', 'redeem-exact-in', 'redeem-exact-out'):
            for native in (False, True):
                with self.subTest(mode=mode, native=native):
                    intent, provider, route, wire = service(31338); self.addAsyncCleanup(route.close)
                    intent.retain_plans = True
                    first = await intent.get(request(mode, native), lambda frame: asyncio.sleep(0))
                    for index in (1, 2):
                        provider.block_hash = '0x'+str(index)*64
                        next_request = {**request(mode, native), 'deadline': str(1792000000+index),
                                        'retainedPlan': retained_plan(first)}
                        wire.batches.clear()
                        current = await intent.get(next_request, lambda frame: asyncio.sleep(0))
                        self.assertEqual(current['context']['blockHash'], provider.block_hash)
                        calls = 4 if mode in ('issue-exact-in', 'redeem-exact-out') else 2
                        self.assertEqual(current['metrics']['candidateCalls'], calls)
                        self.assertEqual(sum(len(batch) for batch in wire.batches), calls)
                        self.assertEqual(current['metrics']['iterations'], 0)
                        self.assertEqual(current['executionAmount'], first['executionAmount'])
                        self.assertLessEqual(int(current['maximumInputAmount']), int(first['maximumInputAmount']))
                        self.assertEqual(intent.retained, {})
                        for leg in current['quotes']:
                            _, _, deadline, _ = route.rpc.w3.codec.decode(
                                ['bytes', 'uint256', 'uint256', 'bool'], bytes.fromhex(leg['data'][2:]))
                            self.assertEqual(deadline, int(next_request['deadline']))
                        if mode.startswith('redeem'):
                            self.assertEqual(current['expectedCoreOutputs'], first['expectedCoreOutputs'])
                            self.assertEqual(current['preview']['minimumAmountOut'], first['preview']['minimumAmountOut'])

    async def test_sandbox_changed_bounds_research_and_a_reverted_route_can_use_an_alternative(self):
        for fault in ('price', 'route-revert'):
            with self.subTest(fault=fault):
                intent, provider, route, wire = service(31338); self.addAsyncCleanup(route.close)
                intent.retain_plans = True
                first = await intent.get(request('redeem-exact-in'), lambda frame: asyncio.sleep(0))
                provider.block_hash = '0x'+'c'*64
                if fault == 'price':
                    async def changed(path, amount): return amount
                    wire.on_quote = changed
                else:
                    original, rejected = route.rpc.quote_batch_counted, False
                    async def once(mode, calls, block, counts):
                        nonlocal rejected
                        rows = await original(mode, calls, block, counts)
                        if not rejected:
                            rejected = True
                            rows[0] = {'status': 'failure', 'code': 'quote-contract-reverted'}
                        return rows
                    route.rpc.quote_batch_counted = once
                events = []
                fresh = await intent.get({**request('redeem-exact-in'), 'retainedPlan': retained_plan(first)},
                                         lambda frame: asyncio.sleep(0, result=events.append(frame)))
                self.assertEqual(events[0]['type'], 'invalidated')
                self.assertEqual(fresh['metrics']['candidateCalls'], 10)
                self.assertEqual(intent.retained, {})

    async def test_sandbox_completed_plans_are_never_retained_under_unchanged_headers(self):
        intent, provider, route, wire = service(31338); self.addAsyncCleanup(route.close)
        intent.retain_plans = True
        for _ in range(2):
            result = await intent.get(request('redeem-exact-in'), lambda frame: asyncio.sleep(0))
            self.assertEqual(result['metrics']['candidateCalls'], 8)
            self.assertEqual(intent.retained, {})

    async def test_failed_selected_read_does_not_prove_the_incumbent_invalid(self):
        for chain_id in (1, 31338):
            for code in ('rpc-unavailable', 'rpc-rate-limit', 'rpc-access-denied', 'rpc-timeout'):
                with self.subTest(chain_id=chain_id, code=code):
                    intent, provider, route, wire = service(chain_id); self.addAsyncCleanup(route.close)
                    intent.retain_plans = True
                    first = await intent.get(request('redeem-exact-in'), lambda frame: asyncio.sleep(0))
                    provider.block_hash = '0x'+'c'*64
                    original, batches = route.rpc.quote_batch_counted, []
                    async def transient(mode, calls, block, counts):
                        batches.append(len(calls))
                        rows = await original(mode, calls, block, counts)
                        rows[0] = {'status': 'failure', 'code': code}
                        return rows
                    route.rpc.quote_batch_counted = transient
                    events = []
                    next_request = {**request('redeem-exact-in'), 'retainedPlan': retained_plan(first)}
                    with self.assertRaises(QuoteFailure) as raised:
                        await intent.get(next_request, lambda frame: asyncio.sleep(0, result=events.append(frame)))
                    self.assertEqual(raised.exception.code, code)
                    self.assertEqual(batches, [2]) # No all-route fallback after a failed selected read.
                    self.assertNotIn('invalidated', [event['type'] for event in events])
                    route.rpc.quote_batch_counted = original
                    fresh = await intent.get(next_request, lambda frame: asyncio.sleep(0))
                    self.assertEqual(fresh['metrics']['candidateCalls'], 2)
                    self.assertEqual(fresh['preview']['minimumAmountOut'], first['preview']['minimumAmountOut'])

    async def test_selected_core_read_rpc_failure_does_not_start_route_search(self):
        for error in (RpcTimeout(), httpx.ConnectError('Private upstream detail')):
            intent, provider, route, wire = service(31338); self.addAsyncCleanup(route.close)
            intent.retain_plans = True
            first = await intent.get(request('redeem-exact-in'), lambda frame: asyncio.sleep(0))
            provider.block_hash = '0x'+'c'*64
            wire.batches.clear()
            original = provider.make_request
            async def fail_core(method, params):
                if method == 'eth_call':
                    raise error
                return await original(method, params)
            provider.make_request = fail_core
            events = []
            with self.assertRaises(type(error)) as raised:
                await intent.get({**request('redeem-exact-in'), 'retainedPlan': retained_plan(first)},
                                 lambda frame: asyncio.sleep(0, result=events.append(frame)))
            self.assertEqual(public_quote_error(raised.exception)['code'], public_quote_error(error)['code'])
            self.assertEqual(wire.batches, [])
            self.assertNotIn('invalidated', [event['type'] for event in events])

    async def test_decoded_core_rejection_invalidates_retained_plan_before_normal_search(self):
        intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
        intent.retain_plans = True
        await intent.get(request('redeem-exact-in'), lambda frame: asyncio.sleep(0))
        provider.block_hash = '0x'+'c'*64
        original, rejected = provider.make_request, False
        async def reject_selected(method, params):
            nonlocal rejected
            if method == 'eth_call' and not rejected:
                rejected = True
                return {'jsonrpc':'2.0','id':1,'error':{'code':3,'data':'0x33aa101c','message':'private provider detail'}}
            return await original(method, params)
        provider.make_request = reject_selected
        events = []
        from cybergold_candidate.preview_errors import KnownPreviewError
        with self.assertRaises(KnownPreviewError):
            await intent.get(request('redeem-exact-in'), lambda frame: asyncio.sleep(0, result=events.append(frame)))
        self.assertTrue(rejected)
        self.assertEqual(events[0]['type'], 'invalidated')
        # The same pinned failed Core preview is reused by normal search;
        # it is not retried or promoted to an executable stale plan.

    async def test_direct_quotes_do_not_require_an_adapter_and_keep_mixed_redemption_outputs(self):
        for mode in ('issue-exact-in', 'issue-exact-out', 'redeem-exact-in'):
            provider, wire = DirectProvider(), QuoteWire()
            wire.provider = provider
            route = RouteSearch(SETTINGS, RouteSearchRpc(SETTINGS, AsyncWeb3(provider),
                httpx.AsyncClient(transport=httpx.MockTransport(wire.send))))
            self.addAsyncCleanup(route.close)
            value = {**request(mode), 'orderedAssets': [WETH], 'targets': [], 'adapter': ''}
            result = await QuoteIntent(SETTINGS, route).get(value, lambda event: asyncio.sleep(0))
            self.assertEqual(result['quotes'], [])
            self.assertEqual(wire.batches, [])
            if mode == 'redeem-exact-in':
                self.assertEqual([row['kind'] for row in result['preview']['projectedCoreOutputs']], [0, 1])
            elif mode == 'issue-exact-in':
                self.assertEqual(result['executionAmount'], '100')
                self.assertEqual(result['displayAmount'], '100')


    async def test_all_eight_paths_share_one_context_and_keep_abi_bounds(self):
        for mode in ('issue-exact-in','issue-exact-out','redeem-exact-in','redeem-exact-out'):
            for native in (False, True):
                with self.subTest(mode=mode,native=native):
                    intent, provider, route, wire = service()
                    self.addAsyncCleanup(route.close)
                    events=[]
                    result=await intent.get(request(mode,native),lambda event: asyncio.sleep(0,result=events.append(event)))
                    self.assertEqual(sum(method=='eth_chainId' for method,_ in provider.calls),1)
                    self.assertEqual(sum(method.startswith('eth_getBlock') and params[0] == 'latest'
                                         for method,params in provider.calls), 1)
                    self.assertGreaterEqual(sum(method.startswith('eth_getBlock') for method,_ in provider.calls), 2)
                    self.assertTrue(all(target=={'blockHash':HASH,'requireCanonical':True} for _,_,target in provider.contract_calls))
                    self.assertGreater(int(result['executionAmount']),0)
                    for quote in result['quotes']:
                        path,limit,deadline,exact_in=Web3().codec.decode(['bytes','uint256','uint256','bool'],bytes.fromhex(quote['data'][2:]))
                        self.assertEqual(limit,int(quote['minimumAmountOut']))
                        self.assertEqual(deadline,1792000000)
                        self.assertEqual(exact_in,mode.startswith('redeem'))
                        self.assertEqual(len(path),43)
                    if mode=='issue-exact-in':
                        self.assertEqual(result['displayAmount'],'200')
                        self.assertEqual(result['executionAmount'],'200')
                        self.assertEqual(sum(int(row['amountIn']) for row in result['quotes']),100)
                    if mode=='redeem-exact-out':
                        self.assertEqual(result['metrics']['iterations'],2)
                        self.assertTrue(200<=int(result['preview']['minimumAmountOut'])<=202)
                        seed=next(args for name,args,_ in provider.contract_calls if name=='previewRedeemToBasketExactOut')
                        self.assertEqual(seed['minimumOutputs'][-1]['id'],int(ASSET_C,16))

    async def test_estimate_arrives_before_blocked_final_validation(self):
        intent,provider,route,_=service();self.addAsyncCleanup(route.close)
        provider.finish_final=asyncio.Event()
        estimate_received=asyncio.Event()
        async def update(event):
            if event['type']=='estimate':estimate_received.set()
        operation=asyncio.create_task(intent.get(request('issue-exact-in'),update))
        await asyncio.wait_for(estimate_received.wait(),2)
        self.assertFalse(operation.done())
        provider.finish_final.set();result=await operation
        self.assertEqual(result['executionAmount'],'200')

    async def test_qualified_execution_precedes_slow_route_tail_and_keeps_full_coverage(self):
        for mode in ('issue-exact-out', 'redeem-exact-in'):
            intent, provider, route, wire = service(); self.addAsyncCleanup(route.close)
            release, qualified = asyncio.Event(), asyncio.Event()
            events = []
            async def quote(path, amount):
                if int.from_bytes(path[20:23]) >= 3000:
                    await release.wait()
                return amount*2 if mode == 'redeem-exact-in' else (amount+1)//2
            async def update(event):
                events.append(event)
                if event['type'] == 'qualified': qualified.set()
            wire.on_quote = quote
            operation = asyncio.create_task(intent.get(request(mode), update))
            try:
                await asyncio.wait_for(qualified.wait(), 2)
                self.assertFalse(operation.done())
                value = next(row['value'] for row in events if row['type'] == 'qualified')
                self.assertEqual(value['context']['blockHash'], HASH)
                self.assertEqual(len(value['quotes']), 2)
                self.assertIn('basketPreview', value)
                self.assertIn('preview', value)
                self.assertGreaterEqual(sum(method.startswith('eth_getBlock') for method,_ in provider.calls), 2)
                release.set(); final = await operation
                self.assertEqual(final['metrics']['candidateCalls'], 8)
                self.assertEqual(final['executionAmount'], value['executionAmount'])
            finally:
                release.set(); operation.cancel(); await asyncio.gather(operation, return_exceptions=True)

    async def test_qualified_helpers_tuple_survives_route_tail_timeout(self):
        for mode in ('issue-exact-in', 'issue-exact-out', 'redeem-exact-in', 'redeem-exact-out'):
            for native in (False, True):
                with self.subTest(mode=mode, native=native):
                    intent, provider, routes, wire = service()
                    self.addAsyncCleanup(routes.close)
                    ready, events, failed_tail = asyncio.Event(), [], []
                    async def quote(path, amount):
                        forward_input = path[:20] == bytes.fromhex(WETH[2:])
                        exact_in = mode == 'redeem-exact-in' or (mode == 'issue-exact-in' and forward_input) \
                            or (mode == 'redeem-exact-out' and not forward_input)
                        if int.from_bytes(path[20:23]) >= 3000 and not (mode == 'issue-exact-in' and forward_input):
                            if mode == 'redeem-exact-out':
                                # Seed/expected-output searches may finish before
                                # the first protected Helpers tuple can qualify.
                                try:
                                    await asyncio.wait_for(ready.wait(), .05)
                                except TimeoutError:
                                    return amount*2 if exact_in else (amount+1)//2
                            else:
                                await ready.wait()
                            failed_tail.append(True)
                            raise TimeoutError('Unfinished optimization deadline')
                        return amount*2 if exact_in else (amount+1)//2
                    async def update(event):
                        events.append(event)
                        if event['type'] == 'qualified':
                            ready.set()
                    wire.on_quote = quote
                    final = await asyncio.wait_for(intent.get(request(mode, native), update), 2)
                    self.assertTrue(failed_tail)
                    incumbent = next(event['value'] for event in events if event['type'] == 'qualified')
                    for field in ('quotes', 'preview', 'executionAmount', 'maximumInputAmount'):
                        self.assertEqual(final[field], incumbent[field])
                    self.assertEqual(final['context']['blockHash'], HASH)
                    self.assertEqual(final['mode'], mode)
                    self.assertGreaterEqual(sum(method.startswith('eth_getBlock') for method, _ in provider.calls), 3)

    async def test_estimate_without_qualified_candidate_does_not_recover_timeout(self):
        intent, _provider, routes, wire = service()
        self.addAsyncCleanup(routes.close)
        intent.qualification = False
        estimated, events = asyncio.Event(), []
        async def quote(path, amount):
            if int.from_bytes(path[20:23]) >= 3000:
                await estimated.wait()
                raise TimeoutError('No executable candidate')
            return amount*2
        async def update(event):
            events.append(event)
            if event['type'] == 'estimate':
                estimated.set()
        wire.on_quote = quote
        with self.assertRaises(TimeoutError) as raised:
            await asyncio.wait_for(intent.get(request('issue-exact-in'), update), 2)
        self.assertTrue(estimated.is_set())
        self.assertFalse(any(event['type'] == 'qualified' for event in events))
        self.assertEqual(public_quote_error(raised.exception)['code'], 'quote-timeout')

    async def test_recovered_candidate_still_requires_final_canonical_snapshot(self):
        intent, provider, routes, wire = service()
        self.addAsyncCleanup(routes.close)
        ready = asyncio.Event()
        async def quote(path, amount):
            if int.from_bytes(path[20:23]) >= 3000:
                await ready.wait()
                provider.reorg = True
                raise TimeoutError('Optimization deadline after a reorg')
            return (amount+1)//2
        async def update(event):
            if event['type'] == 'qualified':
                ready.set()
        wire.on_quote = quote
        with self.assertRaises(SnapshotChanged):
            await asyncio.wait_for(intent.get(request('issue-exact-out'), update), 2)
        self.assertTrue(ready.is_set())

    async def test_qualifier_snapshot_disproof_survives_later_tail_timeout(self):
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        first, disproved = asyncio.Event(), asyncio.Event()
        checks, events = [], []
        async def canonical(block):
            checks.append(block)
            if len(checks) >= 2:
                disproved.set()
                raise SnapshotChanged('Recovery snapshot changed; restart discovery', retry=1)
        routes.rpc.assert_canonical = canonical
        async def search(value, on_update, *, block):
            async def update(amount):
                rows = [{'best': {**candidates(target, value['mode'])[0], 'quote': str(amount)},
                    'attempted': 1, 'total': 2, 'succeeded': 1, 'failures': []} for target in value['targets']]
                await on_update({'results': rows})
            await update(25)
            await first.wait()
            await update(20)
            await disproved.wait()
            raise TimeoutError('Ordinary later candidate deadline')
        routes.get = search
        async def publish(event):
            events.append(event)
            if event['type'] == 'qualified':
                first.set()
        with self.assertRaises(SnapshotChanged):
            await asyncio.wait_for(intent.get(request('issue-exact-out'), publish), 2)
        invalidated = next(index for index, event in enumerate(events) if event['type'] == 'invalidated')
        self.assertFalse(any(event['type'] == 'qualified' for event in events[invalidated+1:]))

    async def test_caller_cancellation_does_not_complete_qualified_candidate(self):
        intent, _provider, routes, wire = service()
        self.addAsyncCleanup(routes.close)
        ready, hold = asyncio.Event(), asyncio.Event()
        async def quote(path, amount):
            if int.from_bytes(path[20:23]) >= 3000:
                await hold.wait()
            return (amount+1)//2
        async def update(event):
            if event['type'] == 'qualified':
                ready.set()
        wire.on_quote = quote
        operation = asyncio.create_task(intent.get(request('issue-exact-out'), update))
        try:
            await asyncio.wait_for(ready.wait(), 2)
            self.assertFalse(operation.done())
            operation.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await operation
            self.assertTrue(operation.cancelled())
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_primary_deadline_diagnostics_survive_auxiliary_preview_cleanup(self):
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        preview_started, preview_cancelled = asyncio.Event(), asyncio.Event()
        primary = []
        async def preview(_service, *_args):
            preview_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # A preview's cancellation cleanup can begin another observed
                # call, replacing the request scope's mutable cancellation list.
                with rpc_call('eth_call', stage='contract-read'):
                    preview_cancelled.set()
                    raise
        async def search(value, on_update, *, block):
            rows = [{'best': {**candidates(target, value['mode'])[0], 'quote': '100'},
                'attempted': 1, 'total': 2, 'succeeded': 1, 'failures': []} for target in value['targets']]
            await on_update({'results': rows})
            await preview_started.wait()
            try:
                async with asyncio.timeout(.01):
                    with rpc_call('eth_call', stage='route-search'):
                        await asyncio.Event().wait()
            except TimeoutError as error:
                primary.append(error_diagnostics(error))
                raise
        routes.get = search
        with rpc_diagnostic_scope(), patch.object(TokenPreviewRpc, 'preview', preview):
            with self.assertRaises(TimeoutError) as raised:
                await asyncio.wait_for(intent.get(request('issue-exact-in'), lambda _: asyncio.sleep(0)), 2)
            payload = public_quote_error(raised.exception)
        self.assertTrue(preview_cancelled.is_set())
        self.assertEqual(payload['code'], 'quote-timeout')
        self.assertEqual(payload['diagnostics'], primary[0])
        self.assertEqual(payload['diagnostics']['stage'], 'route-search')
        self.assertEqual(payload['diagnostics']['failureType'], 'backend-deadline')

    async def test_primary_deadline_diagnostics_survive_inner_route_replay_cleanup(self):
        for mode in ('issue-exact-in', 'redeem-exact-out'):
            with self.subTest(mode=mode):
                intent, _provider, routes, _wire = service()
                self.addAsyncCleanup(routes.close)
                replay_started, replay_cancelled = asyncio.Event(), asyncio.Event()
                primary, events = [], []
                typed = SimpleNamespace(semaphore=asyncio.Semaphore(1))

                async def compose(rows, *_args, **_kwargs):
                    replay_started.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        # The prospective replay is cancelled inside search(),
                        # before get() can freeze the primary route failure.
                        with rpc_call('eth_call', stage='contract-read'):
                            replay_cancelled.set()
                            raise

                async def search(value, on_update, *, block):
                    rows = [{'best': {**candidates(target, value['mode'])[0], 'quote': '100'},
                        'attempted': 1, 'total': 2, 'succeeded': 1, 'failures': []}
                        for target in value['targets']]
                    await on_update({'results': rows})
                    await replay_started.wait()
                    try:
                        async with asyncio.timeout(.01):
                            with rpc_call('eth_call', stage='route-search'):
                                await asyncio.Event().wait()
                    except TimeoutError as error:
                        primary.append(error_diagnostics(error))
                        raise

                async def publish(event):
                    events.append(event)

                typed.compose_core_rows = compose
                routes.multi_protocol, routes.get = typed, search
                with rpc_diagnostic_scope():
                    with self.assertRaises(TimeoutError) as raised:
                        await asyncio.wait_for(intent.get(request(mode), publish), 2)
                    payload = public_quote_error(raised.exception)
                self.assertTrue(replay_cancelled.is_set())
                self.assertFalse(any(event['type'] == 'qualified' for event in events))
                self.assertEqual(payload['code'], 'quote-timeout')
                self.assertEqual(payload['diagnostics'], primary[0])
                self.assertEqual(payload['diagnostics']['stage'], 'route-search')
                self.assertEqual(payload['diagnostics']['failureType'], 'backend-deadline')
                self.assertEqual(payload['quoteDiagnostics']['phase'], 'initial-search')
                self.assertFalse(payload['quoteDiagnostics']['qualified'])
                self.assertGreaterEqual(payload['quoteDiagnostics']['elapsedMs'], payload['diagnostics']['elapsedMs'])

    async def test_initial_deadline_attributes_aggregate_subphase_separately_from_last_read(self):
        ordinary_timeout = asyncio.timeout
        for mode in ('issue-exact-in', 'redeem-exact-out'):
            for subphase in ('eligibility', 'v3-coverage', 'typed-reserve'):
                with self.subTest(mode=mode, subphase=subphase):
                    intent, _provider, routes, _wire = service()
                    self.addAsyncCleanup(routes.close)
                    events = []
                    async def blocked(*_args, **_kwargs):
                        # Work already consumed part of the aggregate budget
                        # before this final physical read starts.
                        await asyncio.sleep(.02)
                        with rpc_call('eth_call', stage='route-search'):
                            await asyncio.Event().wait()
                    if subphase == 'eligibility':
                        routes.rpc.eligible_paths = blocked
                    elif subphase == 'v3-coverage':
                        routes.rpc.quote_batch_counted = blocked
                    else:
                        async def compose(rows, *_args, **_kwargs):
                            with quote_sdk_request() as acquired:
                                acquired()
                                await asyncio.sleep(0)
                                return rows
                        routes.multi_protocol = SimpleNamespace(semaphore=asyncio.Semaphore(8),
                            reserve_quotes=blocked, compose_core_rows=compose)
                    async def publish(event):
                        events.append(event)
                    with rpc_diagnostic_scope(), patch('cybergold_candidate.route_search.asyncio.timeout',
                            side_effect=lambda _seconds: ordinary_timeout(.08)):
                        with self.assertRaises(TimeoutError) as raised:
                            await intent.get(request(mode), publish)
                        payload = public_quote_error(raised.exception)
                    logical, physical = payload['quoteDiagnostics'], payload['diagnostics']
                    self.assertEqual(payload['code'], 'quote-timeout')
                    self.assertEqual(logical['phase'], 'initial-search')
                    self.assertFalse(logical['qualified'])
                    self.assertFalse(any(event['type'] == 'qualified' for event in events))
                    self.assertEqual(logical['routeWave']['subphase'], subphase)
                    self.assertGreater(logical['routeWave']['elapsedMs'], physical['elapsedMs'] + 10)
                    wave = logical['routeWave']
                    if subphase == 'typed-reserve':
                        self.assertEqual(wave['sdkRequests'], 0)
                        self.assertGreater(wave['legacyCompleted'], 0)
                        self.assertEqual(wave['legacyCompleted'], wave['legacyCandidates'])
                    else:
                        self.assertEqual(wave['legacyCompleted'], 0)

    async def test_final_preview_failure_and_reorg_never_complete_after_estimate(self):
        for fault in ('fail_final','reorg','wrong_chain'):
            intent,provider,route,_=service();self.addAsyncCleanup(route.close)
            setattr(provider,fault,True)
            with self.assertRaises(Exception):
                await intent.get(request('issue-exact-in'),lambda event: asyncio.sleep(0))

    async def test_later_expected_input_wave_has_its_own_phase_and_iteration(self):
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        original, calls = routes.get, []
        async def blocked(*_args, **_kwargs):
            async with asyncio.timeout(.01):
                with rpc_call('eth_call', stage='route-search'):
                    await asyncio.Event().wait()
        async def search(value, on_update, *, block):
            calls.append(value['mode'])
            if len(calls) == 2:
                routes.rpc.quote_batch_counted = blocked
            return await original(value, on_update, block=block)
        routes.get = search
        with rpc_diagnostic_scope():
            with self.assertRaises(TimeoutError) as raised:
                await intent.get(request('redeem-exact-out'), lambda _event: asyncio.sleep(0))
            logical = public_quote_error(raised.exception)['quoteDiagnostics']
        self.assertEqual(calls, ['exact-out', 'exact-in'])
        self.assertEqual(logical['phase'], 'expected-input-search')
        self.assertEqual(logical['inversionIteration'], 0)
        self.assertFalse(logical['qualified'])
        self.assertEqual(logical['routeWave']['mode'], 'exact-in')
        self.assertEqual(logical['routeWave']['legacyCompleted'], 0)

    async def test_logical_snapshot_failure_does_not_replace_primary_timeout(self):
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        async def blocked(*_args, **_kwargs):
            async with asyncio.timeout(.01):
                with rpc_call('eth_call', stage='route-search'):
                    await asyncio.Event().wait()
        routes.get = blocked
        with rpc_diagnostic_scope(), patch('cybergold_candidate.rpc_diagnostics._QuoteWork.snapshot',
                side_effect=ValueError('optional observer unavailable')):
            with self.assertRaises(TimeoutError) as raised:
                await intent.get(request('issue-exact-in'), lambda _event: asyncio.sleep(0))
            payload = public_quote_error(raised.exception)
        self.assertEqual(payload['code'], 'quote-timeout')
        self.assertEqual(payload['diagnostics']['stage'], 'route-search')
        self.assertNotIn('quoteDiagnostics', payload)

    async def test_slow_failed_typed_replay_does_not_interrupt_later_candidate_coverage(self):
        from cybergold_candidate.basket_preview import InvalidPreview
        intent, provider, routes, wire = service()
        self.addAsyncCleanup(routes.close)
        wire.missing_fees = {100, 500, 3000, 10000}
        replay_started, later_searched = asyncio.Event(), asyncio.Event()
        release_replay, release_tail, qualified = asyncio.Event(), asyncio.Event(), asyncio.Event()
        events, replay_calls = [], []
        typed = SimpleNamespace(semaphore=asyncio.Semaphore(8))
        def result_rows(value, quote):
            rows = []
            for target in value['targets']:
                pool = {'protocol': 'v2', 'id': target['inputAsset'], 'address': target['inputAsset'], 'feePips': 3000,
                    'token0': {'address': target['inputAsset'], 'decimals': 18, 'chainId': 1},
                    'token1': {'address': ASSET_C, 'decimals': 18, 'chainId': 1}}
                shared = {'protocol': 'v2', 'id': ASSET_C, 'address': ASSET_C, 'feePips': 3000,
                    'token0': {'address': ASSET_C, 'decimals': 18, 'chainId': 1},
                    'token1': {'address': target['outputAsset'], 'decimals': 18, 'chainId': 1}}
                plan = {'version': 1, 'executionContext': 'helpers-core', 'mode': 'exactIn',
                    'tokenIn': target['inputAsset'], 'tokenOut': target['outputAsset'], 'inputAmount': target['amount'],
                    'outputAmount': str(quote), 'limit': '0', 'deadline': '0',
                    'branches': [{'amountIn': target['amount'], 'hops': [
                        {'pool': pool, 'zeroForOne': True}, {'pool': shared, 'zeroForOne': True}]}]}
                rows.append({'target': target, 'best': {'path': '0x', 'quote': str(quote), 'route': 'direct',
                    'feeInfo': '3000', 'routePlan': plan}, 'attempted': 1, 'succeeded': 1, 'failures': [], 'total': 3})
            return rows
        async def reserve(value, block, on_update=None):
            self.assertEqual(block['hash'], HASH)
            await on_update(result_rows(value, 200))
            await replay_started.wait()
            await on_update(result_rows(value, 300))
            later_searched.set()
            await release_tail.wait()
            rows = result_rows(value, 300)
            for row in rows:
                row.update(attempted=3, succeeded=2)
                row['failures'] = [{'path': '0x', 'rpcCode': 0, 'error': 'ordinary failed tail'}]
            return rows
        async def compose(rows, mode, block, **kwargs):
            replay_calls.append([row['best']['quote'] for row in rows])
            if len(replay_calls) == 1:
                replay_started.set()
                await release_replay.wait()
                raise InvalidPreview('Prospective shared-pool candidate cannot settle')
            return rows
        async def update(event):
            events.append(event)
            if event['type'] == 'qualified':
                qualified.set()
        typed.reserve_quotes, typed.compose_core_rows = reserve, compose
        routes.multi_protocol = typed
        operation = asyncio.create_task(intent.get(request('redeem-exact-in'), update))
        try:
            await asyncio.wait_for(later_searched.wait(), 1)
            self.assertFalse(qualified.is_set())
            release_replay.set()
            await asyncio.wait_for(qualified.wait(), 1)
            self.assertFalse(operation.done())
            first = next(event['value'] for event in events if event['type'] == 'qualified')
            self.assertEqual(first['context']['blockHash'], HASH)
            self.assertEqual([leg['minimumAmountOut'] for leg in first['quotes']], ['297', '297'])
            self.assertEqual(replay_calls[:2], [['200', '200'], ['300', '300']])
            self.assertGreaterEqual(sum(method.startswith('eth_getBlock') for method, _ in provider.calls), 2)
            release_tail.set()
            final = await operation
            self.assertEqual(final['preview']['minimumAmountOut'], '594')
        finally:
            release_replay.set(); release_tail.set()
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_context_reads_overlap_and_chain_check_precedes_contract_calls(self):
        intent,provider,route,_=service();self.addAsyncCleanup(route.close)
        provider.hold_chain,provider.hold_header=asyncio.Event(),asyncio.Event()
        operation=asyncio.create_task(intent.get(request('issue-exact-out'),lambda event:asyncio.sleep(0)))
        for _ in range(20):
            if len(provider.calls)>=2:break
            await asyncio.sleep(0)
        self.assertEqual({method for method,_ in provider.calls},{'eth_chainId','eth_getBlockByNumber'})
        self.assertEqual(provider.contract_calls,[])
        provider.hold_chain.set();provider.hold_header.set();await operation

    async def test_disconnect_cancels_pending_final_and_never_publishes_completion(self):
        intent,provider,route,_=service();self.addAsyncCleanup(route.close)
        provider.finish_final=asyncio.Event()
        operation=asyncio.create_task(intent.get(request('issue-exact-in'),lambda event:asyncio.sleep(0)))
        await provider.final_started.wait();operation.cancel()
        with self.assertRaises(asyncio.CancelledError):await operation

    async def test_http_stream_contract_redaction_and_invalid_input(self):
        intent,provider,route,_=service()
        app=create_app(route_search=route,quote_intent=intent)
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            invalid=await client.post('/api/quotes/intent/stream',json={**request('issue-exact-out'),'amount':'-1'})
            self.assertEqual(invalid.status_code,400);self.assertEqual(provider.calls,[])
            provider.fail_final=True
            response=await client.post('/api/quotes/intent/stream',json=request('issue-exact-in'))
            events=[json.loads(line) for line in response.text.splitlines()]
            self.assertEqual(events[-1]['type'],'error')
            self.assertNotIn('private supplier',response.text)
            self.assertEqual(response.headers['x-accel-buffering'],'no')
            self.assertFalse(any(row['type']=='complete' for row in events))


if __name__=='__main__':unittest.main()
