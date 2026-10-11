"""Advisory daily owner facts, with no quote-triggered chain acquisition."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.market_swap import DailyRecipientCache


HELPERS = '0x' + '1' * 40
FIRST, SECOND = ('0x' + digit * 40 for digit in ('2', '3'))


class Store:
    def __init__(self):
        self.values = {}

    async def load(self, namespace):
        assert namespace == 'recipient'
        return deepcopy(self.values)

    async def save(self, namespace, identity, value):
        assert namespace == 'recipient'
        self.values[identity] = deepcopy(value)


class RecipientLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_worker_daily_boundary_failure_and_restart_preserve_last_good_display(self):
        now = [1_700_000_000]
        store = Store()
        cache = DailyRecipientCache(store, HELPERS, now=lambda: now[0])
        self.addAsyncCleanup(cache.close)
        rpc = SimpleNamespace(read_function=AsyncMock(return_value=(FIRST,)))
        block = {'number': 123, 'hash': '0x' + 'a' * 64}
        await cache.refresh(rpc, block)
        await asyncio.gather(*tuple(cache.background))
        self.assertEqual(rpc.read_function.await_count, 1)
        now[0] += 86_399
        await cache.refresh(rpc, block)
        self.assertEqual(rpc.read_function.await_count, 1)
        rpc.read_function.return_value = (SECOND,)
        now[0] += 1
        await cache.refresh(rpc, block)
        await asyncio.gather(*tuple(cache.background))
        self.assertEqual(rpc.read_function.await_count, 2)
        last_good = deepcopy(cache.value)
        self.assertEqual(last_good['address'], SECOND)
        now[0] += 86_400
        rpc.read_function.side_effect = ConnectionError('temporary owner read failure')
        await cache.refresh(rpc, block)
        self.assertEqual(cache.value, last_good)
        restarted = DailyRecipientCache(store, HELPERS, now=lambda: now[0])
        self.addAsyncCleanup(restarted.close)
        self.assertEqual(await restarted.load(wait=True), last_good)
        await restarted.refresh(rpc, block)
        self.assertEqual(restarted.value, last_good)
        reads = rpc.read_function.await_count
        for _ in range(3):
            self.assertEqual(await restarted.load(), last_good)
        self.assertEqual(rpc.read_function.await_count, reads)


if __name__ == '__main__':
    unittest.main()
