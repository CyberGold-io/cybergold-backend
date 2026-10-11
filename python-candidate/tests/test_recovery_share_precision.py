"""Actual Viem pool bytes, permanent ID precision and unavailable/cancelled reads."""
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
from cybergold_candidate.protocol_facts import ProtocolFactsRpc
from cybergold_candidate.recovery_share_precision import ABI, RecoverySharePrecision

REFERENCE = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x' + 'a' * 64


class Provider(AsyncBaseProvider):
    def __init__(self, case=0, failure=False, malformed=False, reorg=False, blocked=False, chain='0x7a6a'):
        super().__init__()
        self.case, self.failure, self.malformed, self.reorg, self.blocked, self.chain = case, failure, malformed, reorg, blocked, chain
        self.calls, self.cancelled = [], False
        self.started = asyncio.Event()

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'eth_getBlockByNumber':
            result = {'number': '0x65', 'timestamp': '0x6a000001',
                      'hash': '0x' + 'b' * 64 if self.reorg and params[0] != 'latest' else HASH}
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
            result = '0x' if self.malformed else REFERENCE[self.case]['result']
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=REFERENCE[0]['core'], NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=None)
    return RecoverySharePrecision(settings, ProtocolFactsRpc(settings, AsyncWeb3(provider), abi=ABI))


class PrecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_viem_calldata_and_zero_six_eighteen_max_precision(self):
        for index, case in enumerate(REFERENCE):
            provider = Provider(case=index)
            value = await service(provider).get(case['asset'])
            self.assertEqual(value['asset'].lower(), case['asset'].lower())
            self.assertEqual(value['shareDecimals'], case['shareDecimals'])
            self.assertEqual(value['context']['blockNumber'], '101')
            calls = [params for method, params in provider.calls if method == 'eth_call']
            self.assertEqual(calls, [[{'to': case['core'], 'data': case['data']},
                                    {'blockHash': HASH, 'requireCanonical': True}]])

    async def test_asset_specific_observations_do_not_reuse_another_ids_precision(self):
        provider = Provider(case=1)
        observer = service(provider)
        self.assertEqual((await observer.get(REFERENCE[1]['asset']))['shareDecimals'], 6)
        provider.case = 2
        self.assertEqual((await observer.get(REFERENCE[2]['asset']))['shareDecimals'], 18)
        self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 2)

    async def test_failed_or_malformed_pool_is_not_zero_precision(self):
        for provider in (Provider(failure=True), Provider(malformed=True)):
            with self.assertRaises(Exception):
                await service(provider).get(REFERENCE[0]['asset'])

    async def test_reorg_and_wrong_chain_are_unavailable(self):
        with self.assertRaises(Exception):
            await service(Provider(reorg=True)).get(REFERENCE[0]['asset'])
        provider = Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            await service(provider).get(REFERENCE[0]['asset'])
        self.assertFalse(any(method == 'eth_call' for method, _ in provider.calls))

    async def test_cancellation_reaches_the_private_rpc_read(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get(REFERENCE[0]['asset']))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.cancelled)

    async def test_fixed_http_target_head_failure_redaction_and_ordinary_address_errors(self):
        for provider, status in ((Provider(), 200), (Provider(failure=True), 503)):
            app = create_app(recovery_share_precision=service(provider))
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                path = '/api/protocol/recovery-share-precision?asset=' + REFERENCE[0]['asset'] + '&core=untrusted'
                value = await client.get(path)
                self.assertEqual(value.status_code, status)
                self.assertEqual(value.headers['cache-control'], 'no-store')
                self.assertNotIn('password', value.text)
                if status == 503:
                    self.assertNotIn('shareDecimals', value.json())
                    self.assertIn('correlationId', value.json())
                head = await client.head(path)
                self.assertEqual(head.status_code, status)
                self.assertEqual(head.content, b'')
                self.assertEqual((await client.get('/api/protocol/recovery-share-precision?asset=bad')).status_code, 400)
                self.assertEqual((await client.get('/api/protocol/recovery-share-precision')).status_code, 400)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
