"""Canonical route pricing without inventory, and one complete candidate set."""
import asyncio
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quote_errors import QuoteFailure, rpc_failure
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.sdk_worker import SdkWorkerError
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.uniswap_routes import (candidate_branches, route_identity,
    v3_branches, v3_path)
from cybergold_candidate.uniswap_state import ZERO

A, B, C = ('0x'+str(i).rjust(40, '0') for i in (1, 2, 3))
BLOCK = {'number': 1, 'hash': '0x'+'ab'*32}


class Rpc:
    factory = C
    def __init__(self):
        self.calls = []
        self.absent = False
        self.empty = False
        self.disproved = False
    async def read_function(self, _address, signature, _types, args, _outputs, _block):
        self.calls.append((signature, args))
        if self.disproved:
            raise SnapshotChanged('changed')
        if signature.startswith('getPool'):
            return (ZERO if self.absent else C,)
        if signature == 'liquidity()':
            return (0 if self.empty else 1,)
        if signature.startswith('quoteExact'):
            return (200, [], [], 0)
        raise KeyError(signature)


class Registry:
    chain = 1
    def __init__(self):
        self.inventory = {}
        self.pending = SharedReads()
        self.rpc = Rpc()
    def get_rpc(self):
        return self.rpc
    async def ensure_loaded(self):
        pass
    async def snapshot(self, pool, _block):
        # Minimal V3 has no observed pool address; the ordinary SDK error
        # selects the native pricing method without metadata admission.
        raise KeyError('address')


class Sdk:
    async def close(self):
        pass
    async def request(self, _payload):
        raise SdkWorkerError('fixture missing state')


class RouteQuoteEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = Registry()
        self.engine = RouteQuoteEngine(SimpleNamespace(NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS=C),
                                       self.registry, Sdk())
        async def connectors(*_args):
            pass
        self.engine.connector_inventory = connectors
    async def asyncTearDown(self):
        await self.engine.close()
        await self.registry.pending.close()
    def request(self, mode='exact-in', amount='10'):
        return {'mode': mode, 'adapter': C, 'targets': [{'inputAsset': A, 'outputAsset': B, 'amount': amount}]}

    async def test_native_v3_without_catalog_metadata_and_exact_output_forward_identity(self):
        for mode in ('exact-in', 'exact-out'):
            rows = await self.engine.search_routes(self.request(mode), BLOCK)
            best = rows[0]['best']
            self.assertEqual(best['quote'], '200')
            self.assertEqual(rows[0]['succeeded'], 13)
            plan = best['routePlan']
            self.assertEqual(plan['tokenIn'], A)
            self.assertEqual(plan['tokenOut'], B)
            self.assertEqual(plan['branches'][0]['hops'][0]['pool']['token0']['address'], A)
            for name, args in self.registry.rpc.calls:
                if name.startswith('quoteExact'):
                    path = '0x'+args[0].hex()
                    normalized = v3_branches(path, 'exactOut' if name.startswith('quoteExactOutput') else 'exactIn', 10)
                    first = normalized[0]['hops'][0]
                    source = first['pool']['token0' if first['zeroForOne'] else 'token1']['address']
                    self.assertEqual(source.lower(), A.lower())
        self.assertTrue(any(name.startswith('quoteExactOutput') for name, _ in self.registry.rpc.calls))

    async def test_known_absent_or_empty_excludes_native_call_unknown_getter_does_not(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 10)
        for attr in ('absent', 'empty'):
            setattr(self.registry.rpc, attr, True)
            with self.assertRaises(QuoteFailure):
                await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK)
            setattr(self.registry.rpc, attr, False)
        self.assertFalse(any(name.startswith('quoteExact') for name, _ in self.registry.rpc.calls))
        read = self.registry.rpc.read_function
        async def unknown(address, signature, types, args, outputs, block):
            if not signature.startswith('quoteExact'):
                raise rpc_failure({'code': -32005, 'message': 'optional getter unavailable'})
            return await read(address, signature, types, args, outputs, block)
        self.registry.rpc.read_function = unknown
        self.assertEqual((await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK))['amountOut'], '200')

    async def test_transport_observation_failure_uses_native_method_but_context_disproof_does_not(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 10)
        async def missing(*_args):
            raise OSError('optional state transport unavailable')
        self.registry.snapshot = missing
        self.assertEqual((await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK))['amountOut'], '200')
        self.registry.rpc.calls.clear()
        async def disproved(*_args):
            raise SnapshotChanged('changed')
        self.registry.snapshot = disproved
        with self.assertRaises(SnapshotChanged):
            await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK)
        self.assertEqual(self.registry.rpc.calls, [])

    async def test_advisory_negative_lookup_cannot_veto_fresh_canonical_pool(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 10)
        self.registry.lookups = {('v3', (A, B), 100): None}
        self.registry.chain = 31338
        self.registry.rpc.absent = True
        with self.assertRaises(QuoteFailure):
            await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK)
        before = len(self.registry.rpc.calls)
        self.registry.rpc.absent = False
        value = await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK)
        self.assertEqual(value['amountOut'], '200')
        self.assertEqual([name for name, _ in self.registry.rpc.calls[before:]],
                         ['getPool(address,address,uint24)', 'liquidity()', 'quoteExactInput(bytes,uint256)'])
        self.assertIsNone(self.registry.lookups[('v3', (A, B), 100)])

    async def test_canonical_disproof_is_not_optional_metadata_failure(self):
        self.registry.rpc.disproved = True
        with self.assertRaises(SnapshotChanged):
            await self.engine.search_routes(self.request(), BLOCK)

    async def test_same_seed_and_observed_pool_quote_once_split_rounding_multiplicity_retained(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 2)
        v3 = branches[0]['hops'][0]['pool']
        v3 = {**v3, 'id': C, 'address': C, 'tickSpacing': 1}
        v2 = {**v3, 'id': 'v2', 'protocol': 'v2', 'feePips': 3000}
        self.registry.inventory = {C: v3, 'v2': v2}
        priced = []
        async def evaluate(_index, candidate):
            priced.append(route_identity(candidate))
        await self.engine.search_candidates(self.request(amount='2'), BLOCK, evaluate)
        expected = [route_identity(row) async for row in candidate_branches(
            [v3, v2], A, B, 'exactIn', 2)]
        seeds = list(self.engine.initial_v3_branches(self.request(amount='2')['targets'][0], 'exactIn'))
        seed_keys = {route_identity(row) for row in seeds}
        wanted = Counter(expected)
        for key in seed_keys:
            wanted[key] = max(1, wanted[key])
        self.assertEqual(Counter(priced), wanted)
        self.assertTrue(any(count == 2 for key, count in wanted.items() if len(key) == 2))

    async def test_enrichment_uses_execution_identity_not_optional_registry_id(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 10)
        pool = {**deepcopy(branches[0]['hops'][0]['pool']), 'id': C, 'address': C,
                'tickSpacing': 1, 'token0': {'address': A, 'decimals': 18},
                'token1': {'address': B, 'decimals': 18}}
        self.registry.inventory[C] = pool
        result = self.engine.enrich_branches(branches)
        self.assertEqual(result[0]['hops'][0]['pool'], pool)
        self.assertEqual(route_identity(result), route_identity(branches))
        self.assertNotIn('address', branches[0]['hops'][0]['pool'])

    async def test_slow_same_leg_graph_prefix_does_not_hold_later_native_seed(self):
        entered, priced, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
        release = asyncio.Event()
        async def graph(*_args):
            try:
                entered.set()
                await release.wait()
                if False:
                    yield
            finally:
                drained.set()
        async def quote(_index, branches):
            if int(branches[0]['hops'][0]['pool']['feePips']) == 500:
                priced.set()
        with patch('cybergold_candidate.route_quote_engine.candidate_branches', graph):
            task = asyncio.create_task(self.engine.search_candidates(self.request(), BLOCK, quote))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                await asyncio.wait_for(priced.wait(), 1)
                self.assertFalse(release.is_set())
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertTrue(drained.is_set())

    async def test_identity_needs_no_inventory_or_native_read(self):
        async def unexpected():
            raise AssertionError('identity must not discover')
        self.registry.ensure_loaded = unexpected
        request = self.request()
        request['targets'][0]['outputAsset'] = A
        result, = await self.engine.search_routes(request, BLOCK)
        self.assertEqual(result['best']['quote'], '10')
        self.assertEqual(result['best']['routePlan']['branches'], [])
        self.assertEqual((result['attempted'], result['total']), (0, 0))
        self.assertEqual(self.registry.rpc.calls, [])

    async def test_owned_later_snapshot_disproof_survives_policy_stop_of_first_read(self):
        first, later, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 5)
        other = v3_branches('0x'+A[2:]+'0001f4'+B[2:], 'exactIn', 5)
        async def snapshot(pool, _block):
            if int(pool['feePips']) == 100:
                first.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            await first.wait()
            later.set()
            raise SnapshotChanged('later owned pool disproved')
        self.registry.snapshot = snapshot
        budget = QuoteBudget()
        with budget_context(budget):
            task = asyncio.create_task(budget.discovery(self.engine.quote_sdk_branches(
                branches+other, 'exactIn', 10, BLOCK)))
        await asyncio.wait_for(later.wait(), 1)
        budget.finish_selection('timeout')
        with self.assertRaisesRegex(SnapshotChanged, 'later owned pool disproved'):
            await asyncio.wait_for(task, 1)
        self.assertTrue(drained.is_set())

    async def test_alias_ids_never_allow_independent_shared_pool_fallback(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 5)
        alias = deepcopy(branches)
        alias[0]['hops'][0]['pool']['id'] = 'optional-alias'
        with self.assertRaises(SdkWorkerError):
            await self.engine.quote_branches(branches+alias, 'exactIn', 10, BLOCK)
        with self.assertRaises(SdkWorkerError):
            await self.engine.quote_fallback_branches(branches+alias, 'exactIn', 10, BLOCK)
        self.assertEqual(self.registry.rpc.calls, [])

    async def test_alias_ids_share_one_sdk_pool_and_candidate_post_state(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 5)
        alias = deepcopy(branches)
        alias[0]['hops'][0]['pool']['id'] = 'optional-alias'
        snapshots, payloads = [], []
        async def snapshot(pool, _block):
            snapshots.append(pool['id'])
            return {**pool, 'liquidity': '100', 'tick': 0}
        async def sdk(payload):
            payloads.append(deepcopy(payload))
            return {'amountIn': '10', 'amountOut': '19', 'settled': True,
                'postState': [{'id': payload['pools'][0]['id'], 'liquidity': '90'}]}
        self.registry.snapshot, self.engine.sdk.request = snapshot, sdk
        candidate, canonical = {}, {}
        await self.engine.quote_sdk_branches(branches+alias, 'exactIn', 10, BLOCK,
                                             candidate=candidate, canonical=canonical)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(len(payloads[0]['pools']), 1)
        self.assertEqual(len({hop['poolId'] for row in payloads[0]['route']['branches'] for hop in row['hops']}), 1)
        identity, = candidate
        self.assertEqual(candidate[identity]['liquidity'], '90')
        self.assertEqual(canonical[identity]['liquidity'], '100')

    async def test_shared_pool_fallback_cannot_sum_independent_split_quotes(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 5)
        with self.assertRaises(SdkWorkerError):
            await self.engine.quote_fallback_branches(branches+deepcopy(branches), 'exactIn', 10, BLOCK)
        self.assertEqual(self.registry.rpc.calls, [])

class MarketEngineOwnership(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from test_uniswap_market import MarketIntegration
        await MarketIntegration.asyncSetUp(self)

    async def asyncTearDown(self):
        from test_uniswap_market import MarketIntegration
        await MarketIntegration.asyncTearDown(self)

    async def test_parallel_native_rechecks_use_same_eight_pricing_slots(self):
        from test_uniswap_market import POOL, BLOCK
        branches = [{'amountIn': '1000', 'hops': [{'pool': deepcopy(POOL), 'zeroForOne': True}]}]
        raw = {'amountIn': '1000', 'amountOut': '1974', 'qualification': 'sdk'}
        full, release = asyncio.Event(), asyncio.Event()
        active = peak = entered = 0
        async def fallback(*_args):
            nonlocal active, peak, entered
            active += 1
            entered += 1
            peak = max(peak, active)
            if active == 8:
                full.set()
            try:
                await release.wait()
                return dict(raw)
            finally:
                active -= 1
        async def emit(_frame):
            pass
        self.quotes.quote_fallback_branches = fallback
        tasks = [asyncio.create_task(self.quotes.qualify_quote(self.request, branches, raw,
            1000, BLOCK, 1000, emit)) for _ in range(9)]
        try:
            await asyncio.wait_for(full.wait(), 1)
            self.assertEqual(entered, 8)
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 1)
            self.assertEqual(peak, 8)
            self.assertEqual(entered, 9)
            self.assertEqual(active, 0)
            self.assertEqual(self.quotes.semaphore._value, 8)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_native_recheck_snapshot_disproof_cannot_be_marked_unavailable(self):
        from test_uniswap_market import POOL, BLOCK
        branches = [{'amountIn': '1000', 'hops': [{'pool': deepcopy(POOL), 'zeroForOne': True}]}]
        raw = {'amountIn': '1000', 'amountOut': '1974', 'qualification': 'sdk'}
        async def disproved(*_args):
            raise SnapshotChanged('native recheck disproved')
        self.quotes.quote_fallback_branches = disproved
        async def emit(_frame):
            pass
        with self.assertRaisesRegex(SnapshotChanged, 'native recheck disproved'):
            await self.quotes.qualify_quote(self.request, branches, raw, 1000, BLOCK, 1000, emit)
        self.assertEqual(self.quotes.semaphore._value, 8)


if __name__ == '__main__':
    unittest.main()
