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

HASH = '0x' + 'a' * 64
ASSET_A, ASSET_B, ASSET_C = ['0x' + letter * 40 for letter in ('1', '2', '3')]
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS=ASSET_C,
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
    return RouteSearch(SETTINGS, RouteSearchRpc(SETTINGS, AsyncWeb3(provider), client)), provider, wire


def target(token_in=ASSET_A, token_out=ASSET_B, amount=2**210):
    return {'inputAsset': token_in, 'outputAsset': token_out, 'amount': str(amount)}


class RouteSearchTests(unittest.IsolatedAsyncioTestCase):
    def results_without_elapsed_time(self, results):
        normalized = []
        for row in results:
            failures = []
            for failure in row['failures']:
                diagnostics = failure['diagnostics']
                self.assertEqual({key: value for key, value in diagnostics.items() if key != 'elapsedMs'}, {
                    'rpcMethod': 'eth_call', 'stage': 'route-search', 'failureType': 'rpc-error',
                    'upstreamErrorCode': 3, 'providerMessage': SAFE_REVERT_MESSAGE,
                })
                self.assertGreaterEqual(diagnostics['elapsedMs'], 0)
                self.assertNotIn('fixture-secret-key', json.dumps(failure))
                failures.append({**failure, 'diagnostics': {**diagnostics, 'elapsedMs': 0}})
            normalized.append({**row, 'failures': failures})
        return normalized

    async def test_two_targets_share_context_and_all_26_candidates_with_shuffled_ids(self):
        search, provider, wire = service()
        self.addAsyncCleanup(search.close)
        request = {'mode': 'exact-in', 'targets': [target(), target(token_out=ASSET_C)]}
        result = await search.get(request)
        self.assertEqual([method for method, _ in provider.calls],
                         ['eth_chainId', 'eth_getBlockByNumber', 'eth_getBlockByNumber'])
        self.assertEqual([len(batch) for batch in wire.batches], [17, 17, 26])
        self.assertTrue(all(row['params'][1] == {'blockHash': HASH, 'requireCanonical': True}
                            for batch in wire.batches for row in batch))
        self.assertTrue(all(row['params'][0]['to'] == ASSET_C for row in wire.batches[-1]))
        self.assertEqual(result['metrics']['rpcReads'], 63)
        self.assertEqual([row['best']['quote'] for row in result['results']], [str(2**200+12), str(2**200+25)])
        self.assertEqual([row['attempted'] for row in result['results']], [13, 13])

    async def test_exact_output_reverses_tokens_and_fees_and_minimizes(self):
        request = target()
        inward, outward = candidates(request, 'exact-in'), candidates(request, 'exact-out')
        for before, after in zip(inward, outward, strict=True):
            raw = bytes.fromhex(before['path'][2:])
            tokens = [raw[0:20]] + [raw[i+3:i+23] for i in range(20, len(raw), 23)]
            fees = [raw[i:i+3] for i in range(20, len(raw), 23)]
            expected = tokens[-1] + b''.join(fee+token for fee, token in zip(reversed(fees), reversed(tokens[:-1])))
            self.assertEqual(after['path'], '0x'+expected.hex())
            self.assertEqual(before['feeInfo'], after['feeInfo'])
        search, _, _ = service()
        self.addAsyncCleanup(search.close)
        result = await search.get({'mode': 'exact-out', 'targets': [request]})
        self.assertEqual(result['results'][0]['best']['quote'], str(2**200))

    async def test_ties_partial_reverts_and_zero_keep_deterministic_full_coverage(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        wire.amounts = lambda index: None if index == 0 else (0 if index == 1 else 777)
        result = await search.get({'mode': 'exact-in', 'targets': [target()]})
        row = result['results'][0]
        self.assertEqual(row['attempted'], 13)
        self.assertEqual(row['succeeded'], 12)
        self.assertEqual(self.results_without_elapsed_time(result['results'])[0]['failures'], [{
            'path': candidates(target(), 'exact-in')[0]['path'], 'rpcCode': 3, 'code': 'quote-contract-reverted',
            'diagnostics': {'rpcMethod': 'eth_call', 'stage': 'route-search', 'elapsedMs': 0,
                            'failureType': 'rpc-error', 'upstreamErrorCode': 3,
                            'providerMessage': SAFE_REVERT_MESSAGE},
        }])
        self.assertEqual(row['best']['path'], candidates(target(), 'exact-in')[2]['path'])
        wire.amounts = lambda _: None
        result = await search.get({'mode': 'exact-in', 'targets': [target()]})
        self.assertIsNone(result['results'][0]['best'])
        self.assertEqual(result['results'][0]['attempted'], 13)
        self.assertEqual(result['results'][0]['succeeded'], 0)
        self.assertEqual(len(self.results_without_elapsed_time(result['results'])[0]['failures']), 13)

    async def test_identity_weth_and_duplicate_targets_keep_order_without_duplicate_calls(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        rows = [target(WETH), target(WETH), target(ASSET_A, ASSET_A), target()]
        result = await search.get({'mode': 'exact-in', 'targets': rows})
        self.assertEqual(len(wire.batches[-1]), 17)
        self.assertEqual([row['target'] for row in result['results']], rows)
        self.assertEqual(result['results'][0]['best'], result['results'][1]['best'])
        self.assertEqual(result['results'][2]['best']['quote'], rows[2]['amount'])

    async def test_known_empty_pools_leave_healthy_quotes_in_one_canonical_wave(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        wire.pool_liquidity = lambda fee: 0 if fee in (100, 500) else 123
        result = await search.get({'mode': 'exact-in', 'targets': [
            target(WETH), target(WETH, ASSET_C)]})
        self.assertEqual([len(batch) for batch in wire.batches], [8, 8, 4])
        self.assertEqual(result['metrics']['candidateCalls'], 4)
        self.assertEqual(result['metrics']['rpcReads'], 23)
        self.assertEqual([row['attempted'] for row in result['results']], [2, 2])
        self.assertTrue(all(row['best'] is not None for row in result['results']))
        paths = [Web3().codec.decode(['bytes', 'uint256'],
            bytes.fromhex(row['params'][0]['data'][2:])[4:])[0] for row in wire.batches[-1]]
        self.assertEqual({int.from_bytes(path[20:23]) for path in paths}, {3000, 10000})

    async def test_absence_is_skipped_but_failed_pool_observations_do_not_reject_routes(self):
        search, _, wire = service()
        self.addAsyncCleanup(search.close)
        wire.missing_fees, wire.pool_errors = {100}, {500}
        wire.pool_liquidity = lambda fee: None if fee == 3000 else 123
        result = await search.get({'mode': 'exact-out', 'targets': [target(WETH)]})
        self.assertEqual(result['metrics']['candidateCalls'], 3)
        self.assertEqual(result['results'][0]['attempted'], 3)
        self.assertIsNotNone(result['results'][0]['best'])

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

    async def test_progress_arrives_before_slow_candidate_and_ties_keep_original_rank(self):
        for mode in ('exact-in', 'exact-out'):
            search, provider, wire = service()
            self.addAsyncCleanup(search.close)
            release, ready = asyncio.Event(), asyncio.Event()
            updates = []

            async def quote(path, amount):
                if int.from_bytes(path[20:23]) == 100:
                    await release.wait()
                return 777

            async def update(event):
                updates.append(event)
                if event['results'][0]['attempted'] == 3:
                    ready.set()

            wire.on_quote = quote
            request = {'mode': mode, 'targets': [target(WETH)]}
            operation = asyncio.create_task(search.get(request, on_update=update))
            try:
                await asyncio.wait_for(ready.wait(), 1)
                self.assertFalse(operation.done())
                self.assertEqual(updates[-1]['results'][0]['best']['feeInfo'], '500')
                self.assertEqual(updates[-1]['results'][0]['total'], 4)
                release.set()
                result = await operation
                self.assertEqual(result['results'][0]['best']['feeInfo'], '100')
                self.assertEqual(result['results'][0]['attempted'], 4)
                self.assertEqual(len(provider.calls), 3)
            finally:
                release.set()
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def test_stream_matches_batch_with_partial_reverts_zero_and_deduplicated_targets(self):
        for mode in ('exact-in', 'exact-out'):
            search, _, wire = service()
            self.addAsyncCleanup(search.close)

            async def quote(path, amount):
                fee = int.from_bytes(path[20:23])
                return None if fee == 500 else 0 if fee == 100 else amount + fee

            wire.on_quote = quote
            request = {'mode': mode, 'targets': [target(WETH), target(WETH), target(WETH, WETH)]}
            batch = await search.get(request)
            before = len(wire.batches)
            streamed = await search.get(request, on_update=lambda event: asyncio.sleep(0))
            self.assertEqual(self.results_without_elapsed_time(batch['results']),
                             self.results_without_elapsed_time(streamed['results']))
            self.assertEqual(batch['metrics']['rpcReadsRequested'], streamed['metrics']['rpcReadsRequested'])
            self.assertEqual([len(rows) for rows in wire.batches[before:]], [1, 1, 1, 1])

    async def test_direct_progress_precedes_multi_hop_batch_and_final_matches_full_batch(self):
        for mode in ('exact-in', 'exact-out'):
            search, _, wire = service()
            self.addAsyncCleanup(search.close)
            release, ready = asyncio.Event(), asyncio.Event()

            async def quote(path, amount):
                if len(path) > 43:
                    await release.wait()
                    return 888 if mode == 'exact-in' else 666
                return 777

            async def update(event):
                if all(row['best'] is not None for row in event['results']):
                    ready.set()

            wire.on_quote = quote
            request = {'mode': mode, 'targets': [target(), target(token_out=ASSET_C), target()]}
            operation = asyncio.create_task(search.get(request, on_update=update))
            try:
                await asyncio.wait_for(ready.wait(), 1)
                self.assertFalse(operation.done())
                quote_batches = wire.batches[2:]
                self.assertEqual(sorted(len(batch) for batch in quote_batches), [2] * 13)
                calldata = [row['params'][0]['data'] for batch in quote_batches for row in batch]
                self.assertEqual(len(set(calldata)), 26)
                release.set()
                streamed = await operation
                batch = await search.get(request)
                self.assertEqual(streamed['results'], batch['results'])
                self.assertEqual(streamed['metrics']['rpcReadsRequested'], batch['metrics']['rpcReadsRequested'])
                self.assertEqual(streamed['results'][0]['best']['route'], 'viaWeth')
            finally:
                release.set()
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

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
        await wire.started.wait()
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertEqual(wire.cancelled, 1)


if __name__ == '__main__':
    unittest.main()
