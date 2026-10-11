import asyncio
import unittest

from cybergold_candidate.cache import MarketFeed


class CacheParity(unittest.IsolatedAsyncioTestCase):
    async def test_coalescing_expiry_and_ordinary_retry(self):
        clock = [0]
        calls = []
        fresh = {'payload': {'price': 3000, 'fetchedAt': '2026-09-28T00:00:00.000Z', 'stale': False},
                 'isFresh': True}

        async def resolve(previous):
            calls.append(previous)
            await asyncio.sleep(0)
            return fresh if len(calls) == 1 else {'payload': {**previous, 'stale': True}, 'isFresh': False}

        feed = MarketFeed(resolve, 10, timer=lambda: clock[0])
        results = await asyncio.gather(*(feed.get() for _ in range(20)))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(result == fresh for result in results))
        clock[0] = 9
        self.assertEqual(await feed.get(), fresh)
        clock[0] = 11  # Cache hits must not extend the acquisition lifetime.
        stale = await feed.get()
        self.assertEqual(stale['payload'], {**fresh['payload'], 'stale': True})
        await feed.get()
        self.assertEqual(len(calls), 3)
        await feed.close()

    async def test_one_cancelled_caller_preserves_shared_refresh(self):
        started, complete = asyncio.Event(), asyncio.Event()

        async def resolve(_previous):
            started.set()
            await complete.wait()
            return {'payload': {'fetchedAt': 'retained', 'stale': False}, 'isFresh': True}

        feed = MarketFeed(resolve, 10)
        first = asyncio.create_task(feed.get())
        await started.wait()
        second = asyncio.create_task(feed.get())
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        complete.set()
        self.assertTrue((await second)['isFresh'])
        self.assertEqual((await feed.get())['payload']['fetchedAt'], 'retained')
        await feed.close()

    async def test_shutdown_cancels_owned_refresh(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def resolve(_previous):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        feed = MarketFeed(resolve, 10)
        caller = asyncio.create_task(feed.get())
        await started.wait()
        await feed.close()
        await asyncio.gather(caller, return_exceptions=True)
        self.assertTrue(cancelled.is_set())


if __name__ == '__main__':
    unittest.main()
