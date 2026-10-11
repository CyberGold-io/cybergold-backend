"""Catch-up pacing counts concurrent transports, retries and cancellation."""
import asyncio
import unittest

from cybergold_candidate.indexing_budget import IndexingRpcPacer, REQUESTS_PER_HOUR
from cybergold_candidate.indexer_rpc import IndexerRpc


class Clock:
    def __init__(self):
        self.now = 0

    async def sleep(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)


class IndexingBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_environments_share_half_the_gateway_hourly_allowance(self):
        clock = Clock()
        pacer = IndexingRpcPacer(monotonic=lambda: clock.now, sleep=clock.sleep)
        stamps = []

        async def attempt():
            await pacer.acquire()
            stamps.append(clock.now)

        await asyncio.gather(*(attempt() for _ in range(50)))
        self.assertEqual(pacer.attempts, 50)
        self.assertGreaterEqual(stamps[0], .36)
        for previous, current in zip(stamps, stamps[1:]):
            self.assertAlmostEqual(current - previous, .36)
        self.assertEqual(REQUESTS_PER_HOUR * 2, 20000)

    async def test_retry_attempts_use_the_same_allowance_as_both_transports(self):
        clock = Clock()
        pacer = IndexingRpcPacer(monotonic=lambda: clock.now, sleep=clock.sleep)
        attempts = []

        class Provider:
            async def make_request(self, method, params):
                attempts.append((method, clock.now))
                return {'error': {'code': -32005, 'message': 'capacity'}} if len(attempts) == 1 else {'result': '0x1'}

        normal = IndexerRpc(provider=Provider(), before_request=pacer.acquire, sleep=clock.sleep)
        raw = IndexerRpc(provider=Provider(), retry_count=0, before_request=pacer.acquire)
        self.assertEqual(await normal.request('eth_getBlockByNumber', ['0x1', False]), '0x1')
        self.assertEqual(await raw.request('eth_getLogs', [{}]), '0x1')
        self.assertEqual(pacer.attempts, 3)
        self.assertEqual(len(attempts), 3)
        self.assertGreaterEqual(attempts[1][1] - attempts[0][1], .36)
        self.assertGreaterEqual(attempts[2][1] - attempts[1][1], .36)

    async def test_cancellation_during_pacing_sends_no_rpc_and_does_not_retry(self):
        calls = []

        async def cancelled(_seconds):
            raise asyncio.CancelledError()

        class Provider:
            async def make_request(self, method, params):
                calls.append(method)

        pacer = IndexingRpcPacer(sleep=cancelled)
        with self.assertRaises(asyncio.CancelledError):
            await IndexerRpc(provider=Provider(), before_request=pacer.acquire).request('eth_getLogs', [{}])
        self.assertEqual(calls, [])
        self.assertEqual(pacer.attempts, 0)

    async def test_live_transport_has_no_pacing_hook(self):
        class Provider:
            async def make_request(self, method, params):
                return {'result': '0x1'}

        self.assertEqual(await IndexerRpc(provider=Provider()).request('eth_chainId', []), '0x1')

    async def test_new_worker_waits_instead_of_receiving_a_new_burst(self):
        clock = Clock()
        first = IndexingRpcPacer(monotonic=lambda: clock.now, sleep=clock.sleep)
        await first.acquire()
        prior = clock.now
        replacement = IndexingRpcPacer(monotonic=lambda: clock.now, sleep=clock.sleep)
        await replacement.acquire()
        self.assertGreaterEqual(clock.now - prior, .36)


if __name__ == '__main__':
    unittest.main()
