"""Real SDK bridge, fee boundary, custody payload and cache/event regressions."""
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from itertools import combinations
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace, MethodType
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from web3 import Web3
from web3.exceptions import BlockNotFound

from cybergold_candidate.app import create_app
from cybergold_candidate.market_fee import quoted_fee, gross_buy_target, routed_sell_budget
from cybergold_candidate.market_swap import MarketQuotes, DailyRecipientCache, encode_adapter, ADAPTER_TYPE
from cybergold_candidate.sdk_worker import SdkWorker, SdkWorkerError
from cybergold_candidate.uniswap_routes import candidate_branches, discover_routes, discover_routes_async, supported_route, v3_path, v4_pool_id
from cybergold_candidate.uniswap_state import PoolRegistry, EVENTS, DISCOVERY, ZERO, V3_SWAP
from cybergold_candidate.uniswap_v4 import STATE_VIEW
from cybergold_candidate.helpers_execution import ABI, argument
from cybergold_candidate.quote_revalidation import revalidate, core_bounds
from cybergold_candidate.recovery_rpc import RecoveryApiError
from cybergold_candidate.quote_history import QuoteHistory
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.rpc_diagnostics import quote_work_scope, route_work_scope, quote_phase, freeze_quote_work

A, B, C = ('0x'+str(index).rjust(40, '0') for index in (1, 2, 3))
BLOCK = {'number': 123, 'hash': '0x'+'ab'*32}


def token(address):
    return {'address': address, 'decimals': 18, 'chainId': 1}


async def collect(events, event):
    events.append(event)


POOL = {'id': C, 'protocol': 'v2', 'address': C, 'feePips': 3000,
        'token0': token(A), 'token1': token(B)}


class Rpc:
    def __init__(self):
        self.chain_id = 1
        self.w3 = Web3()
        self.state_reads = 0
        self.head_reads = 0
        self.owner_reads = 0

    async def block(self, _hash):
        self.head_reads += 1
        return BLOCK

    async def assert_canonical(self, block):
        assert block == BLOCK

    async def read_function(self, address, signature, inputs, args, outputs, block):
        if signature == 'getReserves()':
            self.state_reads += 1
            await asyncio.sleep(.001)
            return 100_000, 200_000, 0
        if signature == 'owner()':
            self.owner_reads += 1
            return (C,)
        raise AssertionError(signature)

    async def close(self):
        pass


class Store:
    def __init__(self):
        self.data = {}
        self.scope = ''

    async def load(self, namespace):
        return deepcopy(self.data.get(self.scope+namespace, {}))

    async def save(self, namespace, identity, value):
        self.data.setdefault(self.scope+namespace, {})[identity] = deepcopy(value)

    async def catalog(self, protocol, cursor, pools, removed):
        for identity in removed:
            for namespace in ('inventory', 'observation'):
                self.data.setdefault(namespace, {}).pop(identity, None)
        for pool in pools:
            await self.save('inventory', pool['id'], pool)
        await self.save('cursor', protocol, cursor)


class RouteIdentityReplay(unittest.IsolatedAsyncioTestCase):
    def pools(self):
        d = '0x'+'4'*40
        return [{**POOL, 'id': '0x'+format(index+100, '040x'), 'protocol': protocol,
                 'token0': token(left), 'token1': token(right)}
            for index, (left, right, protocol) in enumerate([
                (A, B, 'v2'), (A, C, 'v2'), (C, B, 'v3'),
                (A, B, 'v3'), (A, d, 'v4'), (d, B, 'v4'), (A, B, 'v4')])]

    def expected(self, pools, mode, amount):
        paths = [path for path in discover_routes(pools, A, B) if supported_route(path, mode)]
        rows = [[{'amountIn': str(amount) if mode == 'exactIn' else '0', 'hops': path}]
                for path in paths]
        if mode == 'exactIn':
            for left, right in combinations(paths, 2):
                for percent in (25, 50, 75):
                    first = amount*percent//100
                    if first and amount-first:
                        rows.append([{'amountIn': str(first), 'hops': left},
                                     {'amountIn': str(amount-first), 'hops': right}])
        return rows

    async def test_matches_complete_mixed_graph_order_and_raw_allocations(self):
        pools = self.pools()
        for mode in ('exactIn', 'exactOut'):
            for amount in (0, 1, 2, 3, 4, 101, 2**255):
                with self.subTest(mode=mode, amount=amount):
                    rows = [row async for row in candidate_branches(pools, A, B, mode, amount)]
                    self.assertEqual(rows, self.expected(pools, mode, amount))
                    if mode == 'exactIn':
                        self.assertTrue(all(sum(int(branch['amountIn']) for branch in row) == amount for row in rows))

    async def test_keeps_ordered_pair_directions_and_duplicate_raw_rounding(self):
        pools = self.pools()
        paths = [path async for path in discover_routes_async(pools, A, B)]
        rows = [row async for row in candidate_branches(pools, A, B, 'exactIn', 2)]
        splits = rows[len(paths):]
        self.assertEqual(splits[:2], [[{'amountIn': '1', 'hops': paths[0]},
                                      {'amountIn': '1', 'hops': paths[1]}]]*2)
        self.assertEqual(len(splits), len(paths)*(len(paths)-1))

    async def test_enumerates_selected_graph_once_for_all_split_pairs(self):
        with patch('cybergold_candidate.uniswap_routes.discover_routes_async', wraps=discover_routes_async) as discover:
            rows = [row async for row in candidate_branches(self.pools(), A, B, 'exactIn', 101)]
        self.assertTrue(any(len(row) == 2 for row in rows))
        self.assertEqual(discover.call_count, 1)

    async def test_first_candidate_remains_lazy_and_closing_prefix_stops_iterator(self):
        seen = []
        async def observed(*args, **kwargs):
            async for path in discover_routes_async(*args, **kwargs):
                seen.append(path)
                yield path
        with patch('cybergold_candidate.uniswap_routes.discover_routes_async', observed):
            iterator = candidate_branches(self.pools(), A, B, 'exactIn', 101)
            first = await anext(iterator)
            self.assertEqual(len(seen), 1)
            self.assertEqual(len(first), 1)
            await iterator.aclose()
            with self.assertRaises(StopAsyncIteration):
                await anext(iterator)

    async def test_standalone_consumer_cannot_mutate_replayed_hops(self):
        pools = self.pools()
        expected = self.expected(pools, 'exactIn', 101)
        iterator = candidate_branches(pools, A, B, 'exactIn', 101)
        first = await anext(iterator)
        self.assertIs(first[0]['hops'][0]['pool'], pools[0])
        first[0]['hops'][0]['zeroForOne'] = False
        first[0]['hops'].append({'pool': {}, 'zeroForOne': False})
        self.assertEqual([row async for row in iterator], expected[1:])

    async def test_split_consumer_cannot_mutate_later_allocations(self):
        pools = self.pools()
        expected = self.expected(pools, 'exactIn', 101)
        standalone = len(discover_routes(pools, A, B))
        iterator = candidate_branches(pools, A, B, 'exactIn', 101)
        for _ in range(standalone):
            await anext(iterator)
        first = await anext(iterator)
        first[0]['hops'][0]['zeroForOne'] = False
        first[0]['hops'].append({'pool': {}, 'zeroForOne': False})
        self.assertEqual([row async for row in iterator], expected[standalone+1:])

    async def test_zero_allocation_split_scan_remains_cancellable(self):
        pools = [{**POOL, 'id': '0x'+format(index+100, '040x')} for index in range(100)]
        graph_complete = asyncio.Event()
        consumed = 0
        async def observed(*args, **kwargs):
            async for path in discover_routes_async(*args, **kwargs):
                yield path
            graph_complete.set()
        async def consume():
            nonlocal consumed
            async for _row in candidate_branches(pools, A, B, 'exactIn', 1):
                consumed += 1
        with patch('cybergold_candidate.uniswap_routes.discover_routes_async', observed):
            task = asyncio.create_task(consume())
            try:
                await graph_complete.wait()
                self.assertEqual(consumed, len(pools))
                self.assertFalse(task.done())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_graph_error_is_not_hidden_after_standalone_prefix(self):
        error = ValueError('fixture graph failure')
        path = [{'pool': self.pools()[0], 'zeroForOne': True}]
        async def failing(*_args, **_kwargs):
            yield path
            raise error
        with patch('cybergold_candidate.uniswap_routes.discover_routes_async', failing):
            iterator = candidate_branches(self.pools(), A, B, 'exactIn', 101)
            await anext(iterator)
            with self.assertRaises(ValueError) as raised:
                await anext(iterator)
            self.assertIs(raised.exception, error)


class Fees(unittest.TestCase):
    def test_minimal_gross_and_maximal_routed_integer_boundaries(self):
        for amount in range(1, 10_001):
            gross, fee = gross_buy_target(amount, 1000)
            self.assertEqual(fee, quoted_fee(gross, 1000))
            self.assertGreaterEqual(gross-fee, amount)
            self.assertLess(gross-1-quoted_fee(gross-1, 1000), amount)
            routed, fee, dust = routed_sell_budget(amount, 1000)
            self.assertEqual(routed+fee+dust, amount)
            self.assertGreater(routed+1+quoted_fee(routed+1, 1000), amount)
        self.assertEqual(routed_sell_budget(1002, 1000), (1000, 1, 1))

    def test_route_order_and_exact_output_capability(self):
        p = {**POOL, 'protocol': 'v3', 'feePips': 500}
        q = {**POOL, 'id': 'second', 'protocol': 'v4', 'token0': token(B), 'token1': token(C)}
        path = discover_routes([p, q], A, C)[0]
        self.assertTrue(supported_route(path, 'exactIn'))
        self.assertFalse(supported_route(path, 'exactOut'))
        self.assertEqual(v3_path(path[:1], True).lower(), '0x'+B[2:]+'0001f4'+A[2:])


class CatalogAcquisition(unittest.IsolatedAsyncioTestCase):
    # Independent receipt-derived expectations; fake headers/logs exercise the
    # actual acquisition/cursor reducer, never a live factory or quote gate.
    deployments = {
        'v2': ('0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f', 10_000_835),
        'v3': ('0x1F98431c8aD98523631AE4a59f267346ea31F984', 12_369_621),
        'v4': ('0x000000000004444c5dc75cB358380D2e3dE08A90', 21_688_329),
    }

    def fixture(self, chain=1, addresses=None, store=None):
        deployments = self.deployments
        addresses = addresses or {protocol: row[0] for protocol, row in deployments.items()}
        class CatalogRpc(Rpc):
            def __init__(self):
                super().__init__()
                self.chain_id = chain
                self.v2_factory, self.factory, self.pool_manager = (addresses[p] for p in ('v2', 'v3', 'v4'))
                self.queries = []

            async def block(self, number):
                return {'number': number, 'hash': '0x'+hex(number)[2:].rjust(64, '0')}

            async def assert_canonical(self, block):
                assert block == await self.block(block['number'])

            async def read_function(self, address, signature, inputs, args, outputs, block):
                assert signature == 'decimals()'
                return (18,)

            async def logs(self, query):
                self.queries.append(deepcopy(query))
                birth = deployments['v4'][1]
                if query['address'] != self.pool_manager or not int(query['fromBlock'], 16) <= birth <= int(query['toBlock'], 16):
                    return []
                return [{'topics': [DISCOVERY['v4'], v4_pool_id((A, B, 100, 1, ZERO)),
                    '0x'+A[2:].rjust(64, '0'), '0x'+B[2:].rjust(64, '0')],
                    'data': Web3.to_hex(self.w3.codec.encode(['uint24', 'int24', 'address', 'uint160', 'int24'],
                        [100, 1, ZERO, 1 << 96, 0])), 'transactionHash': '0x'+'01'*32,
                    'blockNumber': hex(birth), 'logIndex': '0x0'}]
        rpc = CatalogRpc()
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID=str(chain), NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A,
            ONCHAIN_INDEXER_FROM_BLOCK='25000000')
        return PoolRegistry(settings, rpc=rpc, store=store), rpc

    async def test_cold_known_deployment_starts_inclusive_before_token_deployment(self):
        for chain in (1, 31338):
            with self.subTest(chain=chain):
                registry, rpc = self.fixture(chain)
                try:
                    await registry.discover(await rpc.block(21_688_331), max_blocks=2)
                    self.assertEqual(len(rpc.queries), 6)
                    for _protocol, (address, birth) in self.deployments.items():
                        queries = [row for row in rpc.queries if row['address'] == address]
                        self.assertEqual([int(row['fromBlock'], 16) for row in queries], [birth, birth])
                    pool = registry.inventory[v4_pool_id((A, B, 100, 1, ZERO))]
                    self.assertEqual(pool['discovery']['blockNumber'], '21688329')
                    self.assertEqual(pool['token0']['chainId'], chain)
                finally:
                    await registry.close()

    async def test_saved_cursors_resume_literally_across_restart_below_and_above_floor(self):
        starts = {'v2': 10_000_830, 'v3': 12_369_630, 'v4': 21_688_330}
        store = Store()
        registry, rpc = self.fixture(store=store)
        for protocol, start in starts.items():
            checkpoint = await rpc.block(start-1)
            await store.save('cursor', protocol, {'blockNumber': str(start), 'checkpoints': [
                {'rangeStart': str(start-2), 'blockNumber': str(start-1), 'blockHash': checkpoint['hash']}]})
        try:
            await registry.discover(await rpc.block(21_688_335), max_blocks=2)
            for protocol, start in starts.items():
                address = self.deployments[protocol][0]
                self.assertEqual([int(row['fromBlock'], 16) for row in rpc.queries if row['address'] == address], [start, start])
                self.assertEqual(registry.cursors[protocol]['blockNumber'], str(start+2))
                self.assertEqual(len(registry.cursors[protocol]['checkpoints']), 2)
        finally:
            await registry.close()
        restarted, rpc = self.fixture(store=store)
        try:
            await restarted.discover(await rpc.block(21_688_335), max_blocks=2)
            for protocol, start in starts.items():
                address = self.deployments[protocol][0]
                self.assertEqual([int(row['fromBlock'], 16) for row in rpc.queries if row['address'] == address], [start+2, start+2])
                self.assertEqual(len(restarted.cursors[protocol]['checkpoints']), 3)
        finally:
            await restarted.close()

    async def test_unknown_chain_or_configured_deployment_scans_from_genesis(self):
        custom = dict(zip(('v2', 'v3', 'v4'), (A, B, C), strict=True))
        for chain, addresses in ((31337, None), (1, custom), (31338, custom)):
            with self.subTest(chain=chain, addresses=addresses):
                registry, rpc = self.fixture(chain, addresses)
                try:
                    await registry.discover(await rpc.block(21_688_330), max_blocks=2)
                    self.assertEqual(len(rpc.queries), 6)
                    self.assertTrue(all(row['fromBlock'] == '0x0' for row in rpc.queries))
                finally:
                    await registry.close()

    async def test_completed_catalog_refreshes_incrementally_by_month_and_explicit_force(self):
        store = Store()
        registry, rpc = self.fixture(addresses={'v2': A, 'v3': B, 'v4': C}, store=store)
        self.addAsyncCleanup(registry.close)
        with patch('cybergold_candidate.uniswap_state.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 1, tzinfo=timezone.utc)
            await registry.discover(await rpc.block(2), max_blocks=5)
            self.assertEqual(len(rpc.queries), 6)
            self.assertEqual(registry.discovery_month, '2026-10')
            await registry.discover(await rpc.block(5), max_blocks=5)
            self.assertEqual(len(rpc.queries), 6)
            await registry.discover(await rpc.block(5), force=True, max_blocks=5)
            self.assertEqual([(int(q['fromBlock'], 16), int(q['toBlock'], 16))
                for q in rpc.queries[6:]], [(3, 5)] * 6)
            clock.now.return_value = datetime(2026, 11, 1, tzinfo=timezone.utc)
            await registry.discover(await rpc.block(8), max_blocks=5)
            self.assertEqual([(int(q['fromBlock'], 16), int(q['toBlock'], 16))
                for q in rpc.queries[12:]], [(6, 8)] * 6)
            await asyncio.gather(*tuple(registry.background))
            restarted, _ = self.fixture(addresses={'v2': A, 'v3': B, 'v4': C}, store=store)
            restarted.rpc = rpc
            self.addAsyncCleanup(restarted.close)
            await restarted.discover(await rpc.block(9), max_blocks=5)
            self.assertEqual(len(rpc.queries), 18)
            clock.now.return_value = datetime(2026, 12, 1, tzinfo=timezone.utc)
            await restarted.discover(await rpc.block(10), max_blocks=5)
            self.assertEqual([(int(q['fromBlock'], 16), int(q['toBlock'], 16))
                for q in rpc.queries[18:]], [(9, 10)] * 6)
            self.assertEqual(restarted.discovery_month, '2026-12')


class MarketIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rpc = Rpc()
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A,
            NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS=C, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=C)
        self.registry = PoolRegistry(settings, rpc=self.rpc)
        self.registry.inventory = {C: deepcopy(POOL)}
        node = os.environ.get('CYBERGOLD_TEST_NODE', 'node')
        self.sdk = SdkWorker([node, str(Path('src/uniswap-sdk/worker.ts').resolve())])
        self.cache = DailyRecipientCache(helpers=C)
        self.quotes = MarketQuotes(settings, self.registry, self.sdk, recipient_cache=self.cache)
        async def connectors(*_args):
            pass
        self.quotes.connector_inventory = connectors
        self.request = {'side': 'sell', 'mode': 'exact-in', 'counterToken': B,
            'amount': '1002', 'adapter': C, 'recipient': B, 'deadline': '9999999999', 'slippageBps': 50}

    async def asyncTearDown(self):
        await self.quotes.close()
        await self.registry.close()

    async def test_four_modes_are_fee_inclusive_and_exact_sale_routes_S(self):
        for side in ('buy', 'sell'):
            for mode in ('exact-in', 'exact-out'):
                request = {**self.request, 'side': side, 'mode': mode}
                result = await self.quotes.get(request)
                self.assertEqual(result['qualification'], 'sdk')
                self.assertEqual(result['params']['feeCygld'], result['fee']['amount'])
                decoded = Web3().codec.decode([ADAPTER_TYPE], bytes.fromhex(result['adapterData'][2:]))[0]
                self.assertEqual(decoded[0], mode == 'exact-in')
                self.assertEqual(decoded[1], int(result['plan']['route']['limit']))
                if side == 'sell' and mode == 'exact-in':
                    self.assertEqual(result['params']['routedInput'], '1000')
                    self.assertEqual(decoded[3][0][0], 1000)
                    self.assertEqual(result['refundDust'], '1')
                if side == 'buy' and mode == 'exact-out':
                    self.assertEqual(int(result['grossOutput'])-int(result['fee']['amount']), 1002)
                if side == 'sell' and mode == 'exact-out':
                    self.assertEqual(int(result['totalInput']), int(result['amountIn'])+int(result['fee']['amount']))
        self.assertEqual(self.rpc.owner_reads, 0)

    async def test_replaceable_fee_hook_uses_actual_direction_in_models_and_all_quote_modes(self):
        def policy(chain, token_in, token_out, mode):
            self.assertEqual(chain, 1)
            self.assertIn(mode, ('exact-in', 'exact-out'))
            self.assertEqual({token_in.lower(), token_out.lower()}, {A.lower(), B.lower()})
            return 2500 if token_in.lower() == A.lower() else 3500
        with patch('cybergold_candidate.market_swap.get_market_fee_rate', side_effect=policy):
            for side in ('sell', 'buy'):
                for mode in ('exact-in', 'exact-out'):
                    with self.subTest(side=side, mode=mode):
                        request = {**self.request, 'side': side, 'mode': mode}
                        model = await self.quotes.get_model(request, block=BLOCK)
                        expected = 2500 if side == 'sell' else 3500
                        self.assertEqual(model['feeRatePpm'], expected)
                        quote = await self.quotes.get(request)
                        self.assertEqual(quote['fee']['ratePpm'], expected)
                        self.assertEqual(int(quote['fee']['amount']),
                            quoted_fee(int(quote['fee']['notional']), expected))
        self.assertEqual(self.rpc.owner_reads, 0)

    async def test_changed_fee_hook_reprices_cached_model_without_losing_amm_points(self):
        initial = await self.quotes.get(self.request)
        previous = self.quotes.packet(self.request)
        self.assertTrue(previous['routes'][0]['points'])
        with patch('cybergold_candidate.market_swap.get_market_fee_rate', return_value=2500):
            model = await self.quotes.get_model(self.request, block=BLOCK)
            self.assertEqual(model['feeRatePpm'], 2500)
            self.assertEqual(model['routes'][0]['points'], previous['routes'][0]['points'])
            quote = await self.quotes.get(self.request)
            self.assertEqual(quote['fee']['ratePpm'], 2500)
            self.assertEqual(int(quote['fee']['amount']),
                quoted_fee(int(quote['fee']['notional']), 2500))
            retained = await self.quotes.get({**self.request, 'retainedPlan': initial['plan']})
            self.assertEqual(retained['fee'], initial['fee'])
            self.assertEqual(retained['params']['bound'], initial['params']['bound'])
        self.assertEqual(previous['feeRatePpm'], 1000)
        self.assertEqual(self.rpc.owner_reads, 0)

    async def test_market_only_overlapping_heads_share_and_cancel_independently(self):
        started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def head(_hash):
            self.rpc.head_reads += 1
            started.set()
            try:
                await release.wait()
                return deepcopy(BLOCK)
            except asyncio.CancelledError:
                cancelled.set()
                raise
        self.rpc.block = head
        first = asyncio.create_task(self.quotes.get(self.request))
        second = asyncio.create_task(self.quotes.get(self.request))
        await started.wait()
        # Wait for both subscribers to the same pending context read; no time
        # cache is involved, and cancelling one must not cancel the other.
        while self.registry.pending.pending[('head',1)].users != 2:
            await asyncio.sleep(0)
        first.cancel()
        await asyncio.gather(first,return_exceptions=True)
        self.assertFalse(cancelled.is_set())
        release.set()
        result = await second
        self.assertEqual(result['netOutput'],'1974')
        self.assertEqual(self.rpc.head_reads,1)
        self.assertEqual(self.quotes.sharing.started,1)
        # No completed head retention: a later caller reads again; its last
        # disconnect cancels that read promptly through the shared primitive.
        started.clear()
        release.clear()
        last = asyncio.create_task(self.quotes.get(self.request))
        await started.wait()
        last.cancel()
        await asyncio.gather(last,return_exceptions=True)
        await asyncio.wait_for(cancelled.wait(),1)
        self.assertEqual(self.rpc.head_reads,2)

    async def test_cold_model_needs_no_amount_or_prior_quote_and_bank_is_tagged(self):
        request = {name: self.request[name] for name in ('side', 'mode', 'counterToken', 'adapter')}
        packet = await self.quotes.get_model(request)
        self.assertEqual(packet['namespace'], 'market')
        self.assertEqual(packet['feeRatePpm'], 1000)
        self.assertEqual(packet['routes'][0]['points'], [])
        self.assertEqual(packet['routes'][0]['exchangeRate'], {'numerator': '2', 'denominator': '1'})
        self.assertIsNotNone(self.quotes.estimate(packet, self.request))
        self.assertEqual(self.rpc.owner_reads, 0)

    async def test_snapshot_shared_and_sdk_candidate_does_not_mutate_observation(self):
        states = await asyncio.gather(*(self.registry.snapshot(POOL, BLOCK) for _ in range(10)))
        self.assertEqual(self.rpc.state_reads, 1)
        value = await self.sdk.request({'operation': 'quote', 'mode': 'exactIn', 'amount': '1000',
            'pools': [states[0]], 'poolId': C, 'zeroForOne': True})
        self.assertEqual(value['amountOut'], '1974')
        self.assertEqual(states[0]['reserve0'], '100000')
        self.assertEqual(self.registry.observed[C]['reserve0'], '100000')
        self.assertEqual(value['postState']['reserve0'], '101000')

    async def test_retained_quote_preserves_fee_and_bound_without_new_search(self):
        quote = await self.quotes.get(self.request)
        async def no_search(*_args):
            raise AssertionError('Accepted-route revalidation enumerated candidates')
        self.quotes.connector_inventory = no_search
        repeated = await self.quotes.get({**self.request, 'retainedPlan': quote['plan'], 'deadline': '10000000000'})
        self.assertEqual(repeated['fee'], quote['fee'])
        self.assertEqual(repeated['params']['bound'], quote['params']['bound'])
        self.assertEqual(repeated['params']['deadline'], '10000000000')

    async def test_retained_quote_reprices_with_sdk_and_keeps_frozen_fee_and_limits(self):
        quote = await self.quotes.get(self.request)
        reference = AsyncMock(side_effect=AssertionError('Contract pricing is retired'))
        self.quotes.quote_fallback_branches = reference
        sdk = self.sdk.request
        calls = []
        async def priced(payload, **kwargs):
            calls.append(deepcopy(payload))
            return await sdk(payload, **kwargs)
        self.sdk.request = priced
        repeated = await self.quotes.get({**self.request, 'retainedPlan': quote['plan'], 'deadline': '10000000000'})
        reference.assert_not_awaited()
        self.assertEqual([row['operation'] for row in calls], ['simulateRoute'])
        self.assertEqual(repeated['qualification'], 'sdk')
        self.assertEqual(repeated['fee'], quote['fee'])
        self.assertEqual(repeated['params']['bound'], quote['params']['bound'])
        self.assertEqual(repeated['netOutput'], quote['netOutput'])

    async def test_retained_pool_metadata_uses_canonical_inventory_and_wrong_direction_researches(self):
        quote = await self.quotes.get(self.request)
        retained = deepcopy(quote['plan'])
        pool = retained['route']['branches'][0]['hops'][0]['pool']
        pool.update(protocol='v4', feePips=10000, hooks=C, tickSpacing=200)
        pool['token1'] = token(C)
        result = await self.quotes.get({**self.request, 'retainedPlan': retained})
        self.assertEqual(result['adapterData'], quote['adapterData'])
        self.assertEqual(result['plan']['route']['branches'][0]['hops'][0]['pool'], POOL)
        retained['route']['branches'][0]['hops'][0]['zeroForOne'] = False
        events = []
        result = await self.quotes.get({**self.request, 'retainedPlan': retained}, lambda event: collect(events, event))
        self.assertTrue(any(event['type'] == 'invalidated' for event in events))
        self.assertEqual(result['adapterData'], quote['adapterData'])

    async def test_http_model_quote_and_stream_use_separate_market_contract(self):
        app = create_app(market_quotes=self.quotes)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
            model = await client.post('/api/quotes/market/model', json={name: self.request[name]
                for name in ('side', 'mode', 'counterToken', 'adapter')})
            self.assertEqual(model.status_code, 200)
            quote = await client.post('/api/quotes/market', json=self.request)
            self.assertEqual(quote.status_code, 200)
            self.assertEqual(quote.json()['operation'], 'market')
            stream = await client.post('/api/quotes/market/stream', json=self.request)
            self.assertIn('"type":"complete"', stream.text)

    async def test_daily_recipient_is_advisory_and_reuses_last_good(self):
        await self.cache.refresh(self.rpc, BLOCK)
        await self.cache.refresh(self.rpc, BLOCK)
        self.assertEqual(self.rpc.owner_reads, 1)
        value = await self.quotes.get(self.request)
        self.assertEqual(value['feeBeneficiaryDisplay']['address'], C)
        self.assertEqual(self.rpc.owner_reads, 1)
        self.assertNotIn('feeRecipient', value['params'])

    async def test_blocked_optional_inventory_and_recipient_store_do_not_hold_exact_quote(self):
        # Isolate the cache-dependency assertion from cold Node process startup
        # (notably under CPU emulation). No registry state/model is prequalified.
        await self.sdk.request({'operation': 'quote', 'mode': 'exactIn', 'amount': '1000',
            'poolId': C, 'zeroForOne': True, 'pools': [{**POOL, 'reserve0': '100000', 'reserve1': '200000'}]})
        self.assertFalse(self.registry.observed)
        self.assertFalse(self.quotes.models)
        started = asyncio.Event()
        class BlockedStore:
            async def load(self, namespace):
                started.set()
                await asyncio.Event().wait()
            async def save(self, *args):
                await asyncio.Event().wait()
        store = BlockedStore()
        self.registry.store = self.cache.store = store
        result = await asyncio.wait_for(self.quotes.get(self.request), 2)
        self.assertEqual(result['netOutput'], '1974')
        self.assertTrue(started.is_set())
        self.assertNotIn('feeBeneficiaryDisplay', result)
        self.assertEqual(self.rpc.owner_reads, 0)

    async def test_cold_v4_state_view_preserves_wide_values_and_directional_fees_at_one_hash(self):
        pool = {**POOL, 'id': v4_pool_id((A, B, 100, 1, ZERO)), 'protocol': 'v4',
            'feePips': 100, 'tickSpacing': 1, 'hooks': ZERO}
        self.rpc.state_view = STATE_VIEW
        reads = []
        async def read(address, signature, inputs, args, outputs, block):
            reads.append((address, signature, inputs, args, outputs, block))
            if signature == 'getSlot0(bytes32)':
                self.assertEqual(outputs, ['uint160', 'int24', 'uint24', 'uint24'])
                return 441947936735403526595706575860, 34378, 102425, 100
            self.assertEqual(signature, 'getLiquidity(bytes32)')
            self.assertEqual(outputs, ['uint128'])
            return (879772594612909362900,)
        self.rpc.read_function = read
        snapshot = await self.registry.snapshot(pool, BLOCK)
        self.assertEqual({key: snapshot[key] for key in ('sqrtRatioX96', 'tick', 'protocolFee', 'lpFee', 'liquidity')},
            {'sqrtRatioX96': '441947936735403526595706575860', 'tick': 34378,
             'protocolFee': 102425, 'lpFee': 100, 'liquidity': '879772594612909362900'})
        self.assertEqual(len(reads), 2)
        for address, _signature, inputs, args, _outputs, block in reads:
            self.assertEqual((address, inputs, args, block), (STATE_VIEW, ['bytes32'], [bytes.fromhex(pool['id'][2:])], BLOCK))
        self.assertEqual(await self.registry.snapshot(pool, BLOCK), snapshot)
        self.assertEqual(len(reads), 2)

    async def test_event_updates_only_dirty_ticks_and_active_liquidity(self):
        state = {'protocol': 'v4', 'tick': 5, 'tickSpacing': 1, 'liquidity': '100',
            'ticks': [{'index': 0}, {'index': 10}, {'index': 300}],
            'bitmapWords': [{'wordPosition': 0, 'bitmap': '1025'}, {'wordPosition': 1, 'bitmap': '1'}]}
        log = {'topics': [EVENTS['ModifyLiquidity']], 'data': Web3.to_hex(Web3().codec.encode(
            ['int24', 'int24', 'int256', 'bytes32'], [0, 10, 20, bytes(32)]))}
        self.registry.apply_event(state, log)
        self.assertEqual(state['liquidity'], '120')
        self.assertEqual(state['ticks'], [{'index': 300}])
        self.assertEqual(state['bitmapWords'], [{'wordPosition': 1, 'bitmap': '1'}])

    async def test_ordinary_swap_carries_tick_coverage_to_next_hash_without_getter_reads(self):
        pool = {**POOL, 'protocol': 'v3', 'feePips': 500, 'tickSpacing': 10}
        old = {**pool, 'sqrtRatioX96': str(1 << 96), 'tick': 0, 'liquidity': '1000000',
            'ticks': [{'index': -10, 'liquidityGross': '100', 'liquidityNet': '100'}],
            'bitmapWords': [{'wordPosition': -1, 'bitmap': str(1 << 255)}],
            'context': {'chainId': 1, 'blockNumber': '123', 'blockHash': BLOCK['hash']}}
        self.registry.observed[C] = deepcopy(old)
        next_block = {'number': 124, 'hash': '0x'+'cd'*32}
        reads_before = self.rpc.state_reads
        async def canonical(_block):
            pass
        async def logs(_query):
            return [{'topics': [V3_SWAP], 'data': Web3.to_hex(Web3().codec.encode(
                ['int256', 'int256', 'uint160', 'uint128', 'int24'], [5, -4, (1 << 96)+1, 1000000, 0])),
                'blockNumber': '0x7c', 'transactionIndex': '0x0', 'logIndex': '0x0'}]
        self.rpc.assert_canonical, self.rpc.logs = canonical, logs
        observed = await self.registry.snapshot(pool, next_block)
        self.assertEqual(observed['bitmapWords'], old['bitmapWords'])
        self.assertEqual(observed['ticks'], old['ticks'])
        self.assertEqual(observed['sqrtRatioX96'], str((1 << 96)+1))
        self.assertEqual(observed['context']['blockHash'], next_block['hash'])
        self.assertEqual(self.rpc.state_reads, reads_before)

    async def test_v3_connector_fallback_spacing_crosses_real_initialized_boundary(self):
        self.rpc.v2_factory, self.rpc.factory = A, A
        async def read(address, signature, inputs, args, outputs, block):
            if signature == 'getPair(address,address)':
                return (ZERO,)
            if signature == 'getPool(address,address,uint24)':
                return (C if args[-1] == 500 else ZERO,)
            if signature == 'tickSpacing()':
                raise ValueError('Transient optional metadata read failure')
            if signature == 'decimals()':
                return (18,)
            raise AssertionError(signature)
        self.rpc.read_function = read
        await MarketQuotes.connector_inventory(self.quotes, A, B, BLOCK)
        pool = next(pool for pool in self.registry.inventory.values() if pool['protocol'] == 'v3'
            and pool['token0']['address'].lower() == A.lower() and pool['token1']['address'].lower() == B.lower())
        self.assertEqual(pool['tickSpacing'], 10)
        state = {**pool, 'sqrtRatioX96': str(1 << 96), 'tick': 0, 'liquidity': '1000000',
            'ticks': [{'index': -1000, 'liquidityGross': '1500000', 'liquidityNet': '1500000'},
                {'index': -10, 'liquidityGross': '500000', 'liquidityNet': '-500000'},
                {'index': 1000, 'liquidityGross': '1000000', 'liquidityNet': '-1000000'}],
            'bitmapWords': [{'wordPosition': -1, 'bitmap': str((1 << 255)+(1 << 156))},
                {'wordPosition': 0, 'bitmap': str(1 << 100)}]}
        result = await self.sdk.request({'operation': 'quote', 'mode': 'exactIn', 'amount': '1000',
            'pools': [state], 'poolId': pool['id'], 'zeroForOne': True})
        self.assertTrue(result['fullyFilled'])
        self.assertEqual(result['postState']['liquidity'], '1500000')

    async def test_sdk_economics_rank_candidates_without_contract_repricing(self):
        other = {**POOL, 'id': '0x'+'4'.rjust(40, '0'), 'address': '0x'+'4'.rjust(40, '0'),
            'protocol': 'v3', 'feePips': 100, 'tickSpacing': 1}
        self.registry.inventory[other['id']] = other
        read = self.rpc.read_function
        async def state(address, signature, inputs, args, outputs, block):
            if signature == 'slot0()':
                return 1 << 96, 0, 0, 0, 0, 0, True
            if signature == 'liquidity()':
                return (10**12,)
            if signature == 'tickBitmap(int16)':
                return (0,)
            return await read(address, signature, inputs, args, outputs, block)
        self.rpc.read_function = state
        reference = AsyncMock(side_effect=AssertionError('Contract pricing is retired'))
        self.quotes.quote_fallback_branches = reference
        sdk, prices = self.sdk.request, []
        async def priced(payload, **kwargs):
            value = await sdk(payload, **kwargs)
            prices.append(({pool['protocol'] for pool in payload.get('pools', [])}, deepcopy(value)))
            return value
        self.sdk.request = priced
        request = {**self.request, 'mode': 'exact-out'}
        result = await self.quotes.get(request)
        reference.assert_not_awaited()
        self.assertTrue(any(protocols == {'v3'} and value['fullyFilled'] for protocols, value in prices))
        self.assertTrue(any(protocols == {'v2'} and value['fullyFilled'] for protocols, value in prices))
        self.assertEqual(result['qualification'], 'sdk')
        self.assertEqual(result['netOutput'], request['amount'])
        self.assertEqual(result['plan']['route']['branches'][0]['hops'][0]['pool']['id'], POOL['id'])
        self.assertEqual(result['amountIn'], '506')
        self.assertEqual(result['totalInput'], '507')

    async def test_unavailable_v4_sdk_state_never_uses_contract_quote(self):
        pool = {**POOL, 'protocol': 'v4', 'feePips': 100, 'tickSpacing': 1, 'hooks': ZERO}
        self.rpc.state_view = C
        quoted = []
        async def read(_address, signature, _inputs, _args, _outputs, _block):
            if signature.startswith('quoteExact'):
                quoted.append(signature)
                return (500, 21000)
            raise ValueError('Pinned SDK state unavailable')
        self.rpc.read_function = read
        branches = [{'amountIn': '0', 'hops': [{'pool': pool, 'zeroForOne': False}]}]
        with self.assertRaises(ValueError):
            await self.quotes.quote_branches(branches, 'exactOut', 1004, BLOCK)
        self.assertEqual(quoted, [])

    async def test_sdk_exact_output_keeps_proven_forward_overdelivery(self):
        read = self.rpc.read_function
        async def state(address, signature, inputs, args, outputs, block):
            if signature == 'getReserves()':
                return 200_000, 100_000, 0
            return await read(address, signature, inputs, args, outputs, block)
        self.rpc.read_function = state
        reference = AsyncMock(side_effect=AssertionError('Contract pricing is retired'))
        self.quotes.quote_fallback_branches = reference
        request = {**self.request, 'amount': '1000', 'side': 'buy', 'mode': 'exact-out'}
        quote = await self.quotes.get(request)
        reference.assert_not_awaited()
        self.assertEqual(quote['qualification'], 'sdk')
        self.assertEqual(quote['amountOut'], '1003')
        self.assertEqual(quote['grossOutput'], '1002')
        self.assertEqual(quote['outputRefundEstimate'], '1')
        self.assertEqual(quote['fee']['amount'], '2')

    async def test_stream_publishes_sdk_terms_without_contract_repricing(self):
        reference = AsyncMock(side_effect=AssertionError('Contract pricing is retired'))
        self.quotes.quote_fallback_branches = reference
        app = create_app(market_quotes=self.quotes)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
            response = await client.post('/api/quotes/market/stream', json=self.request)
        events = [json.loads(line) for line in response.text.splitlines()]
        reference.assert_not_awaited()
        self.assertFalse(any(event['type'] == 'invalidated' for event in events))
        qualified = next(event for event in events if event['type'] == 'qualified')
        self.assertEqual(qualified['value']['qualification'], 'sdk')
        self.assertEqual(qualified['value']['netOutput'], '1974')
        self.assertEqual(events[-1]['type'], 'complete')
        self.assertEqual(events[-1]['value']['netOutput'], '1974')

    async def test_amount_edits_across_blocks_reuse_factory_identity_and_decimals(self):
        self.rpc.v2_factory, self.rpc.factory = A, A
        reads = []
        old_read = self.rpc.read_function
        async def read(address, signature, inputs, args, outputs, block):
            reads.append(signature)
            if signature == 'getPair(address,address)':
                return (C if set(args) == {A.lower(), B.lower()} else ZERO,)
            if signature == 'getPool(address,address,uint24)':
                return (ZERO,)
            if signature == 'decimals()':
                return (18,)
            if signature == 'getAmountsOut(uint256,address[])':
                raise ValueError('Native reference unavailable in fixture')
            return await old_read(address, signature, inputs, args, outputs, block)
        async def canonical(_block):
            pass
        async def logs(_query):
            return []
        self.rpc.read_function, self.rpc.assert_canonical, self.rpc.logs = read, canonical, logs
        self.quotes.connector_inventory = MethodType(MarketQuotes.connector_inventory, self.quotes)
        self.registry.inventory.clear()
        first = await self.quotes._get(self.request, block=BLOCK)
        static = {name: reads.count(name) for name in ('getPair(address,address)',
            'getPool(address,address,uint24)', 'decimals()')}
        self.assertGreater(static['getPair(address,address)'], 0)
        self.assertEqual(static['decimals()'], 2)
        second = await self.quotes._get({**self.request, 'amount': '2002'}, block={
            'number': 124, 'hash': '0x'+'cd'*32})
        self.assertNotEqual(first['netOutput'], second['netOutput'])
        self.assertEqual(static['getPair(address,address)'], reads.count('getPair(address,address)'))
        self.assertEqual(static['decimals()'], reads.count('decimals()'))
        # Negative catalog observations are advisory. SDK state acquisition
        # checks all four direct hops and both hops of nine via-WETH candidates
        # at the new block instead of inheriting an old absence as a veto.
        self.assertEqual(reads.count('getPool(address,address,uint24)'),
                         static['getPool(address,address,uint24)']+4+2*9)
        self.assertEqual(reads.count('getReserves()'), 1)

    async def test_native_and_unknown_metadata_pool_do_not_abort_catalog(self):
        self.rpc.v2_factory, self.rpc.factory, self.rpc.pool_manager = A, B, C
        decimals_reads = []
        async def read(address, signature, inputs, args, outputs, block):
            self.assertEqual(signature, 'decimals()')
            decimals_reads.append(address.lower())
            self.assertNotEqual(address.lower(), ZERO)
            if address.lower() == B.lower():
                raise ValueError('Optional decimals unavailable')
            return (18,)
        def event(counter, index):
            a, b = sorted((A.lower(), counter.lower()))
            identity = v4_pool_id((a, b, 100, 1, ZERO))
            return {'topics': [DISCOVERY['v4'], identity, '0x'+a[2:].rjust(64, '0'), '0x'+b[2:].rjust(64, '0')],
                'data': Web3.to_hex(Web3().codec.encode(['uint24', 'int24', 'address', 'uint160', 'int24'],
                    [100, 1, ZERO, 1 << 96, 0])), 'transactionHash': '0x'+str(index).rjust(64, '0'),
                'blockNumber': '0x7b', 'logIndex': hex(index)}
        rows = [event(ZERO, 0), event(B, 1), event(C, 2)]
        async def logs(query):
            return rows if query['address'] == C else []
        self.rpc.read_function, self.rpc.logs = read, logs
        self.registry.inventory.clear()
        await self.registry.discover(BLOCK)
        self.assertEqual(len(self.registry.inventory), 3)
        native = next(pool for pool in self.registry.inventory.values() if pool['token0']['address'] == ZERO)
        self.assertEqual(native['token0']['decimals'], 18)
        unknown = next(pool for pool in self.registry.inventory.values() if any(
            token['address'].lower() == B.lower() for token in (pool['token0'], pool['token1'])))
        self.assertTrue(any(token.get('decimalsKnown') is False for token in (unknown['token0'], unknown['token1'])))
        self.assertEqual(self.registry.cursors['v4']['blockNumber'], '124')
        self.assertIsNotNone(self.registry.discovery_month)

    async def test_catalog_reorg_after_restart_replaces_orphan_identity(self):
        self.rpc.v2_factory, self.rpc.factory, self.rpc.pool_manager = A, B, C
        store = Store()
        self.registry.store = store
        new_block = {**BLOCK, 'hash': '0x'+'cd'*32}
        current = BLOCK
        async def canonical(block):
            if block['hash'] != current['hash']:
                raise RecoveryApiError('Snapshot changed', retry=1)
        async def read(*args):
            return (18,)
        def event(fee):
            identity = v4_pool_id((A, B, fee, 1, ZERO))
            return {'topics': [DISCOVERY['v4'], identity, '0x'+A[2:].rjust(64, '0'), '0x'+B[2:].rjust(64, '0')],
                'data': Web3.to_hex(Web3().codec.encode(['uint24', 'int24', 'address', 'uint160', 'int24'],
                    [fee, 1, ZERO, 1 << 96, 0])), 'transactionHash': '0x'+'01'*32,
                'blockNumber': '0x7b', 'logIndex': '0x0'}
        async def logs(query):
            return [event(100 if current == BLOCK else 500)] if query['address'] == C else []
        self.rpc.assert_canonical, self.rpc.read_function, self.rpc.logs = canonical, read, logs
        await self.registry.discover(BLOCK)
        await asyncio.gather(*tuple(self.registry.background))
        orphan = event(100)['topics'][1]
        self.assertIn(orphan, store.data['inventory'])
        current = new_block
        restarted = PoolRegistry(self.quotes.settings, rpc=self.rpc, store=store)
        try:
            await restarted.discover(new_block)
            replacement = event(500)['topics'][1]
            self.assertNotIn(orphan, restarted.inventory)
            self.assertNotIn(orphan, store.data['inventory'])
            self.assertIn(replacement, restarted.inventory)
            self.assertEqual(restarted.cursors['v4']['checkpoints'][-1]['blockHash'], new_block['hash'])
        finally:
            await restarted.close()

    async def test_large_warm_tick_coverage_crosses_real_sdk_ipc(self):
        state = {**POOL, 'protocol': 'v3', 'feePips': 500, 'tickSpacing': 10,
            'sqrtRatioX96': str(1 << 96), 'tick': 0, 'liquidity': '1000000000000', 'ticks': [],
            'bitmapWords': [{'wordPosition': index, 'bitmap': '0'} for index in range(-2000, 2001)]}
        self.assertGreater(len(json.dumps(state)), 64*1024)
        value = await self.sdk.request({'operation': 'quote', 'mode': 'exactIn', 'amount': '1000',
            'pools': [state], 'poolId': C, 'zeroForOne': True})
        self.assertTrue(value['fullyFilled'])
        self.assertGreater(int(value['amountOut']), 0)
        self.assertNotIn('bitmapWords', value['postState'])
        self.assertEqual(len(state['bitmapWords']), 4001)

    async def test_bad_worker_frame_resets_and_next_request_recovers(self):
        script = '''import json,sys
for line in sys.stdin:
    request=json.loads(line)
    if request.get('bad'): print('x'*(5*1024*1024),flush=True)
    else: print(json.dumps({'id':request['id'],'result':{'amountOut':'1'}}),flush=True)
'''
        worker = SdkWorker([sys.executable, '-u', '-c', script])
        try:
            with self.assertRaises(ValueError):
                await worker.request({'bad': True})
            self.assertIsNone(worker.process)
            self.assertEqual(await worker.request({}), {'amountOut': '1'})
        finally:
            await worker.close()

    async def test_optional_connector_failure_keeps_cached_quote_and_drains_parallel_baseline(self):
        started, stopped = asyncio.Event(), asyncio.Event()
        async def model(*_args, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        async def connectors(*_args):
            await started.wait()
            raise ValueError('Fixture connector error')
        self.quotes.get_model, self.quotes.connector_inventory = model, connectors
        result = await self.quotes._get(self.request, block=BLOCK)
        self.assertGreater(int(result['netOutput']), 0)
        self.assertTrue(stopped.is_set())

    async def test_dense_graph_is_cooperatively_cancellable(self):
        pools = [{**POOL, 'id': str(index), 'token0': token(A), 'token1': token(B)} for index in range(20000)]
        yielded = 0
        async def collect():
            nonlocal yielded
            async for _route in discover_routes_async(pools, A, B):
                yielded += 1
        task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(task.cancelled())
        self.assertLess(yielded, len(pools))

    async def test_existing_fork_generation_scopes_durable_inventory_and_display_recipient(self):
        settings = SimpleNamespace(**vars(self.quotes.settings))
        settings.NEXT_PUBLIC_CHAIN_ID = '31338'
        store = Store()
        registry = PoolRegistry(settings, rpc=self.rpc, store=store)
        try:
            await registry.observe_generation('fork-a')
            await store.save('inventory', C, POOL)
            await store.save('cursor', 'v2', {'blockNumber': '124', 'checkpoints': []})
            await store.save('recipient', C, {'address': B, 'observedAt': 'earlier'})
            await registry.ensure_loaded(wait=True)
            self.assertIn(C, registry.inventory)
            await registry.observe_generation('fork-b')
            await registry.ensure_loaded(wait=True)
            self.assertNotIn(C, registry.inventory)
            self.assertEqual(registry.cursors, {})
            self.assertEqual(await store.load('recipient'), {})
            await registry.observe_generation('fork-a')
            await registry.ensure_loaded(wait=True)
            self.assertIn(C, registry.inventory)
            self.assertEqual((await store.load('recipient'))[C]['address'], B)
        finally:
            await registry.close()

    async def test_superseded_cold_model_cannot_repopulate_current_generation(self):
        started, finish = asyncio.Event(), asyncio.Event()
        snapshot = self.registry.snapshot
        async def delayed(pool, block):
            state = await snapshot(pool, block)
            started.set()
            await finish.wait()
            return state
        self.registry.snapshot = delayed
        model_request = {name: self.request[name] for name in ('side', 'mode', 'counterToken', 'adapter')}
        task = asyncio.create_task(self.quotes.get_model(model_request, block=BLOCK))
        await started.wait()
        await self.quotes.observe_generation('new-fork')
        finish.set()
        packet = await task
        self.assertEqual(packet['routes'], [])
        self.assertEqual(self.quotes.models, {})

    async def test_missing_old_checkpoint_rewinds_but_transport_failure_preserves_cursor(self):
        old = {'blockNumber': '124', 'checkpoints': [{'rangeStart': '100',
            'blockNumber': '123', 'blockHash': BLOCK['hash']}]}
        self.registry.cursors['v4'] = deepcopy(old)
        orphan = {**POOL, 'protocol': 'v4', 'discovery': {'protocol': 'v4', 'blockNumber': '121'}}
        self.registry.inventory[C] = orphan
        async def unavailable(_block):
            raise OSError('Ordinary transport outage')
        self.rpc.assert_canonical = unavailable
        with self.assertRaises(OSError):
            await self.registry.recover_catalog()
        self.assertEqual(self.registry.cursors['v4'], old)
        self.assertIn(C, self.registry.inventory)
        async def missing(_block):
            raise BlockNotFound('Rolled-back checkpoint is above current head')
        self.rpc.assert_canonical = missing
        await self.registry.recover_catalog()
        self.assertEqual(self.registry.cursors['v4']['blockNumber'], '100')
        self.assertTrue(self.registry.cursors['v4']['pending'])
        self.assertNotIn(C, self.registry.inventory)

    async def test_market_execution_abi_accepts_native_permit_full_lot(self):
        quote = await self.quotes.get(self.request)
        function = next(row for row in ABI if row['name'] == 'swapExactInput')
        funding = {'mode': 1, 'nativePermit': {'value': '1002', 'deadline': '9999999999', 'v': 27,
            'r': '0x'+'00'*32, 's': '0x'+'00'*32}, 'permit2': {'permit': {'permitted': {'token': A,
            'amount': '0'}, 'nonce': '0', 'deadline': '0'}, 'signature': '0x'}}
        params = [argument(quote['params'], function['inputs'][0]), argument(funding, function['inputs'][1])]
        encoded = Web3().eth.contract(abi=ABI).encode_abi('swapExactInput', args=params)
        self.assertTrue(encoded.startswith('0x'))
        self.assertEqual(params[0][4], 1000)
        self.assertEqual(params[1][1][0], 1002)

    async def test_historical_adapter_uses_shared_engine_and_preserves_legacy_v3_encoding(self):
        from test_quote_intent import service, request
        legacy = '0x4edb8190232a47e45d861003672938eb7ee84a15'
        intent, _provider, routes, _wire = service()
        search = AsyncMock(wraps=routes.engine.search_routes)
        routes.engine.search_routes = search
        try:
            value = request('issue-exact-out')
            value['adapter'] = legacy
            result = await intent.get(value, lambda _event: asyncio.sleep(0))
            self.assertTrue(result['quotes'])
            for leg in result['quotes']:
                plan = leg['routePlan']
                self.assertEqual(len(plan['branches']), 1)
                self.assertTrue(all(hop['pool']['protocol'] == 'v3' for hop in plan['branches'][0]['hops']))
                Web3().codec.decode(['bytes', 'uint256', 'uint256', 'bool'], bytes.fromhex(leg['data'][2:]))
            await routes.get({'mode': 'exact-in', 'targets': value['targets']})
            self.assertGreaterEqual(search.await_count, 2)
        finally:
            await routes.close()

    async def test_core_reserve_provider_is_fee_neutral_and_typed_revalidation_retains_limits(self):
        target = {'inputAsset': A, 'outputAsset': B, 'amount': '1000'}
        rows = await self.quotes.reserve_quotes({'mode': 'exact-in', 'adapter': C, 'targets': [target]}, BLOCK)
        self.assertEqual(rows[0]['best']['quote'], '1974')
        plan = rows[0]['best']['routePlan']
        self.assertEqual(plan['executionContext'], 'helpers-core')
        plan.update(limit='1900', deadline='9999999999')
        leg = {'adapter': C, 'inputAsset': A, 'inputAmount': '1000', 'minimumAmountOut': '1900',
            'routePlan': plan, 'data': encode_adapter(plan)}
        outputs = [{'kind': 0, 'token': A, 'id': '0', 'amount': '1000'}]
        request = {'mode': 'redeem-exact-in', 'native': False, 'amount': '100',
            'quoteToken': B, 'token': B, 'adapter': C, 'orderedAssets': [A], 'deadline': '10000000000', 'slippageBps': 50}
        previous = {'executionAmount': '100', 'maximumInputAmount': '0', 'quotes': [leg],
            'expectedCoreOutputs': core_bounds(outputs, 50), 'preview': {'minimumAmountOut': '1900'}, 'slippageBps': 50}
        async def preview(service, _value):
            return {'projectedCoreOutputs': outputs, **({'minimumAmountOut': '1900'} if service == 'token' else {})}
        self.rpc.route_engine = self.quotes
        metrics = dict.fromkeys(('rpcReads', 'rpcReadsRequested', 'rpcReadsCoalesced', 'rpcReadsReused', 'candidateCalls'), 0)
        result = await revalidate(request, previous, self.rpc, BLOCK, 'basket', 'token', preview, metrics)
        changed = result['quotes'][0]
        self.assertEqual(changed['routePlan']['limit'], '1900')
        self.assertEqual(changed['routePlan']['deadline'], '10000000000')
        self.assertEqual(changed['routePlan']['executionContext'], 'helpers-core')

    async def test_route_priority_keeps_complete_paths_and_ordered_splits(self):
        d = '0x'+'4'*40
        pools = [{**POOL, 'id': identity, 'token0': token(left), 'token1': token(right)}
            for identity, left, right in [('00', A, C), ('01', C, d), ('02', d, B),
                                         ('03', C, B), ('99', A, B)]]
        paths = [path async for path in discover_routes_async(pools, A, B)]
        identities = [tuple(hop['pool']['id'] for hop in path) for path in paths]
        self.assertEqual(identities, [('99',), ('00', '03'), ('00', '01', '02')])
        self.assertEqual({tuple(hop['pool']['id'] for hop in path)
            for path in discover_routes(pools, A, B)}, set(identities))
        branches = [row async for row in candidate_branches(pools, A, B, 'exactIn', 100)]
        self.assertEqual(len(branches), 3+3*3)
        self.assertTrue(all(sum(int(branch['amountIn']) for branch in row) == 100 for row in branches))
        self.assertEqual(len({tuple((branch['amountIn'], tuple(hop['pool']['id'] for hop in branch['hops']))
            for branch in row) for row in branches}), len(branches))

    async def test_core_reserve_progress_precedes_tail_for_every_leg_and_retains_full_coverage(self):
        d, e = '0x'+'4'*40, '0x'+'5'*40
        pools = [{**POOL, 'id': str(index), 'token0': token(left), 'token1': token(right)}
            for index, (left, right) in enumerate([(A, B), (C, B), (A, d), (C, d), (d, e), (e, B)])]
        self.registry.inventory = {pool['id']: pool for pool in pools}
        targets = [{'inputAsset': source, 'outputAsset': B, 'amount': '1000'} for source in (A, C)]
        release, ready = asyncio.Event(), asyncio.Event()
        expected, observed, frames = [], [], []
        active, maximum = 0, 0
        for target in targets:
            expected.extend([(target['inputAsset'], json.dumps(branches, sort_keys=True))
                async for branches in candidate_branches(pools, target['inputAsset'], B, 'exactIn', 1000)])
        async def quote(branches, mode, amount, block):
            nonlocal active, maximum
            if any(hop['pool']['protocol'] == 'v3' for branch in branches for hop in branch['hops']):
                raise SdkWorkerError('Fixture liquidity is V2 only')
            source = branches[0]['hops'][0]['pool']['token0']['address']
            observed.append((source, json.dumps(branches, sort_keys=True)))
            active += 1
            maximum = max(maximum, active)
            try:
                if any(len(branch['hops']) > 1 for branch in branches):
                    await release.wait()
                return {'amountIn': str(amount), 'amountOut': str(2000+sum(len(branch['hops']) for branch in branches))}
            finally:
                active -= 1
        async def update(rows):
            frames.append(deepcopy(rows))
            if all(row['best'] for row in rows):
                ready.set()
        self.quotes.quote_branches = quote
        operation = asyncio.create_task(self.quotes.reserve_quotes({'mode': 'exact-in', 'adapter': C, 'targets': targets}, BLOCK, on_update=update))
        try:
            await asyncio.wait_for(ready.wait(), 1)
            self.assertFalse(operation.done())
            first = next(frame for frame in frames if all(row['best'] for row in frame))
            self.assertEqual([row['best']['quote'] for row in first], ['2001', '2001'])
            release.set()
            final = await operation
            self.assertCountEqual(observed, expected)
            self.assertLessEqual(maximum, 8)
            self.assertEqual(sum(row['attempted'] for row in final), len(expected)+26)
            self.assertEqual(sum(row['succeeded'] for row in final), len(expected))
            self.assertTrue(all(int(row['best']['quote']) > 2001 for row in final))
        finally:
            release.set()
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_cancelled_core_reserve_search_does_not_cancel_other_search(self):
        started = {1000: asyncio.Event(), 2000: asyncio.Event()}
        stopped, release = set(), asyncio.Event()
        async def quote(branches, mode, amount, block):
            if any(hop['pool']['protocol'] == 'v3' for branch in branches for hop in branch['hops']):
                raise SdkWorkerError('Fixture liquidity is V2 only')
            started[amount].set()
            try:
                await release.wait()
                return {'amountIn': str(amount), 'amountOut': str(amount*2)}
            finally:
                stopped.add(amount)
        self.quotes.quote_branches = quote
        quotes, diagnostics = self.quotes, {}
        class ObservedReserve:
            @route_work_scope
            async def get(self, value):
                return await quotes.reserve_quotes(value, BLOCK, on_update=lambda _rows: asyncio.sleep(0))
        @quote_work_scope
        async def search(amount):
            quote_phase('initial-search')
            try:
                result = await ObservedReserve().get({'mode': 'exact-in', 'adapter': C, 'targets': [
                    {'inputAsset': A, 'outputAsset': B, 'amount': str(amount)}]})
            except asyncio.CancelledError as error:
                diagnostics[amount] = public_quote_error(error)['quoteDiagnostics']
                raise
            probe = ValueError('offline snapshot')
            freeze_quote_work(probe)
            diagnostics[amount] = public_quote_error(probe)['quoteDiagnostics']
            return result
        first, other = asyncio.create_task(search(1000)), asyncio.create_task(search(2000))
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 1)
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            self.assertTrue(first.cancelled())
            cancelled = diagnostics[1000]['routeWave']
            self.assertEqual(cancelled['typedPending'], 1)
            self.assertEqual(cancelled['typedEnumerated']-cancelled['typedCompleted'], 1)
            self.assertEqual(stopped, {1000})
            self.assertFalse(other.done())
            release.set()
            self.assertEqual((await other)[0]['best']['quote'], '4000')
            completed = diagnostics[2000]['routeWave']
            self.assertEqual((completed['typedEnumerated'], completed['typedCompleted'], completed['typedPending']), (14, 14, 0))
            self.assertEqual(diagnostics[1000]['routeWave'], cancelled)
        finally:
            first.cancel(); other.cancel()
            await asyncio.gather(first, other, return_exceptions=True)

    async def test_automatic_core_progress_replays_shared_pools_before_canonical_qualification(self):
        from test_quote_intent import service, request
        from test_route_search import ASSET_A, ASSET_B, ASSET_C, HASH
        from cybergold_candidate.route_search import WETH
        pools = [{**POOL, 'id': '0x'+str(index)*40, 'token0': token(left), 'token1': token(right)}
            for index, (left, right) in enumerate([(ASSET_A, ASSET_C), (ASSET_B, ASSET_C),
                                                 (ASSET_C, WETH), (ASSET_A, ASSET_B)], 6)]
        self.registry.inventory = {pool['id']: pool for pool in pools}
        quote, compose = self.quotes.quote_branches, self.quotes.compose_core_rows
        for reorg in (False, True):
            with self.subTest(reorg=reorg):
                intent, provider, routes, wire = service()
                provider.reorg = reorg
                routes.multi_protocol = self.quotes
                wire.missing_fees = {100, 500, 3000, 10000}
                release, qualified, replayed = asyncio.Event(), asyncio.Event(), asyncio.Event()
                events, replays = [], []
                async def delayed(branches, mode, amount, block):
                    if any(len(branch['hops']) > 2 for branch in branches):
                        await release.wait()
                    return await quote(branches, mode, amount, block)
                async def ordered(rows, mode, block, **kwargs):
                    result = await compose(rows, mode, block, **kwargs)
                    if all(row['best'] and row['best'].get('routePlan') for row in rows):
                        replays.append((deepcopy(rows), deepcopy(result), kwargs))
                        replayed.set()
                    return result
                async def update(event):
                    events.append(event)
                    if event['type'] == 'qualified':
                        qualified.set()
                self.quotes.quote_branches, self.quotes.compose_core_rows = delayed, ordered
                value = {**request('redeem-exact-in'), 'amount': '100000', 'orderedAssets': [ASSET_B, ASSET_A]}
                operation = asyncio.create_task(intent.get(value, update))
                try:
                    await asyncio.wait_for(replayed.wait(), self.sdk.timeout)
                    self.assertFalse(operation.done())
                    before, after, kwargs = replays[0]
                    self.assertEqual(kwargs, {'ordered_assets': [ASSET_B, ASSET_A], 'issue': False})
                    self.assertEqual(before[0]['best']['quote'], before[1]['best']['quote'])
                    self.assertLess(int(after[0]['best']['quote']), int(after[1]['best']['quote']))
                    if reorg:
                        # The existing final canonicality predicate also applies
                        # to a progressive execution tuple at this same hash.
                        await asyncio.sleep(.05)
                        self.assertFalse(qualified.is_set())
                        release.set()
                        with self.assertRaises(Exception):
                            await operation
                        self.assertFalse(any(event['type'] == 'qualified' for event in events))
                    else:
                        await asyncio.wait_for(qualified.wait(), self.sdk.timeout)
                        first = next(event['value'] for event in events if event['type'] == 'qualified')
                        self.assertEqual(first['context']['blockHash'], HASH)
                        self.assertEqual(len(first['quotes']), 2)
                        self.assertTrue(all(leg.get('routePlan') for leg in first['quotes']))
                        self.assertEqual([leg['minimumAmountOut'] for leg in first['quotes']],
                            [str(int(row['best']['quote'])*99//100) for row in after])
                        self.assertGreaterEqual(sum(method.startswith('eth_getBlock') for method, _ in provider.calls), 2)
                        release.set()
                        final = await operation
                        self.assertEqual(final['context']['blockHash'], HASH)
                        self.assertEqual(len(final['quotes']), 2)
                finally:
                    release.set()
                    operation.cancel()
                    await asyncio.gather(operation, return_exceptions=True)
                    await routes.close()

    async def test_core_leg_replay_uses_private_post_state_and_canonical_missing_tick_acquisition(self):
        pool = {**POOL, 'protocol': 'v3', 'feePips': 500, 'tickSpacing': 10}
        connector_id = '0x'+'4'.rjust(40, '0')
        connector = {**POOL, 'id': connector_id, 'address': connector_id, 'token1': token(C)}
        self.registry.inventory = {C: pool, connector_id: connector}
        canonical = {**pool, 'sqrtRatioX96': str(1 << 96), 'tick': 0, 'liquidity': '1000000',
            'ticks': [], 'bitmapWords': [{'wordPosition': 0, 'bitmap': '0'}, {'wordPosition': -1, 'bitmap': '0'}],
            'context': {'chainId': 1, 'blockNumber': '123', 'blockHash': BLOCK['hash']}}
        self.registry.observed[C] = deepcopy(canonical)
        old_read, extend = self.rpc.read_function, self.registry.extend_ticks
        acquired = []
        async def read(address, signature, inputs, args, outputs, block):
            if signature == 'tickBitmap(int16)':
                return (0,)
            if signature == 'getReserves()' and address == connector_id:
                return (1000000000, 4000000000, 0)
            return await old_read(address, signature, inputs, args, outputs, block)
        async def extend_observed(snapshot, requests, block):
            acquired.append((snapshot['sqrtRatioX96'], snapshot['tick']))
            return await extend(snapshot, requests, block)
        self.rpc.read_function, self.registry.extend_ticks = read, extend_observed
        first = [{'amountIn': '1000', 'hops': [{'pool': pool, 'zeroForOne': True}]}]
        second = [{'amountIn': '1000000', 'hops': [{'pool': connector, 'zeroForOne': False},
            {'pool': pool, 'zeroForOne': True}]}]
        def row(source, amount, branches):
            return {'target': {'inputAsset': source, 'outputAsset': B, 'amount': amount}, 'best': {
                'path': '0x', 'quote': '0', 'routePlan': {'version': 1, 'executionContext': 'helpers-core',
                    'mode': 'exactIn', 'tokenIn': source, 'tokenOut': B, 'branches': branches,
                    'inputAmount': amount, 'outputAmount': '0', 'limit': '0', 'deadline': '0'}}}
        rows = [row(A, '1000', first), row(C, '1000000', second)]
        composed = await self.quotes.compose_core_rows(rows, 'exactIn', BLOCK, ordered_assets=[A, C])
        independent = await self.quotes.quote_sdk_branches(second, 'exactIn', 1000000, BLOCK)
        self.assertGreater(int(composed[0]['best']['quote']), 0)
        self.assertLess(int(composed[1]['best']['quote']), int(independent['amountOut']))
        self.assertTrue(acquired)
        self.assertTrue(all(price == str(1 << 96) and tick == 0 for price, tick in acquired))
        self.assertEqual(self.registry.observed[C]['sqrtRatioX96'], str(1 << 96))
        self.assertEqual(self.registry.observed[C]['liquidity'], '1000000')

    async def test_core_typed_model_is_protocol_scoped_and_seeds_without_organic_points(self):
        history = QuoteHistory(self.quotes.settings)
        request = {'mode': 'redeem-exact-in', 'token': B, 'quoteToken': B, 'native': False,
            'adapter': C, 'orderedAssets': [A], 'targets': [], 'amount': '1000'}
        context = {'chainId': 1, 'blockHash': BLOCK['hash'], 'blockNumber': '123', 'observedAt': 'now'}
        try:
            history.ensure_known_typed_pools(self.quotes, request, BLOCK, context)
            while history.tasks:
                await asyncio.gather(*tuple(history.tasks.values()))
            packet = history.packet(request)
            self.assertEqual(packet['routes'][0]['points'], [])
            self.assertEqual(packet['routes'][0]['protocols'], ['v2'])
            self.assertEqual(packet['routes'][0]['exchangeRate'], {'numerator': '2', 'denominator': '1'})
            self.assertEqual(packet['routes'][0]['routePlan']['executionContext'], 'helpers-core')
            plan = packet['routes'][0]['routePlan']
            plan['branches'][0]['amountIn'] = '1000'
            target = {'inputAsset': A, 'outputAsset': B, 'amount': '1000'}
            result = {'context': context, 'basketPreview': {}, 'displayAmount': '1974', 'executionAmount': '1000'}
            history.observe(request, result, [('exact-in', [{'target': target,
                'best': {'path': '0x', 'quote': '1974', 'routePlan': plan}}], context)])
            next_block = {'number': 124, 'hash': '0x'+'cd'*32}
            async def canonical(_block):
                pass
            async def logs(_query):
                return []
            self.rpc.assert_canonical, self.rpc.logs = canonical, logs
            history.ensure_typed_pool(self.quotes, plan, next_block, {**context, 'blockHash': next_block['hash'], 'blockNumber': '124'})
            while history.tasks:
                await asyncio.gather(*tuple(history.tasks.values()))
            self.assertEqual(history.packet(request)['routes'][0]['points'], [])
            self.assertEqual(history.packet(request)['routes'][0]['exchangeContext']['blockHash'], next_block['hash'])
            legacy = '0x'+A[2:]+'000bb8'+B[2:]
            history.observe(request, result, [('exact-in', [{'target': target,
                'best': {'path': legacy, 'quote': '1960'}}], context)])
            self.assertEqual(len(history.routes), 2)
            self.assertEqual({len(key) for key in history.routes}, {3})
        finally:
            await history.close()

    async def test_core_exact_output_replay_reuses_forward_v2_execution_state(self):
        connector_id = '0x'+'4'.rjust(40, '0')
        connector = {**POOL, 'id': connector_id, 'address': connector_id, 'token1': token(C)}
        self.registry.inventory[connector_id] = connector
        first = [{'amountIn': '0', 'hops': [{'pool': POOL, 'zeroForOne': False}]}]
        second = [{'amountIn': '0', 'hops': [{'pool': POOL, 'zeroForOne': False},
            {'pool': connector, 'zeroForOne': True}]}]
        def row(target, branches):
            return {'target': {'inputAsset': B, 'outputAsset': target, 'amount': '1000'}, 'best': {
                'path': '0x', 'quote': '0', 'routePlan': {'version': 1, 'executionContext': 'helpers-core',
                    'mode': 'exactOut', 'tokenIn': B, 'tokenOut': target, 'branches': branches,
                    'inputAmount': '0', 'outputAmount': '1000', 'limit': '0', 'deadline': '0'}}}
        independent = await self.quotes.quote_sdk_branches(second, 'exactOut', 1000, BLOCK)
        composed = await self.quotes.compose_core_rows([row(A, first), row(C, second)], 'exactOut',
            BLOCK, ordered_assets=[A, C], issue=True)
        self.assertGreater(int(composed[1]['best']['quote']), int(independent['amountIn']))
        states = self.registry.observed
        self.assertEqual(states[C]['reserve0'], '100000')
        self.assertEqual(states[C]['reserve1'], '200000')
        self.assertGreaterEqual(int(composed[1]['best']['routePlan']['outputAmount']), 1000)


def acquisition_address(value):
    return '0x' + f'{value:040x}'


ACQUISITION_BLOCK = {'number': 123, 'hash': '0x' + 'ab' * 32}
ACQUISITION_POOLS = [{'id': acquisition_address(i + 100), 'address': acquisition_address(i + 100), 'protocol': 'v2', 'feePips': 3000,
          'token0': {'address': acquisition_address(i), 'chainId': 31338, 'decimals': 18},
          'token1': {'address': acquisition_address(i + 1), 'chainId': 31338, 'decimals': 18}}
         for i in (1, 2)]
ACQUISITION_BRANCHES = [{'amountIn': '1000', 'hops': [{'pool': pool, 'zeroForOne': True} for pool in ACQUISITION_POOLS]}]


class AcquisitionRpc:
    chain_id = 31338
    w3 = Web3()

    def __init__(self):
        self.started = {pool['id']: asyncio.Event() for pool in ACQUISITION_POOLS}
        self.release = {pool['id']: asyncio.Event() for pool in ACQUISITION_POOLS}
        self.errors = {}
        self.calls = Counter()
        self.cancelled = set()
        self.reserves = (100_000, 200_000, 0)

    async def read_function(self, identity, signature, inputs, args, outputs, block):
        assert signature == 'getReserves()' and block == ACQUISITION_BLOCK
        self.calls[identity] += 1
        self.started[identity].set()
        try:
            await self.release[identity].wait()
            if identity in self.errors:
                raise self.errors[identity]
            return self.reserves
        except asyncio.CancelledError:
            self.cancelled.add(identity)
            raise

    async def close(self):
        pass


class AcquisitionSdk:
    def __init__(self):
        self.payloads = []

    async def request(self, payload, on_state=None):
        self.payloads.append(deepcopy(payload))
        return {'amountIn': '1000', 'amountOut': '1900', 'settled': True, 'fullyFilled': True,
                'postState': [{'id': row['id'], 'reserve0': '101000'} for row in payload['pools']]}

    async def close(self):
        pass


class CandidateAcquisition(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=acquisition_address(1))
        self.rpc, self.sdk = AcquisitionRpc(), AcquisitionSdk()
        self.registry = PoolRegistry(settings, rpc=self.rpc)
        self.quotes = MarketQuotes(settings, self.registry, sdk=self.sdk)

    async def asyncTearDown(self):
        for event in self.rpc.release.values():
            event.set()
        await self.quotes.close()
        await self.registry.close()

    async def started(self):
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in self.rpc.started.values())), 1)
        except TimeoutError:
            self.fail('All required candidate snapshots must start before either is released')

    async def test_starts_distinct_snapshots_and_keeps_first_occurrence_payload_order(self):
        # The repeated pool belongs to the same candidate, not another getter.
        branches = deepcopy(ACQUISITION_BRANCHES)
        branches.append({'amountIn': '0', 'hops': [deepcopy(branches[0]['hops'][0])]})
        canonical = {}
        task = asyncio.create_task(self.quotes.quote_sdk_branches(branches, 'exactIn', 1000, ACQUISITION_BLOCK, canonical=canonical))
        try:
            await self.started()
            self.assertFalse(task.done())
            for event in self.rpc.release.values():
                event.set()
            await task
            self.assertEqual(list(canonical), [pool['id'] for pool in ACQUISITION_POOLS])
            self.assertEqual([row['id'] for row in self.sdk.payloads[0]['pools']], list(canonical))
            self.assertEqual(self.rpc.calls, Counter({pool['id']: 1 for pool in ACQUISITION_POOLS}))
            self.assertEqual(self.sdk.payloads[0]['route']['branches'][0]['hops'],
                             [{'poolId': pool['id'], 'zeroForOne': True} for pool in ACQUISITION_POOLS])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_first_read_failure_drains_blocked_sibling_and_preserves_exception(self):
        error = ValueError('first fixture read')
        self.rpc.errors[ACQUISITION_POOLS[0]['id']] = error
        task = asyncio.create_task(self.quotes.quote_sdk_branches(ACQUISITION_BRANCHES, 'exactIn', 1000, ACQUISITION_BLOCK))
        await self.started()
        self.rpc.release[ACQUISITION_POOLS[0]['id']].set()
        with self.assertRaises(ValueError) as caught:
            await task
        self.assertIs(caught.exception, error)
        self.assertEqual(self.rpc.cancelled, {ACQUISITION_POOLS[1]['id']})
        self.assertEqual(self.registry.pending.pending, {})
        self.assertEqual(self.sdk.payloads, [])

    async def test_error_priority_is_route_order_even_when_later_read_fails_first(self):
        first = ValueError('first fixture read')
        self.rpc.errors = {ACQUISITION_POOLS[0]['id']: first, ACQUISITION_POOLS[1]['id']: RuntimeError('second fixture read')}
        self.rpc.release[ACQUISITION_POOLS[1]['id']].set()
        task = asyncio.create_task(self.quotes.quote_sdk_branches(ACQUISITION_BRANCHES, 'exactIn', 1000, ACQUISITION_BLOCK))
        await self.started()
        self.assertFalse(task.done())
        self.rpc.release[ACQUISITION_POOLS[0]['id']].set()
        with self.assertRaises(ValueError) as caught:
            await task
        self.assertIs(caught.exception, first)
        self.assertEqual(self.registry.pending.pending, {})
        self.assertEqual(self.sdk.payloads, [])

    async def test_failure_does_not_cancel_other_snapshot_subscriber(self):
        shared = asyncio.create_task(self.registry.snapshot(ACQUISITION_POOLS[1], ACQUISITION_BLOCK))
        await self.rpc.started[ACQUISITION_POOLS[1]['id']].wait()
        self.rpc.errors[ACQUISITION_POOLS[0]['id']] = ValueError('first fixture read')
        task = asyncio.create_task(self.quotes.quote_sdk_branches(ACQUISITION_BRANCHES, 'exactIn', 1000, ACQUISITION_BLOCK))
        try:
            await self.started()
            key = ('v2', ACQUISITION_POOLS[1]['id'], ACQUISITION_BLOCK['hash'])
            # Awaiting the first start also gives the sibling task its normal
            # subscription turn; inspect the actual shared primitive's users.
            self.assertEqual(self.registry.pending.pending[key].users, 2)
            self.rpc.release[ACQUISITION_POOLS[0]['id']].set()
            with self.assertRaises(ValueError):
                await task
            self.assertFalse(shared.done())
            self.assertNotIn(ACQUISITION_POOLS[1]['id'], self.rpc.cancelled)
            self.assertEqual(self.registry.pending.pending[key].users, 1)
            self.rpc.release[ACQUISITION_POOLS[1]['id']].set()
            self.assertEqual((await shared)['reserve0'], '100000')
            self.assertEqual(self.rpc.calls[ACQUISITION_POOLS[1]['id']], 1)
        finally:
            shared.cancel()
            task.cancel()
            await asyncio.gather(shared, task, return_exceptions=True)

    async def test_caller_cancellation_drains_last_subscriptions_without_sdk(self):
        task = asyncio.create_task(self.quotes.quote_sdk_branches(ACQUISITION_BRANCHES, 'exactIn', 1000, ACQUISITION_BLOCK))
        await self.started()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.rpc.cancelled, {pool['id'] for pool in ACQUISITION_POOLS})
        self.assertEqual(self.registry.pending.pending, {})
        self.assertEqual(self.sdk.payloads, [])

    async def test_existing_canonical_entry_and_candidate_post_state_stay_private(self):
        existing = {**deepcopy(ACQUISITION_POOLS[0]), 'reserve0': '50000', 'reserve1': '200000'}
        canonical = {ACQUISITION_POOLS[0]['id']: existing}
        candidate = {ACQUISITION_POOLS[0]['id']: {**deepcopy(existing), 'reserve0': '51000'}}
        self.rpc.release[ACQUISITION_POOLS[1]['id']].set()
        await self.quotes.quote_sdk_branches(ACQUISITION_BRANCHES, 'exactIn', 1000, ACQUISITION_BLOCK,
                                             candidate=candidate, canonical=canonical)
        self.assertEqual(self.rpc.calls, Counter({ACQUISITION_POOLS[1]['id']: 1}))
        self.assertIs(canonical[ACQUISITION_POOLS[0]['id']], existing)
        self.assertEqual(self.sdk.payloads[0]['pools'][0]['reserve0'], '51000')
        self.assertEqual(existing['reserve0'], '50000')
        self.assertEqual(candidate[ACQUISITION_POOLS[0]['id']]['reserve0'], '101000')
        self.sdk.payloads[0]['pools'][0]['reserve0'] = '0'
        self.assertEqual(existing['reserve0'], '50000')

    async def test_next_sandbox_operation_rereads_mutation_at_same_header(self):
        for event in self.rpc.release.values():
            event.set()
        await self.quotes.quote_sdk_branches(ACQUISITION_BRANCHES, 'exactIn', 1000, ACQUISITION_BLOCK)
        self.rpc.reserves = (200_000, 300_000, 0)
        await self.quotes.quote_sdk_branches(ACQUISITION_BRANCHES, 'exactIn', 1000, ACQUISITION_BLOCK)
        self.assertEqual([row['reserve0'] for row in self.sdk.payloads[1]['pools']], ['200000', '200000'])
        self.assertEqual(self.rpc.calls, Counter({pool['id']: 2 for pool in ACQUISITION_POOLS}))
        self.assertEqual(self.registry.observed, {})
        self.assertEqual(self.registry.pending.completed, {})

    async def test_single_snapshot_keeps_original_caller_await(self):
        # A single read gains no concurrency. Keeping it on the caller retains
        # the existing observation scheduling used by Mainnet model acquisition.
        owner, readers = asyncio.current_task(), []
        original = self.registry.snapshot
        async def snapshot(*arguments):
            readers.append(asyncio.current_task())
            return await original(*arguments)
        self.registry.snapshot = snapshot
        self.rpc.release[ACQUISITION_POOLS[0]['id']].set()
        branches = [{'amountIn': '1000', 'hops': [deepcopy(ACQUISITION_BRANCHES[0]['hops'][0])]}]
        await self.quotes.quote_sdk_branches(branches, 'exactIn', 1000, ACQUISITION_BLOCK)
        self.assertEqual(readers, [owner])
        self.assertEqual(self.rpc.calls, Counter({ACQUISITION_POOLS[0]['id']: 1}))

    async def test_snapshot_failure_propagates_without_contract_quote_fallback(self):
        error = ValueError('first fixture read')
        self.rpc.errors[ACQUISITION_POOLS[0]['id']] = error
        reference = AsyncMock(side_effect=AssertionError('Contract pricing is retired'))
        self.quotes.quote_fallback_branches = reference
        task = asyncio.create_task(self.quotes.quote_branches(ACQUISITION_BRANCHES, 'exactIn', 1000, ACQUISITION_BLOCK))
        await self.started()
        self.rpc.release[ACQUISITION_POOLS[0]['id']].set()
        with self.assertRaises(ValueError) as raised:
            await task
        self.assertIs(raised.exception, error)
        reference.assert_not_awaited()
        self.assertEqual(self.rpc.cancelled, {ACQUISITION_POOLS[1]['id']})
        self.assertEqual(self.sdk.payloads, [])


class TickFillRpc:
    """Controlled getter completion; no transport or chain."""
    def __init__(self):
        self.calls = Counter()
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.active = self.cancelled = 0
        self.bitmap = 1
        self.gross = 100
        self.error = None

    async def read_function(self, _address, signature, _inputs, args, _outputs, _block):
        self.calls[signature] += 1
        if signature == 'tickBitmap(int16)':
            return (self.bitmap,)
        assert signature == 'ticks(int24)'
        self.active += 1
        self.started.set()
        try:
            await self.release.wait()
            if self.error:
                raise self.error
            return self.gross, args[0], 0, 0, 0, 0, 0, True
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1

    async def close(self):
        pass


class PendingTickFillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rpc = TickFillRpc()
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A)
        self.registry = PoolRegistry(settings, rpc=self.rpc)
        self.addAsyncCleanup(self.registry.close)
        self.snapshot = {**deepcopy(POOL), 'protocol': 'v3', 'tickSpacing': 10,
            'sqrtRatioX96': str(1 << 96), 'tick': 1, 'liquidity': '1000',
            'context': {'chainId': 31338, 'blockNumber': str(BLOCK['number']), 'blockHash': BLOCK['hash']},
            'bitmapWords': [], 'ticks': []}
        self.requests = [{'poolId': C, 'wordPositions': [0], 'ticks': []}]

    async def start(self, snapshot=None, requests=None):
        task = asyncio.create_task(self.registry.extend_ticks(
            self.snapshot if snapshot is None else snapshot,
            self.requests if requests is None else requests, BLOCK))
        self.addAsyncCleanup(self.stop, task)
        await asyncio.wait_for(self.rpc.started.wait(), 1)
        return task

    async def stop(self, task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def joined(self, users=2):
        async def wait():
            while not any(key[0] == 'tick-fill' and entry.users == users
                          for key, entry in self.registry.pending.pending.items()):
                await asyncio.sleep(0)
        await asyncio.wait_for(wait(), 1)

    async def test_staggered_identical_fill_shares_finished_bitmap_until_ticks_complete(self):
        first = await self.start()
        self.assertEqual(self.rpc.calls['tickBitmap(int16)'], 1)
        second = asyncio.create_task(self.registry.extend_ticks(self.snapshot, self.requests, BLOCK))
        self.addAsyncCleanup(self.stop, second)
        for _ in range(3):
            await asyncio.sleep(0)
        self.assertEqual(self.rpc.calls['tickBitmap(int16)'], 1)
        await self.joined()
        self.rpc.release.set()
        a, b = await asyncio.gather(first, second)
        self.assertEqual(self.rpc.calls, Counter({'tickBitmap(int16)': 1, 'ticks(int24)': 1}))
        self.assertEqual(a, b)
        a['ticks'][0]['liquidityGross'] = '999'
        self.assertEqual(b['ticks'][0]['liquidityGross'], '100')
        self.assertEqual(self.registry.pending.pending, {})
        self.assertEqual(self.registry.pending.completed, {})
        self.assertEqual(self.registry.observed, {})

    async def test_completed_fill_rereads_changed_sandbox_state_at_the_same_header(self):
        self.rpc.release.set()
        first = await self.registry.extend_ticks(self.snapshot, self.requests, BLOCK)
        self.rpc.bitmap, self.rpc.gross = 2, 200
        second = await self.registry.extend_ticks(self.snapshot, self.requests, BLOCK)
        self.assertEqual(self.rpc.calls, Counter({'tickBitmap(int16)': 2, 'ticks(int24)': 2}))
        self.assertEqual(first['ticks'], [{'index': 0, 'liquidityGross': '100', 'liquidityNet': '0'}])
        self.assertEqual(second['ticks'], [{'index': 10, 'liquidityGross': '200', 'liquidityNet': '10'}])
        self.assertEqual(self.registry.pending.completed, {})
        self.assertEqual(self.registry.observed, {})

    async def test_old_coverage_rows_stay_private_across_shared_fill_consumers(self):
        self.snapshot['bitmapWords'] = [{'wordPosition': 9, 'bitmap': '1'}]
        self.snapshot['ticks'] = [{'index': 23040, 'liquidityGross': '7', 'liquidityNet': '3'}]
        original = deepcopy(self.snapshot)
        one = self.registry.pending.one
        first_mutated = asyncio.Event()
        sequence = 0

        async def delayed_one(key, produce):
            nonlocal sequence
            sequence += 1
            position = sequence
            value = await one(key, produce)
            if position == 2:
                await first_mutated.wait()
            return value
        self.registry.pending.one = delayed_one

        async def first_consumer():
            value = await self.registry.extend_ticks(self.snapshot, self.requests, BLOCK)
            word = next(row for row in value['bitmapWords'] if row['wordPosition'] == 9)
            tick = next(row for row in value['ticks'] if row['index'] == 23040)
            self.assertEqual((word['bitmap'], tick['liquidityGross']), ('1', '7'))
            word['bitmap'] = tick['liquidityGross'] = '999'
            first_mutated.set()
            return value

        first = asyncio.create_task(first_consumer())
        self.addAsyncCleanup(self.stop, first)
        await asyncio.wait_for(self.rpc.started.wait(), 1)
        second = asyncio.create_task(self.registry.extend_ticks(original, self.requests, BLOCK))
        self.addAsyncCleanup(self.stop, second)
        await self.joined()
        self.snapshot['bitmapWords'][0]['bitmap'] = '888'
        self.snapshot['ticks'][0]['liquidityGross'] = '888'
        self.rpc.release.set()
        _, result = await asyncio.gather(first, second)
        self.assertEqual(next(row for row in result['bitmapWords'] if row['wordPosition'] == 9)['bitmap'], '1')
        self.assertEqual(next(row for row in result['ticks'] if row['index'] == 23040)['liquidityGross'], '7')
        self.assertEqual(self.rpc.calls['tickBitmap(int16)'], 1)

    async def test_unequal_prior_coverage_stays_distinct_at_the_same_header(self):
        with_extra = deepcopy(self.snapshot)
        with_extra['bitmapWords'] = [{'wordPosition': 9, 'bitmap': '0'}]
        first = await self.start(with_extra)
        self.rpc.bitmap = 2
        second = asyncio.create_task(self.registry.extend_ticks(self.snapshot, self.requests, BLOCK))
        self.addAsyncCleanup(self.stop, second)
        async def both_started():
            while self.rpc.active != 2:
                await asyncio.sleep(0)
        await asyncio.wait_for(both_started(), 1)
        self.rpc.release.set()
        a, b = await asyncio.gather(first, second)
        self.assertEqual(next(row for row in a['bitmapWords'] if row['wordPosition'] == 0)['bitmap'], '1')
        self.assertEqual(next(row for row in b['bitmapWords'] if row['wordPosition'] == 0)['bitmap'], '2')
        self.assertEqual(self.rpc.calls['tickBitmap(int16)'], 2)

    async def test_unequal_baseline_snapshots_do_not_share_a_fill(self):
        first = await self.start()
        changed = {**self.snapshot, 'liquidity': '2000'}
        second = asyncio.create_task(self.registry.extend_ticks(changed, self.requests, BLOCK))
        self.addAsyncCleanup(self.stop, second)
        await asyncio.sleep(0)
        self.assertEqual(sum(key[0] == 'tick-fill' for key in self.registry.pending.pending), 2)
        self.rpc.release.set()
        a, b = await asyncio.gather(first, second)
        self.assertEqual((a['liquidity'], b['liquidity']), ('1000', '2000'))
        self.assertEqual(self.rpc.calls['tickBitmap(int16)'], 2)

    async def test_unequal_coverage_requests_keep_their_own_words_and_ticks(self):
        first = await self.start()
        second = asyncio.create_task(self.registry.extend_ticks(
            self.snapshot, [{'poolId': C, 'wordPositions': [1], 'ticks': []}], BLOCK))
        self.addAsyncCleanup(self.stop, second)
        await asyncio.sleep(0)
        self.assertEqual(sum(key[0] == 'tick-fill' for key in self.registry.pending.pending), 2)
        self.rpc.release.set()
        a, b = await asyncio.gather(first, second)
        self.assertEqual([row['wordPosition'] for row in a['bitmapWords']], [0])
        self.assertEqual([row['wordPosition'] for row in b['bitmapWords']], [1])
        self.assertEqual([row['index'] for row in a['ticks']], [0])
        self.assertEqual([row['index'] for row in b['ticks']], [2560])

    async def test_caller_mutation_cannot_replace_an_inflight_keyed_baseline_or_coverage(self):
        original = deepcopy(self.snapshot)
        first = await self.start()
        self.snapshot['liquidity'] = '9000'
        self.requests[0]['wordPositions'].append(1)
        second = asyncio.create_task(self.registry.extend_ticks(original,
            [{'poolId': C, 'wordPositions': [0], 'ticks': []}], BLOCK))
        self.addAsyncCleanup(self.stop, second)
        await self.joined()
        self.rpc.release.set()
        a, b = await asyncio.gather(first, second)
        self.assertEqual(a, b)
        self.assertEqual(a['liquidity'], '1000')
        self.assertEqual([row['wordPosition'] for row in a['bitmapWords']], [0])

    async def test_concurrent_mainnet_fills_publish_the_full_coverage_union_atomically(self):
        self.registry.chain = 1
        self.snapshot['context']['chainId'] = 1
        first = await self.start()
        second = asyncio.create_task(self.registry.extend_ticks(self.snapshot,
            [{'poolId': C, 'wordPositions': [1], 'ticks': []}], BLOCK))
        self.addAsyncCleanup(self.stop, second)
        async def both_started():
            while self.rpc.active != 2:
                await asyncio.sleep(0)
        await asyncio.wait_for(both_started(), 1)
        self.rpc.release.set()
        results = await asyncio.gather(first, second)
        observed = self.registry.observed[C]
        self.assertEqual({row['wordPosition'] for row in observed['bitmapWords']}, {0, 1})
        self.assertEqual({row['index'] for row in observed['ticks']}, {0, 2560})
        self.assertTrue(any({row['index'] for row in result['ticks']} == {0, 2560} for result in results))

    async def test_one_cancelled_subscriber_does_not_stop_the_other_fill(self):
        first = await self.start()
        second = asyncio.create_task(self.registry.extend_ticks(self.snapshot, self.requests, BLOCK))
        self.addAsyncCleanup(self.stop, second)
        await self.joined()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual(self.rpc.cancelled, 0)
        self.assertFalse(second.done())
        self.rpc.release.set()
        result = await second
        self.assertEqual(result['ticks'][0]['liquidityGross'], '100')
        self.assertEqual(self.rpc.calls['tickBitmap(int16)'], 1)

    async def test_last_cancelled_subscriber_cancels_and_drains_the_owned_fill(self):
        first = await self.start()
        second = asyncio.create_task(self.registry.extend_ticks(self.snapshot, self.requests, BLOCK))
        self.addAsyncCleanup(self.stop, second)
        await self.joined()
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        self.assertEqual(self.rpc.cancelled, 1)
        self.assertEqual(self.rpc.active, 0)
        self.assertEqual(self.registry.pending.pending, {})

    async def test_shared_ordinary_error_keeps_identity_and_next_call_is_fresh(self):
        error = RuntimeError('public synthetic getter failure')
        self.rpc.error = error
        first = await self.start()
        second = asyncio.create_task(self.registry.extend_ticks(self.snapshot, self.requests, BLOCK))
        self.addAsyncCleanup(self.stop, second)
        await self.joined()
        self.rpc.release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(all(result is error for result in results))
        self.assertEqual(self.registry.pending.pending, {})
        self.rpc.error = None
        result = await self.registry.extend_ticks(self.snapshot, self.requests, BLOCK)
        self.assertEqual(result['ticks'][0]['liquidityGross'], '100')
        self.assertEqual(self.rpc.calls['tickBitmap(int16)'], 2)

    async def test_existing_generation_reset_cancels_old_fill_before_a_fresh_read(self):
        first = await self.start()
        await self.registry.observe_generation('next')
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual(self.rpc.cancelled, 1)
        self.assertEqual(self.registry.pending.pending, {})
        self.rpc.release.set()
        await self.registry.extend_ticks(self.snapshot, self.requests, BLOCK)
        self.assertEqual(self.rpc.calls['tickBitmap(int16)'], 2)


if __name__ == '__main__':
    unittest.main()
