"""V3/V4 empty traversal acquires upcoming state without changing SDK terms."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from web3 import Web3

from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.uniswap_state import PoolRegistry
from cybergold_candidate.uniswap_v3 import empty_traversal_words
from cybergold_candidate.uniswap_v4 import tick_prefetch_scope


BLOCK = {'number': 123, 'hash': '0x' + 'ab' * 32}
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338',
                          NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='0x' + '2' * 40)
MIN_ROOT, MAX_ROOT = 4295128740, 1461446703485210103287273052203988822378723970341


class BitmapRpc:
    """Contract getters and the two real batching ABIs over identical tick data."""
    chain_id, pool_manager, state_view = 31338, '0x' + '4' * 40, '0x' + '5' * 40

    def __init__(self, protocol, tick=0, root=1 << 96, ranges=((-60, 60, 10**18),)):
        self.w3, self.protocol, self.tick, self.root = Web3(), protocol, tick, root
        self.words, self.ticks, self.calls, self.batches = {}, {}, [], []
        self.bulk_error, self.bulk_error_at, self.fail_far_words = None, None, None
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.suspend_bulk, self.cancelled = False, False
        self.liquidity = sum(amount for lower, upper, amount in ranges if lower <= tick < upper)
        for lower, upper, amount in ranges:
            for index, delta in ((lower, amount), (upper, -amount)):
                self.ticks[index] = (amount, delta)
                word, bit = index >> 8, index & 255
                self.words[word] = self.words.get(word, 0) | 1 << bit
        self.pool = {'id': '0x' + '7' * (64 if protocol == 'v4' else 40), 'protocol': protocol,
            'token0': {'address': '0x' + '1' * 40, 'chainId': 31338, 'decimals': 18},
            'token1': {'address': '0x' + '2' * 40, 'chainId': 31338, 'decimals': 18},
            'feePips': 100, 'tickSpacing': 1, 'hooks': '0x' + '0' * 40}
        if protocol == 'v4':
            self.pool['poolManager'] = self.pool_manager
            slot = int.from_bytes(Web3.keccak(self.w3.codec.encode(
                ['bytes32', 'uint256'], [bytes.fromhex(self.pool['id'][2:]), 6])), 'big')
            self.storage_words = {bytes(Web3.keccak(self.w3.codec.encode(['int256', 'uint256'], [word, slot + 5]))): word
                                  for word in range(-3466, 3466)}
        else:
            self.pool['address'] = self.pool['id']

    async def close(self): pass

    async def batch(self, words):
        self.batches.append(list(words))
        if self.suspend_bulk:
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.bulk_error is not None:
            raise self.bulk_error
        if self.bulk_error_at == len(self.batches):
            raise OSError('A later optional window is unavailable')
        if self.fail_far_words is not None and any(abs(word) > self.fail_far_words for word in words):
            raise OSError('An irrelevant far bitmap word is unavailable')
        return [self.words.get(word, 0) for word in words]

    async def read_function(self, _address, signature, _inputs, args, _outputs, block):
        assert block == BLOCK
        self.calls.append((signature, deepcopy(args)))
        if signature == 'getSlot0(bytes32)': return self.root, self.tick, 0, 100
        if signature == 'getLiquidity(bytes32)': return self.liquidity,
        if signature == 'slot0()': return self.root, self.tick, 0, 0, 0, 0, True
        if signature == 'liquidity()': return self.liquidity,
        if signature in ('getTickBitmap(bytes32,int16)', 'tickBitmap(int16)'):
            return self.words.get(args[-1], 0),
        if signature == 'getTickLiquidity(bytes32,int24)': return self.ticks[args[-1]]
        if signature == 'ticks(int24)': return *self.ticks[args[-1]], 0, 0, 0, 0, 0, True
        if signature == 'extsload(bytes32[])':
            values = await self.batch([self.storage_words[bytes(slot)] for slot in args[0]])
            return [value.to_bytes(32, 'big') for value in values],
        if signature == 'aggregate3((address,bool,bytes)[])':
            words = [self.w3.codec.decode(['int16'], data[4:])[0] for _target, _allow, data in args[0]]
            values = await self.batch(words)
            return [(True, self.w3.codec.encode(['uint256'], [value])) for value in values],
        raise AssertionError(signature)


class DirectionalBitmapTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self, protocol, **kwargs):
        rpc = BitmapRpc(protocol, **kwargs)
        registry = PoolRegistry(SETTINGS, rpc=rpc)
        sdk = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'), str(Path('src/uniswap-sdk/worker.ts').resolve())])
        engine = RouteQuoteEngine(SETTINGS, registry, sdk)
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.close)
        return rpc, registry, engine

    async def quote(self, rpc, engine, *, direction=True, amount=10**6, canonical=None):
        return await engine.quote_sdk_branches([{'amountIn': str(amount),
            'hops': [{'pool': rpc.pool, 'zeroForOne': direction}]}], 'exactIn', amount, BLOCK, canonical=canonical)

    async def reference(self, rpc, registry, engine, *, direction=True, amount=10**6):
        normalized = engine.enrich_branches([{'amountIn': str(amount),
            'hops': [{'pool': rpc.pool, 'zeroForOne': direction}]}])
        state = await registry.snapshot(normalized[0]['hops'][0]['pool'], BLOCK)
        state['bitmapWords'] = [{'wordPosition': word, 'bitmap': str(rpc.words.get(word, 0))}
                                for word in range(-3466, 3466)]
        state['ticks'] = [{'index': index, 'liquidityGross': str(gross), 'liquidityNet': str(net)}
                          for index, (gross, net) in rpc.ticks.items()]
        return await engine.sdk.request({'operation': 'simulateRoute', 'mode': 'exactIn', 'amount': str(amount),
            'pools': [state], 'route': {'branches': [{'amountIn': str(amount),
                'hops': [{'poolId': state['id'], 'zeroForOne': direction}]}]}})

    async def test_extreme_empty_start_returns_to_funded_range_in_both_protocols_and_directions(self):
        for protocol in ('v3', 'v4'):
            for direction, tick, root in ((True, 887271, MAX_ROOT), (False, -887272, MIN_ROOT)):
                with self.subTest(protocol=protocol, direction=direction):
                    rpc, registry, engine = await self.fixture(protocol, tick=tick, root=root)
                    expected = await self.reference(rpc, registry, engine, direction=direction)
                    actual = await self.quote(rpc, engine, direction=direction)
                    self.assertEqual(actual, expected)
                    self.assertTrue(actual['fullyFilled'])
                    self.assertEqual(actual['amountIn'], '1000000')
                    self.assertGreater(int(actual['amountOut']), 0)
                    self.assertGreater(len(rpc.batches), 1, 'Distant funded liquidity must remain discoverable across successive windows')
                    first = rpc.batches[0]
                    self.assertLess(len(first), 256)
                    self.assertEqual(first, sorted(first, reverse=direction))
                    self.assertTrue(all(word > 3000 if direction else word < -3000 for word in first),
                                    'The first window must start near the exhausted boundary, not the far price limit')

    async def test_nearby_funded_region_never_waits_for_unrelated_far_coverage(self):
        first_windows = []
        for protocol in ('v3', 'v4'):
            rpc, registry, engine = await self.fixture(protocol, ranges=((-6144, -6000, 10**18),))
            rpc.fail_far_words = 64
            expected = await self.reference(rpc, registry, engine)
            actual = await self.quote(rpc, engine)
            self.assertEqual(actual, expected)
            self.assertTrue(actual['fullyFilled'])
            self.assertTrue(rpc.batches)
            self.assertTrue(all(abs(word) <= 64 for batch in rpc.batches for word in batch))
            first_windows.append(rpc.batches[0])
        self.assertEqual(first_windows[0], first_windows[1], 'V3 and V4 use the same upcoming-word policy')

    async def test_active_liquidity_small_swap_never_prefetches_bitmap_or_unvisited_ticks(self):
        for protocol in ('v3', 'v4'):
            rpc, registry, engine = await self.fixture(protocol)
            expected = await self.reference(rpc, registry, engine)
            rpc.calls.clear()
            actual = await self.quote(rpc, engine)
            self.assertEqual(actual, expected)
            self.assertEqual(rpc.batches, [])
            self.assertFalse(any(signature in ('getTickLiquidity(bytes32,int24)', 'ticks(int24)')
                                 for signature, _args in rpc.calls))

    async def test_failed_optional_supplier_is_not_retried_within_request_and_recovers_next_request(self):
        for protocol in ('v3', 'v4'):
            rpc, registry, engine = await self.fixture(protocol, ranges=((-20000, -19900, 10**18),))
            expected = await self.reference(rpc, registry, engine)
            rpc.bulk_error = OSError('Optional bitmap supplier unavailable')
            async with tick_prefetch_scope():
                first = await self.quote(rpc, engine)
                self.assertEqual(first, expected)
                first_attempts = len(rpc.batches)
                self.assertEqual(first_attempts, 1,
                                 'A failed optional supplier is not retried at every successive empty word')
                demanded = {args[-1] for signature, args in rpc.calls
                            if signature in ('getTickBitmap(bytes32,int16)', 'tickBitmap(int16)')}
                self.assertIn(-2, demanded)
                self.assertIn(-19900 >> 8, demanded,
                              'Required reads must still reach the distant funded range after optional failure')
                self.assertEqual(await self.quote(rpc, engine), expected)
                self.assertEqual(len(rpc.batches), first_attempts,
                                 'Another candidate in the owning request retains supplier failure suppression')
            rpc.bulk_error = None
            before = len(rpc.batches)
            second = await self.quote(rpc, engine)
            self.assertEqual(second, expected)
            self.assertGreater(len(rpc.batches), before, 'A later request must be able to recover normally')

    async def test_cancelling_a_window_drains_it_and_does_not_poison_the_next_quote(self):
        for protocol in ('v3', 'v4'):
            rpc, registry, engine = await self.fixture(protocol, ranges=((-6144, -6000, 10**18),))
            expected = await self.reference(rpc, registry, engine)
            rpc.suspend_bulk = True
            task = asyncio.create_task(self.quote(rpc, engine))
            await asyncio.wait_for(rpc.entered.wait(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(rpc.cancelled)
            self.assertEqual(registry.pending.pending, {})
            rpc.suspend_bulk = False
            self.assertEqual(await self.quote(rpc, engine), expected)

    async def test_later_optional_failure_keeps_preceding_successful_coverage(self):
        for protocol in ('v3', 'v4'):
            rpc, registry, engine = await self.fixture(protocol, ranges=((-50000, -49000, 10**18),))
            expected = await self.reference(rpc, registry, engine)
            rpc.bulk_error_at = 2
            canonical = {}
            actual = await self.quote(rpc, engine, canonical=canonical)
            self.assertEqual(actual, expected)
            self.assertEqual(len(rpc.batches), 2,
                             'A later failed supplier keeps prior successful windows without further advisory retries')
            initial = set(rpc.batches[0])
            demanded = {args[-1] for signature, args in rpc.calls
                        if signature in ('getTickBitmap(bytes32,int16)', 'tickBitmap(int16)')}
            self.assertTrue(initial)
            self.assertTrue(initial.isdisjoint(demanded), 'Successful early windows are not reacquired after a later failure')
            observed = next(iter(canonical.values()))
            self.assertTrue(initial.issubset({row['wordPosition'] for row in observed['bitmapWords']}))

    async def test_optional_acquisition_canonical_disproof_is_never_a_fallback(self):
        for protocol in ('v3', 'v4'):
            rpc, _registry, engine = await self.fixture(protocol, ranges=((-6144, -6000, 10**18),))
            error = SnapshotChanged('Pinned acquisition canonicality changed')
            rpc.bulk_error = error
            with self.assertRaises(SnapshotChanged) as raised:
                await self.quote(rpc, engine)
            self.assertIs(raised.exception, error)


class AdaptiveWindowTests(unittest.TestCase):
    def upcoming(self, direction, empty_behind, *, barrier=None, active='0'):
        step = -1 if direction else 1
        demand = step * (empty_behind + 2)
        snapshot = {'tick': 0, 'tickSpacing': 1}
        words = {demand - step * offset: {'bitmap': '0'} for offset in range(empty_behind + 1)}
        if barrier is not None:
            words[demand - step * barrier]['bitmap'] = '1'
        return empty_traversal_words(snapshot, [{'wordPositions': [demand],
            'zeroForOne': direction, 'activeLiquidity': active}], words)

    def test_observed_empty_run_including_demand_grows_bounded_window_for_both_directions(self):
        for direction in (True, False):
            step = -1 if direction else 1
            for empty, size in ((0, 31), (30, 31), (31, 63), (32, 63), (94, 63), (95, 127), (96, 127), (1000, 127)):
                with self.subTest(direction=direction, empty=empty):
                    demand = step * (empty + 2)
                    actual = self.upcoming(direction, empty)
                    self.assertEqual(actual, [demand + step * offset for offset in range(1, size + 1)])

    def test_initialized_word_or_unknown_active_liquidity_prevents_long_gap_growth(self):
        for direction in (True, False):
            for barrier in (1, 17, 31):
                self.assertEqual(len(self.upcoming(direction, 1000, barrier=barrier)), 31)
            self.assertEqual(self.upcoming(direction, 1000, active='1'), [])
            self.assertEqual(self.upcoming(direction, 1000, active=None), [])

    def test_cached_empty_words_behind_start_do_not_expand_a_nearby_quote(self):
        for direction in (True, False):
            step = -1 if direction else 1
            demand = step
            snapshot = {'tick': 0, 'tickSpacing': 1}
            # Another candidate can have observed many empty words on the
            # other side of this starting price. They do not show that this
            # quote has crossed a long empty gap in its own direction.
            words = {demand - step * offset: {'bitmap': '0'} for offset in range(101)}
            upcoming = empty_traversal_words(snapshot, [{'wordPositions': [demand],
                'zeroForOne': direction, 'activeLiquidity': '0'}], words)
            self.assertEqual(upcoming, [demand + step * offset for offset in range(1, 32)])

    def test_unknown_word_breaks_empty_evidence_and_windows_clip_at_price_limits(self):
        for direction in (True, False):
            step = -1 if direction else 1
            snapshot = {'tick': 0, 'tickSpacing': 1}
            demand = step * 200
            words = {demand - step * offset: {'bitmap': '0'} for offset in range(100)}
            words.pop(demand - step * 2)
            request = {'wordPositions': [demand], 'zeroForOne': direction, 'activeLiquidity': '0'}
            self.assertEqual(len(empty_traversal_words(snapshot, [request], words)), 31)
            limit = (-887272 >> 8) if direction else (887272 >> 8)
            request['wordPositions'] = [limit - step * 2]
            words = {word: {'bitmap': '0'} for word in range(min(0, limit), max(0, limit) + 1)}
            # Only the two still-unread words towards the bound remain valid.
            words.pop(limit)
            words.pop(limit - step)
            self.assertEqual(empty_traversal_words(snapshot, [request], words), [limit - step, limit])


if __name__ == '__main__': unittest.main()
