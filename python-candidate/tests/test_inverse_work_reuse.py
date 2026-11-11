"""Exact inverse arithmetic shares only its actual worker request contract."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter.contracts import HopTrace
from cybergold_candidate.quoter.inverse import inverse_hops
from cybergold_candidate.route_work_slots import PricingSlots, engine_work
from cybergold_candidate.sdk_simulation import simulate_sdk
from cybergold_candidate.sdk_worker import MissingPoolState
from cybergold_candidate.search_observations import search_observation_scope
from quoter_fixture import service, synthetic_pool
from test_universal_quote import WETH, PAXG


class InverseWorkReuseTests(unittest.IsolatedAsyncioTestCase):
    def setup_inverse(self, protocol='v2'):
        pool = synthetic_pool(WETH, PAXG, 9751, protocol)
        q = service(self, [pool])
        hop = {'pool': deepcopy(pool),
               'zeroForOne': pool['token0']['address'].lower() == WETH.lower()}
        return q, HopTrace(hop, 10000, 10000, 9969, deepcopy(pool))

    async def test_legacy_single_argument_request_works_unshared_and_shared(self):
        requests = []
        async def request(payload):
            requests.append(deepcopy(payload))
            return {'amountIn': '4013'}
        engine = SimpleNamespace(sdk=SimpleNamespace(request=request), semaphore=PricingSlots(8))
        q = SimpleNamespace(engine=engine)
        pool = synthetic_pool(WETH, PAXG, 9752, 'v2')
        row = HopTrace({'zeroForOne': True}, 10000, 10000, 9969, pool)
        for _ in range(2):
            self.assertEqual(await inverse_hops(q, [row], 4000), 4013)
        self.assertEqual(len(requests), 2)
        async with search_observation_scope():
            for _ in range(2):
                self.assertEqual(await inverse_hops(q, [row], 4000), 4013)
            self.assertEqual(len(requests), 3)
        async with search_observation_scope():
            self.assertEqual(await inverse_hops(q, [row], 4000), 4013)
        self.assertEqual(len(requests), 4)
        self.assertTrue(all(value == requests[0] for value in requests))
        self.assertEqual(requests[0], {'operation': 'quote', 'pools': [pool], 'poolId': pool['id'],
            'mode': 'exactOut', 'amount': '4000', 'zeroForOne': True})
        self.assertEqual(engine.semaphore._value, 8)

    async def test_request_type_error_is_not_retried_or_negative_cached(self):
        calls = 0
        expected = TypeError('ordinary custom SDK failure')
        async def request(payload):
            nonlocal calls
            calls += 1
            raise expected
        engine = SimpleNamespace(sdk=SimpleNamespace(request=request), semaphore=PricingSlots(8))
        payload = {'operation': 'quote'}
        with self.assertRaises(TypeError) as raised:
            await simulate_sdk(engine, payload)
        self.assertIs(raised.exception, expected)
        async with search_observation_scope():
            for _ in range(2):
                with self.assertRaises(TypeError) as raised:
                    await simulate_sdk(engine, payload)
                self.assertIs(raised.exception, expected)
        self.assertEqual(calls, 3)
        self.assertEqual(engine.semaphore._value, 8)

    async def test_identical_actual_inverse_is_shared_only_inside_one_search(self):
        q, row = self.setup_inverse()
        original = deepcopy(row)
        async with search_observation_scope():
            first = await inverse_hops(q, [row], 4000)
            self.assertEqual(await inverse_hops(q, [row], 4000), first)
            self.assertEqual(q.engine.sdk.sequence, 1)
            changed = deepcopy(row)
            changed.pre_state['reserve0'] = str(int(changed.pre_state['reserve0']) * 2)
            await inverse_hops(q, [changed], 4000)
            await inverse_hops(q, [row], 4001)
            reverse = deepcopy(row)
            reverse.hop['zeroForOne'] = not row.hop['zeroForOne']
            await inverse_hops(q, [reverse], 4000)
            self.assertEqual(q.engine.sdk.sequence, 4)
        async with search_observation_scope():
            self.assertEqual(await inverse_hops(q, [row], 4000), first)
        await inverse_hops(q, [row], 4000)
        await inverse_hops(q, [row], 4000)
        self.assertEqual(q.engine.sdk.sequence, 7)
        self.assertEqual(first, 4013)
        self.assertEqual(row, original)
        self.assertEqual(q.engine.semaphore._value, 8)

    async def test_missing_coverage_does_not_add_continuation_or_reuse_callback_result(self):
        q, row = self.setup_inverse('v3')
        complete = deepcopy(row.pre_state)
        row.pre_state.update(ticks=[], bitmapWords=[])
        original = deepcopy(row)
        payload = {'operation': 'quote', 'pools': [deepcopy(row.pre_state)],
                   'poolId': row.pre_state['id'], 'mode': 'exactOut',
                   'amount': '1000', 'zeroForOne': row.hop['zeroForOne']}
        calls = []
        async def acquire(requests):
            calls.append(deepcopy(requests))
            return [deepcopy(complete)]
        async with search_observation_scope():
            async with engine_work(q.engine.semaphore):
                callback_value = await simulate_sdk(q.engine, payload, acquire)
            self.assertEqual(callback_value['amountOut'], '1000')
            self.assertEqual(len(calls), 1)
            for _ in range(2):
                with self.assertRaises(MissingPoolState):
                    await inverse_hops(q, [row], 1000)
            self.assertEqual(q.engine.sdk.sequence, 3,
                             'Missing coverage remains retryable without a state callback')
            async with engine_work(q.engine.semaphore):
                self.assertEqual(await simulate_sdk(q.engine, payload, acquire), callback_value)
            self.assertEqual((q.engine.sdk.sequence, len(calls)), (3, 2))
        self.assertEqual(row, original)
        self.assertEqual(q.engine.semaphore._value, 8)

    async def test_cancelled_inverse_subscriber_does_not_cancel_shared_owner(self):
        q, row = self.setup_inverse()
        entered, release = asyncio.Event(), asyncio.Event()
        request = q.engine.sdk.request
        callbacks = []
        async def held(payload, on_state=None):
            callbacks.append(on_state)
            entered.set()
            await release.wait()
            return await request(payload, on_state=on_state)
        async with search_observation_scope() as observations:
            with patch.object(q.engine.sdk, 'request', held):
                tasks = [asyncio.create_task(inverse_hops(q, [row], 4000))]
                try:
                    await asyncio.wait_for(entered.wait(), 3)
                    tasks.append(asyncio.create_task(inverse_hops(q, [deepcopy(row)], 4000)))
                    async with asyncio.timeout(3):
                        while not any(entry.users == 2 for entry in observations.reads.pending.values()):
                            await asyncio.sleep(0)
                    tasks[0].cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await tasks[0]
                    release.set()
                    self.assertEqual(await tasks[1], 4013)
                    self.assertEqual(callbacks, [None])
                    self.assertEqual(q.engine.sdk.sequence, 1)
                finally:
                    release.set()
                    for task in tasks:
                        if not task.done(): task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(q.engine.semaphore._value, 8)
