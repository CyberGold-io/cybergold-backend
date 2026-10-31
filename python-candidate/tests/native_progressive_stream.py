"""Actual Uvicorn/TCP NDJSON delivery and caller-disconnect ownership.

Local public fixtures only. No deployed endpoint, chain RPC, wallet or server
administration. Run with the frozen Python environment and loopback permission.
"""
import asyncio
from copy import deepcopy
import json
import socket
import unittest
from unittest.mock import AsyncMock

import httpx
import uvicorn

from cybergold_candidate.app import create_app
from test_progressive_economic_quotes import ProgressiveFixture, economic_request


class NativeProgressiveStream(ProgressiveFixture):
    async def launch(self, service):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0)); listener.listen(16); listener.setblocking(False)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(economic_quotes=service),
            host='127.0.0.1', port=port, loop='asyncio', lifespan='off', log_level='error'))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        async def stop():
            server.should_exit = True
            await asyncio.wait_for(task, 3)
            listener.close()
        self.addAsyncCleanup(stop)
        async with asyncio.timeout(3):
            while not server.started:
                if task.done(): await task
                await asyncio.sleep(.01)
        return 'http://127.0.0.1:'+str(port)

    async def test_first_ready_is_delivered_over_tcp_while_search_waits_then_abort_drains_and_saves(self):
        search_drained, saved = asyncio.Event(), asyncio.Event()
        async def script(value, callback, **_):
            try:
                await callback({'type': 'qualified', 'value': self.value(100)})
                await asyncio.Event().wait()
            finally:
                search_drained.set()
        service = self.service(script)
        original_save = service.store.save
        async def save(*args, **kwargs):
            self.assertTrue(search_drained.is_set())
            value = await original_save(*args, **kwargs)
            saved.set(); return value
        service.store.save = AsyncMock(side_effect=save)
        endpoint = await self.launch(service)
        async with httpx.AsyncClient(timeout=3) as client:
            async with client.stream('POST', endpoint+'/api/economic-quotes/stream', json=economic_request()) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['x-accel-buffering'], 'no')
                frame = json.loads(await anext(response.aiter_lines()))
                self.assertEqual(frame['type'], 'qualified')
                self.assertEqual(frame['value']['quotedOutput'], '100')
                self.assertFalse(search_drained.is_set())
                # Closing this actual TCP response simulates stopping the
                # caller's search; no explicit cancel/session endpoint exists.
            await asyncio.wait_for(search_drained.wait(), 2)
            await asyncio.wait_for(saved.wait(), 2)
        service.store.save.assert_awaited_once()
        self.assertEqual(next(iter(service.store.rows.values()))['quotedOutput'], '100')

    async def test_tcp_improvement_and_terminal_are_separate_incremental_frames(self):
        release = asyncio.Event()
        async def script(value, callback, **_):
            await callback({'type': 'qualified', 'value': self.value(100)})
            await release.wait()
            return self.value(200)
        service = self.service(script)
        endpoint = await self.launch(service)
        async with httpx.AsyncClient(timeout=3) as client:
            async with client.stream('POST', endpoint+'/api/economic-quotes/stream', json=economic_request()) as response:
                lines = response.aiter_lines()
                first = json.loads(await anext(lines))
                self.assertEqual(first['type'], 'qualified')
                self.assertEqual(first['value']['quotedOutput'], '100')
                self.assertFalse(release.is_set())
                release.set()
                remaining = [json.loads(line) async for line in lines]
        self.assertEqual([row['type'] for row in remaining], ['qualified', 'complete'])
        self.assertEqual(remaining[0]['value']['quotedOutput'], '200')
        self.assertEqual(remaining[-1]['value'], remaining[0]['value'])


if __name__ == '__main__':
    unittest.main()
