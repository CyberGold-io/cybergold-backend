"""Directional batch transport, coverage, fallback and subscriber ownership."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from web3 import Web3

from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.uniswap_state import PoolRegistry
from cybergold_candidate.uniswap_v3 import empty_traversal_words
from test_snapshot_copy import _bitmap_snapshot, _BITMAP_BLOCK, _BITMAP_CORE


class Rpc:
    def __init__(self, error=None):
        self.error = error
        self.calls = []
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()
        self.bad_subcalls = False

    async def read_function(self, address, signature, inputs, args, outputs, block):
        assert block == _BITMAP_BLOCK
        self.calls.append((signature, deepcopy(args)))
        if signature == 'tickBitmap(int16)':
            return [0]
        assert signature == 'aggregate3((address,bool,bytes)[])'
        self.started.set()
        await self.release.wait()
        if self.error:
            raise self.error
        return [[(False, b'') if self.bad_subcalls and index == 0 else
                 (True, b'bad') if self.bad_subcalls and index == 1 else
                 (True, Web3().codec.encode(['uint256'], [int.from_bytes(raw[-2:], 'big')]))
                 for index, (_address, _allow, raw) in enumerate(args[0])]]

    async def close(self):
        pass


class BitmapBatchTests(unittest.IsolatedAsyncioTestCase):
    def registry(self, rpc):
        registry = PoolRegistry(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=_BITMAP_CORE), rpc=rpc)
        self.addAsyncCleanup(registry.close)
        return registry

    def request(self, word=1, direction=False):
        return [{'wordPositions': [word], 'ticks': [], 'zeroForOne': direction, 'activeLiquidity': '0'}]

    def test_direction_word_extrema_and_observed_empty_requirement(self):
        source = _bitmap_snapshot('v3')
        for direction, word in [(False, 1), (True, -1)]:
            words = {word: {'bitmap': '0'}}
            expected = list(range(2, 33)) if not direction else list(range(-2, -33, -1))
            self.assertEqual(empty_traversal_words(source, self.request(word, direction), words), expected)
            words[word]['bitmap'] = '1'
            self.assertEqual(empty_traversal_words(source, self.request(word, direction), words), [])
        for direction, word in [(False, (887272 // 10) >> 8), (True, (-887272 // 10) >> 8)]:
            self.assertEqual(empty_traversal_words(source, self.request(word, direction), {word: {'bitmap': '0'}}), [])

    async def test_batch_coverage_and_repeated_demand_reuses_observed_words(self):
        rpc = Rpc(); registry = self.registry(rpc); source = _bitmap_snapshot('v3')
        value = await registry.extend_ticks(source, self.request(), _BITMAP_BLOCK)
        self.assertEqual(len(value['bitmapWords']), 32)
        self.assertEqual(len(rpc.calls), 2)
        await registry.extend_ticks(value, [{'wordPositions': [12], 'ticks': []}], _BITMAP_BLOCK)
        self.assertEqual(len(rpc.calls), 2)
        self.assertEqual(source['bitmapWords'], [])

    async def test_optional_failure_keeps_demanded_word_and_disproof_propagates(self):
        for error in [OSError('optional transport'), SnapshotChanged('changed')]:
            rpc = Rpc(error); registry = self.registry(rpc)
            if isinstance(error, SnapshotChanged):
                with self.assertRaises(SnapshotChanged):
                    await registry.extend_ticks(_bitmap_snapshot('v3'), self.request(), _BITMAP_BLOCK)
            else:
                value = await registry.extend_ticks(_bitmap_snapshot('v3'), self.request(), _BITMAP_BLOCK)
                self.assertEqual(value['bitmapWords'], [{'wordPosition': 1, 'bitmap': '0'}])

    async def test_failed_and_malformed_subcalls_remain_ordinary_demands(self):
        rpc = Rpc(); rpc.bad_subcalls = True; registry = self.registry(rpc)
        value = await registry.extend_ticks(_bitmap_snapshot('v3'), self.request(), _BITMAP_BLOCK)
        self.assertEqual(len(value['bitmapWords']), 30)
        filled = await registry.extend_ticks(value, [{'wordPositions': [2, 3], 'ticks': []}], _BITMAP_BLOCK)
        self.assertEqual(len(filled['bitmapWords']), 32)

    async def test_cancelled_subscriber_does_not_cancel_other_owner(self):
        rpc = Rpc(); rpc.release.clear(); registry = self.registry(rpc)
        source = _bitmap_snapshot('v3')
        first = asyncio.create_task(registry.extend_ticks(source, self.request(), _BITMAP_BLOCK))
        await rpc.started.wait()
        second = asyncio.create_task(registry.extend_ticks(source, self.request(), _BITMAP_BLOCK))
        while not any(entry.users == 2 for entry in registry.pending.pending.values()):
            await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        rpc.release.set()
        self.assertEqual(len((await second)['bitmapWords']), 32)
        self.assertEqual(len(rpc.calls), 2)


if __name__ == '__main__':
    unittest.main()
