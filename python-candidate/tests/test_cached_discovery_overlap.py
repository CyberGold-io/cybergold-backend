"""Private offline overlap experiment: actual SDK and shipped Helpers ABI."""
import asyncio
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.market_swap import MarketQuotes
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.uniswap_routes import candidate_branches
from cybergold_candidate.uniswap_state import PoolRegistry, UniswapRpc, ZERO
from test_quote_intent import service, request, CORE
from test_route_search import ASSET_A, ASSET_B, WETH, HASH

BLOCK = {'number': 101, 'hash': HASH}
RECORDS = []


def pool(identity, source, output=WETH):
    return {'id': identity, 'protocol': 'v2', 'address': identity, 'feePips': 3000,
            'token0': {'address': source, 'decimals': 18, 'chainId': 1},
            'token1': {'address': output, 'decimals': 18, 'chainId': 1}}


POOLS = [pool('0x' + str(i) * 40, asset) for i, asset in ((6, ASSET_A), (7, ASSET_B))]


class Counts:
    def __init__(self):
        self.rows = Counter()
        self.active = Counter()
        self.peak = Counter()

    async def run(self, group, operation, *, members=1):
        self.rows[group + 'Started'] += members
        self.active[group] += members
        self.peak[group] = max(self.peak[group], self.active[group])
        pool_rpc = group in ('discovery', 'freshState', 'poolContext')
        physical_rpc = pool_rpc or group in ('helpersOrCanonical', 'legacyBatchMembers')
        if pool_rpc:
            self.active['poolRpcMembers'] += members
            self.peak['poolRpcMembers'] = max(self.peak['poolRpcMembers'], self.active['poolRpcMembers'])
        if physical_rpc:
            self.rows['rpcMembersStarted'] += members
        try:
            value = await operation()
            self.rows[group + 'Completed'] += members
            if physical_rpc:
                self.rows['rpcMembersCompleted'] += members
            return value
        except asyncio.CancelledError:
            self.rows[group + 'Cancelled'] += members
            if physical_rpc:
                self.rows['rpcMembersCancelled'] += members
            raise
        except Exception:
            self.rows[group + 'Failed'] += members
            if physical_rpc:
                self.rows['rpcMembersFailed'] += members
            raise
        finally:
            self.active[group] -= members
            if pool_rpc:
                self.active['poolRpcMembers'] -= members

    def value(self):
        return {'members': dict(self.rows), 'active': dict(self.active), 'peak': dict(self.peak)}


class PoolProvider(AsyncBaseProvider):
    def __init__(self, counts):
        super().__init__()
        self.counts = counts
        self.release, self.discovery_started = asyncio.Event(), asyncio.Event()
        self.held = False
        self.hold_all = False
        self.reserves = {row['id']: (100_000, 200_000, 0) for row in POOLS}
        self.discovered = {}
        self.invalid = set()
        self.selectors = {Web3.keccak(text=name)[:4].hex(): name for name in (
            'getReserves()', 'getPair(address,address)', 'getPool(address,address,uint24)',
            'decimals()', 'tickSpacing()')}

    async def make_request(self, method, params):
        if method != 'eth_call':
            async def context():
                result = '0x1' if method == 'eth_chainId' else {'number': hex(BLOCK['number']), 'hash': HASH}
                return {'jsonrpc': '2.0', 'id': 1, 'result': result}
            return await self.counts.run('poolContext', context)
        data = bytes.fromhex(params[0]['data'][2:])
        signature = self.selectors.get(data[:4].hex(), 'unsupported')
        group = 'discovery' if signature.startswith(('getPair', 'getPool')) else 'freshState'
        async def call():
            if group == 'discovery':
                if self.hold_all or not self.held:
                    self.held = True
                    self.discovery_started.set()
                    await self.release.wait()
                pair = tuple(sorted(x.lower() for x in Web3().codec.decode(['address', 'address'], data[4:68])))
                address = self.discovered.get(pair, ZERO) if signature.startswith('getPair') else ZERO
                value, types = (address,), ['address']
            elif signature == 'getReserves()':
                address = params[0]['to'].lower()
                if address in self.invalid or address not in self.reserves:
                    return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'message': 'fixture removed pool'}}
                value, types = self.reserves[address], ['uint112', 'uint112', 'uint32']
            elif signature == 'decimals()':
                value, types = (18,), ['uint8']
            elif signature == 'tickSpacing()':
                value, types = (10,), ['int24']
            else:
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'message': 'fixture unsupported read'}}
            await asyncio.sleep(0)
            return {'jsonrpc': '2.0', 'id': 1, 'result': '0x' + Web3().codec.encode(types, value).hex()}
        return await self.counts.run(group, call)

    async def disconnect(self):
        pass


class CountedSdk:
    def __init__(self, counts):
        self.counts = counts
        self.inner = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'),
                               str(Path('src/uniswap-sdk/worker.ts').resolve())])
        self.timeout = self.inner.timeout
        lock = self.inner.lock
        class ObservedLock:
            async def __aenter__(_self):
                await lock.acquire()
                counts.rows['sdkExchangesStarted'] += 1
                counts.active['sdkExchanges'] += 1
                counts.peak['sdkExchanges'] = max(counts.peak['sdkExchanges'], counts.active['sdkExchanges'])

            async def __aexit__(_self, kind, *_args):
                outcome = 'Cancelled' if kind is asyncio.CancelledError else 'Failed' if kind else 'Completed'
                counts.rows['sdkExchanges' + outcome] += 1
                counts.active['sdkExchanges'] -= 1
                lock.release()
        self.inner.lock = ObservedLock()

    async def request(self, payload):
        return await self.counts.run('sdkRequests', lambda: self.inner.request(payload))

    async def close(self):
        await self.inner.close()


class Overlap(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.counts = Counts()
        self.provider = PoolProvider(self.counts)
        self.settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
            NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS=ASSET_B, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=ASSET_B)
        self.rpc = UniswapRpc(self.settings, AsyncWeb3(self.provider))
        self.registry = PoolRegistry(self.settings, rpc=self.rpc)
        self.registry.inventory = {row['id']: deepcopy(row) for row in POOLS}
        self.sdk = CountedSdk(self.counts)
        self.quotes = MarketQuotes(self.settings, self.registry, self.sdk)
        async def counted_graph(*args):
            self.counts.rows['candidateGraphsStarted'] += 1
            async for branches in candidate_branches(*args):
                yield branches
        self.graph_patch = patch('cybergold_candidate.route_quote_engine.candidate_branches', counted_graph)
        self.graph_patch.start()

    async def asyncTearDown(self):
        self.provider.release.set()
        await self.quotes.close()
        await self.registry.close()
        self.graph_patch.stop()

    async def whole_intent(self, *, expect_early, reorg=False, cancel=False, mode='redeem-exact-in'):
        intent, provider, routes, wire = service()
        provider.reorg = reorg
        routes.engine = self.quotes
        wire.missing_fees = {100, 500, 3000, 10000}
        original_request, original_send = provider.make_request, wire.send
        async def counted_request(method, params):
            return await self.counts.run('helpersOrCanonical', lambda: original_request(method, params))
        async def counted_send(value):
            members = json.loads(value.content)
            return await self.counts.run('legacyBatchMembers', lambda: original_send(value), members=len(members))
        provider.make_request = counted_request
        await routes.rpc.client.aclose()
        routes.rpc.client = httpx.AsyncClient(transport=httpx.MockTransport(counted_send))
        events, qualified = [], asyncio.Event()
        started = time.perf_counter()
        first_ms = None
        async def update(event):
            nonlocal first_ms
            events.append(event)
            if event['type'] == 'qualified':
                first_ms = first_ms or (time.perf_counter()-started)*1000
                qualified.set()
        value = request(mode)
        if mode == 'redeem-exact-in':
            value['amount'] = '100000'
        operation = asyncio.create_task(intent.get(value, update))
        try:
            await asyncio.wait_for(self.provider.discovery_started.wait(), 2)
            try:
                # Positive controls prove ordering, including cold SDK startup;
                # this test watchdog is not a production quote budget.
                await asyncio.wait_for(qualified.wait(), 10 if expect_early else 2)
                early = True
            except TimeoutError:
                early = False
            before = self.counts.value()
            RECORDS.append({'case': self._testMethodName, 'qualifiedBeforeDiscoveryReleased': early,
                'mode': mode, 'stagesBeforeRelease': sorted({row['stage'] for row in events if 'stage' in row}),
                'helpersBeforeRelease': [name for name, *_ in provider.contract_calls],
                'firstQualifiedMs': round(first_ms, 3) if first_ms is not None else None,
                'beforeRelease': before})
            self.assertEqual(early, expect_early)
            if early:
                self.assertFalse(self.provider.release.is_set())
                self.assertGreater(self.counts.active['discovery'], 0)
                first = next(row['value'] for row in events if row['type'] == 'qualified')
                self.assertEqual(first['context']['blockHash'], HASH)
                self.assertTrue(all(row.get('routePlan') for row in first['quotes']))
                self.assertTrue(any(name == 'previewRedeemToTokenExactIn' for name, *_ in provider.contract_calls))
                self.assertGreaterEqual(sum(method.startswith('eth_getBlock') for method, _ in provider.calls), 2)
                self.assertFalse(operation.done())
            if cancel:
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
                self.assertTrue(operation.cancelled())
                RECORDS[-1]['finished'] = self.counts.value()
                RECORDS[-1]['totalMs'] = round((time.perf_counter()-started)*1000, 3)
                return
            self.provider.release.set()
            if reorg:
                with self.assertRaises(SnapshotChanged):
                    await operation
                self.assertFalse(any(row['type'] == 'qualified' for row in events))
            else:
                final = await asyncio.wait_for(operation, 5)
                self.assertEqual(final['context']['blockHash'], HASH)
                self.assertTrue(final['quotes'])
                if mode == 'redeem-exact-out':
                    minimum = int(final['preview']['minimumAmountOut'])
                    self.assertLessEqual(int(value['amount']), minimum)
                    self.assertLessEqual(minimum, (int(value['amount'])*10100+9999)//10000)
                RECORDS[-1]['finalEconomics'] = {
                    'executionAmount': final['executionAmount'],
                    'maximumInputAmount': final['maximumInputAmount'],
                    'minimumAmountOut': final['preview']['minimumAmountOut'],
                    'legs': [{key: row[key] for key in ('inputAsset', 'inputAmount', 'minimumAmountOut')}
                             for row in final['quotes']]}
            RECORDS[-1]['finished'] = self.counts.value()
            RECORDS[-1]['firstQualifiedMs'] = round(first_ms, 3) if first_ms is not None else None
            RECORDS[-1]['totalMs'] = round((time.perf_counter()-started)*1000, 3)
        finally:
            operation.cancel()
            self.provider.release.set()
            await asyncio.gather(operation, return_exceptions=True)
            await routes.close()
            self.assertFalse(self.registry.pending.pending)
            self.assertTrue(all(value == 0 for value in self.counts.active.values()))
            self.assertLessEqual(self.counts.peak['poolRpcMembers'], 8)
            self.assertLessEqual(self.counts.peak['sdkExchanges'], 1)

    async def test_known_identity_is_helpers_and_canonical_qualified_during_discovery(self):
        await self.whole_intent(expect_early=os.environ.get('CYBERGOLD_OVERLAP_BASELINE') != '1')

    async def test_exact_out_unseeded_qualifies_protected_point_during_initial_discovery(self):
        await self.whole_intent(expect_early=True, mode='redeem-exact-out')

    async def test_reorg_never_qualifies_and_cleans_up(self):
        await self.whole_intent(expect_early=False, reorg=True)

    async def test_cancellation_drains_discovery_and_state_owners(self):
        await self.whole_intent(expect_early=True, cancel=True)

    async def test_no_cached_route_uses_ordinary_discovery(self):
        self.registry.inventory.clear()
        self.provider.discovered = {tuple(sorted((row['token0']['address'].lower(), WETH.lower()))): row['id'] for row in POOLS}
        await self.whole_intent(expect_early=False)

    async def test_invalid_cached_pool_falls_through_ordinary_discovered_route(self):
        # Stale learned V4 identity is not eligibility. Ordinary V2 factory
        # discovery remains available; unsupported old snapshot/fallback fails.
        self.registry.inventory = {'0x'+str(index)*64: {**row, 'id': '0x'+str(index)*64,
            'protocol': 'v4', 'tickSpacing': 1, 'poolManager': ASSET_A, 'hooks': ZERO}
            for index, row in enumerate(deepcopy(POOLS), 6)}
        self.provider.discovered = {tuple(sorted((row['token0']['address'].lower(), WETH.lower()))): row['id'] for row in POOLS}
        await self.whole_intent(expect_early=False)

    async def test_existing_rpc_capacity_can_still_be_fully_occupied_by_discovery(self):
        self.registry.inventory[self.registry.seed['id']] = deepcopy(self.registry.seed)
        self.provider.hold_all = True
        await self.whole_intent(expect_early=False)
        self.assertEqual(self.counts.peak['poolRpcMembers'], 8)

    async def test_same_header_sandbox_mutation_is_read_again_and_removed_pool_is_not_a_quote(self):
        self.registry.chain = self.rpc.chain_id = 31338
        self.quotes.connector_inventory = lambda *_args: asyncio.sleep(0)
        value = {'mode': 'exact-in', 'targets': [{'inputAsset': ASSET_A, 'outputAsset': WETH, 'amount': '1000'}]}
        # Current V3 factory replies are zero; this special fixture uses a
        # separate discovery barrier, so its RPC transport need not be held.
        self.provider.release.set()
        first = await self.quotes.reserve_quotes(value, BLOCK)
        self.provider.reserves[POOLS[0]['id']] = (100_000, 100_000, 0)
        second = await self.quotes.reserve_quotes(value, BLOCK)
        self.assertLess(int(second[0]['best']['quote']), int(first[0]['best']['quote']))
        self.provider.invalid.add(POOLS[0]['id'])
        third = await self.quotes.reserve_quotes(value, BLOCK)
        self.assertIsNone(third[0]['best'])
        self.assertEqual(third[0]['succeeded'], 0)
        self.registry.inventory.clear()
        self.assertEqual((await self.quotes.reserve_quotes(value, BLOCK))[0]['attempted'], 4)
        RECORDS.append({'case': self._testMethodName, 'beforeMutationQuote': first[0]['best']['quote'],
                        'afterMutationQuote': second[0]['best']['quote'], 'removedPoolQuote': third[0]['best'],
                        'finished': self.counts.value()})

    async def test_complete_expansion_executes_every_candidate_once_and_keeps_equal_incumbent(self):
        await self.complete_expansion('exact-in')

    async def test_exact_out_expansion_retains_ordinary_coverage_and_equal_incumbent(self):
        await self.complete_expansion('exact-out')

    async def test_expansion_preserves_rounded_split_duplicate_multiplicity(self):
        await self.complete_expansion('exact-in', amount=2)

    async def complete_expansion(self, input_mode, amount=1000):
        original = deepcopy(POOLS[0])
        added = [pool('0x'+'8'*40, ASSET_A, ASSET_B), pool('0x'+'9'*40, ASSET_B)]
        self.registry.inventory = {original['id']: original}
        self.provider.reserves[added[0]['id']] = (100_000, 100_000, 0)
        self.provider.reserves[added[1]['id']] = self.provider.reserves[original['id']]
        released = asyncio.Event()
        async def discovery(*_args):
            await released.wait()
            self.registry.inventory.update({row['id']: row for row in added})
        self.quotes.connector_inventory = discovery
        quote = self.quotes.quote_branches
        observed, frames = [], []
        async def counted(branches, mode, amount, block):
            observed.append(json.dumps(branches, sort_keys=True))
            return await quote(branches, mode, amount, block)
        self.quotes.quote_branches = counted
        async def update(rows):
            frames.append(deepcopy(rows))
            if rows[0]['best']:
                released.set()
        value = {'mode': input_mode, 'targets': [{'inputAsset': ASSET_A, 'outputAsset': WETH, 'amount': str(amount)}]}
        # Current V3 factory replies are zero; this special fixture uses a
        # separate discovery barrier, so its RPC transport need not be held.
        self.provider.release.set()
        final = await asyncio.wait_for(self.quotes.reserve_quotes(value, BLOCK, on_update=update), 5)
        expected = [json.dumps(branches, sort_keys=True) async for branches in candidate_branches(
            [original, *added], ASSET_A, WETH, 'exactIn' if input_mode == 'exact-in' else 'exactOut', amount)]
        expected.extend(json.dumps(branches, sort_keys=True) for branches in
            self.quotes.initial_v3_branches(value['targets'][0], 'exactIn' if input_mode == 'exact-in' else 'exactOut'))
        self.assertCountEqual(observed, expected)
        self.assertEqual(Counter(observed), Counter(expected))
        self.assertEqual(final[0]['attempted'], len(expected))
        first = next(frame[0]['best'] for frame in frames if frame[0]['best'])
        # The distinct two-hop path has the same marginal rate but more impact;
        # split improvements remain selectable while equal terms keep the incumbent.
        self.assertEqual(first['routePlan']['branches'][0]['hops'][0]['pool']['id'], original['id'])
        if input_mode == 'exact-in':
            self.assertGreaterEqual(int(final[0]['best']['quote']), int(first['quote']))
        else:
            self.assertLessEqual(int(final[0]['best']['quote']), int(first['quote']))
            self.assertEqual(final[0]['best']['routePlan']['branches'][0]['hops'][0]['pool']['id'], original['id'])
        self.assertLessEqual(self.counts.peak['sdkRequests'], 8)
        RECORDS.append({'case': self._testMethodName, 'mode': input_mode,
            'expectedCandidates': len(expected), 'executedCandidates': len(observed),
            'uniqueExecutions': len(set(observed)), 'firstQuote': first['quote'],
            'finalQuote': final[0]['best']['quote'], 'finished': self.counts.value()})


def tearDownModule():
    target = os.environ.get('CYBERGOLD_OVERLAP_EVIDENCE')
    if target:
        Path(target).write_text(json.dumps({'scope': 'offline exact ae27 or private candidate; actual SDK, ABI-coded mock RPC',
                                          'rows': RECORDS}, indent=2)+'\n')


if __name__ == '__main__':
    unittest.main()
