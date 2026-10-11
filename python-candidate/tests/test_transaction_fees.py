"""Actual Viem fee policy over synthetic RPC, with canonical HTTP behavior."""
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
from cybergold_candidate.transaction_fees import FeeRpc, TransactionFees

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, config=None, reorg=False, blocked=False, chain='0x7a6a'):
        super().__init__()
        self.config = config or REFERENCE[2]['config']
        self.calls, self.reorg, self.blocked, self.chain = [], reorg, blocked, chain
        self.started, self.cancelled = asyncio.Event(), False

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'eth_getBlockByNumber':
            result = {'number': '0x65', 'timestamp': '0x6a000001',
                      'hash': '0x'+'b'*64 if self.reorg and params[0] != 'latest' else HASH}
            if self.config['base'] is not None:
                result['baseFeePerGas'] = hex(int(self.config['base']))
        elif method in ('eth_maxPriorityFeePerGas', 'eth_gasPrice'):
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            if ((method == 'eth_maxPriorityFeePerGas' and self.config.get('fallback')) or
                (method == 'eth_gasPrice' and self.config.get('gasFailure'))):
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32601, 'message': 'https://password@private.invalid'}}
            result = hex(int(self.config['priority' if method == 'eth_maxPriorityFeePerGas' else 'gas']))
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='0x'+'4'*40, NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=None)
    return TransactionFees(settings, FeeRpc(settings, AsyncWeb3(provider)))


class TransactionFeeTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_viem_estimates_and_supported_priority_fallback(self):
        for row in REFERENCE:
            with self.subTest(config=row['config']):
                provider = Provider(row['config'])
                if row.get('error'):
                    with self.assertRaises(Exception):
                        await service(provider).get()
                else:
                    value = await service(provider).get()
                    self.assertEqual({key:value[key] for key in row['fees']}, row['fees'])
                    self.assertEqual(value['context']['blockHash'], HASH)
                # The same supplier operations plus the existing configured
                # chain/canonicality relationship. No implicit HTTP/RPC retry.
                expected = [call['method'] for call in row['calls']]
                actual = [method for method, _ in provider.calls if method != 'eth_chainId']
                if not row.get('error'):
                    actual = actual[:-1]
                self.assertEqual(actual, expected)

    async def test_changed_canonical_block_returns_no_fee_context(self):
        with self.assertRaises(Exception):
            await service(Provider(reorg=True)).get()

    async def test_wrong_configured_chain_reads_no_fee_supplier(self):
        provider = Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            await service(provider).get()
        self.assertEqual([method for method, _ in provider.calls], ['eth_chainId'])

    async def test_repeated_reads_never_reuse_old_fee_data(self):
        provider = Provider()
        observer = service(provider)
        first = await observer.get()
        provider.config = REFERENCE[0]['config']
        second = await observer.get()
        self.assertNotEqual(first['maxFeePerGas'], second['maxFeePerGas'])
        self.assertEqual(second['maxFeePerGas'], '0')
        self.assertEqual(sum(method == 'eth_maxPriorityFeePerGas' for method, _ in provider.calls), 2)

    async def test_cancellation_does_not_start_priority_fallback(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get())
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.cancelled)
        self.assertFalse(any(method == 'eth_gasPrice' for method, _ in provider.calls))

    async def test_http_head_no_store_and_failure_is_not_zero_fees(self):
        for provider, status in ((Provider(), 200), (Provider(REFERENCE[-1]['config']), 503)):
            app = create_app(transaction_fees=service(provider))
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                value = await client.get('/api/transaction/fees')
                self.assertEqual(value.status_code, status)
                self.assertEqual(value.headers['cache-control'], 'no-store')
                self.assertNotIn('password', value.text)
                if status == 503:
                    self.assertNotIn('maxFeePerGas', value.json())
                    self.assertIn('correlationId', value.json())
                head = await client.head('/api/transaction/fees')
                self.assertEqual(head.status_code, status)
                self.assertEqual(head.content, b'')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
