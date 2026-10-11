import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from aiohttp import ClientResponseError, web
from web3 import AsyncWeb3
from web3.exceptions import Web3RPCError

from cybergold_candidate.quote_errors import RpcTimeout, public_quote_error
from cybergold_candidate.quote_cache import IntentSharing
from cybergold_candidate.rpc_diagnostics import (
    RpcDiagnosticsMiddleware,
    error_diagnostics,
    rpc_diagnostic_scope,
    safe_provider_message,
)
from cybergold_candidate.rpc_transport import rpc_provider
from cybergold_candidate.route_search import RouteSearchRpc


class ProviderMessageRedaction(unittest.TestCase):
    def test_benign_provider_text_is_preserved(self):
        message = 'Request limit exceeded. Retry in 10 seconds (code -32005).'
        self.assertEqual(safe_provider_message(message), message)
        self.assertEqual(safe_provider_message(message, secrets=('', None)), message)
        self.assertIsNone(safe_provider_message({'message': message}))
        self.assertIsNone(safe_provider_message('private-password'))
        self.assertEqual(safe_provider_message('Unauthorized'), 'Unauthorized')
        unobserved = public_quote_error(Web3RPCError('fixture', rpc_response={
            'error': {'code': -32000, 'message': 'private provider password'}}))
        self.assertEqual(unobserved['diagnostics']['upstreamErrorCode'], -32000)
        self.assertNotIn('providerMessage', unobserved['diagnostics'])

    def test_url_and_known_credentials_are_removed_including_decoded_values(self):
        url = 'https://fixture-user:short%2Bpass@rpc.example/v3/path%2Fcredential?key=query%2Bsecret'
        message = ('Rate limit exceeded for fixture-user short+pass path/credential query+secret '
                   'at ' + url + '. Retry shortly.')
        value = safe_provider_message(message, secrets=(url,))
        for secret in ('fixture-user', 'short+pass', 'short%2Bpass', 'path/credential',
                       'path%2Fcredential', 'query+secret', 'rpc.example', url):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, value or '')
        self.assertIn('Rate limit exceeded', value)
        self.assertIn('Retry shortly.', value)

    def test_authorization_key_values_and_quoted_credentials_are_removed(self):
        messages = [
            ('Authorization: Bearer fixture-token; rate limit exceeded.', ('fixture-token',)),
            ('Basic dXNlcjpwYXNz; rate limit exceeded.', ('dXNlcjpwYXNz',)),
            ('api_key=fixture-api-key password:fixture-password; retry.',
             ('fixture-api-key', 'fixture-password')),
            ('Invalid secret="violet apricot" token=\'cobalt nectarine\'; retry.',
             ('violet', 'apricot', 'cobalt', 'nectarine')),
        ]
        for message, secrets in messages:
            with self.subTest(message=message):
                value = safe_provider_message(message)
                for secret in secrets:
                    self.assertNotIn(secret, value or '')

    def test_known_short_secret_opaque_token_and_signature_are_removed(self):
        token = 'Fixture9_' * 4
        signature = '0x' + 'a7' * 65
        value = safe_provider_message(
            f'Rate limit for short-key; opaque {token}; signature {signature}. Retry.',
            secrets=('short-key',),
        )
        for secret in ('short-key', token, signature):
            self.assertNotIn(secret, value)
        self.assertIn('Rate limit', value)
        self.assertIn('Retry.', value)

    def test_echoed_short_request_fields_are_removed_without_losing_explanation(self):
        for field in ('params', 'data', 'calldata', 'input', 'arguments', 'request-body'):
            with self.subTest(field=field):
                value = safe_provider_message(
                    f'Provider rejected the request. {field}={{"to":"short-account","input":"short-input"}}')
                self.assertIn('Provider rejected the request.', value)
                self.assertNotIn('short-account', value)
                self.assertNotIn('short-input', value)

    def test_controls_and_size_are_bounded_without_echoing_raw_objects(self):
        value = safe_provider_message('Rate\x00 limit\nexceeded\x7f; ' + 'useful words ' * 100)
        self.assertLessEqual(len(value), 512)
        self.assertFalse(any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value))
        self.assertTrue(value.startswith('Rate'))
        self.assertIsNone(safe_provider_message('https://user:pass@rpc.example/private?token=secret'))


class RpcTransportDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.error = None
        self.http_status = None
        self.hold = False
        self.held_methods = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()

        async def handle(request):
            body = await request.json()
            self.requests.append((body, request.headers.get('Authorization')))
            self.started.set()
            if self.hold and (self.held_methods is None or body['method'] in self.held_methods):
                await self.release.wait()
            if self.http_status:
                return web.Response(status=self.http_status, text='Synthetic provider failure')
            if self.error:
                return web.json_response({'jsonrpc': '2.0', 'id': body['id'], 'error': self.error})
            return web.json_response({'jsonrpc': '2.0', 'id': body['id'], 'result': '0x01'})

        app = web.Application()
        app.router.add_post('/{path:.*}', handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.url = f'http://127.0.0.1:{port}/v3/fixture-path-key?token=fixture-query-key'
        self.authorization = 'Bearer fixture-auth-token'
        self.provider = rpc_provider(self.url, self.authorization, timeout_seconds=.5)
        self.providers = [self.provider]

    async def asyncTearDown(self):
        self.release.set()
        for provider in self.providers:
            await provider.disconnect()
        await self.runner.cleanup()

    def assert_context(self, diagnostics, method, stage, failure_type):
        self.assertEqual(diagnostics['rpcMethod'], method)
        self.assertEqual(diagnostics['stage'], stage)
        self.assertEqual(diagnostics['failureType'], failure_type)
        self.assertGreaterEqual(diagnostics['elapsedMs'], 0)
        self.assertEqual(set(diagnostics) - {
            'rpcMethod', 'stage', 'elapsedMs', 'upstreamErrorCode', 'providerMessage',
            'httpStatus', 'failureType',
        }, set())

    async def test_rpc_error_preserves_wire_fields_numeric_code_and_benign_message(self):
        self.error = {'code': -32005, 'message': 'Request limit exceeded. Retry in 10 seconds.',
                      'data': {'details': 'private-data-7', 'params': ['request-body-7']}}
        params = ['request-body-7']
        with rpc_diagnostic_scope('head-acquisition'):
            response = await self.provider.make_request('eth_blockNumber', params)
            wire = json.loads(json.dumps(response))
            self.assertEqual(wire, {'jsonrpc': '2.0', 'id': self.requests[0][0]['id'], 'error': self.error})
            with self.assertRaises(Web3RPCError) as raised:
                await AsyncWeb3(self.provider).manager.coro_request('eth_blockNumber', params)
            payload = public_quote_error(raised.exception)
        diagnostics = payload['diagnostics']
        self.assert_context(diagnostics, 'eth_blockNumber', 'head-acquisition', 'rpc-error')
        self.assertEqual(diagnostics['upstreamErrorCode'], -32005)
        self.assertEqual(diagnostics['providerMessage'], self.error['message'])
        self.assertEqual(payload['code'], 'rpc-rate-limit')
        public = json.dumps(payload)
        for secret in ('private-data-7', 'request-body-7', self.authorization, self.url):
            self.assertNotIn(secret, public)
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(body['method'] == 'eth_blockNumber' and body['params'] == params
                            and auth == self.authorization for body, auth in self.requests))

    async def test_transport_known_endpoint_and_authorization_secrets_are_redacted(self):
        self.error = {'code': -32005, 'message': (
            'Quota exceeded for fixture-path-key fixture-query-key fixture-auth-token at ' + self.url),
            'data': {'password': 'private-data-7'}}
        with rpc_diagnostic_scope('priority-fee'):
            with self.assertRaises(Web3RPCError) as raised:
                await AsyncWeb3(self.provider).manager.coro_request('eth_maxPriorityFeePerGas', [])
            payload = public_quote_error(raised.exception)
        self.assert_context(payload['diagnostics'], 'eth_maxPriorityFeePerGas', 'priority-fee', 'rpc-error')
        public = json.dumps(payload)
        for secret in ('fixture-path-key', 'fixture-query-key', 'fixture-auth-token',
                       'private-data-7', self.url, self.authorization):
            self.assertNotIn(secret, public)
        self.assertIn('Quota exceeded', payload['diagnostics']['providerMessage'])
        self.assertEqual(len(self.requests), 1)

    async def test_http_504_is_distinct_from_provider_timeout_without_retry(self):
        self.http_status = 504
        with rpc_diagnostic_scope('head-acquisition'):
            with self.assertRaises(ClientResponseError) as raised:
                await self.provider.make_request('eth_getBlockByNumber', ['latest', False])
            diagnostics = error_diagnostics(raised.exception)
            payload = public_quote_error(raised.exception)
        self.assert_context(diagnostics, 'eth_getBlockByNumber', 'head-acquisition', 'http-error')
        self.assertEqual(diagnostics['httpStatus'], 504)
        self.assertEqual(diagnostics['providerMessage'], 'Gateway Timeout')
        self.assertEqual(payload['code'], 'rpc-timeout')
        self.assertEqual(len(self.requests), 1)

    async def test_provider_deadline_keeps_method_stage_and_actual_elapsed(self):
        self.hold = True
        provider = rpc_provider(self.url, self.authorization, timeout_seconds=.05)
        self.providers.append(provider)
        with rpc_diagnostic_scope('priority-fee'):
            with self.assertRaises(RpcTimeout) as raised:
                await provider.make_request('eth_maxPriorityFeePerGas', [])
            diagnostics = error_diagnostics(raised.exception)
            payload = public_quote_error(raised.exception)
        self.assert_context(diagnostics, 'eth_maxPriorityFeePerGas', 'priority-fee', 'provider-timeout')
        self.assertGreater(diagnostics['elapsedMs'], 0)
        self.assertNotIn('httpStatus', diagnostics)
        self.assertEqual(payload['code'], 'rpc-timeout')
        self.assertEqual(len(self.requests), 1)

    async def test_outer_deadline_reports_cancelled_rpc_not_provider_deadline(self):
        self.hold = True
        with rpc_diagnostic_scope('head-acquisition'):
            pending = asyncio.create_task(self.provider.make_request('eth_blockNumber', []))
            await asyncio.wait_for(self.started.wait(), 1)
            with self.assertRaises(TimeoutError) as raised:
                async with asyncio.timeout(.01):
                    await pending
            diagnostics = error_diagnostics(raised.exception)
        self.assert_context(diagnostics, 'eth_blockNumber', 'head-acquisition', 'backend-deadline')
        self.assertNotIn('httpStatus', diagnostics)
        self.assertEqual(len(self.requests), 1)

    async def test_later_outer_deadline_uses_its_own_rpc_instead_of_earlier_longer_call(self):
        self.hold = True
        with rpc_diagnostic_scope('successive-reads'):
            first = asyncio.create_task(self.provider.make_request('eth_blockNumber', []))
            await asyncio.wait_for(self.started.wait(), 1)
            with self.assertRaises(TimeoutError) as raised:
                async with asyncio.timeout(.05):
                    await first
            earlier = error_diagnostics(raised.exception)
            self.assert_context(earlier, 'eth_blockNumber', 'successive-reads', 'backend-deadline')

            self.started.clear()
            second = asyncio.create_task(self.provider.make_request('eth_maxPriorityFeePerGas', []))
            await asyncio.wait_for(self.started.wait(), 1)
            with self.assertRaises(TimeoutError) as raised:
                async with asyncio.timeout(.005):
                    await second
            later = public_quote_error(raised.exception)['diagnostics']
            self.assert_context(later, 'eth_maxPriorityFeePerGas', 'successive-reads', 'backend-deadline')
            self.assertGreater(earlier['elapsedMs'], later['elapsedMs'])
        self.assertEqual([body['method'] for body, _ in self.requests],
                         ['eth_blockNumber', 'eth_maxPriorityFeePerGas'])

    async def test_intent_sharing_preserves_provider_deadline_context_before_routes_start(self):
        self.hold = True
        self.held_methods = {'eth_getBlockByNumber'}
        provider = rpc_provider(self.url, self.authorization, timeout_seconds=.05)
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1',
            NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS='0x' + '3' * 40,
            RPC_URL=self.url, RPC_AUTHORIZATION=self.authorization)
        async def unexpected_routes(request):
            self.fail('Route requests must not start before head acquisition completes')
        client = httpx.AsyncClient(transport=httpx.MockTransport(unexpected_routes))
        rpc = RouteSearchRpc(settings, AsyncWeb3(provider), client)
        service = SimpleNamespace(routes=SimpleNamespace(rpc=rpc), get=AsyncMock())
        sharing = IntentSharing(service)
        try:
            with rpc_diagnostic_scope('head-acquisition'):
                with self.assertRaises(RpcTimeout) as raised:
                    await sharing.get({'mode': 'issue-exact-in'}, lambda frame: asyncio.sleep(0))
                payload = public_quote_error(raised.exception)
            self.assert_context(payload['diagnostics'], 'eth_getBlockByNumber',
                                'head-acquisition', 'provider-timeout')
            self.assertGreater(payload['diagnostics']['elapsedMs'], 0)
            self.assertEqual(payload['code'], 'rpc-timeout')
            self.assertEqual(sharing.started, 0)
            service.get.assert_not_awaited()
            self.assertEqual(len(self.requests), 2)
            self.assertEqual({body['method'] for body, _ in self.requests},
                             {'eth_chainId', 'eth_getBlockByNumber'})
        finally:
            await sharing.close()
            await rpc.close()

    async def test_overlapping_shared_failure_has_independent_caller_stages(self):
        self.hold = True
        self.http_status = 503
        params = [{'to': '0x' + '1' * 40, 'data': '0x1234'},
                  {'blockHash': '0x' + '2' * 64, 'requireCanonical': True}]

        async def caller(stage):
            with rpc_diagnostic_scope(stage):
                try:
                    await self.provider.make_request('eth_call', params)
                except ClientResponseError as error:
                    return public_quote_error(error)
                self.fail('The fixture must fail')

        first = asyncio.create_task(caller('issuance-route'))
        second = asyncio.create_task(caller('redemption-route'))
        await asyncio.wait_for(self.started.wait(), 1)
        self.release.set()
        issued, redeemed = await asyncio.gather(first, second)
        self.assert_context(issued['diagnostics'], 'eth_call', 'issuance-route', 'http-error')
        self.assert_context(redeemed['diagnostics'], 'eth_call', 'redemption-route', 'http-error')
        self.assertEqual(issued['diagnostics']['elapsedMs'], redeemed['diagnostics']['elapsedMs'])
        self.assertIsNot(issued['diagnostics'], redeemed['diagnostics'])
        self.assertEqual(len(self.requests), 1)

    async def test_one_shared_subscriber_timeout_does_not_contaminate_successful_subscriber(self):
        self.hold = True
        params = [{'to': '0x' + '1' * 40, 'data': '0x1234'},
                  {'blockHash': '0x' + '2' * 64, 'requireCanonical': True}]

        async def expiring():
            with rpc_diagnostic_scope('short-route'):
                try:
                    async with asyncio.timeout(.05):
                        await self.provider.make_request('eth_call', params)
                except TimeoutError as error:
                    return error_diagnostics(error)
                self.fail('The held subscriber must time out')

        async def surviving():
            with rpc_diagnostic_scope('long-route'):
                response = await self.provider.make_request('eth_call', params)
                return response, error_diagnostics(ValueError('Unrelated local validation'))

        short = asyncio.create_task(expiring())
        long = asyncio.create_task(surviving())
        await asyncio.wait_for(self.started.wait(), 1)
        diagnostics = await short
        self.assert_context(diagnostics, 'eth_call', 'short-route', 'backend-deadline')
        self.assertFalse(long.done())
        self.release.set()
        response, stale = await long
        self.assertEqual(response['result'], '0x01')
        self.assertIsNone(stale)
        self.assertEqual(len(self.requests), 1)

    async def test_success_and_unrelated_validation_do_not_reuse_prior_rpc_failure(self):
        self.http_status = 429
        with rpc_diagnostic_scope('first-request'):
            with self.assertRaises(ClientResponseError) as raised:
                await self.provider.make_request('eth_blockNumber', [])
            self.assertEqual(error_diagnostics(raised.exception)['httpStatus'], 429)
            self.http_status = None
            self.assertEqual((await self.provider.make_request('eth_blockNumber', []))['result'], '0x01')
            self.assertIsNone(error_diagnostics(ValueError('Local validation failed')))
        with rpc_diagnostic_scope('next-request'):
            payload = public_quote_error(ValueError('Local validation failed'))
            self.assertNotIn('diagnostics', payload)
        self.assertIsNone(error_diagnostics(RpcTimeout('Outside any RPC request')))

    async def test_middleware_keeps_cancelled_rpc_request_local(self):
        self.hold = True

        async def app(scope, receive, send):
            if scope['path'] == '/deadline':
                pending = asyncio.create_task(self.provider.make_request('eth_blockNumber', []))
                await asyncio.wait_for(self.started.wait(), 1)
                try:
                    async with asyncio.timeout(.01):
                        await pending
                except TimeoutError as error:
                    payload = public_quote_error(error)
            else:
                payload = public_quote_error(ValueError('Unrelated validation'))
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': json.dumps(payload).encode()})

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=RpcDiagnosticsMiddleware(app)),
                                     base_url='http://fixture') as client:
            failed = (await client.get('/deadline')).json()
            later = (await client.get('/validation')).json()
        self.assertEqual(failed['diagnostics']['rpcMethod'], 'eth_blockNumber')
        self.assertEqual(failed['diagnostics']['failureType'], 'backend-deadline')
        self.assertNotIn('diagnostics', later)
        self.assertIsNone(error_diagnostics(RpcTimeout('After the middleware request')))
        self.assertEqual(len(self.requests), 1)


if __name__ == '__main__':
    unittest.main()
