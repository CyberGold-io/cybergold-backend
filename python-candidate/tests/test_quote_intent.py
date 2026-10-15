"""Actual ABI, route producer and whole-intent invariants; no live transactions."""
import asyncio
import json
import time
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider
from eth_utils.abi import collapse_if_tuple

from cybergold_candidate.app import create_app
from cybergold_candidate.basket_preview import ABI as BASKET_ABI, InvalidPreview
from cybergold_candidate.token_preview import TokenPreviewRpc
from cybergold_candidate.quote_intent import QuoteIntent, REQUEST, issue_input_bounds, ceil
from cybergold_candidate.quote_correction import delayed_local_step
from cybergold_candidate.issuance_capacity import ABI as CAPACITY_ABI, READS as CAPACITY_READS, capacity_amounts
from cybergold_candidate.quote_errors import QuoteFailure, RpcTimeout, public_quote_error
from cybergold_candidate.route_search import RouteSearch, RouteSearchRpc, WETH, candidates
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.rpc_diagnostics import rpc_call, rpc_diagnostic_scope, error_diagnostics, quote_sdk_request
from cybergold_candidate.market_swap import MarketQuotes
from test_route_search import ASSET_A, ASSET_B, ASSET_C, HASH, Wire, wire_result
from route_engine_fixture import install_fixture_engine

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
    install_fixture_engine(route)
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


class EarlyCheckedIssueTests(unittest.IsolatedAsyncioTestCase):
    """Opt-in experiment using real route/Helpers/revalidation boundaries."""
    async def ready(self, event):
        try:
            await asyncio.wait_for(event.wait(), 1)
        except TimeoutError:
            self.fail('Expected observation did not arrive while the route tail was held')

    def fixture(self, *, protocol='v2', shape='single', opt_in=True, settled=True, filled=True):
        intent, provider, routes, wire = service(31338)
        self.addAsyncCleanup(routes.close)
        wire.missing_fees = {100, 500, 3000, 10000}
        intent.early_issue_probe = opt_in
        release, initial_progress, resolved = asyncio.Event(), asyncio.Event(), asyncio.Event()
        control = SimpleNamespace(release=release, initial_progress=initial_progress, resolved=resolved,
                                  fail_tail=False, requests=[], quote_calls=[], composition_calls=[], source_rows=[])
        inventory = {}
        def pool(source, target, kind, number):
            first, second = sorted((source, target), key=str.lower)
            identity = '0x' + format(number, '064x' if kind == 'v4' else '040x')
            value = {'protocol': kind, 'id': identity, 'address': '0x' + format(number, '040x'),
                'feePips': 3000, 'tickSpacing': 60, 'hooks': '0x' + '0' * 40,
                'token0': {'address': first, 'decimals': 18, 'chainId': 31338},
                'token1': {'address': second, 'decimals': 18, 'chainId': 31338}}
            inventory[identity] = value
            return {'pool': value, 'zeroForOne': first.lower() == source.lower()}
        paths = {}
        for index, asset in enumerate((ASSET_A, ASSET_B)):
            paths[(WETH.lower(), asset.lower())] = [pool(WETH, asset, protocol, index + 10)] if shape not in ('mixed', 'shared') else [
                pool(WETH, ASSET_C, 'v2', 20 if shape == 'shared' else index + 20),
                pool(ASSET_C, asset, 'v2' if shape == 'shared' else 'v3', index + 30)]
        typed = SimpleNamespace(semaphore=asyncio.Semaphore(8), registry=SimpleNamespace(inventory=inventory))
        def resolve(*args):
            control.resolved.set()
            return MarketQuotes.resolve_branches(typed, *args)
        typed.resolve_branches = resolve
        async def sdk(branches, mode, amount, block, **kwargs):
            control.quote_calls.append((mode, amount, deepcopy(branches)))
            index = 0
            if isinstance(candidate := kwargs.get('candidate'), dict):
                index = candidate.get('fixture-order', 0)
                candidate['fixture-order'] = index + 1
                hop = branches[-1]['hops'][-1]
                target = hop['pool']['token1' if hop['zeroForOne'] else 'token0']['address']
                control.composition_calls.append((mode, target, amount, index))
            return {'amountIn': str(amount if mode == 'exactIn' else (amount + 1) // 2 + index),
                    'amountOut': str(amount * 2 - 1 - 2 * index if mode == 'exactIn' and shape == 'shared' else amount * 2 if mode == 'exactIn' else amount),
                    'settled': settled if mode == 'exactOut' else True, 'fullyFilled': filled}
        typed.quote_sdk_branches = sdk
        async def quote(*args):
            return await MarketQuotes.quote_branches(typed, *args)
        typed.quote_branches = quote
        async def compose(*args, **kwargs):
            return await MarketQuotes.compose_core_rows(typed, *args, **kwargs)
        typed.compose_core_rows = compose
        async def reserve(value, block, on_update=None):
            control.requests.append(deepcopy(value))
            mode = 'exactIn' if value['mode'] == 'exact-in' else 'exactOut'
            rows = []
            for target in value['targets']:
                amount = int(target['amount'])
                hops = deepcopy(paths[(target['inputAsset'].lower(), target['outputAsset'].lower())])
                branches = [{'amountIn': str(amount) if mode == 'exactIn' else '0', 'hops': hops}]
                if shape == 'split' and mode == 'exactIn':
                    branches = [{'amountIn': str(amount // 2), 'hops': hops},
                                {'amountIn': str(amount - amount // 2), 'hops': deepcopy(hops)}]
                observed = amount * 2 if mode == 'exactIn' else (amount + 1) // 2
                plan = {'version': 1, 'executionContext': 'helpers-core', 'mode': mode,
                    'tokenIn': target['inputAsset'], 'tokenOut': target['outputAsset'],
                    'inputAmount': str(amount if mode == 'exactIn' else observed),
                    'outputAmount': str(observed if mode == 'exactIn' else amount),
                    'limit': '0', 'deadline': '0', 'branches': branches}
                rows.append({'target': target, 'best': {'path': '0x', 'quote': str(observed), 'routePlan': plan},
                             'attempted': 1, 'succeeded': 1, 'failures': [], 'total': 2})
            control.source_rows.append(deepcopy(rows))
            if on_update:
                await on_update(rows)
            if value['mode'] == 'exact-in':
                control.initial_progress.set()
                await release.wait()
                if control.fail_tail:
                    raise TimeoutError('Ordinary unfinished typed reserve tail')
            for row in rows:
                row.update(attempted=2, total=2)
            return rows
        typed.search_routes = reserve
        routes.multi_protocol = typed
        return intent, provider, routes, control

    async def test_homogeneous_typed_incumbent_is_checked_before_full_initial_coverage(self):
        for protocol in ('v2', 'v4'):
            for native in (False, True):
                with self.subTest(protocol=protocol, native=native):
                    intent, provider, _routes, control = self.fixture(protocol=protocol)
                    qualified, frames = asyncio.Event(), []
                    async def publish(frame):
                        frames.append(frame)
                        if frame['type'] == 'qualified':
                            qualified.set()
                    operation = asyncio.create_task(intent.get(request('issue-exact-in', native), publish))
                    try:
                        await self.ready(qualified)
                        self.assertFalse(operation.done())
                        value = next(frame['value'] for frame in frames if frame['type'] == 'qualified')
                        self.assertEqual(value['executionAmount'], '200')
                        self.assertEqual(value['maximumInputAmount'], '100')
                        self.assertEqual(value['context']['blockHash'], HASH)
                        self.assertEqual(value['basketPreview']['orderedCoreAssets'], [ASSET_A, ASSET_B])
                        self.assertEqual(value['preview']['orderedCoreAssets'], [ASSET_A, ASSET_B])
                        self.assertEqual([leg['amountIn'] for leg in value['quotes']], ['50', '50'])
                        self.assertEqual([leg['minimumAmountOut'] for leg in value['quotes']], ['100', '100'])
                        self.assertTrue(all(leg['routePlan']['mode'] == 'exactOut' for leg in value['quotes']))
                        self.assertTrue(all(leg['routePlan']['deadline'] == request('issue-exact-in')['deadline'] for leg in value['quotes']))
                        self.assertTrue(all(branch['amountIn'] == '0' for leg in value['quotes'] for branch in leg['routePlan']['branches']))
                        self.assertTrue(all(row['best']['routePlan']['mode'] == 'exactIn'
                                            for row in control.source_rows[0]))
                        self.assertTrue(any(name.endswith('ExactOut') and name.startswith('previewIssueFrom')
                                            and name != 'previewIssueFromBasketExactOut' for name, _, _ in provider.contract_calls))
                        self.assertGreaterEqual(sum(method.startswith('eth_getBlock') for method, _ in provider.calls), 2)
                        self.assertEqual(len(control.requests), 1)
                        control.release.set()
                        final = await operation
                        self.assertEqual(len(control.requests), 2)
                        self.assertEqual(final['executionAmount'], value['executionAmount'])
                    finally:
                        control.release.set(); operation.cancel(); await asyncio.gather(operation, return_exceptions=True)

    async def test_preview_and_canonicality_are_both_required_before_qualification(self):
        intent, provider, _routes, control = self.fixture()
        provider.finish_final = asyncio.Event()
        qualified = asyncio.Event()
        async def publish(frame):
            if frame['type'] == 'qualified':
                qualified.set()
        operation = asyncio.create_task(intent.get(request('issue-exact-in'), publish))
        try:
            await self.ready(provider.final_started)
            self.assertFalse(qualified.is_set())
            headers = sum(method.startswith('eth_getBlock') for method, _ in provider.calls)
            provider.hold_header = asyncio.Event()
            provider.finish_final.set()
            for _ in range(100):
                if sum(method.startswith('eth_getBlock') for method, _ in provider.calls) > headers:
                    break
                await asyncio.sleep(0)
            self.assertGreater(sum(method.startswith('eth_getBlock') for method, _ in provider.calls), headers)
            self.assertFalse(qualified.is_set())
            provider.hold_header.set()
            await self.ready(qualified)
        finally:
            control.release.set()
            provider.finish_final.set()
            if provider.hold_header:
                provider.hold_header.set()
            operation.cancel(); await asyncio.gather(operation, return_exceptions=True)

    async def test_released_full_search_keeps_the_same_targets_and_economics_as_default(self):
        results, searches = [], []
        for opt_in in (False, True):
            intent, _provider, _routes, control = self.fixture(opt_in=opt_in)
            observed = asyncio.Event()
            async def publish(frame):
                if frame['type'] == ('qualified' if opt_in else 'estimate'):
                    observed.set()
            operation = asyncio.create_task(intent.get(request('issue-exact-in'), publish))
            try:
                await self.ready(observed)
                self.assertFalse(operation.done())
                control.release.set()
                results.append(await operation)
                searches.append(deepcopy(control.requests))
            finally:
                control.release.set(); operation.cancel(); await asyncio.gather(operation, return_exceptions=True)
        self.assertEqual(searches[0], searches[1])
        for key in ('quotes', 'preview', 'basketPreview', 'initialPreview', 'displayAmount', 'expectedInputAmount',
                    'executionAmount', 'maximumInputAmount', 'requestedGrossCygldOut', 'remainingGrossCapacity',
                    'requestedNetCygldOut', 'remainingNetCapacity', 'mode', 'slippageBps'):
            self.assertEqual(results[0][key], results[1][key], key)

    async def test_shared_selected_pool_uses_core_order_before_protected_qualification(self):
        intent, _provider, _routes, control = self.fixture(shape='shared')
        value = request('issue-exact-in')
        value['targets'].reverse()
        qualified, frames = asyncio.Event(), []
        async def publish(frame):
            frames.append(frame)
            if frame['type'] == 'qualified':
                qualified.set()
        operation = asyncio.create_task(intent.get(value, publish))
        try:
            await self.ready(qualified)
            self.assertFalse(operation.done())
            checked = next(frame['value'] for frame in frames if frame['type'] == 'qualified')
            self.assertEqual(checked['executionAmount'], '196')
            self.assertEqual(checked['maximumInputAmount'], '100')
            self.assertEqual(checked['expectedInputAmount'], '99')
            self.assertEqual([leg['outputAsset'] for leg in checked['quotes']], [ASSET_A, ASSET_B])
            self.assertEqual([leg['minimumAmountOut'] for leg in checked['quotes']], ['98', '98'])
            self.assertEqual(control.composition_calls[:2], [('exactIn', ASSET_A, 50, 0), ('exactIn', ASSET_B, 50, 1)])
            exact_out = [row for row in control.composition_calls if row[0] == 'exactOut']
            self.assertEqual(exact_out[:2], [('exactOut', ASSET_A, 98, 0), ('exactOut', ASSET_B, 98, 1)])
            control.fail_tail = True
            control.release.set()
            result = await operation
            self.assertEqual(result['quotes'], checked['quotes'])
        finally:
            control.release.set(); operation.cancel(); await asyncio.gather(operation, return_exceptions=True)

    async def test_failed_final_helpers_preview_withholds_early_qualification(self):
        intent, provider, _routes, control = self.fixture()
        provider.fail_final = True
        frames = []
        operation = asyncio.create_task(intent.get(request('issue-exact-in'), lambda frame: asyncio.sleep(0, result=frames.append(frame))))
        try:
            await self.ready(provider.final_started)
            for _ in range(20):
                await asyncio.sleep(0)
            self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
            control.fail_tail = True
            control.release.set()
            with self.assertRaises(TimeoutError):
                await operation
        finally:
            control.release.set(); operation.cancel(); await asyncio.gather(operation, return_exceptions=True)

    async def test_checked_tuple_recovers_tail_error_but_not_reorg_or_caller_cancellation(self):
        for outcome in ('timeout', 'reorg', 'cancel'):
            with self.subTest(outcome=outcome):
                intent, provider, _routes, control = self.fixture()
                qualified, frames = asyncio.Event(), []
                async def publish(frame):
                    frames.append(frame)
                    if frame['type'] == 'qualified':
                        qualified.set()
                operation = asyncio.create_task(intent.get(request('issue-exact-in'), publish))
                try:
                    await self.ready(qualified)
                    incumbent = next(frame['value'] for frame in frames if frame['type'] == 'qualified')
                    control.fail_tail = True
                    provider.reorg = outcome == 'reorg'
                    if outcome == 'cancel':
                        operation.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await operation
                        self.assertTrue(operation.cancelled())
                    else:
                        control.release.set()
                        if outcome == 'reorg':
                            with self.assertRaises(SnapshotChanged):
                                await operation
                        else:
                            result = await operation
                            for key in ('quotes', 'preview', 'executionAmount', 'maximumInputAmount'):
                                self.assertEqual(result[key], incumbent[key])
                finally:
                    control.release.set(); operation.cancel(); await asyncio.gather(operation, return_exceptions=True)

    async def test_default_estimates_and_unsupported_or_unsettled_typed_conversions_do_not_qualify(self):
        for options in ({'opt_in': False}, {'shape': 'mixed'}, {'shape': 'split'}, {'settled': False}, {'filled': False}):
            with self.subTest(options=options):
                intent, _provider, _routes, control = self.fixture(**options)
                frames, estimated = [], asyncio.Event()
                async def publish(frame):
                    frames.append(frame)
                    if frame['type'] == 'estimate':
                        estimated.set()
                operation = asyncio.create_task(intent.get(request('issue-exact-in'), publish))
                try:
                    await self.ready(estimated)
                    if options.get('opt_in') is not False:
                        await self.ready(control.resolved)
                    for _ in range(20):
                        await asyncio.sleep(0)
                    self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
                    control.fail_tail = True
                    control.release.set()
                    with self.assertRaises(TimeoutError):
                        await operation
                finally:
                    control.release.set(); operation.cancel(); await asyncio.gather(operation, return_exceptions=True)


class RetainedTypedRedemptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_typed_redemption_preserves_raw_input_interval_and_execution_bounds(self):
        for chain in (31338, 1):
            for native in (False, True):
                intent, provider, routes, wire = service(chain)
                self.addAsyncCleanup(routes.close)
                intent.retain_plans = True
                wire.missing_fees = {100, 500, 3000, 10000}
                inventory, paths, calls, searches = {}, {}, [], []
                price_bonus = 0
                for index, asset in enumerate((ASSET_A, ASSET_B)):
                    first, second = sorted((asset, WETH), key=str.lower)
                    address = '0x' + format(index + 10, '040x')
                    pool = {'protocol': 'v2', 'id': address, 'address': address, 'feePips': 3000,
                        'token0': {'address': first, 'decimals': 18, 'chainId': chain},
                        'token1': {'address': second, 'decimals': 18, 'chainId': chain}}
                    inventory[address] = pool
                    paths[asset.lower()] = [{'pool': pool, 'zeroForOne': first.lower() == asset.lower()}]
                typed = SimpleNamespace(semaphore=asyncio.Semaphore(8), registry=SimpleNamespace(inventory=inventory))
                typed.resolve_branches = lambda *args: MarketQuotes.resolve_branches(typed, *args)
                async def sdk(branches, mode, amount, block, **_kwargs):
                    calls.append((mode, amount, block['hash']))
                    return {'amountIn': str(amount if mode == 'exactIn' else (amount + 1) // 2),
                            'amountOut': str(amount * 2 + price_bonus if mode == 'exactIn' else amount),
                            'settled': True, 'fullyFilled': True}
                typed.quote_sdk_branches = sdk
                async def quote(*args):
                    return await MarketQuotes.quote_branches(typed, *args)
                typed.quote_branches = quote
                async def compose(*args, **kwargs):
                    return await MarketQuotes.compose_core_rows(typed, *args, **kwargs)
                typed.compose_core_rows = compose
                async def reserve(value, block, on_update=None):
                    searches.append(deepcopy(value))
                    mode = 'exactIn' if value['mode'] == 'exact-in' else 'exactOut'
                    rows = []
                    for target in value['targets']:
                        amount = int(target['amount'])
                        observed = amount * 2 + price_bonus if mode == 'exactIn' else (amount + 1) // 2
                        branches = [{'amountIn': str(amount) if mode == 'exactIn' else '0',
                                     'hops': deepcopy(paths[target['inputAsset'].lower()])}]
                        plan = {'version': 1, 'executionContext': 'helpers-core', 'mode': mode,
                            'tokenIn': target['inputAsset'], 'tokenOut': target['outputAsset'],
                            'inputAmount': str(amount if mode == 'exactIn' else observed),
                            'outputAmount': str(observed if mode == 'exactIn' else amount),
                            'limit': '0', 'deadline': '0', 'branches': branches}
                        rows.append({'target': target, 'best': {'path': '0x', 'quote': str(observed), 'routePlan': plan},
                                     'attempted': 1, 'succeeded': 1, 'failures': [], 'total': 1})
                    if on_update:
                        await on_update(rows)
                    return rows
                typed.search_routes = reserve
                routes.multi_protocol = typed
                value = {**request('redeem-exact-out', native), 'slippageBps': 500}
                first = await intent.get(value, lambda _frame: asyncio.sleep(0))
                self.assertEqual(first['expectedInputAmount'], '100')
                self.assertEqual(first['executionAmount'], '106')
                self.assertEqual(first['preview']['minimumAmountOut'], '200')
                old_plan = retained_plan(first)
                old_quotes = deepcopy(first['quotes'])
                provider.block_hash = '0x' + 'c' * 64
                price_bonus = 2
                searches.clear(); calls.clear()
                provider.contract_calls.clear()
                selected = {**value, 'deadline': '1792000010', 'retainedPlan': old_plan}
                try:
                    current = await intent.get(selected, lambda _frame: asyncio.sleep(0))
                except TypeError:
                    self.fail('Retained typed redemption raised TypeError instead of completing selected-route inversion')
                self.assertEqual(searches, [], 'Selected-route revalidation must not restart route discovery')
                self.assertEqual(current['expectedInputAmount'], '98')
                self.assertEqual(current['executionAmount'], first['executionAmount'])
                self.assertEqual(current['preview']['minimumAmountOut'], first['preview']['minimumAmountOut'])
                self.assertEqual(current['expectedCoreOutputs'], first['expectedCoreOutputs'])
                self.assertEqual(current['context']['blockHash'], provider.block_hash)
                self.assertEqual([call[1] for call in calls], [53, 53, 50, 50, 49, 49])
                self.assertTrue(all(call[0] == 'exactIn' and call[2] == provider.block_hash for call in calls))
                raw_previews = {args['grossCygldIn'] if native else args['params']['grossCygldIn']:
                    sum(leg['minimumAmountOut'] for leg in args['legs'])
                    for name, args, _block in provider.contract_calls
                    if name == ('previewRedeemToNativeExactIn' if native else 'previewRedeemToTokenExactIn')}
                raw_output = raw_previews[int(current['expectedInputAmount'])]
                self.assertLessEqual(int(value['amount']), raw_output)
                self.assertLessEqual(raw_output, ceil(int(value['amount'])))
                stale_raw_output = raw_previews[int(old_plan['expectedInputAmount'])]
                self.assertEqual(stale_raw_output, 204)
                self.assertGreater(stale_raw_output, ceil(int(value['amount'])))
                self.assertLessEqual(stale_raw_output, ceil(int(value['amount']), value['slippageBps']))
                self.assertEqual(old_plan['quotes'], old_quotes)
                for leg in current['quotes']:
                    self.assertEqual(leg['routePlan']['mode'], 'exactIn')
                    self.assertEqual(leg['routePlan']['deadline'], selected['deadline'])
                    self.assertEqual(leg['routePlan']['inputAmount'], '53')
                    self.assertEqual(leg['minimumAmountOut'], '100')


class IntentTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def quote_calls(wire):
        selectors = {'0x' + Web3.keccak(text=f'{name}(bytes,uint256)')[:4].hex()
                     for name in ('quoteExactInput', 'quoteExactOutput')}
        return [row for batch in wire.batches for row in batch
                if row['params'][0]['data'][:10] in selectors]

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
        for mode, failing_mode, expected_calls in [('redeem-exact-in', 'exact-in', 1),
                                                    ('issue-exact-in', 'exact-in', 1)]:
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
                successful_quote_calls = len(self.quote_calls(wire))
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
                        self.assertEqual(len(self.quote_calls(wire)), calls)
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
                    original, rejected = route.engine.quote_branches, False
                    async def once(*args, **kwargs):
                        nonlocal rejected
                        if not rejected:
                            rejected = True
                            raise QuoteFailure('quote-contract-reverted')
                        return await original(*args, **kwargs)
                    route.engine.quote_branches = once
                events = []
                fresh = await intent.get({**request('redeem-exact-in'), 'retainedPlan': retained_plan(first)},
                                         lambda frame: asyncio.sleep(0, result=events.append(frame)))
                self.assertEqual(events[0]['type'], 'invalidated')
                self.assertEqual(fresh['metrics']['candidateCalls'], 9 if fault == 'route-revert' else 10)
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
                    original, batches = route.engine.quote_branches, []
                    async def transient(*args, **kwargs):
                        batches.append(args[1])
                        raise QuoteFailure(code)
                    route.engine.quote_branches = transient
                    events = []
                    next_request = {**request('redeem-exact-in'), 'retainedPlan': retained_plan(first)}
                    with self.assertRaises(QuoteFailure) as raised:
                        await intent.get(next_request, lambda frame: asyncio.sleep(0, result=events.append(frame)))
                    self.assertEqual(raised.exception.code, code)
                    self.assertEqual(batches, ['exactIn']) # No all-route fallback after a failed selected read.
                    self.assertNotIn('invalidated', [event['type'] for event in events])
                    route.engine.quote_branches = original
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

    async def test_selected_route_snapshot_disproof_does_not_restart_discovery(self):
        intent, provider, route, _wire = service(31338)
        self.addAsyncCleanup(route.close)
        intent.retain_plans = True
        first = await intent.get(request('redeem-exact-in'), lambda _: asyncio.sleep(0))
        provider.block_hash = '0x'+'c'*64
        async def changed(*_args, **_kwargs):
            raise SnapshotChanged('Selected pool snapshot was disproved', retry=1)
        async def forbidden(*_args, **_kwargs):
            self.fail('A disproved selected snapshot restarted candidate discovery')
        route.engine.quote_branches, route.engine.search_routes = changed, forbidden
        with self.assertRaisesRegex(SnapshotChanged, 'Selected pool snapshot'):
            await intent.get({**request('redeem-exact-in'), 'retainedPlan': retained_plan(first)},
                lambda _: asyncio.sleep(0))
        self.assertEqual(route.engine.semaphore._value, 8)

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
            install_fixture_engine(route)
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
                        self.assertEqual(result['metrics']['iterations'],0)
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
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        intent.qualification = False
        estimated, events = asyncio.Event(), []
        search = routes.engine.search_routes
        async def held(*args, **kwargs):
            await search(*args, **kwargs)
            await estimated.wait()
            raise TimeoutError('No executable candidate before producer deadline')
        routes.engine.search_routes = held
        async def update(event):
            events.append(event)
            if event['type'] == 'estimate':
                estimated.set()
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

    async def test_prospective_composition_disproof_survives_ordinary_search_tail(self):
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        invalidated, frames = asyncio.Event(), []
        async def compose(*_args, **_kwargs):
            raise SnapshotChanged('Pinned pool observation was disproved', retry=1)
        routes.engine.compose_core_rows = compose
        async def search(value, on_update, *, block):
            rows = [{'best': {**candidates(target, value['mode'])[0], 'quote': '25'},
                'attempted': 1, 'total': 2, 'succeeded': 1, 'failures': []}
                for target in value['targets']]
            await on_update({'results': rows})
            await invalidated.wait()
            raise TimeoutError('Ordinary optimization tail')
        routes.get = search
        async def update(frame):
            frames.append(frame)
            if frame['type'] == 'invalidated':
                invalidated.set()
        with self.assertRaises(SnapshotChanged):
            await asyncio.wait_for(intent.get(request('issue-exact-out'), update), 2)
        self.assertTrue(invalidated.is_set())
        self.assertFalse(any(frame['type'] in ('qualified', 'complete') for frame in frames))
        self.assertEqual(routes.engine.semaphore._value, 8)

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
                    try:
                        async with asyncio.timeout(.01):
                            with rpc_call('eth_call', stage='route-search'):
                                # Cold redemption now awaits protected work in
                                # this callback; its existing route deadline
                                # must include that pending replay too.
                                await on_update({'results': rows})
                                await replay_started.wait()
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
                        async with asyncio.timeout(2):
                            await intent.get(request(mode), publish)
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
            with self.subTest(mode=mode):
                intent, _provider, routes, _wire = service()
                self.addAsyncCleanup(routes.close)
                events = []
                async def blocked(*_args, **_kwargs):
                    # The common producer consumes part of the aggregate phase
                    # before its final physical read begins.
                    await asyncio.sleep(.02)
                    with rpc_call('eth_call', stage='route-search'):
                        await asyncio.Event().wait()
                routes.engine.search_routes = blocked
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
                self.assertEqual(logical['routeWave']['subphase'], 'structured-search')
                self.assertGreater(logical['routeWave']['elapsedMs'], physical['elapsedMs'] + 10)
                self.assertEqual(logical['routeWave']['legacyCompleted'], 0)

    async def test_final_preview_failure_and_reorg_never_complete_after_estimate(self):
        for fault in ('fail_final','reorg','wrong_chain'):
            intent,provider,route,_=service();self.addAsyncCleanup(route.close)
            setattr(provider,fault,True)
            with self.assertRaises(Exception):
                await intent.get(request('issue-exact-in'),lambda event: asyncio.sleep(0))

    async def test_first_protected_search_wave_has_its_own_phase_and_iteration(self):
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        original, quote, calls, early_forward = routes.get, routes.engine.quote_branches, [], []
        async def unavailable(branches, mode, amount, block, **kwargs):
            if mode == 'exactIn' and calls == ['exact-out']:
                # A failed cold prospective point resumes ordinary coverage.
                # This test then observes the first complete forward search.
                early_forward.append(amount)
                raise QuoteFailure('quote-no-route')
            return await quote(branches, mode, amount, block, **kwargs)
        routes.engine.quote_branches = unavailable
        async def blocked(*_args, **_kwargs):
            async with asyncio.timeout(.01):
                with rpc_call('eth_call', stage='route-search'):
                    await asyncio.Event().wait()
        async def search(value, on_update, *, block):
            calls.append(value['mode'])
            if len(calls) == 2:
                routes.engine.search_routes = blocked
            return await original(value, on_update, block=block)
        routes.get = search
        with rpc_diagnostic_scope():
            with self.assertRaises(TimeoutError) as raised:
                await intent.get(request('redeem-exact-out'), lambda _event: asyncio.sleep(0))
            logical = public_quote_error(raised.exception)['quoteDiagnostics']
        self.assertEqual(calls, ['exact-out', 'exact-in'])
        self.assertTrue(early_forward)
        self.assertEqual(logical['phase'], 'execution-search')
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
        typed.search_routes, typed.compose_core_rows = reserve, compose
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


class ProtectionAwareRedemptionSeedTests(unittest.IsolatedAsyncioTestCase):
    """Actual ABI reads; numeric hints never replace the protected tuple."""
    def fixture(self, *, shape='routed', amount=200, bps=100, supply=None,
                fees=(0, 0), seed_override=None, raw_fault=None, basket_fault=None):
        ready, raw_started, hold = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class SeedProvider(Provider):
            def __init__(self):
                super().__init__()
                self.chain_id = 31338
                self.seed = None
                self.burns = []
            async def make_request(self, method, params):
                if method != 'eth_call' or params[0]['to'].lower() == CORE.lower():
                    return await super().make_request(method, params)
                function, args = self.contract.decode_function_input(params[0]['data'])
                name = function.fn_name
                if not name.startswith('previewRedeem'):
                    return await super().make_request(method, params)
                self.calls.append((method, params))
                self.contract_calls.append((name, args, params[1]))
                def rejected(code, data=None):
                    return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': code,
                        **({'data': data} if data else {})}}
                if name == 'previewRedeemToBasketExactOut':
                    outputs = args['minimumOutputs']
                    self.seed = seed_override if seed_override is not None else sum(
                        row['minimumAmount'] for row in outputs if row['kind'] == 0) + sum(fees)
                    value = (self.seed, [(row['kind'], row['token'], row['id'], row['minimumAmount'])
                             for row in outputs], fees)
                else:
                    gross = args['grossCygldIn'] if name == 'previewRedeemToBasketExactIn' else args['params']['grossCygldIn']
                    if name == 'previewRedeemToBasketExactIn':
                        self.burns.append(gross)
                        if supply is not None and gross > supply:
                            return rejected(3, '0x33aa101c')
                        if basket_fault and gross != self.seed:
                            if basket_fault == 'hold':
                                raw_started.set(); await hold.wait()
                            if basket_fault == 'timeout':
                                raise TimeoutError
                            return rejected(-32603)
                        if raw_fault and gross == self.seed and any(value != self.seed for value in self.burns):
                            await ready.wait()
                            raw_started.set()
                            if raw_fault == 'hold':
                                await hold.wait()
                            if raw_fault == 'reorg':
                                self.reorg = True
                            return rejected(-32603)
                    elif raw_fault == 'later-supply':
                        return rejected(3, '0x33aa101c')
                    net = max(0, gross - sum(fees))
                    direct = net if shape == 'direct' else net * 99 // 100 if shape == 'mixed' else 0
                    assets = [WETH] if shape == 'direct' else [WETH, ASSET_A] if shape == 'mixed' else [ASSET_A, ASSET_B]
                    outputs = [(0, WETH, 0, direct)] if shape == 'direct' else [(0, WETH, 0, direct),
                        (0, ASSET_A, 0, net-direct)] if shape == 'mixed' else [(0, ASSET_A, 0, net//2), (0, ASSET_B, 0, net-net//2)]
                    outputs.append((1, CORE, int(ASSET_C, 16), gross))
                    minimum = direct + sum(row['minimumAmountOut'] for row in args.get('legs', []))
                    value = (outputs, fees) if name == 'previewRedeemToBasketExactIn' else (minimum, outputs, fees)
                output = function.abi['outputs'][0]
                return {'jsonrpc': '2.0', 'id': 1, 'result': '0x' + Web3().codec.encode(
                    [collapse_if_tuple(output)], [value]).hex()}
        provider, wire = SeedProvider(), QuoteWire()
        wire.provider = provider
        settings = SimpleNamespace(**{**vars(SETTINGS), 'NEXT_PUBLIC_CHAIN_ID': '31338'})
        routes = RouteSearch(settings, RouteSearchRpc(settings, AsyncWeb3(provider),
            httpx.AsyncClient(transport=httpx.MockTransport(wire.send))))
        install_fixture_engine(routes)
        self.addAsyncCleanup(routes.close)
        intent = QuoteIntent(settings, routes)
        value = {**request('redeem-exact-out'), 'amount': str(amount), 'slippageBps': bps}
        if shape == 'direct':
            value.update(orderedAssets=[WETH], targets=[{'inputAsset': WETH, 'outputAsset': WETH, 'amount': str(amount)}], adapter='')
        elif shape == 'mixed':
            value.update(orderedAssets=[WETH, ASSET_A], targets=[{'inputAsset': WETH, 'outputAsset': WETH, 'amount': str(amount-1)},
                {'inputAsset': ASSET_A, 'outputAsset': WETH, 'amount': '1'}])
        else:
            value['targets'] = [{'inputAsset': asset, 'outputAsset': WETH, 'amount': str(amount//2)} for asset in (ASSET_A, ASSET_B)]
        frames = []
        async def publish(frame):
            frames.append(frame)
            if frame['type'] == 'qualified':
                ready.set()
        return intent, provider, wire, value, frames, publish, raw_started

    async def test_first_protected_burn_is_adjusted_but_raw_metadata_keeps_the_original_seed(self):
        intent, provider, _, value, _, publish, _ = self.fixture()
        result = await intent.get(value, publish)
        self.assertEqual(provider.burns[0], 102)
        self.assertEqual(result['executionAmount'], '102')
        self.assertEqual(result['displayAmount'], '102')
        self.assertEqual(result['expectedInputAmount'], '100')
        self.assertEqual(result['preview']['minimumAmountOut'], '200')

    async def test_direct_output_and_recovery_shares_do_not_pad_a_valid_supply_limited_seed(self):
        intent, provider, wire, value, _, publish, _ = self.fixture(shape='direct', amount=100, supply=100)
        result = await intent.get(value, publish)
        self.assertEqual(provider.burns, [100])
        self.assertEqual(result['executionAmount'], '100')
        self.assertEqual(result['expectedInputAmount'], '100')
        self.assertEqual(result['quotes'], [])
        self.assertEqual(wire.batches, [])

    async def test_mixed_supply_rejection_restores_original_gross_in_every_returned_field(self):
        intent, provider, _, value, frames, publish, _ = self.fixture(shape='mixed', amount=100, supply=100)
        result = await intent.get(value, publish)
        self.assertEqual(provider.burns[:2], [102, 100])
        self.assertEqual(result['executionAmount'], '100')
        self.assertEqual(result['displayAmount'], '100')
        self.assertEqual(result['expectedInputAmount'], '100')
        self.assertEqual(result['preview']['minimumAmountOut'], '100')
        self.assertTrue(all(frame['value']['executionAmount'] == '100' for frame in frames if frame['type'] == 'qualified'))

    async def test_tiny_routed_plateau_uses_specific_supply_fallback_and_keeps_raw_inversion(self):
        intent, provider, _, value, _, publish, _ = self.fixture(amount=2, supply=2)
        result = await intent.get(value, publish)
        self.assertEqual(provider.burns[:2], [3, 2])
        self.assertEqual(result['executionAmount'], '2')
        self.assertEqual(result['expectedInputAmount'], '1')
        self.assertEqual(result['preview']['minimumAmountOut'], '2')

    async def test_zero_custom_and_full_tolerance_preserve_existing_domain_and_bounds(self):
        for bps, first in ((0, 100), (37, 101), (100, 102), (500, 106), (10_000, 100)):
            with self.subTest(bps=bps):
                intent, provider, _, value, frames, publish, _ = self.fixture(bps=bps)
                if bps == 10_000:
                    with self.assertRaises(InvalidPreview):
                        await intent.get(value, publish)
                    self.assertEqual(len(provider.burns), 11)
                    self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
                else:
                    result = await intent.get(value, publish)
                    minimum = int(result['preview']['minimumAmountOut'])
                    self.assertLessEqual(200, minimum)
                    self.assertLessEqual(minimum, ceil(200, bps))
                    self.assertEqual(result['expectedInputAmount'], '100')
                self.assertEqual(provider.burns[0], first)

    async def test_protocol_and_helper_fees_remain_in_the_burn_and_advisory_metadata(self):
        intent, provider, _, value, _, publish, _ = self.fixture(fees=(5, 7))
        result = await intent.get(value, publish)
        self.assertEqual(provider.burns[0], 114)
        self.assertEqual(result['executionAmount'], '114')
        self.assertEqual(result['expectedInputAmount'], '112')
        self.assertEqual(result['preview']['fees'], {'protocolFeeCygld': '5', 'helperFeeCygld': '7'})
        self.assertEqual(result['preview']['minimumAmountOut'], '200')

    async def test_accepted_mainnet_hint_is_not_padded_again(self):
        from cybergold_candidate.quote_cache import VerifiedGrossSeed
        intent, provider, _, value, _, publish, _ = self.fixture()
        provider.chain_id = 1
        intent.routes.rpc.chain_id = 1
        seeds = VerifiedGrossSeed()
        seeds.rows[seeds.key(value, {'chainId': 1, 'blockHash': HASH})] = (time.monotonic(), 101)
        intent.seeds = seeds
        result = await intent.get(value, publish)
        self.assertEqual(provider.burns[0], 101)
        self.assertEqual(result['executionAmount'], '102')
        self.assertEqual(result['expectedInputAmount'], '101')

    async def test_reciprocal_uint_overflow_keeps_the_original_abi_encodable_seed(self):
        maximum = 2**256-1
        intent, provider, wire, value, _, publish, _ = self.fixture(amount=2, seed_override=maximum)
        async def identity(_path, amount):
            return amount
        wire.on_quote = identity
        result = await intent.get(value, publish)
        self.assertEqual(provider.burns[0], maximum)
        self.assertEqual(result['executionAmount'], '2')
        self.assertEqual(result['expectedInputAmount'], '2')
        self.assertEqual(result['preview']['minimumAmountOut'], '2')

    async def test_unknown_first_basket_error_and_later_helpers_supply_error_are_not_fallbacks(self):
        from cybergold_candidate.preview_errors import KnownPreviewError
        for options, error_type in (({'basket_fault': 'rpc'}, QuoteFailure),
                ({'basket_fault': 'timeout'}, TimeoutError), ({'raw_fault': 'later-supply'}, KnownPreviewError)):
            with self.subTest(options=options):
                intent, provider, _, value, _, publish, _ = self.fixture(**options)
                with self.assertRaises(error_type):
                    await intent.get(value, publish)
                self.assertEqual(provider.burns, [102])

    async def test_late_advisory_rpc_failure_preserves_checked_execution_with_optional_metadata_absent(self):
        intent, _, _, value, frames, publish, _ = self.fixture(raw_fault='rpc')
        result = await intent.get(value, publish)
        self.assertNotIn('expectedInputAmount', result)
        self.assertEqual(result['executionAmount'], '102')
        self.assertEqual(result['preview']['minimumAmountOut'], '200')
        self.assertTrue(any(frame['type'] == 'qualified' for frame in frames))

    async def test_late_advisory_reorg_and_caller_cancellation_never_return_a_checked_stale_tuple(self):
        intent, _, _, value, _, publish, _ = self.fixture(raw_fault='reorg')
        with self.assertRaises(SnapshotChanged):
            await intent.get(value, publish)
        intent, _, _, value, frames, publish, started = self.fixture(raw_fault='hold')
        task = asyncio.create_task(intent.get(value, publish))
        try:
            await asyncio.wait_for(started.wait(), 1)
            self.assertTrue(any(frame['type'] == 'qualified' for frame in frames))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_first_padded_basket_cancellation_does_not_retry_the_original_seed(self):
        intent, provider, _, value, _, publish, started = self.fixture(basket_fault='hold')
        task = asyncio.create_task(intent.get(value, publish))
        try:
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(provider.burns, [102])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class EarlyProtectedRedemptionPointTests(unittest.IsolatedAsyncioTestCase):
    """Fresh protected points can qualify without awaiting unrelated coverage."""

    def fixture(self, *, target=200, native=False, price=(3, 2), late_price=None,
                typed=False, changed=False, rejected=False, reorg=False, zero_basket=False, curve=None):
        intent, provider, routes, wire = service(31338)
        release, previewed, refined = asyncio.Event(), asyncio.Event(), asyncio.Event()
        control = SimpleNamespace(release=release, previewed=previewed, refined=refined,
            fail_tail=True, first_gross=None, state_changed=False, calls=[], composed=[])
        async def close():
            release.set()
            await intent.close()
        self.addAsyncCleanup(close)
        original_read = provider.make_request
        async def read(method, params):
            function, args = (None, None)
            if method == 'eth_call' and params[0]['to'].lower() != CORE.lower():
                function, args = provider.contract.decode_function_input(params[0]['data'])
            token = function and function.fn_name in ('previewRedeemToTokenExactIn', 'previewRedeemToNativeExactIn')
            gross = (args.get('grossCygldIn') if 'grossCygldIn' in args else args['params']['grossCygldIn']) if token else None
            if token and rejected and control.first_gross is not None and gross != control.first_gross:
                refined.set()
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'message': 'Synthetic revised preview rejection'}}
            response = await original_read(method, params)
            if function and function.fn_name == 'previewRedeemToBasketExactIn' and zero_basket:
                output = function.abi['outputs'][0]
                prior = provider.contract.w3.codec.decode([collapse_if_tuple(output)], bytes.fromhex(response['result'][2:]))[0]
                outputs = [(kind, token, identity, 0 if kind == 0 else amount) for kind, token, identity, amount in prior[0]]
                response = {**response, 'result': '0x' + provider.contract.w3.codec.encode(
                    [collapse_if_tuple(output)], [(outputs, prior[1])]).hex()}
            if token:
                if control.first_gross is None:
                    control.first_gross = gross
                    control.state_changed = changed
                    previewed.set()
                elif gross != control.first_gross:
                    if reorg:
                        provider.reorg = True
                    refined.set()
            return response
        provider.make_request = read
        def output(amount, *, complete=False):
            if curve is not None:
                return curve(amount)
            numerator, denominator = (2, 1) if control.state_changed else late_price if complete and late_price else price
            return amount * numerator // denominator
        async def quoted(path, amount):
            if path[:20] == bytes.fromhex(WETH[2:]):
                return (amount + 1) // 2
            fee = int.from_bytes(path[20:23])
            if fee > 500:
                await release.wait()
                if control.fail_tail:
                    raise TimeoutError('Ordinary unfinished coverage')
            control.calls.append(('legacy', amount))
            return output(amount, complete=release.is_set())
        wire.on_quote = quoted
        value = request('redeem-exact-out', native)
        value['amount'] = str(target)
        value['targets'] = [{'inputAsset': asset, 'outputAsset': WETH, 'amount': str(amount)}
                           for asset, amount in zip((ASSET_A, ASSET_B), (target // 2, target - target // 2), strict=True) if amount]
        if typed:
            wire.missing_fees = {100, 500, 3000, 10000}
            inventory, paths = {}, {}
            def hop(source, destination, identity):
                left, right = sorted((source, destination), key=str.lower)
                pool = {'id': '0x' + f'{identity:040x}', 'address': '0x' + f'{identity:040x}', 'protocol': 'v2', 'feePips': 3000,
                    'token0': {'address': left, 'decimals': 18, 'chainId': 31338},
                    'token1': {'address': right, 'decimals': 18, 'chainId': 31338}}
                inventory[pool['id']] = pool
                return {'pool': pool, 'zeroForOne': left.lower() == source.lower()}
            trunk = hop(ASSET_C, WETH, 20)
            for index, asset in enumerate((ASSET_A, ASSET_B)):
                paths[asset.lower()] = [hop(asset, ASSET_C, index + 30), deepcopy(trunk)]
            engine = SimpleNamespace(semaphore=asyncio.Semaphore(8), registry=SimpleNamespace(inventory=inventory))
            engine.resolve_branches = lambda *args: MarketQuotes.resolve_branches(engine, *args)
            async def sdk(branches, mode, amount, block, **kwargs):
                control.calls.append((mode, amount, deepcopy(branches)))
                if isinstance(candidate := kwargs.get('candidate'), dict):
                    index = candidate.get('fixture-order', 0)
                    candidate['fixture-order'] = index + 1
                    control.composed.append((amount, index))
                return {'amountIn': str(amount if mode == 'exactIn' else (amount + 1) // 2),
                    'amountOut': str(output(amount, complete=release.is_set()) if mode == 'exactIn' else amount),
                    'settled': True, 'fullyFilled': True}
            engine.quote_sdk_branches = sdk
            async def quote(*args):
                return await MarketQuotes.quote_branches(engine, *args)
            engine.quote_branches = quote
            async def compose(*args, **kwargs):
                return await MarketQuotes.compose_core_rows(engine, *args, **kwargs)
            engine.compose_core_rows = compose
            async def reserve(values, block, on_update=None):
                mode = 'exactIn' if values['mode'] == 'exact-in' else 'exactOut'
                rows = []
                for target in values['targets']:
                    amount = int(target['amount'])
                    hops = deepcopy(paths[target['inputAsset'].lower()])
                    observed = output(amount, complete=release.is_set()) if mode == 'exactIn' else (amount + 1) // 2
                    plan = {'version': 1, 'executionContext': 'helpers-core', 'mode': mode,
                        'tokenIn': target['inputAsset'], 'tokenOut': target['outputAsset'],
                        'inputAmount': str(amount if mode == 'exactIn' else observed), 'outputAmount': str(observed if mode == 'exactIn' else amount),
                        'limit': '0', 'deadline': '0', 'branches': [{'amountIn': str(amount) if mode == 'exactIn' else '0', 'hops': hops}]}
                    rows.append({'target': target, 'best': {'path': '0x', 'quote': str(observed), 'routePlan': plan},
                                 'attempted': 1, 'succeeded': 1, 'failures': [], 'total': 2})
                if on_update:
                    await on_update(rows)
                if mode == 'exactIn':
                    await release.wait()
                    if control.fail_tail:
                        raise TimeoutError('Ordinary unfinished typed reserve')
                return rows
            engine.search_routes = reserve
            routes.multi_protocol = engine
        return intent, provider, control, value

    def start(self, intent, value):
        frames, qualified = [], asyncio.Event()
        async def update(frame):
            if frame['type'] == 'qualified':
                frames.append(frame['value'])
                qualified.set()
        task = asyncio.create_task(intent.get(value, update))
        async def cancel():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.addAsyncCleanup(cancel)
        return task, frames, qualified

    async def wait(self, event):
        # Readiness assertions are event-based; the watchdog follows the
        # existing producer phase budget, including cold native ABI work.
        await asyncio.wait_for(event.wait(), 15)

    async def test_legacy_token_and_native_lower_points_qualify_before_tail(self):
        for native in (False, True):
            with self.subTest(native=native):
                intent, provider, control, value = self.fixture(native=native)
                task, frames, ready = self.start(intent, value)
                await self.wait(ready)
                result = frames[0]
                self.assertFalse(task.done())
                self.assertEqual((result['executionAmount'], result['preview']['minimumAmountOut']), ('136', '200'))
                self.assertEqual([leg['inputAmount'] for leg in result['quotes']], ['68', '68'])
                self.assertIn(('legacy', 68), control.calls)
                names = [name for name, _args, _block in provider.contract_calls]
                self.assertIn('previewRedeemToNativeExactIn' if native else 'previewRedeemToTokenExactIn', names)
                control.release.set()
                self.assertEqual((await task)['executionAmount'], '136')

    def assert_checked_points(self, provider, value, frames):
        name = 'previewRedeemToNativeExactIn' if value['native'] else 'previewRedeemToTokenExactIn'
        previews = [(args['grossCygldIn'] if value['native'] else args['params']['grossCygldIn'],
                     tuple((leg['minimumAmountOut'], Web3.to_hex(leg['data']).lower()) for leg in args['legs']))
                    for function, args, _block in provider.contract_calls if function == name]
        for result in frames:
            minimum = int(result['preview']['minimumAmountOut'])
            self.assertLessEqual(int(value['amount']), minimum)
            self.assertLessEqual(minimum, ceil(int(value['amount']), value.get('slippageBps', 100)))
            self.assertIn((int(result['executionAmount']), tuple((int(leg['minimumAmountOut']),
                leg['data'].lower()) for leg in result['quotes'])), previews)

    async def test_upper_point_and_later_checked_rounding_point_keep_the_existing_interval(self):
        intent, _provider, control, value = self.fixture(target=100, price=(21, 10))
        task, frames, ready = self.start(intent, value)
        await self.wait(ready)
        self.assertEqual((frames[0]['executionAmount'], frames[0]['preview']['minimumAmountOut']), ('49', '100'))
        control.release.set()
        await task
        intent, provider, control, value = self.fixture(price=(21, 10))
        task, frames, _ready = self.start(intent, value)
        await self.wait(control.refined)
        control.release.set()
        # The old batch tail timeout cancelled97→98 before the next check.
        # An isolated failed candidate leaves that fresh correction available.
        result = await task
        self.assertEqual((result['executionAmount'], result['preview']['minimumAmountOut']), ('98', '200'))
        self.assertTrue(frames)
        self.assert_checked_points(provider, value, frames)

    async def test_zero_helpers_output_has_no_division_or_executable_point(self):
        intent, _provider, control, value = self.fixture(zero_basket=True)
        task, frames, _ready = self.start(intent, value)
        with self.assertRaises(InvalidPreview):
            await task
        self.assertEqual(frames, [])

    async def test_fresh_state_is_rechecked_and_helpers_rejection_or_reorg_do_not_complete(self):
        for option in ('changed', 'rejected', 'reorg'):
            with self.subTest(option=option):
                intent, provider, control, value = self.fixture(**{option: True})
                task, frames, _ready = self.start(intent, value)
                await self.wait(control.refined)
                control.release.set()
                if option == 'changed':
                    result = await task
                    self.assertEqual((result['executionAmount'], result['preview']['minimumAmountOut']), ('102', '200'))
                    self.assertTrue(frames)
                    self.assertTrue(all(frame['executionAmount'] != '136' for frame in frames))
                    self.assert_checked_points(provider, value, frames)
                else:
                    # Per-candidate tail failures no longer replace a reached
                    # Helpers rejection with the old whole-batch timeout.
                    with self.assertRaises(SnapshotChanged if option == 'reorg' else QuoteFailure) as raised:
                        await task
                    if option == 'rejected':
                        self.assertEqual(raised.exception.code, 'quote-contract-reverted')
                    self.assertEqual(frames, [])

    async def test_budget_timeout_while_next_rounding_check_is_held_does_not_qualify(self):
        from cybergold_candidate.quote_budget import QuoteBudget, budget_context
        intent, provider, control, value = self.fixture(price=(21, 10))
        entered, release = asyncio.Event(), asyncio.Event()
        original = provider.make_request
        async def read(method, params):
            if method == 'eth_call' and params[0]['to'].lower() != CORE.lower():
                function, args = provider.contract.decode_function_input(params[0]['data'])
                if function.fn_name == 'previewRedeemToTokenExactIn' and args['params']['grossCygldIn'] == 98:
                    entered.set()
                    await release.wait()
            return await original(method, params)
        provider.make_request = read
        frames = []
        budget = QuoteBudget(.3, .3)
        with budget_context(budget):
            task = asyncio.create_task(budget.produce(intent.get(value,
                lambda frame: asyncio.sleep(0, result=frames.append(frame)))))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            with self.assertRaises(TimeoutError):
                await task
            self.assertIsNone(budget.first_qualified)
            self.assertFalse(any(frame['type'] == 'qualified' for frame in frames))
        finally:
            release.set()
            control.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_complete_coverage_can_improve_the_early_point(self):
        intent, _provider, control, value = self.fixture(late_price=(2, 1))
        task, frames, ready = self.start(intent, value)
        await self.wait(ready)
        self.assertEqual(frames[0]['executionAmount'], '136')
        control.fail_tail = False
        control.release.set()
        result = await task
        self.assertEqual((result['executionAmount'], result['preview']['minimumAmountOut']), ('102', '200'))

    async def test_caller_cancellation_does_not_return_an_incumbent(self):
        intent, _provider, _control, value = self.fixture()
        task, frames, ready = self.start(intent, value)
        await self.wait(ready)
        self.assertTrue(frames)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_typed_shared_legs_reprice_and_compose_new_quantities(self):
        for native in (False, True):
            with self.subTest(native=native):
                intent, _provider, control, value = self.fixture(typed=True, native=native)
                task, frames, ready = self.start(intent, value)
                await self.wait(ready)
                first = frames[0]
                self.assertEqual((first['executionAmount'], first['preview']['minimumAmountOut']), ('136', '200'))
                self.assertEqual([leg['routePlan']['inputAmount'] for leg in first['quotes']], ['68', '68'])
                self.assertEqual([sum(int(branch['amountIn']) for branch in leg['routePlan']['branches']) for leg in first['quotes']], [68, 68])
                self.assertIn((68, 0), control.composed)
                self.assertIn((68, 1), control.composed)
                control.release.set()
                self.assertEqual((await task)['executionAmount'], '136')


class RepeatedProtectedRedemptionPointTests(unittest.IsolatedAsyncioTestCase):
    fixture = EarlyProtectedRedemptionPointTests.fixture
    start = EarlyProtectedRedemptionPointTests.start
    wait = EarlyProtectedRedemptionPointTests.wait

    def concave_fixture(self, **options):
        intent, provider, control, value = self.fixture(curve=lambda amount: 1000 * amount // (1000 + amount), **options)
        intent.seeds = SimpleNamespace(suggest=lambda *_: 100, observe=lambda *_: None, fallback=False)
        intent.correction = delayed_local_step
        return intent, provider, control, value

    async def test_concave_token_native_and_typed_shared_routes_qualify_after_multiple_fresh_points(self):
        for typed in (False, True):
            for native in (False, True):
                with self.subTest(typed=typed, native=native):
                    intent, provider, control, value = self.concave_fixture(typed=typed, native=native)
                    task, frames, ready = self.start(intent, value)
                    await self.wait(ready)
                    self.assertFalse(task.done())
                    result = frames[0]
                    self.assertEqual((result['executionAmount'], result['preview']['minimumAmountOut']), ('230', '202'))
                    self.assertEqual([leg['inputAmount'] for leg in result['quotes']], ['115', '115'])
                    names = [name for name, _args, _block in provider.contract_calls]
                    self.assertGreaterEqual(names.count('previewRedeemToNativeExactIn' if native else 'previewRedeemToTokenExactIn'), 5)
                    if typed:
                        self.assertIn((115, 0), control.composed)
                        self.assertIn((115, 1), control.composed)
                    control.release.set()
                    self.assertEqual((await task)['executionAmount'], '230')

    async def test_reorg_after_an_intermediate_point_cannot_publish_a_later_refinement(self):
        intent, _provider, control, value = self.concave_fixture(reorg=True)
        invalidated, frames = asyncio.Event(), []
        async def update(frame):
            if frame['type'] == 'invalidated':
                invalidated.set()
            elif frame['type'] == 'qualified':
                frames.append(frame['value'])
        task = asyncio.create_task(intent.get(value, update))
        try:
            await self.wait(invalidated)
            self.assertEqual(frames, [])
            control.release.set()
            with self.assertRaises(SnapshotChanged):
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_cancellation_during_an_additional_forward_check_does_not_publish(self):
        intent, provider, _control, value = self.concave_fixture()
        entered, release = asyncio.Event(), asyncio.Event()
        original_read = provider.make_request
        async def read(method, params):
            if method == 'eth_call' and params[0]['to'].lower() != CORE.lower():
                function, args = provider.contract.decode_function_input(params[0]['data'])
                if function.fn_name == 'previewRedeemToTokenExactIn' and args['params']['grossCygldIn'] == 224:
                    entered.set()
                    await release.wait()
            return await original_read(method, params)
        provider.make_request = read
        task, frames, _ready = self.start(intent, value)
        try:
            await self.wait(entered)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(frames, [])
        finally:
            release.set()


class SelectedRedemptionRepricingOverlapTests(unittest.IsolatedAsyncioTestCase):
    concave_fixture = RepeatedProtectedRedemptionPointTests.concave_fixture
    fixture = EarlyProtectedRedemptionPointTests.fixture
    start = EarlyProtectedRedemptionPointTests.start
    wait = EarlyProtectedRedemptionPointTests.wait

    async def test_selected_token_and_native_legs_start_before_either_read_finishes(self):
        for native in (False, True):
            with self.subTest(native=native):
                intent, _provider, control, value = self.concave_fixture(typed=True, native=native)
                engine = intent.routes.multi_protocol
                original = engine.quote_branches
                entered, release = asyncio.Event(), asyncio.Event()
                started = 0
                async def quote(*args, entered=entered, release=release, original=original):
                    nonlocal started
                    started += 1
                    if started <= 2:
                        if started == 2:
                            entered.set()
                        await release.wait()
                    return await original(*args)
                engine.quote_branches = quote
                task, frames, ready = self.start(intent, value)
                try:
                    try:
                        await asyncio.wait_for(entered.wait(), 1)
                    except TimeoutError:
                        self.fail('The second selected leg did not start before the first was released.')
                    self.assertEqual(started, 2)
                    self.assertEqual(frames, [])
                    release.set()
                    await self.wait(ready)
                    self.assertEqual((frames[0]['executionAmount'], frames[0]['preview']['minimumAmountOut']), ('230', '202'))
                    self.assertEqual([leg['inputAmount'] for leg in frames[0]['quotes']], ['115', '115'])
                    self.assertIn((115, 0), control.composed)
                    self.assertIn((115, 1), control.composed)
                    control.release.set()
                    self.assertEqual((await task)['executionAmount'], '230')
                finally:
                    release.set()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_cancellation_drains_both_legs_without_cancelling_another_shared_read_user(self):
        from cybergold_candidate.shared_reads import SharedReads
        intent, _provider, _control, value = self.concave_fixture(typed=True)
        engine = intent.routes.multi_protocol
        bank = SharedReads()
        self.addAsyncCleanup(bank.close)
        entered, release = asyncio.Event(), asyncio.Event()
        started = cancelled = 0
        async def read():
            await release.wait()
            return 123
        async def quote(*_args):
            nonlocal started, cancelled
            started += 1
            if started == 2:
                entered.set()
            try:
                await bank.one('shared-pool', read)
            except asyncio.CancelledError:
                cancelled += 1
                raise
        engine.quote_branches = quote
        outside = asyncio.create_task(bank.one('shared-pool', read))
        task, frames, _ready = self.start(intent, value)
        try:
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(cancelled, 2)
            self.assertEqual(frames, [])
            self.assertFalse(outside.done())
            self.assertEqual(engine.semaphore._value, 8)
            release.set()
            self.assertEqual(await outside, 123)
            self.assertEqual(bank.pending, {})
        finally:
            release.set()
            await asyncio.gather(outside, return_exceptions=True)

    async def test_failed_first_leg_drains_its_parallel_sibling_and_keeps_the_ordinary_tail_error(self):
        intent, _provider, control, value = self.concave_fixture(typed=True)
        engine = intent.routes.multi_protocol
        entered, sibling_cancelled = asyncio.Event(), asyncio.Event()
        started = 0
        async def quote(*_args):
            nonlocal started
            started += 1
            first = started == 1
            if started == 2:
                entered.set()
            if first:
                await entered.wait()
                raise RpcTimeout()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sibling_cancelled.set()
                raise
        engine.quote_branches = quote
        task, frames, _ready = self.start(intent, value)
        await asyncio.wait_for(sibling_cancelled.wait(), 1)
        self.assertEqual(started, 2)
        self.assertEqual(frames, [])
        self.assertEqual(engine.semaphore._value, 8)
        control.release.set()
        with self.assertRaises(TimeoutError):
            await task


if __name__ == '__main__':
    unittest.main()
