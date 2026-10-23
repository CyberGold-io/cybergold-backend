"""Concrete Swap simulation/gas calldata versus independent Viem encoding."""
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
from cybergold_candidate.helpers_execution import HelpersExecution, HelpersExecutionRequest, HelpersExecutionRpc
from cybergold_candidate.rpc_diagnostics import error_diagnostics, rpc_diagnostic_scope

ROWS = json.loads(Path(sys.argv[1]).read_text())
HASH = '0x'+'a'*64


class Provider(AsyncBaseProvider):
    def __init__(self, failure=None, blocked=False, reorg=False, chain='0x7a6a'):
        super().__init__()
        self.calls = []
        self.failure, self.blocked, self.reorg, self.chain = failure, blocked, reorg, chain
        self.started, self.cancelled = asyncio.Event(), False
        self.error_override = None

    async def make_request(self, method, params):
        self.calls.append({'method': method, 'params': list(params)})
        if method == 'eth_chainId':
            result = self.chain
        elif method == 'eth_getBlockByNumber':
            result = {'number': '0x65', 'timestamp': '0x6a000001',
                      'hash': '0x'+'b'*64 if self.reorg and params[0] != 'latest' else HASH}
        elif method in ('eth_call', 'eth_estimateGas'):
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            if self.failure == method:
                return {'jsonrpc': '2.0', 'id': 1, 'error': self.error_override or {'code': 3, 'message': 'execution reverted https://password@private.invalid'}}
            if self.failure == 'decode' and method == 'eth_call':
                result = '0x'
            else:
                row = next(row for row in ROWS if row['calls'][0]['params'][0] == params[0])
                expected = next(call for call in row['calls'] if call['method'] == method)
                if expected['params'] != list(params):
                    raise AssertionError('Original latest-state request changed')
                result = row['encoded'] if method == 'eth_call' else hex(int(row['gas']))
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer fixture',
        NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=ROWS[0]['helpers'])
    return HelpersExecution(settings, HelpersExecutionRpc(settings, AsyncWeb3(provider)))


class HelpersExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_viem_payloads_native_values_and_wide_gas(self):
        self.assertEqual(len(ROWS), 16)
        for row in ROWS:
            provider = Provider()
            result = await service(provider).get(HelpersExecutionRequest.model_validate(row['payload']))
            self.assertEqual(result['gas'], row['gas'])
            self.assertEqual(result['blockTag'], 'latest')
            self.assertEqual([call for call in provider.calls if call['method'] in ('eth_call', 'eth_estimateGas')], row['calls'])

    async def test_true_exact_out_mixed_basket_preserves_order_permit_amount_and_compact_permit2_subset(self):
        rows = [row for row in ROWS if row['payload']['operation'].endswith('WithMixedPermits')]
        self.assertEqual(len(rows), 2)
        for row in rows:
            provider = Provider()
            payload = HelpersExecutionRequest.model_validate(row['payload'])
            await service(provider).get(payload)
            inputs, permit2 = payload.args[1:]
            self.assertEqual([part['authorization'] for part in inputs], [0, 1, 2])
            self.assertEqual(inputs[1]['permit']['value'], inputs[1]['maximumInputAmount'])
            self.assertEqual(permit2['permit']['permitted'], [
                {'token': inputs[2]['token'], 'amount': inputs[2]['maximumInputAmount']}])
            self.assertEqual([call for call in provider.calls if call['method'] in ('eth_call', 'eth_estimateGas')], row['calls'])

    async def test_concurrent_signed_intents_are_isolated_and_uncached(self):
        provider = Provider()
        observer = service(provider)
        results = await asyncio.gather(*(observer.get(HelpersExecutionRequest.model_validate(row['payload'])) for row in ROWS))
        self.assertEqual([value['gas'] for value in results], [row['gas'] for row in ROWS])
        await observer.get(HelpersExecutionRequest.model_validate(ROWS[0]['payload']))
        self.assertEqual(sum(call['method'] == 'eth_estimateGas' for call in provider.calls), len(ROWS) + 1)

    async def test_chain_and_changed_head_do_not_publish_a_fee_observation(self):
        provider = Provider(chain='0x1')
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            await service(provider).get(HelpersExecutionRequest.model_validate(ROWS[0]['payload']))
        self.assertEqual([call['method'] for call in provider.calls], ['eth_chainId'])
        with self.assertRaisesRegex(ValueError, 'head changed'):
            await service(Provider(reorg=True)).get(HelpersExecutionRequest.model_validate(ROWS[0]['payload']))

    async def test_cancellation_stops_simulation_before_estimation(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get(HelpersExecutionRequest.model_validate(ROWS[0]['payload'])))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.cancelled)
        self.assertFalse(any(call['method'] == 'eth_estimateGas' for call in provider.calls))

    async def test_simulation_decode_and_estimation_failures_are_redacted(self):
        for failure in ('eth_call', 'decode', 'eth_estimateGas'):
            provider = Provider(failure=failure)
            app = create_app(helpers_execution=service(provider))
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                result = await client.post('/api/transaction/helpers-execution', json=ROWS[0]['payload'])
                self.assertEqual(result.status_code, 503)
                self.assertEqual(result.headers['cache-control'], 'no-store')
                self.assertNotIn('password', result.text)
                self.assertNotIn('gas', result.json())
            if failure != 'eth_estimateGas':
                self.assertFalse(any(call['method'] == 'eth_estimateGas' for call in provider.calls))

    async def test_fixed_operation_shape_and_native_abi_errors(self):
        provider = Provider()
        app = create_app(helpers_execution=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            self.assertEqual((await client.post('/api/transaction/helpers-execution', content='{')).status_code, 400)
            self.assertEqual((await client.post('/api/transaction/helpers-execution', json={**ROWS[0]['payload'], 'operation': 'arbitrary'})).status_code, 400)
            result = await client.post('/api/transaction/helpers-execution', json={**ROWS[0]['payload'], 'provider': 'http://untrusted.invalid', 'contractAddress': '0x'+'9'*40})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['helpers'], ROWS[0]['helpers'])
            result = await client.post('/api/transaction/helpers-execution', json={**ROWS[0]['payload'], 'args': []})
            self.assertEqual(result.status_code, 503)
        self.assertTrue(all(call['method'] in ('eth_call', 'eth_estimateGas', 'eth_chainId', 'eth_getBlockByNumber') for call in provider.calls))

    async def test_simulation_and_estimation_preserve_rpc_stage_and_known_revert_identity(self):
        for signature, types, values, code in (
                ('NativeValueMismatch(uint256,uint256)', ['uint256','uint256'], [100, 99], 'quote-contract-reverted'),
                ('InsufficientCygldSupply()', [], [], 'redemption-supply-exceeded'),
                ('InsufficientReserveBalance()', [], [], 'insufficient-reserve-balance'),
                ('InsufficientRecoveryShares()', [], [], 'insufficient-recovery-shares')):
            selector = AsyncWeb3.to_hex(AsyncWeb3.keccak(text=signature))[:10]
            data = selector+AsyncWeb3().codec.encode(types, values).hex()
            for method, stage in [('eth_call','helpers-simulation'), ('eth_estimateGas','helpers-gas-estimation')]:
                with self.subTest(method=method, signature=signature):
                    provider = Provider(failure=method)
                    provider.error_override = {'code': 3, 'message': 'execution reverted https://password@private.invalid', 'data': data}
                    app = create_app(helpers_execution=service(provider))
                    async with app.router.lifespan_context(app), httpx.AsyncClient(
                            transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                        with self.assertLogs('cybergold.candidate', level='ERROR') as logs:
                            result = await client.post('/api/transaction/helpers-execution', json=ROWS[0]['payload'])
                    payload = result.json()
                    diagnostic = payload['diagnostics']
                    self.assertEqual(result.status_code, 503)
                    self.assertEqual(payload['code'], code)
                    self.assertEqual(diagnostic['rpcMethod'], method)
                    self.assertEqual(diagnostic['stage'], stage)
                    self.assertEqual(diagnostic['upstreamErrorCode'], 3)
                    self.assertEqual(diagnostic['errorSelector'], selector)
                    self.assertEqual(diagnostic['errorName'], signature.split('(')[0])
                    self.assertEqual(sum(row['method'] == method for row in provider.calls), 1)
                    if method == 'eth_call':
                        self.assertFalse(any(row['method'] == 'eth_estimateGas' for row in provider.calls))
                    record = json.loads(logs.records[-1].getMessage())
                    self.assertEqual(record['diagnostics'], diagnostic)
                    self.assertEqual(record['requestId'], result.headers['X-CyberGold-Request-Id'])
                    self.assertEqual(record['correlationId'], payload['correlationId'])
                    # Selectors are public diagnostics; encoded return arguments stay private.
                    if types:
                        self.assertNotIn(data, result.text+record.__repr__())
                    self.assertNotIn('password', result.text+record.__repr__())

    async def test_backend_deadline_retains_the_simulation_stage_without_inventing_provider_error(self):
        provider = Provider(blocked=True)
        observer = service(provider)
        with rpc_diagnostic_scope():
            try:
                async with asyncio.timeout(.01):
                    await observer.rpc.estimate(ROWS[0]['helpers'], HelpersExecutionRequest.model_validate(ROWS[0]['payload']))
            except TimeoutError as error:
                diagnostics = error_diagnostics(error)
            else:
                self.fail('Blocked simulation should reach the existing caller deadline')
        self.assertEqual(diagnostics['rpcMethod'],'eth_call')
        self.assertEqual(diagnostics['stage'],'helpers-simulation')
        self.assertEqual(diagnostics['failureType'],'backend-deadline')
        self.assertGreater(diagnostics['elapsedMs'],0)
        self.assertNotIn('providerMessage',diagnostics)
        self.assertNotIn('upstreamErrorCode',diagnostics)
        self.assertTrue(provider.cancelled)
        self.assertFalse(any(row['method']=='eth_estimateGas' for row in provider.calls))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
