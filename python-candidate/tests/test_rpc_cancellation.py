import asyncio
import json
import unittest

import httpx
from starlette.requests import Request

from cybergold_candidate.rpc_http import RpcHttp


class RpcCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_http_disconnect_cancels_the_pending_supplier(self):
        entered, disconnected, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def supplier(request):
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()
        body = json.dumps({'jsonrpc': '2.0', 'id': 'caller', 'method': 'eth_chainId'}).encode()
        consumed = False
        async def receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            await disconnected.wait()
            return {'type': 'http.disconnect'}
        request = Request({'type': 'http', 'method': 'POST', 'headers': []}, receive)
        async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as client:
            rpc = RpcHttp(client, 'https://fixture.invalid/rpc')
            task = asyncio.create_task(rpc.handle(request))
            await entered.wait()
            disconnected.set()
            response = await asyncio.wait_for(task, 1)
            self.assertEqual(response.status_code, 504)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(json.loads(response.body)['id'], 'caller')
            rpc.close()


if __name__ == '__main__':
    unittest.main()
