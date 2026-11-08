"""Initial canonical reads park pricing capacity, retaining read ownership.

The inert SDK only records admission; these are concurrency/ownership checks,
not an AMM arithmetic or whole-Quoter economic model.
"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.route_work_slots import engine_work
from cybergold_candidate.shared_reads import SharedReads


BLOCK = {'number': 101, 'hash': '0x'+'ab'*32}
A, B, C = ('0x'+value*40 for value in ('1', '2', '3'))


def pool(target, number):
    return {'id': '0x'+format(number, '040x'), 'protocol': 'v2',
            'token0': {'address': A, 'decimals': 18, 'chainId': 1},
            'token1': {'address': target, 'decimals': 18, 'chainId': 1},
            'feePips': 3000, 'reserve0': '1000000', 'reserve1': '1000000',
            'context': {'chainId': 1, 'blockNumber': '101', 'blockHash': BLOCK['hash']}}


class AdmissionSdk:
    def __init__(self):
        self.requests = []

    async def request(self, payload, on_state=None):
        self.requests.append(deepcopy(payload))
        await asyncio.sleep(0)
        return {'amountIn': payload['amount'], 'amountOut': '1',
                'fullyFilled': True, 'settled': True, 'postState': deepcopy(payload['pools'])}

    async def close(self):
        pass


class InitialReadRegistry:
    chain = 1

    def __init__(self):
        self.cold, self.ready = pool(B, 1801), pool(C, 1802)
        self.inventory = {row['id']: row for row in (self.cold, self.ready)}
        self.pending = SharedReads()
        self.release, self.started, self.cancelled = (asyncio.Event() for _ in range(3))
        self.producers, self.subscribers = 0, 0
        self.failure = None

    async def snapshot(self, value, block):
        async def produce():
            self.producers += 1
            self.started.set()
            try:
                await self.release.wait()
                if self.failure is not None:
                    raise self.failure
                return deepcopy(value)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        self.subscribers += 1
        return await self.pending.one((value['id'], block['hash']), produce)


class InitialSnapshotSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = InitialReadRegistry()
        self.sdk = AdmissionSdk()
        self.engine = RouteQuoteEngine(SimpleNamespace(), self.registry, sdk=self.sdk)
        self.owned = []

    async def asyncTearDown(self):
        self.registry.release.set()
        for task in self.owned:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.owned, return_exceptions=True)
        await self.engine.close()
        await self.registry.pending.close()

    async def quote(self, value, *, canonical=None):
        branches = [{'amountIn': '1000', 'hops': [{'pool': value, 'zeroForOne': True}]}]
        async with engine_work(self.engine.semaphore):
            return await self.engine.quote_sdk_branches(branches, 'exactIn', 1000, BLOCK,
                candidate={}, canonical={} if canonical is None else canonical)

    def start(self, operation):
        task = asyncio.create_task(operation)
        self.owned.append(task)
        return task

    async def subscribed(self, count):
        async with asyncio.timeout(1):
            while self.registry.subscribers < count:
                await asyncio.sleep(0)
        await self.registry.started.wait()

    async def test_ready_quote_prices_before_eight_shared_cold_reads_finish(self):
        cold = [self.start(self.quote(self.registry.cold)) for _ in range(8)]
        await self.subscribed(8)
        ready = self.start(self.quote(self.registry.ready,
            canonical={self.registry.ready['id']: deepcopy(self.registry.ready)}))
        # This is a test bound, not a discovery allowance. A ready observation
        # needs no chain I/O and must not await the unrelated initial read.
        async with asyncio.timeout(.25):
            value = await ready
        self.assertTrue(value['fullyFilled'])
        self.assertFalse(self.registry.release.is_set())
        self.assertTrue(all(not task.done() for task in cold))
        self.assertEqual(self.registry.producers, 1)
        self.assertEqual(len(self.sdk.requests), 1)
        self.assertEqual(self.engine.semaphore._value, 8)
        self.registry.release.set()
        await asyncio.gather(*cold)
        self.assertEqual(self.engine.semaphore._value, 8)

    async def test_cancelled_quote_leaves_foreign_shared_read_subscriber_alive(self):
        foreign = self.start(self.registry.snapshot(self.registry.cold, BLOCK))
        await self.subscribed(1)
        owner = self.start(self.quote(self.registry.cold))
        await self.subscribed(2)
        owner.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await owner
        self.assertFalse(foreign.done())
        self.assertFalse(self.registry.cancelled.is_set())
        self.assertEqual(self.engine.semaphore._value, 8)
        self.registry.release.set()
        self.assertEqual((await foreign)['id'], self.registry.cold['id'])
        self.assertEqual(len(self.sdk.requests), 0)

    async def test_cancelling_all_owners_drains_last_initial_read_and_restores_capacity(self):
        owners = [self.start(self.quote(self.registry.cold)) for _ in range(8)]
        await self.subscribed(8)
        for task in owners:
            task.cancel()
        results = await asyncio.gather(*owners, return_exceptions=True)
        self.assertTrue(all(isinstance(value, asyncio.CancelledError) for value in results))
        self.assertTrue(self.registry.cancelled.is_set())
        self.assertFalse(self.registry.pending.pending)
        self.assertEqual(self.engine.semaphore._value, 8)
        self.assertEqual(len(self.sdk.requests), 0)

    async def test_initial_read_ordinary_error_and_disproof_restore_capacity(self):
        for kind in (OSError, SnapshotChanged):
            with self.subTest(failure=kind.__name__):
                self.registry.failure = kind('controlled canonical read failure')
                self.registry.release.clear()
                before = self.registry.subscribers
                owners = [self.start(self.quote(self.registry.cold)) for _ in range(8)]
                await self.subscribed(before+8)
                self.registry.release.set()
                results = await asyncio.gather(*owners, return_exceptions=True)
                self.assertTrue(all(isinstance(value, kind) for value in results))
                self.assertFalse(self.registry.pending.pending)
                self.assertEqual(self.engine.semaphore._value, 8)
                self.assertEqual(len(self.sdk.requests), 0)


if __name__ == '__main__':
    unittest.main()
