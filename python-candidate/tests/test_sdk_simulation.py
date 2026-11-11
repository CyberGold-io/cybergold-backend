"""Real arithmetic sharing preserves private state, demand and pricing ownership."""
import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.route_work_slots import engine_work
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
from cybergold_candidate.sdk_worker import SdkInputTooSmall, SdkWorkerError, MissingPoolState
from cybergold_candidate.sdk_simulation import simulate_sdk
from cybergold_candidate.search_observations import search_observation_scope
from quoter_fixture import Registry, synthetic_pool
from test_universal_quote import WETH, PAXG, OTHER, settings


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

    async def test_required_read_error_remains_retryable(self):
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
        self.assertEqual(engine.semaphore._value, 8)

    async def test_typed_no_quote_is_reused_only_for_same_full_payload_and_search(self):
        pool, registry, engine = self.engine('v2')
        errors = []
        async with search_observation_scope() as observations:
            for _ in range(4):
                bank = {}
                with self.assertRaises(SdkInputTooSmall) as raised:
                    await self.quote(engine, pool, amount=1, candidate=bank)
                errors.append(raised.exception)
                self.assertEqual(bank, {})
            self.assertEqual(engine.sdk.sequence, 1, 'Four identical mathematical failures need one SDK calculation')
            self.assertEqual(len({id(error) for error in errors}), 4, 'Subscribers receive fresh typed errors')
            stored = next(iter(observations.reads.completed.values()))['value']
            json.dumps(stored)  # A retained marker must not own an exception or its traceback frames.
            self.assertEqual(stored['demands'], [])
            changed_amount = await self.quote(engine, pool, amount=2)
            self.assertEqual(changed_amount['amountOut'], '1')
            changed = deepcopy(pool)
            output_reserve = 'reserve1' if pool['token0']['address'].lower() == WETH.lower() else 'reserve0'
            changed[output_reserve] = str(int(changed[output_reserve])*2)
            changed_state = await self.quote(engine, pool, amount=1, candidate={pool['id']: changed})
            self.assertEqual(changed_state['amountOut'], '1')
            self.assertEqual(engine.sdk.sequence, 3, 'Changed amount and private state each require fresh arithmetic')
        async with search_observation_scope():
            with self.assertRaises(SdkInputTooSmall): await self.quote(engine, pool, amount=1)
        self.assertEqual(engine.sdk.sequence, 4)
        for _ in range(2):
            with self.assertRaises(SdkInputTooSmall): await self.quote(engine, pool, amount=1)
        self.assertEqual(engine.sdk.sequence, 6, 'No cross-search or unscoped negative reuse')
        self.assertEqual((registry.heads, registry.verifications, engine.semaphore._value), (0, 0, 8))

    def mixed_dust(self, pool, registry):
        pair = synthetic_pool(PAXG, OTHER, 8502, 'v2')
        registry.inventory[pair['id']] = deepcopy(pair)
        return pair, [{'amountIn': '3', 'hops': [self.branch(pool, 3)[0]['hops'][0],
            {'pool': pair, 'zeroForOne': pair['token0']['address'].lower() == PAXG.lower()}]}]

    async def test_typed_failure_replays_required_coverage_without_committing_private_post_state(self):
        pool, registry, engine = self.engine()
        pair, branches = self.mixed_dust(pool, registry)
        demands = []
        async def extend(_snapshot, requests, _block):
            demands.append(deepcopy(requests))
            return deepcopy(pool)
        registry.extend_ticks = extend
        originals = deepcopy((pool, pair, branches))
        canonicals, errors = [], []
        async with search_observation_scope() as observations:
            for _ in range(4):
                canonical = {pool['id']: self.initial(pool), pair['id']: deepcopy(pair)}
                bank = {}
                with self.assertRaises(SdkInputTooSmall) as raised:
                    await self.quote(engine, pool, amount=3, branches=branches, candidate=bank, canonical=canonical)
                canonicals.append(canonical)
                errors.append(raised.exception)
                self.assertEqual(bank, {}, 'A failed mixed route never commits its earlier V3 post-state')
                self.assertTrue(canonical[pool['id']]['bitmapWords'])
            self.assertEqual(engine.sdk.sequence, 1)
            self.assertEqual(len(demands), 4, 'Each owner still receives the original required observations')
            self.assertTrue(all(request == demands[0] for request in demands))
            self.assertEqual(len({id(error) for error in errors}), 4)
            for stored in observations.reads.completed.values(): json.dumps(stored)
        self.assertEqual((pool, pair, branches), originals)
        self.assertEqual(canonicals[0], canonicals[1])
        canonicals[0][pool['id']]['bitmapWords'][0]['bitmap'] = 'private mutation'
        self.assertNotEqual(canonicals[0], canonicals[1])
        self.assertEqual(engine.semaphore._value, 8)

    async def test_cached_failure_demand_error_propagates_and_retry_replays_before_typed_error(self):
        pool, registry, engine = self.engine()
        pair, branches = self.mixed_dust(pool, registry)
        calls, unavailable = 0, OSError('follower coverage unavailable')
        async def extend(*_args):
            nonlocal calls
            calls += 1
            if calls == 2: raise unavailable
            return deepcopy(pool)
        registry.extend_ticks = extend
        async def quote():
            canonical = {pool['id']: self.initial(pool), pair['id']: deepcopy(pair)}
            return await self.quote(engine, pool, amount=3, branches=branches, canonical=canonical)
        async with search_observation_scope():
            with self.assertRaises(SdkInputTooSmall): await quote()
            with self.assertRaises(OSError) as raised: await quote()
            self.assertIs(raised.exception, unavailable, 'Cached math cannot mask a follower observation error')
            with self.assertRaises(SdkInputTooSmall): await quote()
            self.assertEqual((engine.sdk.sequence, calls), (1, 3))
        self.assertEqual(engine.semaphore._value, 8)

    async def test_cancelled_no_quote_subscriber_preserves_survivor_and_its_demand_replay(self):
        pool, registry, engine = self.engine()
        pair, branches = self.mixed_dust(pool, registry)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def extend(*_args):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return deepcopy(pool)
        registry.extend_ticks = extend
        canonicals = [{pool['id']: self.initial(pool), pair['id']: deepcopy(pair)} for _ in range(2)]
        async with search_observation_scope() as observations:
            tasks = [asyncio.create_task(self.quote(engine, pool, amount=3, branches=branches, canonical=canonicals[0]))]
            try:
                await asyncio.wait_for(entered.wait(), 3)
                tasks.append(asyncio.create_task(self.quote(engine, pool, amount=3, branches=branches, canonical=canonicals[1])))
                await until(lambda: any(entry.users == 2 for entry in observations.reads.pending.values()))
                tasks[0].cancel()
                with self.assertRaises(asyncio.CancelledError): await tasks[0]
                release.set()
                with self.assertRaises(SdkInputTooSmall): await tasks[1]
                self.assertTrue(canonicals[1][pool['id']]['bitmapWords'])
                self.assertEqual((engine.sdk.sequence, calls), (1, 2))
                with self.assertRaises(SdkInputTooSmall):
                    await self.quote(engine, pool, amount=3, branches=branches,
                        canonical={pool['id']: self.initial(pool), pair['id']: deepcopy(pair)})
                self.assertEqual(engine.sdk.sequence, 1)
            finally:
                release.set()
                for task in tasks:
                    if not task.done(): task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(engine.semaphore._value, 8)

    async def test_other_sdk_and_observation_errors_are_not_negative_cached(self):
        pool, _, engine = self.engine('v2')
        payload = {'operation': 'quote', 'mode': 'exactIn', 'amount': '1', 'pools': [pool],
                   'poolId': pool['id'], 'zeroForOne': True}
        async def unused(_requests): raise AssertionError('No controlled state demand')
        errors = [SdkWorkerError('ordinary SDK failure'), OSError('RPC unavailable'), TimeoutError('timeout'),
                  MissingPoolState([{'poolId': pool['id'], 'wordPositions': [0], 'ticks': []}])]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                async with search_observation_scope() as observations:
                    with patch.object(engine.sdk, 'request', side_effect=error) as request:
                        for _ in range(2):
                            with self.assertRaises(type(error)) as raised:
                                await simulate_sdk(engine, payload, unused)
                            self.assertIs(raised.exception, error)
                        self.assertEqual(request.await_count, 2)
                    self.assertEqual(observations.reads.completed, {})
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
