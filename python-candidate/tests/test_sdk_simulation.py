"""Real arithmetic sharing preserves private state, demand and pricing ownership."""
import asyncio
from copy import deepcopy
import unittest

from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.route_work_slots import engine_work
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
from cybergold_candidate.sdk_worker import SdkInputTooSmall
from cybergold_candidate.search_observations import search_observation_scope
from quoter_fixture import Registry, synthetic_pool
from test_universal_quote import WETH, PAXG, settings


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


class SdkSimulationTests(unittest.IsolatedAsyncioTestCase):
    def engine(self, protocol='v3'):
        pool = synthetic_pool(WETH, PAXG, 8501, protocol)
        registry = Registry([pool])
        engine = RouteQuoteEngine(settings(), registry)
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.pending.close)
        return pool, registry, engine

    def branch(self, pool, amount=1000):
        return [{'amountIn': str(amount), 'hops': [{'pool': pool,
            'zeroForOne': pool['token0']['address'].lower() == WETH.lower()}]}]

    def initial(self, pool):
        return {**deepcopy(pool), 'ticks': [], 'bitmapWords': []}

    async def quote(self, engine, pool, *, amount=1000, candidate=None, canonical=None,
                    branches=None, mode='exactIn'):
        async with engine_work(engine.semaphore):
            return await engine.quote_sdk_branches(branches or self.branch(pool, amount), mode, amount,
                LATEST_BLOCK, candidate=candidate if candidate is not None else {},
                canonical=canonical if canonical is not None else {pool['id']: self.initial(pool)})

    async def test_v3_followers_receive_demanded_coverage_and_owned_result_copies(self):
        pool, registry, engine = self.engine()
        demands = []
        async def extend(snapshot, requests, block):
            demands.append(deepcopy(requests))
            return deepcopy(pool)
        registry.extend_ticks = extend
        banks = [{}, {}]
        canonicals = [{pool['id']: self.initial(pool)} for _ in banks]
        async with search_observation_scope():
            first = await self.quote(engine, pool, candidate=banks[0], canonical=canonicals[0])
            second = await self.quote(engine, pool, candidate=banks[1], canonical=canonicals[1])
            self.assertEqual(engine.sdk.sequence, 1)
            self.assertEqual(first, second)
            self.assertEqual((first['amountIn'], first['amountOut']), ('1000', '996'))
            self.assertEqual(banks[0], banks[1])
            self.assertEqual(canonicals[0], canonicals[1])
            self.assertTrue(banks[1][pool['id']]['bitmapWords'])
            self.assertEqual(len(demands), 2)
            first['postState'][0]['liquidity'] = '0'
            banks[0][pool['id']]['bitmapWords'][0]['bitmap'] = 'changed privately'
            self.assertNotEqual(first, second)
            self.assertNotEqual(banks[0], banks[1])
            third = await self.quote(engine, pool)
            self.assertEqual(third, second)
            self.assertEqual(engine.sdk.sequence, 1)
        self.assertEqual((registry.heads, registry.verifications, engine.semaphore._value), (0, 0, 8))

    async def test_full_payload_separates_private_state_mode_amount_direction_and_allocation(self):
        pool, registry, engine = self.engine('v2')
        base = {pool['id']: deepcopy(pool)}
        async with search_observation_scope():
            first = await self.quote(engine, pool, amount=10007, canonical=deepcopy(base))
            self.assertEqual(await self.quote(engine, pool, amount=10007, canonical=deepcopy(base)), first)
            self.assertEqual(engine.sdk.sequence, 1)
            changed = deepcopy(base)
            changed[pool['id']]['reserve0'] = str(int(pool['reserve0']) * 2)
            current = await self.quote(engine, pool, amount=10007, candidate=changed, canonical=deepcopy(base))
            self.assertNotEqual(current['amountOut'], first['amountOut'])
            await self.quote(engine, pool, amount=10008, canonical=deepcopy(base))
            await self.quote(engine, pool, amount=10007, mode='exactOut', canonical=deepcopy(base))
            reversed_branch = self.branch(pool, 10007)
            reversed_branch[0]['hops'][0]['zeroForOne'] = not reversed_branch[0]['hops'][0]['zeroForOne']
            await self.quote(engine, pool, amount=10007, branches=reversed_branch, canonical=deepcopy(base))
            allocated = await self.quote(engine, pool, amount=10007, branches=self.branch(pool, 5000),
                                         canonical=deepcopy(base))
            self.assertEqual(allocated['amountIn'], '5000')
            self.assertEqual(engine.sdk.sequence, 6)
        async with search_observation_scope():
            self.assertEqual(await self.quote(engine, pool, amount=10007, canonical=deepcopy(base)), first)
        self.assertEqual(engine.sdk.sequence, 7)
        await self.quote(engine, pool, amount=10007, canonical=deepcopy(base))
        await self.quote(engine, pool, amount=10007, canonical=deepcopy(base))
        self.assertEqual(engine.sdk.sequence, 9)
        self.assertEqual((registry.heads, registry.verifications, engine.semaphore._value), (0, 0, 8))

    async def test_required_read_error_and_too_small_arithmetic_remain_retryable(self):
        pool, registry, engine = self.engine()
        calls = 0
        expected = OSError('ordinary state acquisition failure')
        async def extend(snapshot, requests, block):
            nonlocal calls
            calls += 1
            if calls == 1: raise expected
            return deepcopy(pool)
        registry.extend_ticks = extend
        async with search_observation_scope():
            with self.assertRaises(OSError) as raised: await self.quote(engine, pool)
            self.assertIs(raised.exception, expected)
            result = await self.quote(engine, pool)
            self.assertEqual(result['amountOut'], '996')
            self.assertEqual(engine.sdk.sequence, 2)
            self.assertEqual(await self.quote(engine, pool), result)
            self.assertEqual(engine.sdk.sequence, 2)
            pair, _, pair_engine = self.engine('v2')
            for _ in range(2):
                with self.assertRaises(SdkInputTooSmall): await self.quote(pair_engine, pair, amount=1)
            self.assertEqual(pair_engine.sdk.sequence, 2)
        self.assertEqual(engine.semaphore._value, 8)

    async def test_cancelled_initial_subscriber_preserves_survivor_and_its_v3_bank(self):
        pool, registry, engine = self.engine()
        entered, release = asyncio.Event(), asyncio.Event()
        async def extend(snapshot, requests, block):
            entered.set(); await release.wait(); return deepcopy(pool)
        registry.extend_ticks = extend
        bank = {}
        async with search_observation_scope() as observations:
            first = asyncio.create_task(self.quote(engine, pool))
            second = None
            try:
                await asyncio.wait_for(entered.wait(), 3)
                process = engine.sdk.process
                second = asyncio.create_task(self.quote(engine, pool, candidate=bank))
                await until(lambda: any(entry.users == 2 for entry in observations.reads.pending.values()))
                first.cancel()
                with self.assertRaises(asyncio.CancelledError): await first
                self.assertIs(engine.sdk.process, process)
                release.set()
                result = await asyncio.wait_for(second, 3)
                self.assertEqual(result['amountOut'], '996')
                self.assertTrue(bank[pool['id']]['bitmapWords'])
                self.assertEqual(engine.sdk.sequence, 1)
            finally:
                release.set()
                for task in (first, second):
                    if task is not None and not task.done(): task.cancel()
                await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)
        self.assertEqual(observations.reads.pending, {})
        self.assertEqual(observations.reads.groups, {})
        self.assertEqual(engine.semaphore._value, 8)

    async def test_eight_subscribers_park_their_permits_while_shared_producer_owns_required_read(self):
        pool, registry, engine = self.engine()
        entered, release, unrelated = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def extend(snapshot, requests, block):
            entered.set(); await release.wait(); return deepcopy(pool)
        registry.extend_ticks = extend
        async def independent():
            async with engine_work(engine.semaphore): unrelated.set()
        async with search_observation_scope() as observations:
            first = asyncio.create_task(self.quote(engine, pool))
            followers, probe = [], None
            try:
                await asyncio.wait_for(entered.wait(), 3)
                followers = [asyncio.create_task(self.quote(engine, pool)) for _ in range(7)]
                await until(lambda: any(entry.users == 8 for entry in observations.reads.pending.values()))
                probe = asyncio.create_task(independent())
                await asyncio.wait_for(unrelated.wait(), 1)
                self.assertFalse(release.is_set())
                release.set()
                results = await asyncio.wait_for(asyncio.gather(first, *followers), 3)
                await probe
                self.assertEqual([value['amountOut'] for value in results], ['996'] * 8)
                self.assertEqual(engine.sdk.sequence, 1)
            finally:
                release.set()
                for task in (first, *followers, probe):
                    if task is not None and not task.done(): task.cancel()
                await asyncio.gather(*(task for task in (first, *followers, probe) if task is not None),
                                     return_exceptions=True)
        self.assertEqual(engine.semaphore._value, 8)

    async def test_last_subscriber_cancel_drains_shared_state_work_and_retries_normally(self):
        pool, registry, engine = self.engine()
        entered, drained = asyncio.Event(), asyncio.Event()
        calls = 0
        async def extend(snapshot, requests, block):
            nonlocal calls
            calls += 1
            if calls == 1:
                try:
                    entered.set(); await asyncio.Event().wait()
                finally:
                    drained.set()
            return deepcopy(pool)
        registry.extend_ticks = extend
        async with search_observation_scope() as observations:
            reader = asyncio.create_task(self.quote(engine, pool))
            await asyncio.wait_for(entered.wait(), 3)
            reader.cancel()
            with self.assertRaises(asyncio.CancelledError): await reader
            self.assertTrue(drained.is_set())
            self.assertEqual(observations.reads.pending, {})
            self.assertEqual(observations.reads.groups, {})
            self.assertEqual(engine.semaphore._value, 8)
            self.assertEqual((await self.quote(engine, pool))['amountOut'], '996')
            self.assertEqual(engine.sdk.sequence, 2)


if __name__ == '__main__':
    unittest.main()
