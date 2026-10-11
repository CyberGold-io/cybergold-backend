import asyncio
import json
import unittest

from cybergold_candidate.cache import MarketFeed
from cybergold_candidate.shared_market import SharedMarketCache


class Store:
    def __init__(self):
        self.rows = {}
        self.commands = []
        self.fail = False

    async def mget(self, keys):
        if self.fail: raise ConnectionError('fixture outage')
        return [self.rows.get(key) for key in keys]

    def pipeline(self, **_kwargs): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): pass
    def set(self, key, value, **_kwargs): self.commands.append((key, value))
    async def execute(self):
        if self.fail: raise ConnectionError('fixture outage')
        self.rows.update(self.commands)
        self.commands.clear()
    async def aclose(self): pass


class SharedMarketCases(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = [0]
        self.store = Store()
        self.calls = 0
        self.payload = {'price': 3000, 'fetchedAt': '2026-10-01T00:00:00.000Z', 'stale': False}
        self.shared = SharedMarketCache(None, 31338, client=self.store, clock=lambda: self.clock[0])

    async def supplier(self, _previous):
        self.calls += 1
        await asyncio.sleep(0)
        return {'payload': self.payload, 'isFresh': True}

    def feed(self, supplier=None):
        return MarketFeed(lambda previous: self.shared.resolve('gold', previous, supplier or self.supplier, 10),
                          10, timer=lambda: self.clock[0])

    async def test_two_process_reuse_never_renews_acquisition_expiry(self):
        first = self.feed()
        value = await first.get()
        self.clock[0] = 8
        second = self.feed()
        self.assertEqual(await second.get(), value)
        self.assertEqual(self.calls, 1)
        self.clock[0] = 11
        await second.get()
        self.assertEqual(self.calls, 2)

    async def test_old_one_hour_gold_record_expires_at_current_thirty_minute_policy(self):
        from datetime import datetime
        acquired = datetime.fromisoformat(self.payload['fetchedAt']).timestamp()
        fresh_key, last_key = self.shared.keys('gold')
        self.store.rows[fresh_key] = json.dumps({'payload': self.payload, 'expiresAt': acquired + 3600})
        self.store.rows[last_key] = json.dumps(self.payload)
        self.clock[0] = acquired + 1799
        value = await self.shared.resolve('gold', None, self.supplier, 1800)
        self.assertEqual(value.remaining_ttl, 1)
        self.assertEqual(self.calls, 0)
        self.clock[0] = acquired + 1800
        await self.shared.resolve('gold', None, self.supplier, 1800)
        self.assertEqual(self.calls, 1)

    async def test_shared_last_known_is_stale_and_not_written_on_failure(self):
        await self.feed().get()
        retained = dict(self.store.rows)
        self.clock[0] = 11
        previous = []
        async def unavailable(last):
            previous.append(last)
            return {'payload': {**last, 'stale': True}, 'isFresh': False}
        second = self.feed(unavailable)
        self.assertTrue((await second.get())['payload']['stale'])
        await second.get()
        self.assertEqual(previous, [self.payload, self.payload])
        self.assertEqual(self.store.rows, retained)

    async def test_outage_retains_twenty_caller_local_coalescing(self):
        self.store.fail = True
        feed = self.feed()
        results = await asyncio.gather(*(feed.get() for _ in range(20)))
        self.assertEqual(self.calls, 1)
        self.assertTrue(all(result['isFresh'] for result in results))
        self.assertEqual(await feed.get(), results[0])
        self.assertEqual(self.calls, 1)

    async def test_corrupt_or_expired_fresh_value_cannot_replace_supplier(self):
        for value in ('invalid', json.dumps({'payload': self.payload, 'expiresAt': -1}),
                      json.dumps({'payload': {**self.payload, 'price': 0}, 'expiresAt': 10})):
            self.store.rows[self.shared.keys('gold')[0]] = value
            self.assertEqual((await self.feed().get())['payload'], self.payload)
        self.assertEqual(self.calls, 3)

    async def test_chain_feed_and_representation_keys_are_separate(self):
        await self.feed().get()
        other = SharedMarketCache(None, 1, client=self.store, clock=lambda: self.clock[0])
        self.assertNotEqual(other.keys('gold'), self.shared.keys('gold'))
        self.assertNotEqual(self.shared.keys('gold'), self.shared.keys('fx'))
        await other.resolve('gold', None, self.supplier, 10)
        self.assertEqual(self.calls, 2)
        self.assertEqual(len(self.store.rows), 4)

    async def test_cancelled_caller_keeps_shared_producer_and_shutdown_drains_it(self):
        started, completed = asyncio.Event(), asyncio.Event()
        async def slow(_previous):
            started.set()
            await completed.wait()
            return {'payload': self.payload, 'isFresh': True}
        feed = self.feed(slow)
        caller = asyncio.create_task(feed.get())
        await started.wait()
        second = asyncio.create_task(feed.get())
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError): await caller
        completed.set()
        self.assertTrue((await second)['isFresh'])
        await feed.close()


if __name__ == '__main__': unittest.main()
