"""Whole-wave quote coverage, wire batches, selection and ordinary recovery."""
import asyncio
import json
from types import SimpleNamespace
import unittest

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.route_search import RouteSearch, RouteSearchRpc, WETH, candidates
from cybergold_candidate.uniswap_routes import v3_path
from route_engine_fixture import install_fixture_engine

HASH = '0x' + 'a' * 64
ASSET_A, ASSET_B, ASSET_C = ['0x' + letter * 40 for letter in ('1', '2', '3')]
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS=ASSET_C,
                           NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=None,
                           RPC_URL='http://fixture.invalid', RPC_AUTHORIZATION='Bearer fixture')
REVERT_MESSAGE = 'execution reverted: route rejected; api_key=fixture-secret-key'
SAFE_REVERT_MESSAGE = 'execution reverted: route rejected; [redacted credential]'


class Provider(AsyncBaseProvider):
    def __init__(self, chain='0x1', reorg=False):
        super().__init__()
        self.calls, self.chain, self.reorg = [], chain, reorg
        self.block_hash = HASH

    async def make_request(self, method, params):
        self.calls.append((method, params))
        result = self.chain if method == 'eth_chainId' else {
            'number': '0x65', 'hash': '0x' + 'c' * 64 if self.reorg and params[0] != 'latest' else self.block_hash}
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    async def disconnect(self):
        pass


def wire_result(amount):
    return '0x' + Web3().codec.encode(['uint256', 'uint160[]', 'uint32[]', 'uint256'],
                                    [amount, [], [], 123]).hex()


class Wire:
    def __init__(self):
        self.batches, self.failure, self.blocked = [], False, False
        self.started, self.cancelled = asyncio.Event(), 0
        self.amounts = lambda index: 2**200 + index
        self.pool_liquidity = lambda fee: 123
        self.pool_fees, self.missing_fees, self.pool_errors = {}, set(), set()
        self.on_quote = None

    async def send(self, request):
        batch = json.loads(request.content)
        self.batches.append(batch)
        self.started.set()
        if self.blocked:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        if self.failure:
            return httpx.Response(503, text='private supplier credential')
        selector = batch[0]['params'][0]['data'][:10]
        if selector == '0x1698ee82':  # canonical V3 factory getPool
            rows = []
            for row in batch:
                data = bytes.fromhex(row['params'][0]['data'][2:])
                fee = Web3().codec.decode(['address', 'address', 'uint24'], data[4:])[2]
                address = '0x' + (b'\0'*20 if fee in self.missing_fees else Web3.keccak(data)[-20:]).hex()
                self.pool_fees[address.lower()] = fee
                rows.append({'jsonrpc': '2.0', 'id': row['id'], **(
                    {'error': {'code': -32603, 'message': 'unavailable'}} if fee in self.pool_errors else
                    {'result': '0x' + Web3().codec.encode(['address'], [address]).hex()})})
            return httpx.Response(200, json=list(reversed(rows)))
        if selector == '0x1a686502':  # canonical V3 pool active liquidity
            rows = []
            for row in batch:
                amount = self.pool_liquidity(self.pool_fees[row['params'][0]['to'].lower()])
                rows.append({'jsonrpc': '2.0', 'id': row['id'], **(
                    {'error': {'code': -32603, 'message': 'unavailable'}} if amount is None else
                    {'result': '0x' + Web3().codec.encode(['uint128'], [amount]).hex()})})
            return httpx.Response(200, json=list(reversed(rows)))
        if self.on_quote:
            rows = []
            for row in batch:
                path, amount = Web3().codec.decode(['bytes', 'uint256'],
                    bytes.fromhex(row['params'][0]['data'][2:])[4:])
                result = await self.on_quote(path, amount)
                rows.append({'jsonrpc': '2.0', 'id': row['id'], **(
                    {'error': {'code': 3, 'message': REVERT_MESSAGE}} if result is None else
                    {'result': wire_result(result)})})
            return httpx.Response(200, json=list(reversed(rows)))
        return httpx.Response(200, json=list(reversed([
            {'jsonrpc': '2.0', 'id': row['id'], **(
                {'error': {'code': 3, 'message': REVERT_MESSAGE}} if self.amounts(row['id']) is None else
                {'result': wire_result(self.amounts(row['id']))})} for row in batch])))


def service(provider=None, wire=None):
    provider, wire = provider or Provider(), wire or Wire()
    client = httpx.AsyncClient(transport=httpx.MockTransport(wire.send))
    search = RouteSearch(SETTINGS, RouteSearchRpc(SETTINGS, AsyncWeb3(provider), client))
    install_fixture_engine(search)
    return search, provider, wire


def target(token_in=ASSET_A, token_out=ASSET_B, amount=2**210):
    return {'inputAsset': token_in, 'outputAsset': token_out, 'amount': str(amount)}


class RouteSearchTests(unittest.IsolatedAsyncioTestCase):
    def paths(self, wire):
        selectors = {'0x'+Web3.keccak(text=name)[:4].hex() for name in (
            'quoteExactInput(bytes,uint256)', 'quoteExactOutput(bytes,uint256)')}
        return [Web3().codec.decode(['bytes', 'uint256'], bytes.fromhex(row['params'][0]['data'][2:])[4:])[0]
            for batch in wire.batches for row in batch if row['params'][0]['data'][:10] in selectors]

    def plan_path(self, row, mode='exact-in'):
        plan = row['best']['routePlan']
        self.assertEqual(plan['executionContext'], 'helpers-core')
        self.assertEqual(plan['mode'], 'exactIn' if mode == 'exact-in' else 'exactOut')
        return v3_path(plan['branches'][0]['hops'], mode == 'exact-out').lower()

    async def test_low_level_wire_keeps_shuffled_ids_wide_values_and_canonical_hash(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        rows = candidates(target(), 'exact-in')
        data = [search.rpc.encode({'mode': 'exact-in', 'path': row['path'], 'amount': str(2**210)}) for row in rows]
        result = await search.rpc.quote_batch('exact-in', data, {'number': 101, 'hash': HASH})
        self.assertEqual([row['amount'] for row in result], [str(2**200+index) for index in range(13)])
        self.assertTrue(all(row['params'][1] == {'blockHash': HASH, 'requireCanonical': True}
                            for row in wire.batches[0]))

    async def test_common_engine_covers_original_paths_for_all_targets_at_one_context(self):
        search, provider, wire = service()
        self.addAsyncCleanup(search.close)
        async def quote(path, _amount):
            return 2**200 + sum(int.from_bytes(path[offset:offset+3]) for offset in range(20, len(path), 23))
        wire.on_quote = quote
        requests = [target(), target(token_out=ASSET_C)]
        result = await search.get({'mode': 'exact-in', 'targets': requests})
        expected = {row['path'] for value in requests for row in candidates(value, 'exact-in')}
        self.assertEqual({'0x'+path.hex() for path in self.paths(wire)}, expected)
        self.assertEqual([row['target'] for row in result['results']], requests)
        self.assertEqual([row['attempted'] for row in result['results']], [13, 13])
        self.assertTrue(all(int(row['best']['quote']) > 2**200 for row in result['results']))
        self.assertTrue(all(self.plan_path(row) in expected for row in result['results']))
        self.assertEqual([method for method, _ in provider.calls],
                         ['eth_chainId', 'eth_getBlockByNumber', 'eth_getBlockByNumber'])

    async def test_exact_output_keeps_forward_plan_and_reversed_native_calldata(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        async def quote(path, _amount):
            return 100 + sum(int.from_bytes(path[offset:offset+3]) for offset in range(20, len(path), 23))
        wire.on_quote = quote
        value = target()
        result = await search.get({'mode': 'exact-out', 'targets': [value]})
        expected = {row['path'] for row in candidates(value, 'exact-out')}
        self.assertEqual({'0x'+path.hex() for path in self.paths(wire)}, expected)
        row = result['results'][0]
        self.assertEqual(row['best']['quote'], '200')
        plan = row['best']['routePlan']
        self.assertEqual(plan['tokenIn'].lower(), value['inputAsset'].lower())
        self.assertEqual(plan['tokenOut'].lower(), value['outputAsset'].lower())
        self.assertIn(self.plan_path(row, 'exact-out'), expected)

    async def test_partial_reverts_zero_and_ties_preserve_ordinary_redacted_failures(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        async def quote(path, _amount):
            fee = int.from_bytes(path[20:23])
            return None if fee == 500 else 0 if fee == 100 else 777
        wire.on_quote = quote
        result = await search.get({'mode': 'exact-in', 'targets': [target(WETH)]})
        row = result['results'][0]
        self.assertEqual((row['attempted'], row['succeeded']), (4, 3))
        self.assertEqual(row['best']['quote'], '777')
        self.assertEqual(row['best']['feeInfo'], '3000')
        failure, = row['failures']
        self.assertEqual(failure['code'], 'quote-contract-reverted')
        self.assertEqual(failure['diagnostics']['providerMessage'], SAFE_REVERT_MESSAGE)
        self.assertNotIn('fixture-secret-key', json.dumps(result))

    async def test_identity_and_duplicate_targets_keep_caller_order_and_canonical_plans(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        rows = [target(WETH), target(WETH), target(ASSET_A, ASSET_A), target()]
        result = await search.get({'mode': 'exact-in', 'targets': rows})
        self.assertEqual([row['target'] for row in result['results']], rows)
        self.assertEqual(result['results'][0]['best'], result['results'][1]['best'])
        self.assertEqual(result['results'][2]['best']['quote'], rows[2]['amount'])
        self.assertTrue(all(path[:20] != path[-20:] for path in self.paths(wire)))

    async def test_known_empty_pools_skip_native_quotes_without_rejecting_healthy_routes(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        wire.pool_liquidity = lambda fee: 0 if fee in (100, 500) else 123
        result = await search.get({'mode': 'exact-in', 'targets': [target(WETH), target(WETH, ASSET_C)]})
        self.assertTrue(all(row['best'] is not None for row in result['results']))
        self.assertEqual({int.from_bytes(path[20:23]) for path in self.paths(wire)}, {3000, 10000})

    async def test_absence_is_skipped_but_failed_pool_observations_stay_unknown(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        wire.missing_fees, wire.pool_errors = {100}, {500}
        wire.pool_liquidity = lambda fee: None if fee == 3000 else 123
        result = await search.get({'mode': 'exact-out', 'targets': [target(WETH)]})
        self.assertIsNotNone(result['results'][0]['best'])
        self.assertEqual({int.from_bytes(path[20:23]) for path in self.paths(wire)}, {500, 3000, 10000})

    async def test_completed_candidates_publish_while_an_earlier_v3_candidate_is_blocked(self):
        for mode in ('exact-in', 'exact-out'):
            search, _, wire = service()
            self.addAsyncCleanup(search.close)
            release, ready = asyncio.Event(), asyncio.Event()
            updates = []
            async def quote(path, _amount):
                if int.from_bytes(path[20:23]) == 100:
                    await release.wait()
                return 777
            async def update(event):
                updates.append(event)
                if event['results'][0]['best'] is not None:
                    ready.set()
            wire.on_quote = quote
            operation = asyncio.create_task(search.get({'mode': mode, 'targets': [target(WETH)]}, on_update=update))
            try:
                await asyncio.wait_for(ready.wait(), 1)
                self.assertFalse(operation.done())
                self.assertNotEqual(updates[-1]['results'][0]['best']['feeInfo'], '100')
                release.set()
                result = await operation
                self.assertEqual(result['results'][0]['attempted'], 4)
                self.assertEqual(result['results'][0]['best']['quote'], '777')
            finally:
                release.set()
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def test_direct_progress_precedes_multihop_tail_for_every_required_leg(self):
        for mode in ('exact-in', 'exact-out'):
            search, _, wire = service()
            self.addAsyncCleanup(search.close)
            release, ready = asyncio.Event(), asyncio.Event()
            async def quote(path, _amount):
                if len(path) > 43:
                    await release.wait()
                    return 888 if mode == 'exact-in' else 666
                return 777
            async def update(event):
                if all(row['best'] is not None for row in event['results']):
                    ready.set()
            wire.on_quote = quote
            requests = [target(), target(token_out=ASSET_C), target()]
            operation = asyncio.create_task(search.get({'mode': mode, 'targets': requests}, on_update=update))
            try:
                await asyncio.wait_for(ready.wait(), 1)
                self.assertFalse(operation.done())
                release.set()
                result = await operation
                self.assertEqual([row['target'] for row in result['results']], requests)
                self.assertEqual([row['attempted'] for row in result['results']], [13, 13, 13])
                self.assertTrue(all(len(row['best']['routePlan']['branches'][0]['hops']) == 2
                                    for row in result['results']))
            finally:
                release.set()
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def test_http_invalid_inputs_fail_before_rpc_and_transport_recovers(self):
        search, provider, wire = service()
        app = create_app(route_search=search)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for invalid in [{}, {'mode': 'exact-in', 'targets': [target(amount=-1)]},
                            {'mode': 'exact-in', 'targets': [target(amount=2**256)]},
                            {'mode': 'exact-in', 'targets': [target(token_in='invalid')]}]:
                response = await client.post('/api/quotes/routes', json=invalid)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(provider.calls, [])
            wire.failure = True
            response = await client.post('/api/quotes/routes', json={'mode': 'exact-in', 'targets': [target()]})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('credential', response.text)
            self.assertIn('correlationId', response.json())
            wire.failure = False
            response = await client.post('/api/quotes/routes', json={'mode': 'exact-in', 'targets': [target()]})
            self.assertEqual(response.status_code, 200)

    async def test_http_stream_emits_before_completion_and_disconnect_cancels_candidates(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def quote(path, amount):
            if int.from_bytes(path[20:23]) == 100:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return 777

        wire.on_quote = quote
        app = create_app(route_search=search)
        received, disconnected = False, asyncio.Event()
        messages = asyncio.Queue()

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {'type': 'http.request', 'body': json.dumps({
                    'mode': 'exact-in', 'targets': [target(WETH)]}).encode()}
            await disconnected.wait()
            return {'type': 'http.disconnect'}

        scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
                 'method': 'POST', 'path': '/api/quotes/routes/stream', 'root_path': '',
                 'query_string': b'', 'headers': [], 'scheme': 'http',
                 'server': ('test', 80), 'client': ('test', 123)}
        async with app.router.lifespan_context(app):
            operation = asyncio.create_task(app(scope, receive, messages.put))
            try:
                await asyncio.wait_for(started.wait(), 1)
                found = False
                while not found:
                    message = await asyncio.wait_for(messages.get(), 1)
                    if message['type'] == 'http.response.body' and message.get('body'):
                        event = json.loads(message['body'])
                        self.assertEqual(event['type'], 'progress')
                        found = event['results'][0]['best'] is not None
                self.assertFalse(operation.done())
                disconnected.set()
                await asyncio.wait_for(operation, 1)
                await asyncio.wait_for(cancelled.wait(), 1)
            finally:
                disconnected.set()
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def test_stream_errors_are_terminal_redacted_and_reorg_never_completes(self):
        for provider in (Provider(reorg=True), Provider(chain='0x2')):
            search, _, _ = service(provider)
            app = create_app(route_search=search)
            async with app.router.lifespan_context(app), httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                bad = await client.post('/api/quotes/routes/stream', json={
                    'mode': 'exact-in', 'targets': [target(amount=-1)]})
                self.assertEqual(bad.status_code, 400)
                response = await client.post('/api/quotes/routes/stream', json={
                    'mode': 'exact-in', 'targets': [target(WETH)]})
                self.assertEqual(response.headers['x-accel-buffering'], 'no')
                events = [json.loads(line) for line in response.text.splitlines()]
                self.assertEqual(events[-1]['type'], 'error')
                self.assertFalse(any(event['type'] == 'complete' for event in events))
                self.assertIn('correlationId', events[-1])
                self.assertNotIn('credential', response.text)

    async def test_wrong_chain_reorg_and_cancellation_never_publish_stale_quote(self):
        for provider in (Provider(chain='0x2'), Provider(reorg=True)):
            search, _, _ = service(provider)
            self.addAsyncCleanup(search.close)
            with self.assertRaises(Exception):
                await search.get({'mode': 'exact-in', 'targets': [target()]})
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        wire.blocked = True
        operation = asyncio.create_task(search.get({'mode': 'exact-in', 'targets': [target()]}))
        await asyncio.wait_for(wire.started.wait(), 1)
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertGreaterEqual(wire.cancelled, 1)


if __name__ == '__main__':
    unittest.main()
