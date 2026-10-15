from legacy_quote_wire_fixture import ReferenceRouteSearchRpc as RouteSearchRpc
"""Sharing preserves exact read identity, cancellation, errors and fork behavior."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.shared_reads import SharedReads
from route_engine_fixture import install_fixture_engine
from cybergold_candidate.route_search import RouteSearch, WETH
from test_route_search import Provider, Wire, service, target, ASSET_A, ASSET_B, ASSET_C, SETTINGS, HASH, candidates
from cybergold_candidate.uniswap_state import UniswapRpc, PoolRegistry
from cybergold_candidate.quote_errors import QuoteFailure
from web3 import AsyncWeb3, Web3
import httpx


class SharedReadTests(unittest.IsolatedAsyncioTestCase):
    def getter_pair(self, chain=1, wire=None, bank=None):
        bank, wire = bank if bank is not None else SharedReads(), wire or Wire()
        settings = SimpleNamespace(**{**vars(SETTINGS), 'NEXT_PUBLIC_CHAIN_ID': str(chain)})
        class GetterProvider(Provider):
            async def make_request(self, method, params):
                if method != 'eth_call':
                    return await super().make_request(method, params)
                request = httpx.Request('POST', settings.RPC_URL,
                    json=[{'jsonrpc': '2.0', 'id': 0, 'method': method, 'params': params}])
                response = await wire.send(request)
                response.request = request
                response.raise_for_status()
                return response.json()[0]
        provider = GetterProvider(chain=hex(chain))
        legacy = RouteSearchRpc(settings, AsyncWeb3(provider),
            httpx.AsyncClient(transport=httpx.MockTransport(wire.send)), pool_reads=bank)
        typed = UniswapRpc(settings, AsyncWeb3(provider), pool_reads=bank)
        self.addAsyncCleanup(legacy.close)
        self.addAsyncCleanup(typed.close)
        self.addAsyncCleanup(bank.close)
        return legacy, typed, wire, bank

    def factory_call(self, legacy, fee=500):
        return (legacy.pools.factory, legacy.pools.pool_contracts['factory'].encode_abi(
            'getPool', args=[ASSET_A, ASSET_B, fee]))

    async def typed_factory(self, typed, block, fee=500):
        value, = await typed.read_function(typed.factory, 'getPool(address,address,uint24)',
            ['address', 'address', 'uint24'], [ASSET_A, ASSET_B, fee], ['address'], block)
        return Web3.to_checksum_address(value)

    async def test_legacy_and_typed_factory_liquidity_reuse_in_both_orders(self):
        block = {'number': 101, 'hash': HASH}
        for first in ('legacy', 'typed'):
            with self.subTest(first=first):
                legacy, typed, wire, bank = self.getter_pair()
                path = next(row['path'] for row in candidates(target(), 'exact-in') if row['feeInfo'] == '500')
                address = Web3.to_checksum_address('0x'+Web3.keccak(
                    bytes.fromhex(self.factory_call(legacy)[1][2:]))[-20:].hex())
                async def observe_typed():
                    self.assertEqual(await self.typed_factory(typed, block), address)
                    self.assertEqual(await typed.read_function(address, 'liquidity()', [], [], ['uint128'], block), (123,))
                if first == 'typed':
                    await observe_typed()
                eligible, counts = await legacy.eligible_paths([path], block)
                self.assertEqual(eligible, {path})
                self.assertEqual(counts['reused'], 2 if first == 'typed' else 0)
                await observe_typed()
                self.assertEqual(len(wire.batches), 2)
                # Closing a borrower does not discard the other path's observations.
                await legacy.close()
                await observe_typed()
                self.assertEqual(len(wire.batches), 2)
                self.assertEqual(len(bank.completed), 2)

    async def test_cross_getter_bank_separates_hash_chain_and_sandbox_overrides(self):
        legacy, typed, wire, bank = self.getter_pair()
        block = {'number': 101, 'hash': HASH}
        await legacy.pool_batch([self.factory_call(legacy)], block, {})
        await self.typed_factory(typed, block)
        self.assertEqual(len(wire.batches), 1)
        await self.typed_factory(typed, {**block, 'hash': '0x'+'b'*64})
        self.assertEqual(len(wire.batches), 2)
        sandbox_legacy, sandbox_typed, _, _ = self.getter_pair(31338, wire, bank)
        await self.typed_factory(sandbox_typed, block)
        self.assertEqual(len(wire.batches), 3)
        address = await self.typed_factory(sandbox_typed, block)
        self.assertEqual(len(wire.batches), 4)
        registry = PoolRegistry(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=ASSET_A), rpc=sandbox_typed)
        await registry.observe_generation('old')
        self.assertEqual(await sandbox_typed.read_function(address, 'liquidity()', [], [], ['uint128'], block), (123,))
        wire.pool_liquidity = lambda _fee: 456
        await registry.observe_generation('new')
        self.assertEqual(await sandbox_typed.read_function(address, 'liquidity()', [], [], ['uint128'], block), (456,))
        self.assertEqual(len(wire.batches), 6)
        rows, counts = await sandbox_legacy.pool_batch([self.factory_call(sandbox_legacy)], block, {})
        self.assertEqual(counts, {'requested': 1, 'issued': 1, 'coalesced': 0, 'reused': 0})
        self.assertEqual(Web3().codec.decode(['address'], bytes.fromhex(rows[0]['result'][2:]))[0], address.lower())

    async def test_cross_getter_error_and_malformed_observations_allow_retry(self):
        legacy, typed, wire, bank = self.getter_pair()
        block = {'number': 101, 'hash': HASH}
        wire.pool_errors.add(500)
        rows, _ = await legacy.pool_batch([self.factory_call(legacy)], block, {})
        self.assertIn('error', rows[0])
        with self.assertRaises(QuoteFailure) as failure:
            await self.typed_factory(typed, block)
        self.assertEqual(failure.exception.code, 'rpc-unavailable')
        self.assertEqual(bank.completed, {})
        wire.pool_errors.clear()
        address = await self.typed_factory(typed, block)
        self.assertEqual(len(wire.batches), 3)
        rows, counts = await legacy.pool_batch([self.factory_call(legacy)], block, {})
        self.assertEqual(counts['reused'], 1)
        self.assertEqual(Web3().codec.decode(['address'], bytes.fromhex(rows[0]['result'][2:]))[0], address.lower())
        malformed_block = {**block, 'hash': '0x'+'c'*64}
        original = wire.send
        async def malformed(request):
            response = await original(request)
            return httpx.Response(200, json=[{**row, 'result': '0x'} for row in response.json()])
        wire.send = malformed
        await legacy.client.aclose()
        legacy.client = httpx.AsyncClient(transport=httpx.MockTransport(wire.send))
        await legacy.pool_batch([self.factory_call(legacy)], malformed_block, {})
        with self.assertRaises(Exception):
            await self.typed_factory(typed, malformed_block)
        self.assertEqual(len(bank.completed), 1)
        # Typed-first malformed replies also remain ordinary failures, not hits.
        with self.assertRaises(Exception):
            await self.typed_factory(typed, malformed_block)
        wire.send = original
        self.assertEqual(await self.typed_factory(typed, malformed_block), address)
        self.assertEqual(len(wire.batches), 6)

    async def test_cross_getter_partial_batch_cancellation_preserves_other_subscriber(self):
        wire = Wire()
        release, started, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = wire.send
        async def blocked(request):
            started.set()
            try:
                await release.wait()
                return await original(request)
            except asyncio.CancelledError:
                cancelled.set()
                raise
        wire.send = blocked
        legacy, typed, _, bank = self.getter_pair(31338, wire)
        block = {'number': 101, 'hash': HASH}
        calls = [self.factory_call(legacy, fee) for fee in (500, 3000)]
        key = (31338, HASH, calls[0][0].lower(), calls[0][1].lower())
        for cancelled_path in ('legacy', 'typed'):
            with self.subTest(cancelled_path=cancelled_path):
                release.clear(); started.clear(); cancelled.clear()
                first = asyncio.create_task(legacy.pool_batch(calls, block, {}))
                await asyncio.wait_for(started.wait(), 1)
                second = asyncio.create_task(self.typed_factory(typed, block))
                async def joined():
                    while bank.pending[key].users < 2:
                        await asyncio.sleep(0)
                await asyncio.wait_for(joined(), 1)
                removed, remaining = (first, second) if cancelled_path == 'legacy' else (second, first)
                removed.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await removed
                self.assertFalse(cancelled.is_set())
                if cancelled_path == 'legacy':
                    release.set()
                    self.assertIsInstance(await remaining, str)
                    self.assertEqual(len(wire.batches), 1)
                else:
                    remaining.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await remaining
                    self.assertTrue(cancelled.is_set())
                self.assertEqual(bank.pending, {})

    async def test_shared_pool_bank_does_not_retain_quote_simulations(self):
        legacy, typed, wire, bank = self.getter_pair()
        block = {'number': 101, 'hash': HASH}
        await self.typed_factory(typed, block)
        path = candidates(target(), 'exact-in')[0]['path']
        calldata = legacy.encode({'mode': 'exact-in', 'path': path, 'amount': '123'})
        self.assertEqual(await legacy.quote_batch('exact-in', [calldata], block),
                         await legacy.quote_batch('exact-in', [calldata], block))
        self.assertEqual(len(wire.batches), 3)
        self.assertEqual(len(bank.completed), 1)

    async def test_configured_runtime_owns_one_getter_bank_and_closes_it(self):
        from cybergold_candidate.environment import load_environment
        from cybergold_candidate.runtime import create_configured_app
        from cybergold_candidate.protocol_facts import ProtocolFacts
        routes, registries, facts = [], [], []
        def route(*args, **kwargs):
            value = RouteSearch(*args, **kwargs)
            routes.append(value)
            return value
        def registry(*args, **kwargs):
            value = PoolRegistry(*args, **kwargs)
            registries.append(value)
            return value
        def protocol(*args, **kwargs):
            value = ProtocolFacts(*args, **kwargs)
            facts.append(value)
            return value
        class Database:
            closed = False
            async def close(self):
                self.closed = True
        database = Database()
        settings = load_environment({'NEXT_PUBLIC_CHAIN_ID': '1',
            'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': ASSET_A, 'NEXT_PUBLIC_RPC_URL': SETTINGS.RPC_URL,
            'NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS': ASSET_C})
        with patch('cybergold_candidate.runtime.RouteSearch', side_effect=route), \
                patch('cybergold_candidate.runtime.PoolRegistry', side_effect=registry), \
                patch('cybergold_candidate.runtime.ProtocolFacts', side_effect=protocol):
            app = create_configured_app(settings, database)
        self.assertIsNone(routes[0].rpc)
        self.assertIs(registries[0].pool_reads, registries[0].rpc.reads)
        self.assertIsNone(facts[0].rpc)
        self.assertIs(facts[0].pool_reads, registries[0].pool_reads)
        async with app.router.lifespan_context(app):
            routes[0].rpc = routes[0].rpc_factory(settings)
            typed = registries[0].get_rpc()
            bank = routes[0].rpc.pool_reads
            self.assertIs(bank, typed.reads)
            self.assertFalse(routes[0].rpc.owns_pool_reads)
            self.assertFalse(typed.owns_pool_reads)
            started = asyncio.Event()
            async def blocked(_keys):
                started.set()
                await asyncio.Event().wait()
            pending = asyncio.create_task(bank.many(['held'], blocked))
            await started.wait()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(bank.pending, {})
        self.assertEqual(bank.completed, {})
        self.assertTrue(database.closed)

    async def test_one_cancelled_subscriber_does_not_cancel_other_and_last_cancel_does(self):
        reads = SharedReads()
        self.addAsyncCleanup(reads.close)
        started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = 0
        async def produce():
            nonlocal calls
            calls += 1
            started.set()
            try:
                await release.wait()
                return {'result': 'value'}
            finally:
                cancelled.set()
        first = asyncio.create_task(reads.one('same', produce))
        second = asyncio.create_task(reads.one('same', produce))
        await started.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertFalse(cancelled.is_set())
        release.set()
        self.assertEqual(await second, {'result': 'value'})
        self.assertEqual(calls, 1)
        release.clear(); started.clear(); cancelled.clear()
        last = asyncio.create_task(reads.one('same', produce))
        await started.wait()
        last.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await last
        self.assertTrue(cancelled.is_set())
        self.assertEqual(reads.pending, {})

    async def test_partially_overlapping_batches_share_members_and_errors_are_not_retained(self):
        reads = SharedReads()
        self.addAsyncCleanup(reads.close)
        calls = []
        async def produce(keys):
            calls.extend(keys)
            await asyncio.sleep(.005)
            return [{'result': key} for key in keys]
        (a, first), (b, second) = await asyncio.gather(
            reads.many(['a', 'b'], produce, retain=True), reads.many(['b', 'c'], produce, retain=True))
        self.assertEqual(calls, ['a', 'b', 'c'])
        self.assertEqual(a, [{'result': 'a'}, {'result': 'b'}])
        self.assertEqual(b, [{'result': 'b'}, {'result': 'c'}])
        self.assertEqual(first['issued'] + second['issued'], 3)
        values, counts = await reads.many(['b'], produce, retain=True)
        self.assertEqual(counts['reused'], 1)
        async def error(_keys): return [{'error': {'code': 3}}]
        await reads.many(['failed'], error, retain=True)
        values, counts = await reads.many(['failed'], produce, retain=True)
        self.assertEqual(values, [{'result': 'failed'}])
        self.assertEqual(counts['issued'], 1)

    async def test_five_concurrent_fresh_waves_reduce_issued_reads_without_dropping_candidates(self):
        for asset, current, shared in ((WETH, 135, 71), (target()['inputAsset'], 315, 179)):
            search, _, wire = service()
            self.addAsyncCleanup(search.close)
            original = wire.send
            async def delayed(request):
                await asyncio.sleep(.005)
                return await original(request)
            await search.rpc.client.aclose()
            search.rpc.client = httpx.AsyncClient(transport=httpx.MockTransport(delayed))
            requests = [{'mode': 'exact-in', 'targets': [target(asset, amount=100 + i),
                target(asset, ASSET_C, amount=200 + i)]} for i in range(5)]
            values = await asyncio.gather(*(search.get(request) for request in requests))
            self.assertEqual(sum(value['metrics']['rpcReadsRequested'] for value in values), 15)
            self.assertEqual(sum(value['metrics']['rpcReads'] for value in values), 15)
            self.assertTrue(all(value['metrics']['rpcReadsScope'] == 'coordinator' for value in values))
            self.assertTrue(all(value['metrics']['candidateCalls'] == (8 if asset == WETH else 26) for value in values))
            self.assertEqual(sum(len(batch) for batch in wire.batches) + 15, shared)

    async def test_mainnet_warm_pool_reuse_keeps_amount_reads_fresh_and_new_hash_misses(self):
        search, provider, wire = service()
        self.addAsyncCleanup(search.close)
        async def quote(_path, amount): return amount + 777
        wire.on_quote = quote
        def members():
            return sum(len(batch) for batch in wire.batches)
        first = await search.get({'mode': 'exact-out', 'targets': [target(WETH, amount=100), target(WETH, ASSET_C, amount=200)]})
        first_members = members()
        second = await search.get({'mode': 'exact-out', 'targets': [target(WETH, amount=101), target(WETH, ASSET_C, amount=201)]})
        second_members = members()-first_members
        self.assertEqual((first_members, second_members), (24, 8))
        self.assertEqual((first['metrics']['rpcReads'], second['metrics']['rpcReads']), (3, 3))
        self.assertEqual(second['metrics']['rpcReadsScope'], 'coordinator')
        self.assertEqual(int(second['results'][0]['best']['quote']), int(first['results'][0]['best']['quote']) + 1)
        provider.block_hash = '0x' + 'b' * 64
        third = await search.get({'mode': 'exact-out', 'targets': [target(WETH, amount=102), target(WETH, ASSET_C, amount=202)]})
        self.assertEqual(members()-first_members-second_members, 24)
        self.assertEqual(third['metrics']['rpcReads'], 3)
        self.assertEqual(third['context']['blockHash'], provider.block_hash)
        provider.reorg = True
        with self.assertRaisesRegex(Exception, 'snapshot changed'):
            await search.get({'mode': 'exact-out', 'targets': [target(WETH, amount=103)]})

    async def test_sandbox_same_hash_override_is_observed_without_any_new_marker(self):
        settings = SimpleNamespace(**{**vars(SETTINGS), 'NEXT_PUBLIC_CHAIN_ID': '31338'})
        provider, wire = Provider(chain='0x7a6a'), Wire()
        search = RouteSearch(settings, RouteSearchRpc(settings, AsyncWeb3(provider),
            httpx.AsyncClient(transport=httpx.MockTransport(wire.send))))
        install_fixture_engine(search)
        self.addAsyncCleanup(search.close)
        wire.pool_liquidity = lambda _fee: 0
        first = await search.get({'mode': 'exact-in', 'targets': [target(WETH)]})
        self.assertEqual(first['metrics']['candidateCalls'], 4)
        self.assertFalse(any(row['params'][0]['data'][:10] in ('0xcdca1753', '0x2f80bb1d')
            for batch in wire.batches for row in batch))
        before = len(wire.batches)
        wire.pool_liquidity = lambda _fee: 123
        second = await search.get({'mode': 'exact-in', 'targets': [target(WETH)]})
        self.assertEqual(second['context']['blockHash'], HASH)
        self.assertEqual(second['metrics']['candidateCalls'], 4)
        native = [row for batch in wire.batches[before:] for row in batch
            if row['params'][0]['data'][:10] not in ('0x1698ee82', '0x1a686502')]
        self.assertEqual(len(native), 4)
        self.assertEqual(second['metrics']['rpcReadsReused'], 0)


if __name__ == '__main__':
    unittest.main()
