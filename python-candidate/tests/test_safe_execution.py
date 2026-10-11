"""Original Viem Safe simulation bytes and success/revert behavior."""
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
from cybergold_candidate.safe_execution import SafeExecution, SafeExecutionRequest, SafeExecutionRpc

ROWS = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, failure=False, blocked=False, reorg=False, chain='0x7a6a'):
        super().__init__()
        self.calls = []
        self.failure, self.blocked, self.reorg, self.chain = failure, blocked, reorg, chain
        self.started, self.cancelled = asyncio.Event(), False

    async def make_request(self, method, params):
        self.calls.append({'method': method, 'params': list(params)})
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
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'message': 'execution reverted https://password@private.invalid'}}
            row = next(row for row in ROWS if row['calls'][0]['params'] == list(params))
            result = row['encoded']
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture', NEXT_PUBLIC_CHAIN_ID='31338')
    return SafeExecution(settings, SafeExecutionRpc(settings, AsyncWeb3(provider)))


class SafeExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_viem_execution_bytes_sender_nonce_and_false_result(self):
        for row in ROWS:
            provider = Provider()
            result = await service(provider).get(SafeExecutionRequest.model_validate(row['payload']))
            self.assertEqual(result['success'], row['result'])
            self.assertEqual(result['executorNonce'], row['payload']['executorNonce'])
            self.assertEqual(result['blockTag'], 'latest')
            self.assertEqual([call for call in provider.calls if call['method'] == 'eth_call'], row['calls'])

    async def test_concurrent_exact_payloads_are_independent_and_never_cached(self):
        provider = Provider()
        observer = service(provider)
        results = await asyncio.gather(*(observer.get(SafeExecutionRequest.model_validate(row['payload'])) for row in ROWS))
        self.assertEqual([value['success'] for value in results], [row['result'] for row in ROWS])
        await observer.get(SafeExecutionRequest.model_validate(ROWS[0]['payload']))
        self.assertEqual(sum(call['method'] == 'eth_call' for call in provider.calls), 4)

    async def test_wrong_chain_does_not_simulate(self):
        provider = Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            await service(provider).get(SafeExecutionRequest.model_validate(ROWS[0]['payload']))
        self.assertEqual([call['method'] for call in provider.calls], ['eth_chainId'])

    async def test_changed_head_does_not_publish_simulation_context(self):
        with self.assertRaisesRegex(ValueError, 'head changed'):
            await service(Provider(reorg=True)).get(SafeExecutionRequest.model_validate(ROWS[0]['payload']))

    async def test_cancellation_stops_the_provider_simulation(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get(SafeExecutionRequest.model_validate(ROWS[0]['payload'])))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.cancelled)

    async def test_http_revert_is_redacted_and_never_success(self):
        app = create_app(safe_execution=service(Provider(failure=True)))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            result = await client.post('/api/governance/safe-execution', json=ROWS[0]['payload'])
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.headers['cache-control'], 'no-store')
            self.assertNotIn('password', result.text)
            self.assertNotIn('success', result.json())

    async def test_fixed_http_shapes_false_and_native_abi_errors(self):
        provider = Provider()
        app = create_app(safe_execution=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            self.assertEqual((await client.post('/api/governance/safe-execution', content='{')).status_code, 400)
            self.assertEqual((await client.post('/api/governance/safe-execution', json={})).status_code, 400)
            result = await client.post('/api/governance/safe-execution', json={**ROWS[1]['payload'], 'provider': 'http://untrusted.invalid'})
            self.assertEqual(result.status_code, 200)
            self.assertIs(result.json()['success'], False)
            self.assertEqual(result.headers['cache-control'], 'no-store')
            result = await client.post('/api/governance/safe-execution', json={**ROWS[0]['payload'], 'operation': 256})
            self.assertEqual(result.status_code, 503)
            self.assertNotIn('success', result.json())
        self.assertTrue(all(call['method'] in ('eth_call', 'eth_chainId', 'eth_getBlockByNumber') for call in provider.calls))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
