"""Finite V4 liquidity completes through real SDK math, including empty gaps."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from web3 import Web3
from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.market_swap import MarketQuotes
from cybergold_candidate.quote_errors import QuoteFailure, public_quote_error
from cybergold_candidate.sdk_worker import SdkWorker, SdkInputTooSmall
from cybergold_candidate.uniswap_state import PoolRegistry
from cybergold_candidate.uniswap_v4 import tick_prefetch_scope
from cybergold_candidate.uniswap_routes import resize_branches
from cybergold_candidate.market_fee import quoted_fee
from cybergold_candidate.market_capacity import maximum_filled_input
from cybergold_candidate.universal_quote import UniversalQuotes

CORE = '0x'+'6'*40
BLOCK = {'number': 123, 'hash': '0x'+'ab'*32}
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE)


class LiquidityRpc:
    chain_id, pool_manager, state_view, w3 = 31338, '0x'+'4'*40, '0x'+'5'*40, Web3()

    def __init__(self, ranges):
        self.ranges, self.calls, self.bulk_words = ranges, [], []
        self.ticks, self.words = {}, {}
        for lower, upper, liquidity in ranges:
            for tick, net in ((lower, liquidity), (upper, -liquidity)):
                self.ticks[tick] = (liquidity, net)
                position, bit = tick >> 8, tick & 255
                self.words[position] = self.words.get(position, 0) | (1 << bit)
        self.liquidity = sum(value for lower, upper, value in ranges if lower <= 0 < upper)
        self.slots = {}

    def bind(self, pool):
        state = int.from_bytes(Web3.keccak(self.w3.codec.encode(
            ['bytes32', 'uint256'], [bytes.fromhex(pool['id'][2:]), 6])), 'big')
        self.slots = {bytes(Web3.keccak(self.w3.codec.encode(['int256', 'uint256'], [word, state+5]))): word
                      for word in range(-3466, 3466)}

    async def block(self, _): return deepcopy(BLOCK)
    async def assert_canonical(self, block): assert block == BLOCK
    async def close(self): pass

    async def read_function(self, address, signature, inputs, args, outputs, block):
        assert block == BLOCK
        self.calls.append((signature, deepcopy(args)))
        if signature == 'getSlot0(bytes32)': return (1 << 96, 0, 0, 100)
        if signature == 'getLiquidity(bytes32)': return (self.liquidity,)
        if signature == 'getTickBitmap(bytes32,int16)': return (self.words.get(args[1], 0),)
        if signature == 'getTickLiquidity(bytes32,int24)': return self.ticks[args[1]]
        if signature == 'getReserves()': return (10**24, 10**12, 0)
        if signature == 'extsload(bytes32[])':
            words = [self.slots[bytes(slot)] for slot in args[0]]
            self.bulk_words.extend(words)
            return ([self.words.get(word, 0).to_bytes(32, 'big') for word in words],)
        raise AssertionError(signature)


class MarketLiquidityTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self, ranges):
        rpc = LiquidityRpc(ranges)
        registry = PoolRegistry(SETTINGS, rpc=rpc)
        rpc.bind(registry.seed)
        registry.ensure_loaded = lambda **_: asyncio.sleep(0)
        sdk = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'), str(Path('src/uniswap-sdk/worker.ts').resolve())])
        quotes = MarketQuotes(SETTINGS, registry, sdk)
        self.addAsyncCleanup(quotes.close)
        self.addAsyncCleanup(registry.close)
        return quotes, registry, rpc

    async def expected(self, quotes, registry, rpc, mode, amount):
        state = await registry.snapshot(registry.seed, BLOCK)
        state['bitmapWords'] = [{'wordPosition': word, 'bitmap': str(rpc.words.get(word, 0))}
                                for word in range(-3466, 3466)]
        state['ticks'] = [{'index': tick, 'liquidityGross': str(gross), 'liquidityNet': str(net)}
                          for tick, (gross, net) in rpc.ticks.items()]
        return await quotes.sdk.request({'operation': 'simulateRoute', 'mode': mode, 'amount': str(amount),
            'pools': [state], 'route': {'branches': [{'amountIn': str(amount),
                'hops': [{'poolId': state['id'], 'zeroForOne': True}]}]}})

    def branches(self, registry, amount):
        return [{'amountIn': str(amount), 'hops': [{'pool': registry.seed, 'zeroForOne': True}]}]

    async def test_finite_purchase_uses_smaller_fully_filled_funding_without_timeout(self):
        quotes, registry, rpc = await self.fixture([(-60, 60, 10**18)])
        request = {'side': 'buy', 'mode': 'exact-in', 'counterToken': registry.seed['token0']['address'],
            'amount': str(10**18), 'adapter': '0x'+'7'*40, 'recipient': CORE,
            'deadline': '2000000000', 'slippageBps': 100}
        # Full provider search rebuilds a usable purchase within the budget.
        async with asyncio.timeout(3):
            result = await quotes._get(request, block=BLOCK)
        self.assertLessEqual(sum(name == 'getTickBitmap(bytes32,int16)' for name, _ in rpc.calls), 3)
        actual = int(result['totalInput'])
        self.assertGreater(actual, 0)
        self.assertLess(actual, int(request['amount']))
        self.assertEqual(result['plan']['amount'], request['amount'])
        self.assertEqual(result['params']['amount'], str(actual))
        self.assertEqual(result['inputMaximum'], str(actual))
        self.assertEqual(result['plan']['route']['inputAmount'], str(actual))
        self.assertEqual(result['fee']['amount'], str(quoted_fee(int(result['grossOutput']), 1000)))
        self.assertEqual(int(result['netOutput'])+int(result['fee']['amount']), int(result['grossOutput']))
        self.assertEqual(int(result['plan']['route']['limit']), int(result['outputMinimum'])+int(result['fee']['amount']))
        verified = await quotes.quote_market_branches(result['plan']['route']['branches'], 'exactIn', actual, BLOCK)
        self.assertTrue(verified['fullyFilled'] and verified['settled'])
        with self.assertRaises(QuoteFailure):
            await quotes.quote_market_branches(self.branches(registry, actual+1), 'exactIn', actual+1, BLOCK)
        self.assertTrue(rpc.bulk_words)
        self.assertEqual(min(rpc.bulk_words), -3466)
        with self.assertRaises(QuoteFailure) as failure:
            await quotes.quote_market_branches(self.branches(registry, 10**18), 'exactOut', 10**18, BLOCK)
        self.assertEqual(failure.exception.code, 'quote-insufficient-liquidity')
        # The runtime also shares this engine with Core conversion legs. Keep
        # their existing refundable original-input partial-fill behavior.
        core_leg = await quotes.quote_branches(self.branches(registry, 10**18), 'exactIn', 10**18, BLOCK)
        self.assertFalse(core_leg['fullyFilled'])

    async def test_universal_exact_input_keeps_gross_budget_when_legacy_purchase_resizes_funding(self):
        quotes, registry, _rpc = await self.fixture([(-60, 60, 10**18)])
        budget = 10**18
        legacy = await quotes._get(self.purchase(registry, budget), block=BLOCK)
        self.assertLess(int(legacy['inputMaximum']), budget)
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
            NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS='0x'+'2'*40,
            CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS='0x'+'7'*40)
        universal = UniversalQuotes(settings, quotes)
        request = {'intent': 0, 'inputs': [{'currency': registry.seed['token0']['address'], 'amount': str(budget)}],
            'outputCurrency': CORE, 'recipient': '0x'+'8'*40, 'deadline': '2000000000', 'slippageBps': 100}
        # The same finite-liquidity SDK result is retainable at the declared
        # universal conversion endpoint. It does not enter the legacy budget
        # resizer, and the compiled execution still acquires all original Q.
        value = await universal.candidate(request, 0, 'core-first', BLOCK, [], [], first=True)
        self.assertEqual(value['operation'], 'executeExactInput')
        self.assertEqual(value['settlementPolicy'], 'protocol-retained-input')
        self.assertEqual(value['quotedInput'], str(budget))
        self.assertEqual(value['inputMaximum'], str(budget))
        self.assertEqual(value['plan']['inputs'], request['inputs'])
        self.assertEqual(value['planDescription']['branches'][0]['amountIn'], str(budget))
        retained = value['estimatedRetainedInputCharges']
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]['currency'].lower(), request['inputs'][0]['currency'].lower())
        self.assertGreater(int(retained[0]['amount']), 0)
        self.assertGreater(int(value['quotedOutput']), 0)

    def purchase(self, registry, budget, token=None):
        return {'side': 'buy', 'mode': 'exact-in', 'counterToken': token or registry.seed['token0']['address'],
            'amount': str(budget), 'adapter': '0x'+'7'*40, 'recipient': CORE,
            'deadline': '2000000000', 'slippageBps': 100}

    def set_ranges(self, rpc, ranges):
        changed = LiquidityRpc(ranges)
        rpc.ranges, rpc.words, rpc.ticks, rpc.liquidity = changed.ranges, changed.words, changed.ticks, changed.liquidity

    async def test_multihop_budget_rebuilds_settled_usdc_purchase_and_full_budget_is_unchanged(self):
        quotes, registry, _rpc = await self.fixture([(-60, 60, 10**18)])
        counter = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
        connector = {'id': '0x'+'9'*40, 'address': '0x'+'9'*40, 'protocol': 'v2',
            'token0': deepcopy(registry.seed['token0']),
            'token1': {'address': counter, 'decimals': 6, 'chainId': 31338}, 'feePips': 3000}
        registry.inventory[connector['id']] = connector
        fixed = [{'amountIn': '1000000', 'hops': [{'pool': connector, 'zeroForOne': False},
                                               {'pool': registry.seed, 'zeroForOne': True}]}]
        async def candidates(request, block, evaluate, **_):
            await evaluate(0, resize_branches(fixed, int(request['targets'][0]['amount'])))
        quotes.search_candidates = candidates
        request = self.purchase(registry, 1000000, counter)
        result = await quotes._get(request, block=BLOCK)
        actual = int(result['params']['amount'])
        self.assertGreater(actual, 0)
        self.assertLess(actual, 1000000)
        self.assertEqual(result['totalInput'], str(actual))
        self.assertEqual(result['plan']['amount'], '1000000')
        self.assertEqual(sum(int(branch['amountIn']) for branch in result['plan']['route']['branches']), actual)
        verified = await quotes.quote_market_branches(result['plan']['route']['branches'], 'exactIn', actual, BLOCK)
        self.assertTrue(verified['fullyFilled'] and verified['settled'])
        small = await quotes._get(self.purchase(registry, 1000, counter), block=BLOCK)
        self.assertEqual(small['totalInput'], '1000')
        self.assertEqual(small['params']['amount'], '1000')

    async def test_capacity_search_crosses_v2_minimum_input_rounding(self):
        quotes, registry, rpc = await self.fixture([(-60, 60, 1000)])
        mid = {'address': '0x'+'8'*40, 'decimals': 18, 'chainId': 31338}
        counter = {'address': '0x'+'9'*40, 'decimals': 18, 'chainId': 31338}
        first = {'id': '0x'+'a'*40, 'address': '0x'+'a'*40, 'protocol': 'v2',
            'token0': mid, 'token1': counter, 'feePips': 3000}
        second = {'id': '0x'+'b'*40, 'address': '0x'+'b'*40, 'protocol': 'v2',
            'token0': deepcopy(registry.seed['token0']), 'token1': mid, 'feePips': 3000}
        registry.inventory.update({first['id']: first, second['id']: second})
        original = rpc.read_function
        async def reserves(address, signature, inputs, args, outputs, block):
            if signature == 'getReserves()':
                return (1000000, 100000000, 0) if address.lower() == first['address'] else (5000000, 1000000, 0)
            return await original(address, signature, inputs, args, outputs, block)
        rpc.read_function = reserves
        fixed = [{'amountIn': '201', 'hops': [{'pool': first, 'zeroForOne': False},
            {'pool': second, 'zeroForOne': False}, {'pool': registry.seed, 'zeroForOne': True}]}]
        async def candidates(request, block, evaluate, **_):
            await evaluate(0, resize_branches(fixed, int(request['targets'][0]['amount'])))
        quotes.search_candidates = candidates
        # The first binary midpoint has zero output, yet the upper part of the
        # interval contains a fully executable route with positive net output.
        with self.assertRaises(SdkInputTooSmall) as small:
            await quotes.quote_market_branches(resize_branches(fixed, 100), 'exactIn', 100, BLOCK)
        self.assertEqual(public_quote_error(small.exception)['code'], 'quote-unavailable')
        for funding in (101, 200):
            raw = await quotes.quote_market_branches(resize_branches(fixed, funding), 'exactIn', funding, BLOCK)
            self.assertTrue(raw['fullyFilled'] and raw['settled'])
            self.assertEqual(raw['amountOut'], '2')
        with self.assertRaises(QuoteFailure):
            await quotes.quote_market_branches(fixed, 'exactIn', 201, BLOCK)
        result = await quotes._get(self.purchase(registry, 201, counter['address']), block=BLOCK)
        self.assertEqual(result['plan']['amount'], '201')
        self.assertEqual(result['params']['amount'], '200')
        self.assertEqual(result['totalInput'], '200')
        self.assertEqual(result['inputMaximum'], '200')
        self.assertEqual(result['grossOutput'], '2')
        self.assertEqual(result['netOutput'], '1')

    async def test_capacity_search_preserves_unrelated_probe_errors(self):
        expected = OSError('required state read failed')
        async def unavailable(_amount):
            raise expected
        with self.assertRaises(OSError) as raised:
            await maximum_filled_input(201, {'amountIn': '201'}, unavailable)
        self.assertIs(raised.exception, expected)

    async def test_verified_capacity_reuse_and_same_header_distant_liquidity_change(self):
        quotes, registry, rpc = await self.fixture([(-60, 60, 10**18)])
        calls, original = [], quotes.sdk.request
        async def counted(payload, **kwargs):
            calls.append(payload['amount'])
            return await original(payload, **kwargs)
        quotes.sdk.request = counted
        request = self.purchase(registry, 10**18)
        first = await quotes._get(request, block=BLOCK)
        first_calls = len(calls)
        calls.clear()
        second = await quotes._get(request, block=BLOCK)
        self.assertEqual(second['params']['amount'], first['params']['amount'])
        self.assertLess(len(calls), first_calls)
        # Add a distant range without changing current tick or active liquidity.
        self.set_ranges(rpc, [(-60, 60, 10**18), (-6144, -6000, 10**18)])
        changed = await quotes._get(request, block=BLOCK)
        self.assertGreater(int(changed['params']['amount']), int(first['params']['amount']))
        self.assertEqual(rpc.liquidity, 10**18)

    async def test_retained_purchase_never_increases_funding_and_smaller_capacity_invalidates(self):
        quotes, registry, rpc = await self.fixture([(-60, 60, 10**18)])
        request = self.purchase(registry, 10**18)
        first = await quotes._get(request, block=BLOCK)
        retained = {**request, 'retainedPlan': first['plan']}
        self.set_ranges(rpc, [(-60, 60, 2*10**18)])
        improved = await quotes._get(retained, block=BLOCK)
        self.assertEqual(improved['params']['amount'], first['params']['amount'])
        self.assertEqual(improved['plan']['amount'], request['amount'])
        self.set_ranges(rpc, [(-60, 60, 10**18//2)])
        frames = []
        async def emit(frame): frames.append(frame)
        reduced = await quotes._get(retained, emit, block=BLOCK)
        self.assertTrue(any(frame['type'] == 'invalidated' for frame in frames))
        self.assertLess(int(reduced['params']['amount']), int(first['params']['amount']))
        self.assertEqual(reduced['plan']['amount'], request['amount'])

    async def test_multihop_countertoken_partial_fill_has_market_liquidity_error(self):
        quotes, registry, _rpc = await self.fixture([(-60, 60, 10**18)])
        connector = {'id': '0x'+'9'*40, 'address': '0x'+'9'*40, 'protocol': 'v2',
            'token0': deepcopy(registry.seed['token0']),
            'token1': {'address': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', 'decimals': 6, 'chainId': 31338},
            'feePips': 3000}
        branches = [{'amountIn': '1000000', 'hops': [
            {'pool': connector, 'zeroForOne': False}, {'pool': registry.seed, 'zeroForOne': True}]}]
        raw = await quotes.quote_sdk_branches(branches, 'exactIn', 1000000, BLOCK)
        self.assertFalse(raw['fullyFilled'])
        self.assertFalse(raw['settled'])
        self.assertTrue(any(not residual['originalInput'] for residual in raw['residuals']))
        # The shared Core conversion path keeps its original exception, message
        # and public error; only Market classifies the known partial-fill cause.
        with self.assertRaises(InvalidPreview) as core_error:
            await quotes.quote_branches(branches, 'exactIn', 1000000, BLOCK)
        self.assertIs(type(core_error.exception), InvalidPreview)
        self.assertEqual(str(core_error.exception), 'Unsettled current-operation intermediate currency.')
        self.assertEqual(public_quote_error(core_error.exception)['code'], 'quote-unavailable')
        with self.assertRaises(QuoteFailure) as market_error:
            await quotes.quote_market_branches(branches, 'exactIn', 1000000, BLOCK)
        self.assertEqual(market_error.exception.code, 'quote-insufficient-liquidity')
        # A fully filled USDC route preserves all SDK terms and settlement.
        valid = deepcopy(branches)
        valid[0]['amountIn'] = '1000'
        core_valid = await quotes.quote_branches(valid, 'exactIn', 1000, BLOCK)
        market_valid = await quotes.quote_market_branches(valid, 'exactIn', 1000, BLOCK)
        self.assertTrue(market_valid['fullyFilled'])
        self.assertTrue(market_valid['settled'])
        self.assertEqual(market_valid, core_valid)

    async def test_fully_filled_but_unsettled_route_keeps_ordinary_error(self):
        quotes, registry, _rpc = await self.fixture([(-60, 60, 10**18)])
        async def unsettled(*_args, **_kwargs):
            return {'amountIn': '1000', 'amountOut': '999', 'fullyFilled': True, 'settled': False}
        quotes.quote_sdk_branches = unsettled
        for method in (quotes.quote_branches, quotes.quote_market_branches):
            with self.assertRaises(InvalidPreview) as failure:
                await method(self.branches(registry, 1000), 'exactIn', 1000, BLOCK)
            self.assertIs(type(failure.exception), InvalidPreview)
            self.assertEqual(public_quote_error(failure.exception)['code'], 'quote-unavailable')

    async def test_distant_funded_range_is_used_after_empty_gap_with_identical_sdk_terms(self):
        quotes, registry, rpc = await self.fixture([(-60, 60, 10**18), (-6144, -6000, 10**22)])
        expected = await self.expected(quotes, registry, rpc, 'exactIn', 10**18)
        observed = await quotes.quote_market_branches(self.branches(registry, 10**18), 'exactIn', 10**18, BLOCK)
        self.assertTrue(observed['fullyFilled'])
        self.assertEqual(observed['amountIn'], expected['amountIn'])
        self.assertEqual(observed['amountOut'], expected['amountOut'])
        self.assertEqual(observed['postState'], expected['postState'])
        self.assertTrue(rpc.bulk_words)
        self.assertTrue(any(name == 'getTickLiquidity(bytes32,int24)' and args[1] == -6000
                            for name, args in rpc.calls))

    async def test_small_quote_and_active_wide_range_never_bulk_fetch(self):
        for ranges, amount in (([(-60, 60, 10**18)], 1000000),
                               ([(-60000, 60000, 10**18)], 10**17)):
            quotes, registry, rpc = await self.fixture(ranges)
            expected = await self.expected(quotes, registry, rpc, 'exactIn', amount)
            observed = await quotes.quote_market_branches(self.branches(registry, amount), 'exactIn', amount, BLOCK)
            self.assertEqual(observed['amountOut'], expected['amountOut'])
            self.assertTrue(observed['fullyFilled'])
            self.assertEqual(rpc.bulk_words, [])
            self.assertFalse(any(name == 'extsload(bytes32[])' for name, _ in rpc.calls))

    async def test_failed_optional_bulk_attempt_is_not_repeated_within_request(self):
        quotes, registry, rpc = await self.fixture([(-60, 60, 10**18)])
        snapshot = registry.snapshot
        async def covered(pool, block):
            state = await snapshot(pool, block)
            state['bitmapWords'] = [{'wordPosition': word, 'bitmap': str(rpc.words.get(word, 0))}
                                    for word in range(-3466, 3466) if word not in (-2, -3)]
            state['ticks'] = [{'index': tick, 'liquidityGross': str(gross), 'liquidityNet': str(net)}
                              for tick, (gross, net) in rpc.ticks.items()]
            return state
        registry.snapshot = covered
        attempts = 0
        async def unavailable(*_):
            nonlocal attempts
            attempts += 1
            raise OSError('Optional bulk transport is unavailable')
        with patch('cybergold_candidate.uniswap_state.read_tick_bitmap_words', unavailable):
            # Multiple candidates and successive missing words retain ordinary
            # required reads, without retrying a failed advisory bulk fetch.
            async with tick_prefetch_scope():
                for _ in range(2):
                    with self.assertRaises(QuoteFailure):
                        await quotes.quote_market_branches(self.branches(registry, 10**18), 'exactIn', 10**18, BLOCK)
            self.assertEqual(attempts, 1)
            async with tick_prefetch_scope():
                with self.assertRaises(QuoteFailure):
                    await quotes.quote_market_branches(self.branches(registry, 10**18), 'exactIn', 10**18, BLOCK)
            self.assertEqual(attempts, 2, 'The next request must retry normally after supplier recovery')
        requested = [args[1] for name, args in rpc.calls if name == 'getTickBitmap(bytes32,int16)']
        self.assertIn(-2, requested)
        self.assertIn(-3, requested)

    async def test_cancelling_bulk_acquisition_does_not_poison_next_request(self):
        quotes, registry, _rpc = await self.fixture([(-60, 60, 10**18)])
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def suspended(*_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch('cybergold_candidate.uniswap_state.read_tick_bitmap_words', suspended):
            task = asyncio.create_task(quotes.quote_market_branches(
                self.branches(registry, 10**18), 'exactIn', 10**18, BLOCK))
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cancelled.is_set())
        small = await quotes.quote_market_branches(self.branches(registry, 1000000), 'exactIn', 1000000, BLOCK)
        self.assertTrue(small['fullyFilled'])
        with self.assertRaises(QuoteFailure) as failure:
            await quotes.quote_market_branches(self.branches(registry, 10**18), 'exactIn', 10**18, BLOCK)
        self.assertEqual(failure.exception.code, 'quote-insufficient-liquidity')


if __name__ == '__main__': unittest.main()
