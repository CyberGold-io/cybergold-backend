"""Canonical snapshot copy ownership controls."""
import asyncio
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from cybergold_candidate.uniswap_state import PoolRegistry, copy_pool_snapshot
from test_uniswap_market import A, BLOCK, POOL, TickFillRpc


class SnapshotCopyTests(unittest.TestCase):
    def test_absence_and_nested_metadata_remain_independent(self):
        source = {'nested': {'unknown': [{'value': 'original'}]}}
        copied = copy_pool_snapshot(source)
        self.assertEqual(copied, deepcopy(source))
        self.assertEqual(list(copied), list(source))
        self.assertNotIn('ticks', copied)
        self.assertNotIn('bitmapWords', copied)
        copied['nested']['unknown'][0]['value'] = 'changed'
        self.assertEqual(source['nested']['unknown'][0]['value'], 'original')

    def test_all_scalar_coverage_fields_and_container_independence(self):
        source = {'bitmapWords': [{'wordPosition': -1, 'bitmap': '1', 'unknownScalar': 'keep'}],
                  'ticks': [{'index': -256, 'liquidityGross': '2', 'liquidityNet': '-2', 'extra': 4}]}
        copied = copy_pool_snapshot(source)
        self.assertEqual(copied, deepcopy(source))
        self.assertEqual(list(copied), list(source))
        self.assertIsNot(source['ticks'], copied['ticks'])
        self.assertIsNot(source['ticks'][0], copied['ticks'][0])
        copied['ticks'][0]['extra'] = 9
        copied['bitmapWords'][0]['unknownScalar'] = 'changed'
        self.assertEqual(source['ticks'][0]['extra'], 4)
        self.assertEqual(source['bitmapWords'][0]['unknownScalar'], 'keep')


class SnapshotPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_input_shared_consumers_observed_and_persistence_are_independent(self):
        rpc = TickFillRpc()
        registry = PoolRegistry(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A), rpc=rpc)
        self.addAsyncCleanup(registry.close)
        entered, release = asyncio.Event(), asyncio.Event()
        saved = []
        class Store:
            async def save(self, namespace, identity, value):
                saved.append(value)
                entered.set()
                await release.wait()
        registry.store = Store()
        source = {**deepcopy(POOL), 'protocol': 'v3', 'tickSpacing': 10,
            'sqrtRatioX96': str(1 << 96), 'tick': 1, 'liquidity': '1000',
            'context': {'chainId': 1, 'blockNumber': str(BLOCK['number']), 'blockHash': BLOCK['hash']},
            'nestedUnknown': {'rows': [{'value': 'original'}]},
            'bitmapWords': [{'wordPosition': 9, 'bitmap': '1'}],
            'ticks': [{'index': 23040, 'liquidityGross': '7', 'liquidityNet': '3'}]}
        requests = [{'poolId': source['id'], 'wordPositions': [0], 'ticks': []}]
        first = asyncio.create_task(registry.extend_ticks(source, requests, BLOCK))
        await asyncio.wait_for(rpc.started.wait(), 1)
        second = asyncio.create_task(registry.extend_ticks(deepcopy(source), requests, BLOCK))
        async def joined():
            while not any(entry.users == 2 for entry in registry.pending.pending.values()):
                await asyncio.sleep(0)
        await asyncio.wait_for(joined(), 1)
        source['nestedUnknown']['rows'][0]['value'] = 'input-mutated'
        source['ticks'][0]['liquidityGross'] = 'input-mutated'
        rpc.release.set()
        one, two = await asyncio.gather(first, second)
        await asyncio.wait_for(entered.wait(), 1)
        observed = registry.observed[source['id']]
        records = [one, two, observed, *saved]
        self.assertGreaterEqual(len(records), 4)
        for record in records:
            self.assertEqual(record['nestedUnknown']['rows'][0]['value'], 'original')
            self.assertEqual(next(row for row in record['ticks'] if row['index'] == 23040)['liquidityGross'], '7')
        for index, record in enumerate(records):
            record['nestedUnknown']['rows'][0]['value'] = str(index)
            next(row for row in record['ticks'] if row['index'] == 23040)['liquidityGross'] = str(index)
        self.assertEqual([record['nestedUnknown']['rows'][0]['value'] for record in records],
                         [str(index) for index in range(len(records))])
        self.assertEqual([next(row for row in record['ticks'] if row['index'] == 23040)['liquidityGross']
                          for record in records], [str(index) for index in range(len(records))])
        release.set()
        await asyncio.gather(*tuple(registry.background))
        self.assertEqual(rpc.calls['tickBitmap(int16)'], 1)
        self.assertEqual(registry.pending.pending, {})


from cybergold_candidate.recovery_rpc import SnapshotChanged

_BITMAP_BLOCK = {'number': 101, 'hash': '0x' + 'a' * 64}
_BITMAP_ADDRESS = '0x' + '3' * 40
_BITMAP_CORE = '0x' + '1' * 40
_BITMAP_TOKEN = '0x' + '2' * 40

def _bitmap_expected_indices(word, bitmap, spacing=10):
    return {((word << 8) + bit) * spacing for bit in range(256) if bitmap & 1 << bit}

def _bitmap_snapshot(protocol, words=(), ticks=()):
    return {'id': _BITMAP_ADDRESS if protocol == 'v3' else '0x' + '4' * 64, 'protocol': protocol, 'address': _BITMAP_ADDRESS, 'tickSpacing': 10, 'token0': {'address': _BITMAP_CORE, 'decimals': 18}, 'token1': {'address': _BITMAP_TOKEN, 'decimals': 18}, 'feePips': 500, 'sqrtRatioX96': str(1 << 96), 'liquidity': '1000', 'tick': 1, 'context': {'chainId': 31338, 'blockNumber': '101', 'blockHash': _BITMAP_BLOCK['hash']}, 'unknown': {'nested': ['preserve']}, 'bitmapWords': [{'wordPosition': word, 'bitmap': str(bits)} for (word, bits) in words], 'ticks': [{'index': tick, 'liquidityGross': '999', 'liquidityNet': '-7'} for tick in ticks]}

class _BitmapExpansionRpc:
    state_view = '0x' + '5' * 40

    def __init__(self, words, *, block_phase=None, error=None):
        self.words = words
        self.calls = []
        self.block_phase = block_phase
        self.error = error
        (self.started, self.release) = (asyncio.Event(), asyncio.Event())
        self.active = self.cancelled = 0

    async def read_function(self, _address, signature, _inputs, args, _outputs, block):
        phase = 'bitmap' if signature.startswith(('tickBitmap(', 'getTickBitmap(')) else 'tick'
        index = args[-1]
        self.calls.append((phase, index, signature))
        self.active += 1
        try:
            self.assert_block(block)
            if phase == self.block_phase:
                self.started.set()
                await self.release.wait()
            await asyncio.sleep(0)
            if phase == 'tick' and self.error is not None:
                raise self.error
            if phase == 'bitmap':
                return (self.words[index],)
            return (1000 + abs(index), -index - 1, 0, 0, 0, 0, 0, True)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1

    def assert_block(self, block):
        assert block == _BITMAP_BLOCK

    async def close(self):
        pass

async def _bitmap_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)

class BitmapExpansionTests(unittest.IsolatedAsyncioTestCase):

    def registry(self, rpc):
        result = PoolRegistry(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=_BITMAP_CORE), rpc=rpc)
        self.addAsyncCleanup(result.close)
        return result

    def assert_drained(self, registry, rpc):
        self.assertEqual(registry.pending.pending, {})
        self.assertEqual(registry.pending.completed, {})
        self.assertEqual(registry.observed, {})
        self.assertEqual(rpc.active, 0)

    async def test_v3_v4_eager_empty_sparse_dense_and_bounded_integer_semantics(self):
        patterns = [0, 1, 1 << 255, (1 << 256) - 1, sum((1 << bit for bit in range(0, 256, 2))), -1, (1 << 300) + (1 << 255) + 1, -(1 << 300)]
        for protocol in ('v3', 'v4'):
            for bitmap in patterns:
                with self.subTest(protocol=protocol, bitmap=bitmap):
                    rpc = _BitmapExpansionRpc({-1: bitmap})
                    registry = self.registry(rpc)
                    source = _bitmap_snapshot(protocol)
                    original = deepcopy(source)
                    expected = sorted(_bitmap_expected_indices(-1, bitmap))
                    result = await registry.extend_ticks(source, [{'poolId': source['id'], 'wordPositions': [-1], 'ticks': []}], _BITMAP_BLOCK)
                    self.assertEqual([row[1] for row in rpc.calls if row[0] == 'bitmap'], [-1])
                    self.assertEqual([row[1] for row in rpc.calls if row[0] == 'tick'], expected)
                    self.assertEqual(result['bitmapWords'], [{'wordPosition': -1, 'bitmap': str(bitmap)}])
                    self.assertEqual(result['ticks'], [{'index': tick, 'liquidityGross': str(1000 + abs(tick)), 'liquidityNet': str(-tick - 1)} for tick in expected])
                    self.assertEqual(source, original)
                    self.assert_drained(registry, rpc)

    async def test_known_coverage_explicit_ticks_duplicate_words_and_mutable_copies(self):
        for protocol in ('v3', 'v4'):
            rpc = _BitmapExpansionRpc({1: 1 << 2})
            registry = self.registry(rpc)
            source = _bitmap_snapshot(protocol, [(-1, 0), (0, 5)], [0])
            original = deepcopy(source)
            requests = [{'poolId': source['id'], 'wordPositions': [-1, 0, 1, 1], 'ticks': [13, 13]}]
            requested = deepcopy(requests)
            result = await registry.extend_ticks(source, requests, _BITMAP_BLOCK)
            self.assertEqual([row[1] for row in rpc.calls if row[0] == 'bitmap'], [1])
            self.assertEqual([row[1] for row in rpc.calls if row[0] == 'tick'], [13, 20, 2580])
            self.assertEqual([row['index'] for row in result['ticks']], [0, 13, 20, 2580])
            self.assertEqual(result['ticks'][0], original['ticks'][0])
            self.assertEqual(source, original)
            self.assertEqual(requests, requested)
            saved = deepcopy(result)
            result['unknown']['nested'].append('changed')
            result['bitmapWords'][0]['bitmap'] = 'changed'
            result['ticks'][0]['liquidityNet'] = 'changed'
            self.assertEqual(source, original)
            self.assert_drained(registry, rpc)

    async def test_shared_subscriber_cancellation_preserves_eager_foreign_read(self):
        for protocol in ('v3', 'v4'):
            rpc = _BitmapExpansionRpc({0: 3}, block_phase='tick')
            registry = self.registry(rpc)
            source = _bitmap_snapshot(protocol)
            requests = [{'poolId': source['id'], 'wordPositions': [0], 'ticks': []}]
            first = asyncio.create_task(registry.extend_ticks(source, requests, _BITMAP_BLOCK))
            await rpc.started.wait()
            second = asyncio.create_task(registry.extend_ticks(deepcopy(source), requests, _BITMAP_BLOCK))
            await _bitmap_until(lambda : any((entry.users == 2 for entry in registry.pending.pending.values())))
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            self.assertFalse(second.done())
            self.assertEqual(rpc.cancelled, 0)
            rpc.release.set()
            result = await second
            self.assertEqual([row[1] for row in rpc.calls if row[0] == 'tick'], [0, 10])
            self.assertEqual([row['index'] for row in result['ticks']], [0, 10])
            self.assert_drained(registry, rpc)

    async def test_error_identity_and_last_subscriber_drain(self):
        for protocol in ('v3', 'v4'):
            for error in (ValueError('ordinary'), SnapshotChanged('disproved')):
                rpc = _BitmapExpansionRpc({0: 3}, error=error)
                registry = self.registry(rpc)
                source = _bitmap_snapshot(protocol)
                with self.assertRaises(type(error)) as raised:
                    await registry.extend_ticks(source, [{'poolId': source['id'], 'wordPositions': [0], 'ticks': []}], _BITMAP_BLOCK)
                self.assertIs(raised.exception, error)
                self.assert_drained(registry, rpc)
            for phase in ('bitmap', 'tick'):
                rpc = _BitmapExpansionRpc({0: 3}, block_phase=phase)
                registry = self.registry(rpc)
                source = _bitmap_snapshot(protocol)
                task = asyncio.create_task(registry.extend_ticks(source, [{'poolId': source['id'], 'wordPositions': [0], 'ticks': []}], _BITMAP_BLOCK))
                await rpc.started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assert_drained(registry, rpc)
                self.assertGreater(rpc.cancelled, 0)

if __name__ == '__main__':
    unittest.main()
