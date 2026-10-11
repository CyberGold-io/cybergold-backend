"""Actual Viem wire fixtures, empty/failure distinction and canonical context."""
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
from cybergold_candidate.core_recovery_assets import ABI, CoreRecoveryAssets
from cybergold_candidate.protocol_facts import ProtocolFactsRpc

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, empty=False, failure=False, reorg=False, blocked=False, chain='0x7a6a', malformed=False):
        super().__init__()
        self.calls, self.empty, self.failure, self.reorg, self.blocked, self.chain, self.malformed = [], empty, failure, reorg, blocked, chain, malformed
        self.started, self.cancelled = asyncio.Event(), False

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'eth_getBlockByNumber':
            result = {'number': '0x65', 'timestamp': '0x6a000001',
                      'hash': '0x'+'b'*64 if self.reorg and params[0] != 'latest' else HASH}
        elif method == 'eth_call':
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            if self.failure:
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'https://password@private.invalid'}}
            result = '0x' if self.malformed else REFERENCE['empty'] if self.empty else REFERENCE['result']
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE['core'], NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=None)
    return CoreRecoveryAssets(settings, ProtocolFactsRpc(settings, AsyncWeb3(provider), abi=ABI))


class RecoveryAssetsTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_viem_bytes_order_and_canonical_block(self):
        provider = Provider()
        value = await service(provider).get()
        self.assertEqual(value['assets'], REFERENCE['assets'])
        self.assertEqual(value['core'], REFERENCE['core'])
        self.assertEqual(value['context']['blockNumber'], '101')
        self.assertEqual(value['context']['blockHash'], HASH)
        calls = [params for method, params in provider.calls if method == 'eth_call']
        self.assertEqual(calls, [[{'to': REFERENCE['core'], 'data': REFERENCE['data']},
                                 {'blockHash': HASH, 'requireCanonical': True}]])

    async def test_authoritative_empty_list_is_distinct_from_unavailable(self):
        self.assertEqual((await service(Provider(empty=True)).get())['assets'], [])
        for provider in (Provider(failure=True), Provider(malformed=True)):
            with self.assertRaises(Exception):
                await service(provider).get()

    async def test_repeated_observations_do_not_reuse_old_list(self):
        provider = Provider()
        observer = service(provider)
        self.assertEqual((await observer.get())['assets'], REFERENCE['assets'])
        provider.empty = True
        self.assertEqual((await observer.get())['assets'], [])
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 2)

    async def test_changed_canonical_block_is_unavailable(self):
        with self.assertRaises(Exception):
            await service(Provider(reorg=True)).get()

    async def test_wrong_configured_chain_reads_no_contract(self):
        provider = Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            await service(provider).get()
        self.assertFalse(any(method == 'eth_call' for method, _ in provider.calls))

    async def test_cancellation_reaches_contract_read(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get())
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.cancelled)

    async def test_http_fixed_target_head_and_failure_redaction(self):
        for provider, status in ((Provider(), 200), (Provider(failure=True), 503)):
            app = create_app(core_recovery_assets=service(provider))
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                value = await client.get('/api/protocol/recovery-assets?target=untrusted')
                self.assertEqual(value.status_code, status)
                self.assertEqual(value.headers['cache-control'], 'no-store')
                self.assertNotIn('password', value.text)
                if status == 503:
                    self.assertNotIn('assets', value.json())
                    self.assertIn('correlationId', value.json())
                head = await client.head('/api/protocol/recovery-assets')
                self.assertEqual(head.status_code, status)
                self.assertEqual(head.content, b'')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
