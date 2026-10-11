"""Native receipt-wait wire observations, absence/outage and cancellation."""
import asyncio
from types import SimpleNamespace
import unittest

import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.receipt_wait import ReceiptWait, ReceiptWaitRpc

HASH = '0x' + 'ab' * 32
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', RPC_URL='http://synthetic.invalid',
                           RPC_AUTHORIZATION='Bearer fixture-only')


class Provider(AsyncBaseProvider):
    def __init__(self, value=None, chain='0x7a6a'):
        super().__init__()
        self.value, self.chain, self.calls = value, chain, []
        self.failure, self.blocked, self.cancelled = False, False, False
        self.started = asyncio.Event()

    async def make_request(self, method, params):
        self.calls.append((method, list(params)))
        if method == 'eth_chainId':
            return {'jsonrpc': '2.0', 'id': 1, 'result': self.chain}
        self.started.set()
        if self.blocked:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.failure:
            return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000,
                'message': 'https://token:password@private.invalid'}}
        return {'jsonrpc': '2.0', 'id': 1, 'result': self.value}

    async def disconnect(self):
        pass


def service(provider):
    return ReceiptWait(SETTINGS, ReceiptWaitRpc(SETTINGS, AsyncWeb3(provider)))


class ReceiptWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_four_native_operations_preserve_wire_objects_and_wide_quantities(self):
        for operation, argument, method, params, field, value, expected in (
            ('head', None, 'eth_getBlockByNumber', ['latest', False], 'blockNumber',
             {'number': hex(2**200), 'hash': HASH, 'timestamp': '0x64'}, str(2**200)),
            ('transaction', HASH, 'eth_getTransactionByHash', [HASH], 'transaction',
             {'hash': HASH, 'nonce': hex(2**53), 'blockNumber': None, 'value': hex(2**200)},
             {'hash': HASH, 'nonce': hex(2**53), 'blockNumber': None, 'value': hex(2**200)}),
            ('receipt', HASH, 'eth_getTransactionReceipt', [HASH], 'receipt',
             {'transactionHash': HASH, 'status': '0x0', 'logs': []},
             {'transactionHash': HASH, 'status': '0x0', 'logs': []}),
            ('block', '0x123', 'eth_getBlockByNumber', ['0x123', True], 'block',
             {'number': '0x123', 'transactions': [{'hash': HASH}]},
             {'number': '0x123', 'transactions': [{'hash': HASH}]}),
        ):
            provider = Provider(value)
            result = await service(provider).get(operation, argument)
            self.assertEqual(result[field], expected)
            self.assertEqual(result['chainId'], 31338)
            if operation == 'head':
                self.assertEqual(result['blockHash'], HASH)
                self.assertEqual(result['blockTimestamp'], '100')
            self.assertEqual(provider.calls, [('eth_chainId', []), (method, params)])

    async def test_missing_then_available_then_missing_is_fresh_and_never_infers_pending(self):
        provider = Provider()
        observer = service(provider)
        for operation, field in (('transaction', 'transaction'), ('receipt', 'receipt'), ('block', 'block')):
            provider.value = None
            self.assertIsNone((await observer.get(operation, HASH))[field])
            provider.value = {'hash': HASH}
            self.assertEqual((await observer.get(operation, HASH))[field], {'hash': HASH})
            provider.value = None
            self.assertIsNone((await observer.get(operation, HASH))[field])
        self.assertEqual(len(provider.calls), 18)

    async def test_overlapping_head_reads_share_but_later_observations_are_fresh(self):
        provider = Provider({'number': '0x64', 'hash': HASH, 'timestamp': '0x64'})
        observer = service(provider)
        values = await asyncio.gather(*(observer.get('head') for _ in range(5)))
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(all(value['blockHash'] == HASH for value in values))
        provider.value = {'number': '0x64', 'hash': '0x' + 'cd' * 32, 'timestamp': '0x64'}
        value = await observer.get('head')
        self.assertEqual(value['blockHash'], provider.value['hash'])
        self.assertEqual(len(provider.calls), 4)

    async def test_wrong_chain_does_not_read_other_chain_transaction(self):
        provider = Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            await service(provider).get('receipt', HASH)
        self.assertEqual(provider.calls, [('eth_chainId', [])])

    async def test_cancelled_caller_stops_native_read(self):
        provider = Provider()
        provider.blocked = True
        task = asyncio.create_task(service(provider).get('receipt', HASH))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.cancelled)

    async def test_each_fixed_http_operation_and_head_with_no_cache(self):
        provider = Provider('0x64')
        app = create_app(receipt_wait=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for operation, query, method, params in (
                ('head', '', 'eth_getBlockByNumber', ['latest', False]),
                ('transaction', '?hash=' + HASH, 'eth_getTransactionByHash', [HASH]),
                ('receipt', '?hash=' + HASH, 'eth_getTransactionReceipt', [HASH]),
                ('block', '?blockNumber=123', 'eth_getBlockByNumber', ['0x7b', True]),
            ):
                provider.value = {'number': '0x64', 'hash': HASH, 'timestamp': '0x64'} if operation == 'head' else None
                response = await client.get('/api/transaction/wait/' + operation + query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(provider.calls[-1], (method, params))
                response = await client.head('/api/transaction/wait/' + operation + query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b'')
            metrics = (await client.get('/metrics')).text
            self.assertIn('operation="/api/transaction/wait/receipt"', metrics)

    async def test_invalid_hash_or_block_is_ordinary_redacted_request_error(self):
        provider = Provider()
        app = create_app(receipt_wait=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for query in ('receipt?hash=private-password', 'transaction?hash=0x1',
                          'block?blockNumber=latest', 'block?blockNumber=-1'):
                result = await client.get('/api/transaction/wait/' + query)
                self.assertEqual(result.status_code, 400)
                self.assertNotIn('private-password', result.text)
            self.assertEqual(provider.calls, [])

    async def test_provider_failure_is_not_absence_and_later_recovery_works(self):
        provider = Provider()
        provider.failure = True
        app = create_app(receipt_wait=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/api/transaction/wait/receipt?hash=' + HASH)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertNotIn('receipt', response.json())
            self.assertNotIn('password', response.text)
            self.assertIn('correlationId', response.json())
            provider.failure = False
            response = await client.get('/api/transaction/wait/receipt?hash=' + HASH)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()['receipt'])


if __name__ == '__main__':
    unittest.main()
