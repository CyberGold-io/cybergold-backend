"""Actual Viem pending-nonce wire requests and fresh Web3/HTTP behavior."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import httpx
from web3 import AsyncWeb3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.transaction_nonce import NonceRpc, TransactionNonce

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x'+'a'*64
OWNER = '0x'+'1'*40
OTHER = '0x'+'2'*40


class Provider(AsyncBaseProvider):
    def __init__(self, nonce=7, failure=False, reorg=False, blocked=False, chain='0x7a6a'):
        super().__init__()
        self.nonce, self.failure, self.reorg, self.blocked, self.chain = nonce, failure, reorg, blocked, chain
        self.calls, self.started, self.cancelled = [], asyncio.Event(), False

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'eth_getBlockByNumber':
            result = {'number': '0x65', 'timestamp': '0x6a000001',
                'hash': '0x'+'b'*64 if self.reorg and params[0] != 'latest' else HASH}
        elif method == 'eth_getTransactionCount':
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            if self.failure:
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000,
                    'message': 'https://secret:password@private.invalid'}}
            value = self.nonce.get(params[0].lower(), 0) if isinstance(self.nonce, dict) else self.nonce
            result = hex(value)
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


def service(provider):
    # This account operation does not require Core/Helpers/Safe metadata.
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid',
        RPC_AUTHORIZATION='Bearer fixture-only', NEXT_PUBLIC_CHAIN_ID='31338')
    return TransactionNonce(settings, NonceRpc(settings, AsyncWeb3(provider)))


class TransactionNonceTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_viem_wire_requests_and_lossless_nonce(self):
        for row in REFERENCE:
            provider = Provider(int(row['nonce']))
            result = await service(provider).get(row['owner'])
            self.assertEqual(result['nonce'], row['nonce'])
            self.assertEqual(result['blockTag'], 'pending')
            self.assertEqual(result['context']['blockHash'], HASH)
            calls = [{'method': method, 'params': list(params)} for method,params in provider.calls
                     if method == 'eth_getTransactionCount']
            self.assertEqual(calls, row['calls'])
            if not row.get('error'):
                self.assertEqual(result['nonce'], row['value'])

    async def test_concurrent_owners_and_successive_calls_do_not_share_or_reserve_nonce(self):
        provider = Provider({OWNER: 4, OTHER: 90})
        observer = service(provider)
        values = await asyncio.gather(observer.get(OWNER), observer.get(OTHER))
        self.assertEqual([value['nonce'] for value in values], ['4', '90'])
        provider.nonce[OWNER] = 8
        self.assertEqual((await observer.get(OWNER))['nonce'], '8')
        self.assertEqual(sum(method == 'eth_getTransactionCount' for method,_ in provider.calls), 3)

    async def test_reorg_does_not_supply_a_nonce_with_old_head_context(self):
        with self.assertRaisesRegex(ValueError, 'head changed'):
            await service(Provider(reorg=True)).get(OWNER)

    async def test_wrong_chain_never_reads_account_nonce(self):
        provider = Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            await service(provider).get(OWNER)
        self.assertEqual([method for method,_ in provider.calls], ['eth_chainId'])

    async def test_cancellation_stops_pending_provider_request(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get(OWNER))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.cancelled)

    async def test_http_outage_is_redacted_unavailable_and_never_zero(self):
        app = create_app(transaction_nonce=service(Provider(failure=True)))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            result = await client.get('/api/account/transaction-nonce', params={'owner':OWNER})
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.headers['cache-control'], 'no-store')
            self.assertNotIn('nonce', result.json())
            self.assertNotIn('password', result.text)
            self.assertIn('correlationId', result.json())

    async def test_fixed_http_validation_head_and_no_store(self):
        provider = Provider()
        app = create_app(transaction_nonce=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            result = await client.get('/api/account/transaction-nonce?owner=private-password')
            self.assertEqual(result.status_code, 400)
            self.assertNotIn('private-password', result.text)
            self.assertEqual(provider.calls, [])
            result = await client.get('/api/account/transaction-nonce',
                params={'owner':OWNER,'provider':'http://untrusted.invalid','blockTag':'latest'})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['blockTag'], 'pending')
            self.assertEqual(result.headers['cache-control'], 'no-store')
            head = await client.head('/api/account/transaction-nonce', params={'owner':OWNER})
            self.assertEqual(head.status_code, 200)
            self.assertEqual(head.content, b'')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
