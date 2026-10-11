"""Actual Viem receipt/log formatting; native absence differs from outage."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.transaction_receipt import ReceiptRpc, TransactionReceipt

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = REFERENCE[0]['hash']


class Provider(AsyncBaseProvider):
    def __init__(self, receipt=None, failure=False, blocked=False, chain='0x7a6a'):
        super().__init__()
        self.receipt, self.failure, self.blocked, self.chain = receipt, failure, blocked, chain
        self.calls, self.started, self.cancelled = [], asyncio.Event(), False

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'eth_getTransactionReceipt':
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            if self.failure:
                return {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'https://secret:password@private.invalid'}}
            result = self.receipt
        else:
            raise AssertionError(method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid',
        RPC_AUTHORIZATION='Bearer fixture-only', NEXT_PUBLIC_CHAIN_ID='31338')
    return TransactionReceipt(settings, ReceiptRpc(settings, AsyncWeb3(provider)))


class TransactionReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_viem_status_block_identity_and_log_bytes(self):
        for row in REFERENCE:
            provider = Provider(copy.deepcopy(row['raw']))
            result = await service(provider).get(row['hash'])
            self.assertEqual(result['receipt'], row['receipt'])
            self.assertEqual(result['chainId'], 31338)
            self.assertEqual([{'method':method,'params':list(params)} for method,params in provider.calls
                if method=='eth_getTransactionReceipt'], row['calls'])

    async def test_fresh_missing_then_available_then_missing_without_receipt_cache(self):
        provider = Provider()
        observer = service(provider)
        self.assertIsNone((await observer.get(HASH))['receipt'])
        provider.receipt = REFERENCE[0]['raw']
        self.assertIsNotNone((await observer.get(HASH))['receipt'])
        provider.receipt = None
        self.assertIsNone((await observer.get(HASH))['receipt'])
        self.assertEqual(sum(method=='eth_getTransactionReceipt' for method,_ in provider.calls), 3)

    async def test_wrong_chain_never_reads_receipt(self):
        provider = Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError,'chain mismatch'):
            await service(provider).get(HASH)
        self.assertEqual([method for method,_ in provider.calls], ['eth_chainId'])

    async def test_cancellation_stops_provider_read(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get(HASH))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.cancelled)

    async def test_http_outage_is_not_missing_or_replaced(self):
        app = create_app(transaction_receipt=service(Provider(failure=True)))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            result = await client.get('/api/transaction/receipt', params={'hash':HASH})
            self.assertEqual(result.status_code,503)
            self.assertEqual(result.headers['cache-control'],'no-store')
            self.assertNotIn('receipt',result.json())
            self.assertNotIn('password',result.text)
            self.assertIn('correlationId',result.json())

    async def test_invalid_native_receipt_status_is_not_reported_successful(self):
        raw = {**REFERENCE[0]['raw'], 'status':'0x2'}
        with self.assertRaises(KeyError):
            await service(Provider(raw)).get(HASH)

    async def test_fixed_hash_validation_missing_success_and_head(self):
        provider = Provider()
        app = create_app(transaction_receipt=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            result = await client.get('/api/transaction/receipt?hash=private-password')
            self.assertEqual(result.status_code,400)
            self.assertNotIn('private-password',result.text)
            self.assertEqual(provider.calls,[])
            result = await client.get('/api/transaction/receipt', params={'hash':HASH})
            self.assertEqual(result.status_code,200)
            self.assertIsNone(result.json()['receipt'])
            self.assertEqual(result.headers['cache-control'],'no-store')
            head = await client.head('/api/transaction/receipt', params={'hash':HASH})
            self.assertEqual(head.status_code,200)
            self.assertEqual(head.content,b'')


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]])
