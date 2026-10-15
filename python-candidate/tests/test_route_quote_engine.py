"""Canonical route pricing without inventory, and one complete candidate set."""
import asyncio
from collections import Counter
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quote_errors import QuoteFailure, rpc_failure
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.sdk_worker import SdkWorker, SdkWorkerError, MissingPoolState
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.uniswap_routes import (candidate_branches, route_identity,
    v3_branches)
from cybergold_candidate.uniswap_state import PoolRegistry, ZERO

A, B, C = ('0x'+str(i).rjust(40, '0') for i in (1, 2, 3))
BLOCK = {'number': 1, 'hash': '0x'+'ab'*32}


class Rpc:
    factory = C
    def __init__(self):
        self.calls, self.blocks = [], []
        self.absent = False
        self.disproved = False
    async def read_function(self, _address, signature, _types, args, _outputs, block):
        self.calls.append((signature, args))
        self.blocks.append(deepcopy(block))
        if signature.startswith(('quoteExact', 'getAmountsIn', 'getAmountsOut')):
            raise AssertionError('Contract pricing is forbidden: '+signature)
        if self.disproved:
            raise SnapshotChanged('changed')
        if signature.startswith('getPool'):
            return (ZERO if self.absent else C,)
        if signature == 'slot0()':
            return (2**96, 0, 0, 0, 0, 0, True)
        if signature == 'liquidity()':
            return (10**15,)
        if signature == 'tickSpacing()':
            return (1,)
        if signature == 'decimals()':
            return (18,)
        if signature == 'tickBitmap(int16)':
            return (0,)
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
        if self.rpc.disproved:
            raise SnapshotChanged('changed')
        return {**deepcopy(pool), 'sqrtRatioX96': str(2**96), 'liquidity': str(10**15),
            'tick': 0, 'tickSpacing': 1, 'ticks': [], 'bitmapWords': []}


class Sdk:
    def __init__(self):
        self.payloads = []
    async def close(self):
        pass
    async def request(self, payload):
        self.payloads.append(deepcopy(payload))
        return {'amountIn': payload['amount'] if payload['mode'] == 'exactIn' else '200',
            'amountOut': '200' if payload['mode'] == 'exactIn' else payload['amount'],
            'settled': True, 'fullyFilled': True, 'postState': []}


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

    async def test_sdk_seed_pricing_and_exact_output_forward_identity(self):
        for mode in ('exact-in', 'exact-out'):
            rows = await self.engine.search_routes(self.request(mode), BLOCK)
            best = rows[0]['best']
            self.assertEqual(best['quote'], '200')
            self.assertEqual(rows[0]['succeeded'], 13)
            self.assertEqual(best['routePlan']['tokenIn'], A)
            self.assertEqual(best['routePlan']['tokenOut'], B)
        self.assertEqual({p['mode'] for p in self.engine.sdk.payloads}, {'exactIn', 'exactOut'})
        for payload in self.engine.sdk.payloads:
            pools = {pool['id']: pool for pool in payload['pools']}
            hop = payload['route']['branches'][0]['hops'][0]
            source = pools[hop['poolId']]['token0' if hop['zeroForOne'] else 'token1']['address']
            self.assertEqual(source.lower(), A.lower())
        self.assertEqual(self.registry.rpc.calls, [])


    async def test_sdk_failure_propagates_without_contract_pricing_fallback(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 10)
        expected = SdkWorkerError('worker unavailable')
        async def failed(_payload):
            raise expected
        self.engine.sdk.request = failed
        with self.assertRaises(SdkWorkerError) as caught:
            await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK)
        self.assertIs(caught.exception, expected)
        self.assertEqual(self.registry.rpc.calls, [])


    async def test_required_state_transport_failure_and_context_disproof_propagate(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 10)
        for expected in (OSError('state transport unavailable'), SnapshotChanged('changed')):
            async def failed(*_args):
                raise expected
            self.registry.snapshot = failed
            with self.assertRaises(type(expected)) as caught:
                await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK)
            self.assertIs(caught.exception, expected)
        self.assertEqual(self.registry.rpc.calls, [])



    async def test_tick_fill_uses_existing_producer_budget_instead_of_four_round_limit(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 10)
        requests, fills = [], []
        async def sdk(payload):
            requests.append(deepcopy(payload))
            if len(requests) <= 6:
                raise MissingPoolState([{'poolId': payload['pools'][0]['id'],
                    'wordPositions': [len(requests)]}])
            return {'amountIn': '10', 'amountOut': '19', 'settled': True, 'fullyFilled': True}
        async def extend(snapshot, missing, block):
            self.assertEqual(block, BLOCK)
            fills.extend(deepcopy(missing))
            return {**snapshot, 'bitmapWords': snapshot['bitmapWords']+[
                {'wordPosition': missing[0]['wordPositions'][0], 'bitmap': '0'}]}
        self.engine.sdk.request, self.registry.extend_ticks = sdk, extend
        value = await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK)
        self.assertEqual(value['amountOut'], '19')
        self.assertEqual(len(requests), 7)
        self.assertEqual([r['wordPositions'] for r in fills], [[i] for i in range(1, 7)])
        self.assertEqual(self.registry.rpc.calls, [])

    async def test_tick_fill_preserves_known_rpc_cause_and_context_disproof(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 10)
        async def missing(payload):
            raise MissingPoolState([{'poolId': payload['pools'][0]['id'], 'wordPositions': [0]}])
        self.engine.sdk.request = missing
        for expected in (rpc_failure({'code': -32005, 'message': 'rate limit'}),
                         TimeoutError('pool state timed out'), SnapshotChanged('tick context changed')):
            async def failed(*_args):
                raise expected
            self.registry.extend_ticks = failed
            with self.assertRaises(type(expected)) as caught:
                await self.engine.quote_branches(branches, 'exactIn', 10, BLOCK)
            self.assertIs(caught.exception, expected)
        self.assertEqual(self.registry.rpc.calls, [])


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

    async def test_slow_same_leg_graph_prefix_does_not_hold_later_sdk_seed(self):
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

    async def test_identity_needs_no_inventory_or_pool_read(self):
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

    async def test_alias_ids_cannot_select_a_second_pricing_engine_on_sdk_failure(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 5)
        alias = deepcopy(branches)
        alias[0]['hops'][0]['pool']['id'] = 'optional-alias'
        calls = []
        async def failed(payload):
            calls.append(payload)
            raise SdkWorkerError('SDK unavailable')
        self.engine.sdk.request = failed
        with self.assertRaises(SdkWorkerError):
            await self.engine.quote_branches(branches+alias, 'exactIn', 10, BLOCK)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]['pools']), 1)
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

    async def test_shared_core_replay_failure_cannot_return_independent_quotes(self):
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 5)
        rows = [{'target': {'inputAsset': A, 'outputAsset': B, 'amount': '5'},
            'best': {'quote': '200', 'routePlan': {'branches': deepcopy(branches)}}} for _ in range(2)]
        expected = SdkWorkerError('shared pool replay unavailable')
        async def failed(_payload):
            raise expected
        self.engine.sdk.request = failed
        with self.assertRaises(SdkWorkerError) as caught:
            await self.engine.compose_core_rows(rows, 'exactIn', BLOCK)
        self.assertIs(caught.exception, expected)
        self.assertEqual([row['best']['quote'] for row in rows], ['200', '200'])
        self.assertEqual(self.registry.rpc.calls, [])



class RichV3Pricing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings = SimpleNamespace(NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS=C,
            NEXT_PUBLIC_CHAIN_ID=31338, NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=C)
        self.rpc = Rpc()
        self.registry = PoolRegistry(settings, self.rpc)
        self.branches = v3_branches('0x'+A[2:]+'000064'+B[2:], 'exactIn', 1000)
        pool = deepcopy(self.branches[0]['hops'][0]['pool'])
        pool.update(id=C, address=C, tickSpacing=1)
        for token in (pool['token0'], pool['token1']):
            token.update(decimals=18, chainId=31338)
        self.registry.inventory = {C: pool}
        self.sdk = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'),
                             str(Path('src/uniswap-sdk/worker.ts').resolve())])
        self.engine = RouteQuoteEngine(settings, self.registry, self.sdk)

    async def asyncTearDown(self):
        await self.engine.close()
        await self.registry.pending.close()


    async def test_rich_v3_uses_actual_sdk_and_fresh_ticks_without_contract_pricing(self):
        native_calls = []
        async def state(_address, signature, _types, _args, _outputs, _block):
            if signature.startswith('quoteExact'):
                native_calls.append(signature)
                raise rpc_failure({'code': -32000, 'message': 'quoter unavailable'})
            if signature == 'slot0()':
                return (2**96, 0, 0, 0, 0, 0, True)
            if signature == 'liquidity()':
                return (10**15,)
            if signature == 'tickBitmap(int16)':
                return (0,)
            raise AssertionError(signature)
        self.rpc.read_function = state
        for mode in ('exactIn', 'exactOut'):
            value = await self.engine.quote_branches(self.branches, mode, 1000, BLOCK)
            self.assertEqual(value['qualification'], 'sdk')
            self.assertGreater(int(value['amountIn']), 0)
            self.assertGreaterEqual(int(value['amountOut']), 1000 if mode == 'exactOut' else 1)
            self.assertTrue(value['settled'])
            self.assertTrue(value['fullyFilled'])
        self.assertEqual(native_calls, [])

    async def test_multihop_exact_input_keeps_actual_sdk_intermediate_settlement_rejection(self):
        from cybergold_candidate.basket_preview import InvalidPreview
        other, output = ('0x'+str(i).rjust(40, '0') for i in (4, 5))
        branches = v3_branches('0x'+A[2:]+'000064'+B[2:]+'000064'+output[2:],
                               'exactIn', 1000000)
        states = {}
        for index, hop in enumerate(branches[0]['hops']):
            pool = deepcopy(hop['pool'])
            pool.update(id=(C, other)[index], address=(C, other)[index], tickSpacing=1)
            for token in (pool['token0'], pool['token1']):
                token.update(decimals=18, chainId=31338)
            self.registry.inventory[pool['id']] = deepcopy(pool)
            # The second pool exhausts its active range at tick -10. Remaining
            # words prove empty liquidity through the SDK's lower price limit.
            pool.update(sqrtRatioX96=str(2**96), tick=0,
                liquidity=str(10**15 if index == 0 else 10**9),
                ticks=[] if index == 0 else [{'index': -10,
                    'liquidityGross': str(10**9), 'liquidityNet': str(10**9)}],
                bitmapWords=[{'wordPosition': position,
                    'bitmap': str(1 << 246) if index == 1 and position == -1 else '0'}
                    for position in (range(-3466, 1) if index == 1 else (-1, 0))])
            states[pool['id']] = pool
        async def snapshot(pool, _block):
            return deepcopy(states[pool['id']])
        observed, request = [], self.sdk.request
        async def capture(payload):
            result = await request(payload)
            observed.append(deepcopy(result))
            return result
        self.registry.snapshot, self.sdk.request = snapshot, capture
        with self.assertRaisesRegex(InvalidPreview, 'Unsettled current-operation intermediate'):
            await self.engine.quote_branches(branches, 'exactIn', 1000000, BLOCK)
        self.assertTrue(observed)
        self.assertEqual(observed[-1]['amountOut'], '499850')
        self.assertFalse(observed[-1]['settled'])
        self.assertFalse(observed[-1]['fullyFilled'])
        self.assertEqual(observed[-1]['residuals'], [
            {'poolId': other, 'amount': '499747', 'originalInput': False}])
        self.assertEqual(self.rpc.calls, [])

    async def test_minimal_v3_seed_acquires_pinned_sdk_state_and_preserves_forward_identity(self):
        self.registry.inventory.clear()
        payloads, request = [], self.sdk.request
        async def capture(payload):
            payloads.append(deepcopy(payload))
            return await request(payload)
        self.sdk.request = capture
        for mode in ('exactIn', 'exactOut'):
            value = await self.engine.quote_branches(self.branches, mode, 1000, BLOCK)
            self.assertEqual(value['qualification'], 'sdk')
            self.assertTrue(value['settled'])
            self.assertTrue(value['fullyFilled'])
        names = Counter(name for name, _ in self.rpc.calls)
        self.assertEqual(names['getPool(address,address,uint24)'], 2)
        self.assertEqual(names['tickSpacing()'], 2)
        self.assertEqual(names['decimals()'], 2)
        self.assertEqual(names['slot0()'], 2)
        self.assertEqual(names['liquidity()'], 2)
        self.assertGreater(names['tickBitmap(int16)'], 0)
        self.assertTrue(all(block == BLOCK for block in self.rpc.blocks))
        self.assertFalse(any(name.startswith(('quoteExact', 'getAmounts')) for name in names))
        for payload in payloads:
            pool, = payload['pools']
            hop, = payload['route']['branches'][0]['hops']
            self.assertEqual(hop['poolId'], pool['id'])
            self.assertEqual(pool['address'], C)
            self.assertEqual(pool['token0']['address'], A)
            self.assertEqual(pool['token1']['address'], B)
            self.assertEqual(pool['token0']['chainId'], 31338)
        self.assertEqual(self.registry.inventory, {})

    async def test_minimal_v3_absence_does_not_use_advisory_negative_cache(self):
        self.registry.inventory.clear()
        self.registry.lookups = {('v3', (A, B), 100): None}
        self.rpc.absent = True
        with self.assertRaises(QuoteFailure) as caught:
            await self.engine.quote_branches(self.branches, 'exactIn', 1000, BLOCK)
        self.assertEqual(caught.exception.code, 'quote-no-route')
        self.rpc.absent = False
        value = await self.engine.quote_branches(self.branches, 'exactIn', 1000, BLOCK)
        self.assertEqual(value['qualification'], 'sdk')
        self.assertTrue(value['settled'])
        self.assertIsNone(self.registry.lookups[('v3', (A, B), 100)])
        self.assertEqual(sum(name.startswith('getPool') for name, _ in self.rpc.calls), 2)

    async def test_concurrent_minimal_seed_state_and_token_metadata_reads_are_shared(self):
        self.registry.inventory.clear()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.rpc.read_function
        async def held(address, signature, types, args, outputs, block):
            if signature == 'slot0()':
                entered.set()
                await release.wait()
            return await original(address, signature, types, args, outputs, block)
        self.rpc.read_function = held
        tasks = [asyncio.create_task(self.engine.quote_branches(self.branches, 'exactIn', 1000, BLOCK))
                 for _ in range(2)]
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.sleep(0)
            release.set()
            values = await asyncio.wait_for(asyncio.gather(*tasks), 5)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(all(value['qualification'] == 'sdk' for value in values))
        names = Counter(name for name, _ in self.rpc.calls)
        self.assertEqual(names['getPool(address,address,uint24)'], 1)
        self.assertEqual(names['tickSpacing()'], 1)
        self.assertEqual(names['slot0()'], 1)
        self.assertEqual(names['liquidity()'], 1)
        self.assertEqual(names['decimals()'], 2)

    async def test_unknown_display_decimals_do_not_gate_raw_sdk_arithmetic(self):
        self.registry.inventory.clear()
        original, payloads, request = self.rpc.read_function, [], self.sdk.request
        async def unknown(address, signature, types, args, outputs, block):
            if signature == 'decimals()':
                raise OSError('metadata unavailable')
            return await original(address, signature, types, args, outputs, block)
        async def capture(payload):
            payloads.append(deepcopy(payload))
            return await request(payload)
        self.rpc.read_function, self.sdk.request = unknown, capture
        value = await self.engine.quote_branches(self.branches, 'exactIn', 1000, BLOCK)
        self.assertEqual(value['qualification'], 'sdk')
        self.assertTrue(value['settled'])
        pool = payloads[0]['pools'][0]
        self.assertFalse(pool['token0']['decimalsKnown'])
        self.assertFalse(pool['token1']['decimalsKnown'])
        self.assertEqual(value['amountIn'], '1000')

    async def test_metadata_snapshot_disproof_is_preserved_and_sibling_read_drained(self):
        self.registry.inventory.clear()
        held, drained = asyncio.Event(), asyncio.Event()
        original = self.rpc.read_function
        async def state(address, signature, types, args, outputs, block):
            if signature == 'decimals()' and address == A:
                held.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            if signature == 'decimals()' and address == B:
                await held.wait()
                raise SnapshotChanged('metadata context changed')
            return await original(address, signature, types, args, outputs, block)
        self.rpc.read_function = state
        with self.assertRaisesRegex(SnapshotChanged, 'metadata context changed'):
            await asyncio.wait_for(self.engine.quote_branches(self.branches, 'exactIn', 1000, BLOCK), 2)
        self.assertTrue(drained.is_set())

    async def test_slot_snapshot_disproof_is_preserved_and_sibling_read_drained(self):
        held, drained = asyncio.Event(), asyncio.Event()
        original = self.rpc.read_function
        async def state(address, signature, types, args, outputs, block):
            if signature == 'slot0()':
                held.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            if signature == 'liquidity()':
                await held.wait()
                raise SnapshotChanged('liquidity context changed')
            return await original(address, signature, types, args, outputs, block)
        self.rpc.read_function = state
        with self.assertRaisesRegex(SnapshotChanged, 'liquidity context changed'):
            await asyncio.wait_for(self.engine.quote_branches(self.branches, 'exactIn', 1000, BLOCK), 2)
        self.assertTrue(drained.is_set())

    async def test_tick_snapshot_disproof_is_preserved_and_sibling_read_drained(self):
        held, drained = asyncio.Event(), asyncio.Event()
        original = self.rpc.read_function
        async def state(address, signature, types, args, outputs, block):
            if signature == 'tickBitmap(int16)' and args == [-1]:
                held.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            if signature == 'tickBitmap(int16)' and args == [0]:
                await held.wait()
                raise SnapshotChanged('bitmap context changed')
            return await original(address, signature, types, args, outputs, block)
        self.rpc.read_function = state
        pool = deepcopy(self.registry.inventory[C])
        snapshot = await self.registry.snapshot(pool, BLOCK)
        with self.assertRaisesRegex(SnapshotChanged, 'bitmap context changed'):
            await asyncio.wait_for(self.registry.extend_ticks(snapshot,
                [{'poolId': C, 'wordPositions': [-1, 0]}], BLOCK), 2)
        self.assertTrue(drained.is_set())

    async def test_actual_sdk_prices_v2_v3_v4_mixed_and_split_without_contract_pricing(self):
        other, output = ('0x'+str(i).rjust(40, '0') for i in (4, 5))
        def token(address):
            return {'address': address, 'decimals': 18, 'chainId': 31338}
        v2 = {'id': 'v2', 'protocol': 'v2', 'address': other, 'feePips': 3000,
            'token0': token(A), 'token1': token(B), 'reserve0': '1000000', 'reserve1': '2000000'}
        v3 = {**deepcopy(self.registry.inventory[C]), 'sqrtRatioX96': str(2**96),
            'liquidity': str(10**15), 'tick': 0, 'ticks': [],
            'bitmapWords': [{'wordPosition': p, 'bitmap': '0'} for p in (-1, 0)]}
        v4 = {**deepcopy(v3), 'id': '0x'+'44'*32, 'protocol': 'v4',
            'token0': token(B), 'token1': token(output), 'hooks': ZERO,
            'lpFee': 100, 'protocolFee': 0}
        states = {p['id']: p for p in (v2, v3, v4)}
        self.registry.inventory = deepcopy(states)
        async def snapshot(pool, _block):
            return deepcopy(states[pool['id']])
        self.registry.snapshot = snapshot
        single = lambda p: [{'amountIn': '1000', 'hops': [{'pool': p, 'zeroForOne': True}]}]
        candidates = [(single(p), mode) for p in (v2, v3, v4) for mode in ('exactIn', 'exactOut')]
        candidates += [([{'amountIn': '1000', 'hops': [{'pool': v2, 'zeroForOne': True},
            {'pool': v4, 'zeroForOne': True}]}], 'exactIn'),
            ([{'amountIn': '500', 'hops': [{'pool': v2, 'zeroForOne': True}]},
              {'amountIn': '500', 'hops': [{'pool': v3, 'zeroForOne': True}]}], 'exactIn')]
        for branches, mode in candidates:
            value = await self.engine.quote_branches(branches, mode, 1000, BLOCK)
            self.assertEqual(value['qualification'], 'sdk')
            self.assertTrue(value['settled'])
            self.assertTrue(value['fullyFilled'])
            self.assertGreater(int(value['amountIn']), 0)
            self.assertGreaterEqual(int(value['amountOut']), 1000 if mode == 'exactOut' else 1)
        self.assertEqual(self.rpc.calls, [])


if __name__ == '__main__':
    unittest.main()
