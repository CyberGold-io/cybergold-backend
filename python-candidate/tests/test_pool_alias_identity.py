"""Seed/catalog aliases reuse canonical coverage without sharing SDK post-state."""
import asyncio
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.uniswap_routes import v3_branches
from cybergold_candidate.uniswap_state import PoolRegistry
from test_route_quote_engine import A, B, C, BLOCK, Rpc


class AliasRpc(Rpc):
    def __init__(self):
        super().__init__()
        self.words = Counter()
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.block_word = None

    async def read_function(self, address, signature, inputs, args, outputs, block):
        if signature == 'tickBitmap(int16)':
            word = args[0]
            self.words[word] += 1
            if word == self.block_word:
                self.started.set()
                await self.release.wait()
            return ({-1: 1 << 56, 0: 1 << 200}.get(word, 0),)
        return await super().read_function(address, signature, inputs, args, outputs, block)

    async def close(self):
        pass


class MemoryStore:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.saved = []

    async def load(self, namespace):
        return deepcopy(self.rows) if namespace == 'observation' else {}

    async def save(self, namespace, identity, value):
        self.saved.append((namespace, identity, deepcopy(value)))


class PoolAliasIdentityTests(unittest.IsolatedAsyncioTestCase):
    def registry(self, *, store=None, chain=1):
        rpc = AliasRpc()
        registry = PoolRegistry(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID=str(chain),
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A), rpc=rpc, store=store)
        self.addAsyncCleanup(registry.close)
        return registry, rpc

    def branches(self, amount=1_000_000):
        return v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', amount, 1)

    async def test_real_sdk_seed_then_catalog_alias_reuses_words_and_keeps_private_post_state(self):
        store = MemoryStore()
        registry, rpc = self.registry(store=store)
        engine = RouteQuoteEngine(SimpleNamespace(), registry)
        self.addAsyncCleanup(engine.close)
        amount = 1_000_000_000
        branches = self.branches(amount)
        seed_id = branches[0]['hops'][0]['pool']['id']
        first_private, first_canonical = {}, {}
        payloads, request_sdk = [], engine.sdk.request
        async def capture(payload, on_state=None):
            payloads.append(deepcopy(payload))
            return await request_sdk(payload, on_state=on_state)
        engine.sdk.request = capture
        first = await engine.quote_sdk_branches(branches, 'exactIn', amount, BLOCK,
            candidate=first_private, canonical=first_canonical)
        self.assertTrue(rpc.words)
        acquired_words, getter_count = rpc.words.copy(), len(rpc.calls)
        self.assertEqual(set(registry.observed), {C.lower()})
        self.assertEqual(registry.observed[C]['sqrtRatioX96'], str(1 << 96))
        self.assertNotEqual(first_private[seed_id]['sqrtRatioX96'], first_canonical[seed_id]['sqrtRatioX96'])

        # The worker/catalog can now supply the physical address as its ID.
        discovered = deepcopy(first_canonical[seed_id])
        discovered['id'] = C
        registry.inventory[C] = discovered
        second_private, second_canonical = {}, {}
        second = await engine.quote_sdk_branches(branches, 'exactIn', amount, BLOCK,
            candidate=second_private, canonical=second_canonical)
        self.assertEqual((first['amountIn'], first['amountOut']), (second['amountIn'], second['amountOut']))
        self.assertEqual(rpc.words, acquired_words)
        self.assertEqual(len(rpc.calls), getter_count)
        self.assertEqual(set(second_canonical), {C})
        self.assertEqual(registry.observed[C]['sqrtRatioX96'], str(1 << 96))
        self.assertEqual(first_canonical[seed_id]['sqrtRatioX96'], str(1 << 96))
        self.assertEqual(second_canonical[C]['sqrtRatioX96'], str(1 << 96))

        # Enrichment can also happen between two conversions in one plan.
        # Continue from its prior physical post-state, never canonical again.
        post_ratio = first_private[seed_id]['sqrtRatioX96']
        continued = await engine.quote_sdk_branches(branches, 'exactIn', amount, BLOCK,
            candidate=first_private, canonical=first_canonical)
        self.assertEqual(payloads[-1]['pools'][0]['sqrtRatioX96'], post_ratio)
        self.assertLess(int(continued['amountOut']), int(first['amountOut']))
        self.assertEqual(set(first_private), {C})
        self.assertNotEqual(first_private[C]['sqrtRatioX96'], post_ratio)
        self.assertEqual({state['sqrtRatioX96'] for state in first_canonical.values()}, {str(1 << 96)})
        self.assertEqual(registry.observed[C]['sqrtRatioX96'], str(1 << 96))
        self.assertEqual(rpc.words, acquired_words)
        await asyncio.gather(*tuple(registry.background))
        observations = [(identity, value) for namespace, identity, value in store.saved if namespace == 'observation']
        self.assertTrue(observations)
        self.assertEqual({identity for identity, _ in observations}, {C})
        self.assertEqual({value['id'] for _, value in observations}, {C})

    async def test_concurrent_alias_tick_fills_share_reads_and_return_each_sdk_id(self):
        registry, rpc = self.registry()
        pool = self.branches()[0]['hops'][0]['pool']
        seed = await registry.snapshot(pool, BLOCK)
        address = {**deepcopy(seed), 'id': C}
        rpc.block_word = 3
        left = asyncio.create_task(registry.extend_ticks(seed,
            [{'poolId': seed['id'], 'wordPositions': [3], 'ticks': []}], BLOCK))
        await asyncio.wait_for(rpc.started.wait(), 1)
        right = asyncio.create_task(registry.extend_ticks(address,
            [{'poolId': address['id'], 'wordPositions': [3], 'ticks': []}], BLOCK))
        async def joined():
            while not any(entry.users == 2 for entry in registry.pending.pending.values()):
                await asyncio.sleep(0)
        await asyncio.wait_for(joined(), 1)
        rpc.release.set()
        first, second = await asyncio.gather(left, right)
        self.assertEqual((first['id'], second['id']), (seed['id'], C))
        self.assertEqual(rpc.words[3], 1)
        self.assertEqual(set(registry.observed), {C})
        first['bitmapWords'][0]['bitmap'] = 'changed-by-subscriber'
        self.assertEqual(second['bitmapWords'][0]['bitmap'], '0')
        self.assertEqual(registry.observed[C]['bitmapWords'][0]['bitmap'], '0')

    async def test_reload_legacy_alias_records_merges_into_one_address_observation(self):
        registry, _ = self.registry()
        source = await registry.snapshot(self.branches()[0]['hops'][0]['pool'], BLOCK)
        first = {**deepcopy(source), 'bitmapWords': [{'wordPosition': 1, 'bitmap': '1'}]}
        second = {**deepcopy(source), 'id': C,
            'bitmapWords': [{'wordPosition': 2, 'bitmap': '2'}]}
        registry.observed.clear()
        registry.store = MemoryStore({first['id']: first, C: second})
        await registry._load()
        self.assertEqual(set(registry.observed), {C})
        self.assertEqual([row['wordPosition'] for row in registry.observed[C]['bitmapWords']], [1, 2])
        self.assertIs(registry.observation(first), registry.observation(second))

    async def test_v4_poolkey_and_manager_remain_distinct(self):
        registry, _ = self.registry()
        state = {**deepcopy(registry.seed), 'context': {'blockNumber': str(BLOCK['number']),
            'blockHash': BLOCK['hash']}, 'bitmapWords': [], 'ticks': []}
        registry.publish_observation(state)
        self.assertIsNotNone(registry.observation(state))
        changed = {**deepcopy(state), 'poolManager': C}
        self.assertIsNone(registry.observation(changed))
        changed = {**deepcopy(state), 'feePips': state['feePips']+1}
        self.assertIsNone(registry.observation(changed))
        self.assertEqual(set(registry.observed), {state['id']})

    async def test_sandbox_reacquires_alias_at_the_same_header(self):
        registry, rpc = self.registry(chain=31338)
        source = await registry.snapshot(self.branches()[0]['hops'][0]['pool'], BLOCK)
        before = len(rpc.calls)
        await registry.snapshot({**source, 'id': C}, BLOCK)
        self.assertGreater(len(rpc.calls), before)
        self.assertEqual(registry.observed, {})


if __name__ == '__main__':
    unittest.main()
