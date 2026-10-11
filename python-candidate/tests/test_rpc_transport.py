import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import gc
import unittest
from unittest.mock import patch

from aiohttp import web, ClientResponseError
from web3._utils.http_session_manager import HTTPSessionManager

from cybergold_candidate.rpc_transport import rpc_provider


class TransportParity(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.fail = False
        self.delay = 0

        async def rpc(request):
            body = await request.json()
            self.requests.append((body, request.headers.get('Authorization')))
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                return web.Response(status=503)
            return web.json_response({'jsonrpc': '2.0', 'id': body['id'], 'result': '0x01'})

        app = web.Application()
        app.router.add_post('/', rpc)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.provider = rpc_provider(f'http://127.0.0.1:{port}/', 'Bearer local-fixture', timeout_seconds=.1)

    async def asyncTearDown(self):
        await self.provider.disconnect()
        await self.runner.cleanup()

    @asynccontextmanager
    async def held_session_lock(self):
        manager = self.provider._request_session_manager
        lock, loop, started = manager._lock, asyncio.get_running_loop(), asyncio.Event()
        class ObservedExecutor(ThreadPoolExecutor):
            def submit(self, fn, /, *args, **kwargs):
                def acquire():
                    if fn == lock.acquire:
                        loop.call_soon_threadsafe(started.set)
                    return fn(*args, **kwargs)
                return super().submit(acquire)
        manager.session_pool.shutdown(wait=True)
        manager.session_pool = ObservedExecutor(max_workers=1)
        self.assertTrue(lock.acquire(blocking=False))
        held = True
        def release():
            nonlocal held
            if held:
                held = False
                lock.release()
        try:
            yield manager, started, release
        finally:
            release()
            await manager.finish_pending()
            manager.session_pool.shutdown(wait=True)

    async def test_pre_http_cancellation_cannot_poison_another_provider(self):
        async with self.held_session_lock() as (manager, started, release):
            request = asyncio.create_task(self.provider.make_request('eth_chainId', []))
            await asyncio.wait_for(started.wait(), 1)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(request, 1)
            self.assertTrue(manager._lock.locked())
            self.assertEqual(self.requests, [])
            self.assertEqual(len(manager.pending), 1)
            other = rpc_provider(self.provider.endpoint_uri, 'Bearer local-fixture', timeout_seconds=.1)
            try:
                self.assertIs(other._request_session_manager._lock, manager._lock)
                next_request = asyncio.create_task(other.make_request('eth_chainId', []))
                release()
                response = await asyncio.wait_for(next_request, 1)
                self.assertEqual(response['result'], '0x01')
                await asyncio.wait_for(manager.finish_pending(), 1)
                self.assertFalse(manager._lock.locked())
                self.assertEqual(len(manager.pending), 0)
                response = await asyncio.wait_for(self.provider.make_request('eth_chainId', []), 1)
                self.assertEqual(response['result'], '0x01')
                self.assertEqual(len(self.requests), 2)
            finally:
                await other.disconnect()
                other._request_session_manager.session_pool.shutdown(wait=True)

    async def test_abandoned_cache_failure_is_consumed_and_active_caller_still_raises(self):
        manager, loop = self.provider._request_session_manager, asyncio.get_running_loop()
        started, release, unhandled = asyncio.Event(), asyncio.Event(), []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        async def fail_cache(_manager, *args, **kwargs):
            started.set()
            await release.wait()
            raise ValueError('Synthetic session-cache failure')
        try:
            with patch.object(HTTPSessionManager, 'async_cache_and_return_session', fail_cache):
                request = asyncio.create_task(self.provider.make_request('eth_chainId', []))
                await asyncio.wait_for(started.wait(), 1)
                request.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await request
                release.set()
                async with asyncio.timeout(1):
                    while manager.pending:
                        await asyncio.sleep(0)
                await asyncio.sleep(0)
                gc.collect()
                await asyncio.sleep(0)
                self.assertEqual(unhandled, [])
                with self.assertRaisesRegex(ValueError, 'Synthetic session-cache failure'):
                    await self.provider.make_request('eth_chainId', [])
                self.assertEqual(self.requests, [])
        finally:
            loop.set_exception_handler(previous_handler)

    async def test_disconnect_finishes_abandoned_lookup_then_closes_its_session(self):
        async with self.held_session_lock() as (manager, started, release):
            request = asyncio.create_task(self.provider.make_request('eth_chainId', []))
            await asyncio.wait_for(started.wait(), 1)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            lookup, = manager.pending
            disconnect = asyncio.create_task(self.provider.disconnect())
            await asyncio.sleep(0)
            self.assertFalse(disconnect.done())
            release()
            await asyncio.wait_for(disconnect, 1)
            self.assertTrue(lookup.result().closed)
            self.assertEqual(len(manager.session_cache), 0)
            self.assertFalse(manager._lock.locked())
            self.assertEqual(self.requests, [])

    async def test_cancelled_disconnect_does_not_cancel_abandoned_lookup(self):
        async with self.held_session_lock() as (manager, started, release):
            request = asyncio.create_task(self.provider.make_request('eth_chainId', []))
            await asyncio.wait_for(started.wait(), 1)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            lookup, = manager.pending
            disconnect = asyncio.create_task(self.provider.disconnect())
            await asyncio.sleep(0)
            disconnect.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await disconnect
            self.assertFalse(lookup.done())
            self.assertTrue(manager._lock.locked())
            release()
            await asyncio.wait_for(self.provider.disconnect(), 1)
            self.assertTrue(lookup.result().closed)
            self.assertFalse(manager._lock.locked())

    async def test_block_hash_and_canonicality_are_preserved_without_cache(self):
        params = [{'to': '0x' + '1' * 40, 'data': '0x1234'},
                  {'blockHash': '0x' + '2' * 64, 'requireCanonical': True}]
        for _ in range(2):
            response = await self.provider.make_request('eth_call', params)
            self.assertEqual(response['result'], '0x01')
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(body['method'] == 'eth_call' and body['params'] == params
                            and auth == 'Bearer local-fixture' for body, auth in self.requests))

    async def test_no_implicit_retry_after_http_failure(self):
        self.fail = True
        with self.assertRaises(ClientResponseError):
            await self.provider.make_request('eth_blockNumber', [])
        self.assertEqual(len(self.requests), 1)

    async def test_identical_hash_reads_share_only_while_in_flight(self):
        self.delay = .01
        params = [{'to': '0x' + '1' * 40, 'data': '0x1234'},
                  {'blockHash': '0x' + '2' * 64, 'requireCanonical': True}]
        await asyncio.gather(*(self.provider.make_request('eth_call', params) for _ in range(5)))
        self.assertEqual(len(self.requests), 1)
        await self.provider.make_request('eth_call', params)
        self.assertEqual(len(self.requests), 2)
        other = [params[0], {'blockHash': '0x' + '3' * 64, 'requireCanonical': True}]
        await self.provider.make_request('eth_call', other)
        self.assertEqual(len(self.requests), 3)

    async def test_total_deadline_and_cancellation_do_not_retry(self):
        self.delay = .2
        with self.assertRaises(TimeoutError):
            await self.provider.make_request('eth_blockNumber', [])
        self.assertEqual(len(self.requests), 1)
        task = asyncio.create_task(self.provider.make_request('eth_blockNumber', []))
        while len(self.requests) < 2:
            await asyncio.sleep(.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.requests), 2)


if __name__ == '__main__':
    unittest.main()
