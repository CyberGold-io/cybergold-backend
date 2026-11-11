"""Independent pool getters share one physical POST without changing read scope."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from aiohttp import ClientResponseError, web
from eth_abi.exceptions import InsufficientDataBytes
from web3 import AsyncWeb3, Web3

from cybergold_candidate.quote_errors import QuoteFailure, RpcTimeout
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
from cybergold_candidate.rpc_transport import rpc_provider
from cybergold_candidate.search_observations import search_observation_scope
from cybergold_candidate.uniswap_state import PoolRegistry, UniswapRpc


A, B, POOL = ('0x' + format(i, '040x') for i in (1, 2, 3))
PIN = {'number': 123, 'hash': '0x' + 'ab' * 32}
SLOT = (1 << 96, -12, 1, 2, 3, 0x65, True)
SLOT_TYPES = ['uint160', 'int24', 'uint16', 'uint16', 'uint16', 'uint8', 'bool']
CALLS = [(POOL, 'slot0()', [], [], SLOT_TYPES),
         (POOL, 'liquidity()', [], [], ['uint128'])]


class GetterBatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests, self.errors, self.malformed = [], {}, set()
        self.http_status, self.batch_error = None, None
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()
        self.liquidity = 1000

        async def request(req):
            payload = await req.json()
            self.requests.append((deepcopy(payload), req.headers.get('Authorization')))
            self.started.set()
            await self.release.wait()
            if self.http_status:
                return web.Response(status=self.http_status)
            if self.batch_error:
                return web.json_response({'jsonrpc': '2.0', 'id': None, 'error': self.batch_error})
            rows = []
            for member in payload if isinstance(payload, list) else [payload]:
                signature = next(name for name in ('slot0()', 'liquidity()')
                    if member['params'][0]['data'] == Web3.to_hex(Web3.keccak(text=name)[:4]))
                row = {'jsonrpc': '2.0', 'id': member['id']}
                if signature in self.errors:
                    row['error'] = self.errors[signature]
                elif signature in self.malformed:
                    row['result'] = '0x01'
                else:
                    types, values = (SLOT_TYPES, SLOT) if signature == 'slot0()' else (['uint128'], [self.liquidity])
                    row['result'] = Web3.to_hex(Web3().codec.encode(types, values))
                rows.append(row)
            # JSON-RPC does not guarantee response order.
            return web.json_response(list(reversed(rows)) if isinstance(payload, list) else rows[0])

        app = web.Application()
        app.router.add_post('/', request)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A,
            RPC_URL=f'http://127.0.0.1:{port}/', RPC_AUTHORIZATION='Bearer getter-fixture')
        self.rpc = UniswapRpc(self.settings)
        self.addAsyncCleanup(self.runner.cleanup)
        self.addAsyncCleanup(self.rpc.close)

    async def getters(self, block=PIN):
        return await self.rpc.read_functions(CALLS, block)

    async def test_v3_snapshot_uses_one_authenticated_post_and_reordered_members(self):
        registry = PoolRegistry(self.settings, rpc=self.rpc)
        self.addAsyncCleanup(registry.close)
        pool = {'id': POOL, 'address': POOL, 'protocol': 'v3', 'feePips': 500, 'tickSpacing': 10,
            'token0': {'address': A, 'decimals': 18}, 'token1': {'address': B, 'decimals': 18}}
        snapshot = await registry.snapshot(pool, PIN, publish=False)
        self.assertEqual((snapshot['sqrtRatioX96'], snapshot['tick'], snapshot['liquidity'],
            snapshot['protocolFee'], snapshot['lpFee']), (str(SLOT[0]), -12, '1000', 0x65, 500))
        self.assertEqual(snapshot['context'], {'chainId': 1, 'blockNumber': '123', 'blockHash': PIN['hash']})
        self.assertEqual(len(self.requests), 1)
        body, authorization = self.requests[0]
        self.assertEqual(authorization, 'Bearer getter-fixture')
        self.assertEqual(len(body), 2)
        self.assertTrue(all(row['params'][1] == {'blockHash': PIN['hash'], 'requireCanonical': True} for row in body))

    async def test_partial_cache_sends_only_missing_getter_and_single_read_reuses_batch(self):
        self.assertEqual(await self.rpc.read_function(*CALLS[0], PIN), SLOT)
        self.assertEqual(await self.getters(), [SLOT, (1000,)])
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(isinstance(body, dict) for body, _ in self.requests))
        self.assertEqual(await self.rpc.read_function(*CALLS[1], PIN), (1000,))
        self.assertEqual(await self.getters(), [SLOT, (1000,)])
        self.assertEqual(len(self.requests), 2)

    async def test_rpc_member_failure_does_not_discard_successful_independent_getter(self):
        self.errors['liquidity()'] = {'code': -32005, 'message': 'Request quota reached.'}
        with self.assertRaises(QuoteFailure) as raised:
            await self.getters()
        self.assertEqual(raised.exception.code, 'rpc-rate-limit')
        self.assertEqual(raised.exception.rpc_diagnostics['rpcMethod'], 'eth_call')
        self.assertEqual(raised.exception.rpc_diagnostics['upstreamErrorCode'], -32005)
        self.assertEqual(len(self.rpc.reads.completed), 1)
        del self.errors['liquidity()']
        self.assertEqual(await self.getters(), [SLOT, (1000,)])
        self.assertEqual(len(self.requests), 2)
        self.assertIsInstance(self.requests[-1][0], dict)
        self.assertEqual(self.requests[-1][0]['params'][0]['data'], Web3.to_hex(Web3.keccak(text='liquidity()')[:4]))

    async def test_typed_member_failure_is_not_cached_and_other_member_is_reusable(self):
        self.malformed.add('slot0()')
        with self.assertRaises(InsufficientDataBytes):
            await self.getters()
        self.assertEqual(len(self.rpc.reads.completed), 1)
        self.malformed.clear()
        self.assertEqual(await self.getters(), [SLOT, (1000,)])
        self.assertEqual(len(self.requests), 2)
        self.assertIsInstance(self.requests[-1][0], dict)
        self.assertEqual(self.requests[-1][0]['params'][0]['data'], Web3.to_hex(Web3.keccak(text='slot0()')[:4]))

    async def test_other_raw_bank_subscribers_receive_the_same_typed_failure_not_a_private_envelope(self):
        self.malformed.add('liquidity()')
        self.release.clear()
        batch = asyncio.create_task(self.getters())
        await asyncio.wait_for(self.started.wait(), 1)
        key = next(key for key in self.rpc.reads.pending
            if key[-1] == Web3.to_hex(Web3.keccak(text='liquidity()')[:4]))
        async def forbidden(_keys):
            raise AssertionError('The independent raw reader must join the existing getter')
        raw = asyncio.create_task(self.rpc.reads.many([key], forbidden, retain=True))
        async def joined():
            while self.rpc.reads.pending[key].users < 2:
                await asyncio.sleep(0)
        await asyncio.wait_for(joined(), 1)
        self.release.set()
        batch_result, raw_result = await asyncio.gather(batch, raw, return_exceptions=True)
        self.assertIsInstance(batch_result, InsufficientDataBytes)
        self.assertIs(raw_result, batch_result)
        self.assertEqual(len(self.rpc.reads.completed), 1)
        self.assertEqual(len(self.requests), 1)

    async def test_latest_is_fresh_between_scopes_and_shared_only_inside_search(self):
        for _ in range(2):
            await self.getters(LATEST_BLOCK)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.rpc.reads.completed, {})
        async with search_observation_scope():
            self.assertEqual(await self.getters(LATEST_BLOCK), [SLOT, (1000,)])
            self.liquidity = 2000
            self.assertEqual(await self.getters(LATEST_BLOCK), [SLOT, (1000,)])
        async with search_observation_scope():
            self.assertEqual(await self.getters(LATEST_BLOCK), [SLOT, (2000,)])
        self.assertEqual(len(self.requests), 4)
        self.assertTrue(all(row['params'][1] == 'latest' for body, _ in self.requests for row in body))

    async def test_whole_batch_http_and_rpc_failures_keep_ordinary_errors_and_allow_retry(self):
        self.http_status = 503
        with self.assertRaises(ClientResponseError) as raised:
            await self.getters()
        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(raised.exception.rpc_diagnostics['rpcMethod'], 'eth_call')
        self.assertFalse(self.rpc.reads.completed)
        self.http_status = None
        self.batch_error = {'code': -32005, 'message': 'Request quota reached.'}
        with self.assertRaises(QuoteFailure) as raised:
            await self.getters()
        self.assertEqual(raised.exception.code, 'rpc-rate-limit')
        self.assertFalse(self.rpc.reads.completed)
        self.batch_error = None
        self.assertEqual(await self.getters(), [SLOT, (1000,)])
        self.assertEqual(len(self.requests), 3)

    async def test_batch_transport_timeout_remains_rpc_timeout_and_is_not_retained(self):
        await self.rpc.w3.provider.disconnect()
        self.rpc.w3 = AsyncWeb3(rpc_provider(self.settings.RPC_URL, self.settings.RPC_AUTHORIZATION, .03))
        self.release.clear()
        try:
            with self.assertRaises(RpcTimeout) as raised:
                await self.getters()
            self.assertEqual(raised.exception.rpc_diagnostics['rpcMethod'], 'eth_call')
            self.assertFalse(self.rpc.reads.pending)
            self.assertFalse(self.rpc.reads.groups)
            self.assertFalse(self.rpc.reads.completed)
        finally:
            self.release.set()
        self.assertEqual(await self.getters(), [SLOT, (1000,)])

    async def test_sandbox_pinned_reads_do_not_retain_completed_getters(self):
        self.rpc.chain_id = 31338
        await self.getters()
        self.liquidity = 2000
        self.assertEqual(await self.getters(), [SLOT, (2000,)])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.rpc.reads.completed, {})

    async def test_cancelled_batch_subscriber_keeps_overlapping_single_getter_alive(self):
        self.release.clear()
        first = asyncio.create_task(self.getters())
        await asyncio.wait_for(self.started.wait(), 1)
        second = asyncio.create_task(self.rpc.read_function(*CALLS[1], PIN))
        for _ in range(5):
            await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertFalse(second.done())
        self.assertEqual(len(self.requests), 1)
        self.release.set()
        self.assertEqual(await second, (1000,))
        self.assertFalse(self.rpc.reads.pending)
        self.assertFalse(self.rpc.reads.groups)

    async def test_last_subscriber_cancellation_drains_then_allows_a_fresh_batch(self):
        self.release.clear()
        task = asyncio.create_task(self.getters())
        await asyncio.wait_for(self.started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.rpc.reads.pending)
        self.assertFalse(self.rpc.reads.groups)
        self.assertFalse(self.rpc.reads.completed)
        self.release.set()
        self.assertEqual(await self.getters(), [SLOT, (1000,)])
        self.assertEqual(len(self.requests), 2)


if __name__ == '__main__':
    unittest.main()
