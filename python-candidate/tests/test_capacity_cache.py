"""Capacity memoization reuses facts without weakening canonical-read freshness."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from web3 import AsyncWeb3

from cybergold_candidate import capacity_cache
from cybergold_candidate.capacity_cache import (
    VerifiedCapacityCache, capacity_key, core_capacity_facts, pool_capacity_facts,
)
from cybergold_candidate.issuance_capacity import exhausted_capacity_error, read_supply_capacity
from cybergold_candidate.shared_reads import SharedReads
from test_exhausted_issuance_capacity import BLOCK, Provider, SETTINGS


class CapacityRpc:
    def __init__(self, chain=31338):
        self.chain_id, self.provider = chain, Provider()
        self.w3, self.pool_reads = AsyncWeb3(self.provider), SharedReads()
        self.batches, self.fail = 0, False

    async def pool_batch(self, calls, block, counts):
        keys = [(self.chain_id, block['hash'], address, data) for address, data in calls]
        by_key = dict(zip(keys, calls, strict=True))
        async def produce(missing):
            self.batches += 1
            if self.fail:
                raise RuntimeError('Fixture transport failed')
            return [await self.provider.make_request('eth_call', [
                {'to': by_key[key][0], 'data': by_key[key][1]},
                {'blockHash': block['hash'], 'requireCanonical': True}]) for key in missing]
        return await self.pool_reads.many(keys, produce, retain=self.chain_id == 1, counts=counts)


def market_key(snapshot, *, direction=True, fee=100, chain=31338, block=BLOCK):
    return capacity_key('market-buy', chain=chain, block=block,
        identity={'pool': snapshot['id'], 'zeroForOne': direction, 'fee': fee},
        facts=pool_capacity_facts(snapshot))


class CapacityCacheTests(unittest.IsolatedAsyncioTestCase):
    def test_core_math_reuses_same_verified_values_and_returns_independent_results(self):
        cache = VerifiedCapacityCache()
        with patch.object(capacity_cache, '_core_capacity', cache), patch.object(
                cache, 'remember', wraps=cache.remember) as publish:
            first = core_capacity_facts((90, 100, 120), 10000, 10000)
            first['remainingGrossCapacity'] = 'mutated caller copy'
            self.assertEqual(core_capacity_facts((90, 100, 120), 10000, 10000)['remainingGrossCapacity'], '10')
            self.assertEqual(publish.call_count, 1)
            self.assertEqual(core_capacity_facts((80, 100, 120), 10000, 10000)['remainingGrossCapacity'], '20')
            self.assertEqual(core_capacity_facts((80, 110, 120), 10000, 10000)['remainingGrossCapacity'], '30')
            self.assertEqual(core_capacity_facts((80, 110, 90), 10000, 10000)['remainingGrossCapacity'], '10')
            core_capacity_facts((80, 110, 90), 20000, 10000)
            self.assertEqual(publish.call_count, 5)

    async def test_sandbox_completed_same_header_supply_and_cap_changes_are_fresh(self):
        rpc = CapacityRpc()
        self.addAsyncCleanup(rpc.pool_reads.close)
        first = await read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True)
        self.assertEqual(exhausted_capacity_error(first).code, 'issuance-cap-exceeded')
        rpc.provider.values['totalSupply'] = 240  # A redemption reopens mint capacity.
        current = await read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True)
        self.assertIsNone(exhausted_capacity_error(current))
        self.assertEqual(core_capacity_facts(current)['remainingGrossCapacity'], '10')
        rpc.provider.values['maxTotalSupply'] = 245
        current = await read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True)
        self.assertEqual(core_capacity_facts(current)['remainingGrossCapacity'], '5')
        rpc.provider.values['effectiveCygldSupplyCap'] = 240
        current = await read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True)
        self.assertEqual(exhausted_capacity_error(current).constraint['limitKind'], 'effective-supply-cap')
        self.assertEqual(rpc.batches, 4)
        self.assertEqual(len(rpc.provider.calls), 12)

    async def test_mainnet_reuses_only_the_same_block_identity(self):
        rpc = CapacityRpc(chain=1)
        self.addAsyncCleanup(rpc.pool_reads.close)
        first = await read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True)
        self.assertEqual(await read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True), first)
        self.assertEqual(rpc.batches, 1)
        rpc.provider.values['totalSupply'] = 240
        changed_block = {**BLOCK, 'hash': '0x' + 'c' * 64}
        next_values = await read_supply_capacity(rpc, SETTINGS, changed_block, shared=True)
        self.assertEqual(next_values[0], 240)
        self.assertEqual(rpc.batches, 2)

    async def test_failed_reads_never_turn_into_cached_exhaustion(self):
        rpc = CapacityRpc(chain=1)
        self.addAsyncCleanup(rpc.pool_reads.close)
        rpc.fail = True
        with self.assertRaises(RuntimeError):
            await read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True)
        self.assertEqual(rpc.pool_reads.completed, {})
        rpc.fail = False
        rpc.provider.values['totalSupply'] = 240
        current = await read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True)
        self.assertIsNone(exhausted_capacity_error(current))
        self.assertEqual(rpc.batches, 2)

    def test_pool_capacity_identity_changes_after_swaps_liquidity_or_fee_changes(self):
        snapshot = {'id': 'pool-1', 'protocol': 'v4', 'tick': -1, 'sqrtRatioX96': '7922',
            'liquidity': '100', 'lpFee': 100, 'protocolFee': 0,
            'bitmapWords': [{'wordPosition': -1, 'bitmap': '1'}, {'wordPosition': 0, 'bitmap': '2'}],
            'ticks': [{'index': -256, 'liquidityGross': '100', 'liquidityNet': '100'}],
            'context': {'observedAt': 'old'}, 'acquisition': {'observedAt': 'old'}}
        cache = VerifiedCapacityCache()
        original = market_key(snapshot)
        cache.remember(original, {'maximumInputRaw': '50'})
        same = deepcopy(snapshot)
        same['context']['observedAt'] = 'new'
        same['acquisition']['observedAt'] = 'new'
        same['bitmapWords'].reverse()
        self.assertEqual(cache.get(market_key(same)), {'maximumInputRaw': '50'})
        for field, value in (('tick', 1), ('sqrtRatioX96', '9000'), ('liquidity', '101'),
                             ('lpFee', 200), ('protocolFee', 100), ('id', 'pool-2')):
            changed = deepcopy(snapshot)
            changed[field] = value
            self.assertIsNone(cache.get(market_key(changed)), field)
        distant_liquidity = deepcopy(snapshot)
        distant_liquidity['bitmapWords'].append({'wordPosition': -25, 'bitmap': '4'})
        self.assertIsNone(cache.get(market_key(distant_liquidity)))
        changed_tick = deepcopy(snapshot)
        changed_tick['ticks'][0]['liquidityNet'] = '200'
        self.assertIsNone(cache.get(market_key(changed_tick)))
        self.assertIsNone(cache.get(market_key(snapshot, direction=False)))
        self.assertIsNone(cache.get(market_key(snapshot, fee=200)))
        self.assertIsNone(cache.get(market_key(snapshot, chain=1)))
        self.assertIsNone(cache.get(market_key(snapshot, block={**BLOCK, 'hash': '0x' + 'd' * 64})))

    def test_bounded_cache_owns_copies_and_does_not_cross_directions(self):
        cache = VerifiedCapacityCache(limit=2)
        source = {'maximumInputRaw': '100', 'terms': {'fee': 100}}
        cache.remember(('buy', True), source)
        source['terms']['fee'] = 200
        copy = cache.get(('buy', True))
        self.assertEqual(copy['terms']['fee'], 100)
        copy['terms']['fee'] = 300
        self.assertEqual(cache.get(('buy', True))['terms']['fee'], 100)
        self.assertIsNone(cache.get(('buy', False)))
        cache.remember(('buy', False), {'maximumInputRaw': '20'})
        cache.remember(('other-pool', True), {'maximumInputRaw': '30'})
        self.assertIsNone(cache.get(('buy', True)))
        cache.clear()
        self.assertEqual(cache.completed, {})

    async def test_cancelled_subscriber_preserves_shared_reads_and_last_subscriber_drains(self):
        class BlockingRpc(CapacityRpc):
            def __init__(self):
                super().__init__()
                self.started, self.release, self.joined = asyncio.Event(), asyncio.Event(), asyncio.Event()
                self.subscribers, self.cancelled = 0, 0

            async def pool_batch(self, calls, block, counts):
                self.subscribers += 1
                if self.subscribers == 2:
                    self.joined.set()
                keys = [(self.chain_id, block['hash'], address, data) for address, data in calls]
                async def produce(missing):
                    self.batches += 1
                    self.started.set()
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        self.cancelled += 1
                        raise
                    return [await self.provider.make_request('eth_call', [
                        {'to': address, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}])
                        for _, _, address, data in missing]
                return await self.pool_reads.many(keys, produce, retain=False, counts=counts)

        rpc = BlockingRpc()
        self.addAsyncCleanup(rpc.pool_reads.close)
        first = asyncio.create_task(read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True))
        await rpc.started.wait()
        second = asyncio.create_task(read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True))
        await rpc.joined.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertFalse(second.done())
        rpc.release.set()
        self.assertEqual(await second, (250, 250, 1000))
        self.assertEqual(rpc.batches, 1)
        self.assertEqual(rpc.cancelled, 0)
        rpc.release.clear()
        rpc.started.clear()
        final = asyncio.create_task(read_supply_capacity(rpc, SETTINGS, BLOCK, shared=True))
        await rpc.started.wait()
        final.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await final
        self.assertEqual(rpc.cancelled, 1)
        self.assertEqual(rpc.pool_reads.pending, {})


if __name__ == '__main__':
    unittest.main()
