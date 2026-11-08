"""Latest exploration reads never become retained canonical observations."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from web3 import Web3

from cybergold_candidate.rpc_block_context import LATEST_BLOCK, is_latest, rpc_block_parameter
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.uniswap_state import PoolRegistry, UniswapRpc, observation_storage_id


A, B, C = ('0x'+format(index, '040x') for index in (1, 2, 3))
PIN = {'number': 10, 'hash': '0x'+'ab'*32}


def pool(protocol='v3'):
    return {'id': '0x'+'12'*32 if protocol == 'v4' else B, 'address': B, 'protocol': protocol,
            'token0': {'address': A, 'decimals': 18, 'chainId': 1},
            'token1': {'address': C, 'decimals': 18, 'chainId': 1},
            'feePips': 500, 'tickSpacing': 10, 'hooks': '0x'+'00'*20, 'poolManager': C}


class Rpc:
    factory, state_view, pool_manager = C, C, C
    def __init__(self):
        self.calls, self.value, self.bitmap = [], 100, 2

    async def read_function(self, address, signature, types, args, outputs, block):
        self.calls.append((signature, deepcopy(args), deepcopy(block)))
        if signature == 'getReserves()':
            return self.value, self.value+1, 0
        if signature == 'slot0()':
            return 2**96, 0, 0, 0, 0, 0, True
        if signature.startswith('getSlot0('):
            return 2**96, 0, 0, 500
        if signature == 'liquidity()' or signature.startswith('getLiquidity('):
            return (self.value,)
        if signature.startswith(('tickBitmap(', 'getTickBitmap(')):
            return (self.bitmap,)
        if signature.startswith(('ticks(', 'getTickLiquidity(')):
            return (5, -3, 0, 0, 0, 0, 0, True) if signature.startswith('ticks(') else (5, -3)
        raise AssertionError(signature)

    async def close(self):
        pass


class LatestStateTests(unittest.IsolatedAsyncioTestCase):
    def registry(self):
        rpc = Rpc()
        store = SimpleNamespace(save=AsyncMock())
        registry = PoolRegistry(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A), rpc=rpc, store=store)
        self.addAsyncCleanup(registry.close)
        return registry, rpc, store

    def test_explicit_latest_parameter_does_not_change_pinned_parameters(self):
        self.assertTrue(is_latest(LATEST_BLOCK))
        self.assertEqual(rpc_block_parameter(LATEST_BLOCK), 'latest')
        self.assertFalse(is_latest(PIN))
        self.assertEqual(rpc_block_parameter(PIN), {'blockHash': PIN['hash'], 'requireCanonical': True})

    async def test_latest_snapshots_ignore_retained_values_and_never_publish_or_advance(self):
        for protocol in ('v2', 'v3', 'v4'):
            with self.subTest(protocol=protocol):
                registry, rpc, store = self.registry()
                identity = pool(protocol)
                stale = {**deepcopy(identity), 'reserve0': '777', 'liquidity': '777',
                    'sqrtRatioX96': str(2**96), 'tick': 0, 'ticks': [], 'bitmapWords': [],
                    'context': {'chainId': 1, 'blockNumber': '9', 'blockHash': '0x'+'cd'*32}}
                registry.observed[observation_storage_id(identity)] = deepcopy(stale)
                registry.advance = AsyncMock(side_effect=AssertionError('Latest cannot advance event history'))
                first = await registry.snapshot(identity, LATEST_BLOCK)
                rpc.value = 200
                second = await registry.snapshot(identity, LATEST_BLOCK)
                field = 'reserve0' if protocol == 'v2' else 'liquidity'
                self.assertEqual((first[field], second[field]), ('100', '200'))
                self.assertEqual(second['context'], {'chainId': 1, 'blockNumber': None,
                    'blockHash': None, 'blockTag': 'latest'})
                self.assertEqual(registry.observed[observation_storage_id(identity)], stale)
                registry.advance.assert_not_awaited()
                store.save.assert_not_called()
                self.assertNotIn(identity['id'], registry.inventory)

    async def test_pinned_snapshot_still_reuses_and_persists_its_canonical_observation(self):
        registry, rpc, store = self.registry()
        identity = pool()
        first = await registry.snapshot(identity, PIN)
        calls = len(rpc.calls)
        rpc.value = 200
        second = await registry.snapshot(identity, PIN)
        await asyncio.gather(*tuple(registry.background))
        self.assertEqual(first, second)
        self.assertEqual(second['liquidity'], '100')
        self.assertEqual(len(rpc.calls), calls)
        self.assertEqual(second['context'], {'chainId': 1, 'blockNumber': '10', 'blockHash': PIN['hash']})
        store.save.assert_awaited_once()

    async def test_latest_tick_fill_uses_passed_coverage_and_does_not_publish_or_borrow_observed_rows(self):
        registry, rpc, store = self.registry()
        identity = pool()
        snapshot = {**identity, 'sqrtRatioX96': str(2**96), 'tick': 0, 'liquidity': '100',
                    'bitmapWords': [{'wordPosition': 0, 'bitmap': '1'}], 'ticks': [],
                    'context': {'chainId': 1, 'blockNumber': None, 'blockHash': None, 'blockTag': 'latest'}}
        stale = {**deepcopy(snapshot), 'bitmapWords': [{'wordPosition': 1, 'bitmap': '999'}],
                 'ticks': [{'index': 120, 'liquidityGross': '999', 'liquidityNet': '999'}],
                 'context': {'chainId': 1, 'blockNumber': '10', 'blockHash': PIN['hash']}}
        registry.observed[identity['id']] = deepcopy(stale)
        requests = [{'poolId': identity['id'], 'wordPositions': [1], 'ticks': [120]}]
        first = await registry.extend_ticks(snapshot, requests, LATEST_BLOCK)
        rpc.bitmap = 3
        second = await registry.extend_ticks(snapshot, requests, LATEST_BLOCK)
        self.assertEqual(first['bitmapWords'], [{'wordPosition': 0, 'bitmap': '1'}, {'wordPosition': 1, 'bitmap': '2'}])
        self.assertEqual(second['bitmapWords'][1]['bitmap'], '3')
        self.assertEqual(first['ticks'], [{'index': 120, 'liquidityGross': '5', 'liquidityNet': '-3'}])
        self.assertEqual(snapshot['ticks'], [])
        self.assertEqual(registry.observed[identity['id']], stale)
        self.assertEqual(second['context'], snapshot['context'])
        store.save.assert_not_called()

    async def test_latest_identity_can_be_cached_without_a_fake_acquisition_anchor(self):
        registry, rpc, store = self.registry()
        identity = registry.acquire_pool(pool(), LATEST_BLOCK)
        await asyncio.gather(*tuple(registry.background))
        self.assertNotIn('acquisition', identity)
        self.assertEqual(store.save.call_args.args[0], 'inventory')
        self.assertNotIn('context', store.save.call_args.args[2])


class GetterProvider:
    def __init__(self):
        self.calls, self.value = [], 1
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()

    async def make_request(self, method, params):
        self.calls.append((method, deepcopy(params)))
        self.entered.set()
        await self.release.wait()
        return {'result': Web3.to_hex(Web3().codec.encode(['uint256'], [self.value]))}


class LatestGetterTests(unittest.IsolatedAsyncioTestCase):
    def rpc(self):
        provider = GetterProvider()
        rpc = object.__new__(UniswapRpc)
        rpc.chain_id, rpc.before_request, rpc.semaphore = 1, None, asyncio.Semaphore(8)
        rpc.reads = SharedReads()
        rpc.w3 = SimpleNamespace(codec=Web3().codec, provider=provider)
        self.addAsyncCleanup(rpc.reads.close)
        return rpc, provider

    async def test_latest_getter_uses_latest_and_never_reuses_completed_values(self):
        rpc, provider = self.rpc()
        self.assertEqual(await rpc.read_function(A, 'value()', [], [], ['uint256'], LATEST_BLOCK), (1,))
        provider.value = 2
        self.assertEqual(await rpc.read_function(A, 'value()', [], [], ['uint256'], LATEST_BLOCK), (2,))
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(all(method == 'eth_call' and params[1] == 'latest' for method, params in provider.calls))
        self.assertEqual(rpc.reads.completed, {})

    async def test_identical_latest_getters_still_coalesce_while_in_flight(self):
        rpc, provider = self.rpc()
        provider.release.clear()
        first = asyncio.create_task(rpc.read_function(A, 'value()', [], [], ['uint256'], LATEST_BLOCK))
        await provider.entered.wait()
        second = asyncio.create_task(rpc.read_function(A, 'value()', [], [], ['uint256'], LATEST_BLOCK))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(len(provider.calls), 1)
        provider.release.set()
        self.assertEqual(await asyncio.gather(first, second), [(1,), (1,)])
        self.assertEqual(rpc.reads.completed, {})

    async def test_pinned_getter_still_retains_completed_typed_values(self):
        rpc, provider = self.rpc()
        await rpc.read_function(A, 'value()', [], [], ['uint256'], PIN)
        provider.value = 2
        self.assertEqual(await rpc.read_function(A, 'value()', [], [], ['uint256'], PIN), (1,))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][1][1], {'blockHash': PIN['hash'], 'requireCanonical': True})


if __name__ == '__main__':
    unittest.main()
