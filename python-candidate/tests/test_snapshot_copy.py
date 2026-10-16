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


if __name__ == '__main__':
    unittest.main()
