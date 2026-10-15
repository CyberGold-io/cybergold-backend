"""Canonical direction, deployed execution shape and direct-engine boundary."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from web3 import Web3

from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.route_encoding import ADAPTER_TYPE, encode_adapter, encode_route
from cybergold_candidate.uniswap_quote import UniswapQuote
from cybergold_candidate.uniswap_routes import (RoutePlan, pool_identity, route_identity,
                                                initial_v3_branches, v3_branches, v3_path, v3_plan)


A, B, C = ('0x'+value*40 for value in ('1', '2', '3'))
LEGACY = '0x4edb8190232a47e45d861003672938eb7ee84a15'
MULTI = '0x'+'4'*40
PATH = '0x'+A[2:]+'0001f4'+B[2:]+'000bb8'+C[2:]
REVERSE = '0x'+C[2:]+'000bb8'+B[2:]+'0001f4'+A[2:]
BLOCK = {'number': 101, 'hash': '0x'+'a'*64}


class CanonicalEncodingTests(unittest.TestCase):
    def plan(self, mode='exactIn', context='helpers-core'):
        return v3_plan(REVERSE if mode == 'exactOut' else PATH, mode, '123',
            execution_context=context, limit='456', deadline='789')

    def test_exact_output_decodes_to_same_forward_execution_identity(self):
        exact_in, exact_out = self.plan(), self.plan('exactOut')
        self.assertEqual(exact_in['tokenIn'], A)
        self.assertEqual(exact_in['tokenOut'], C)
        self.assertEqual(exact_out['tokenIn'], A)
        self.assertEqual(exact_out['tokenOut'], C)
        self.assertEqual(exact_in['branches'][0]['hops'], exact_out['branches'][0]['hops'])
        self.assertEqual(v3_path(exact_out['branches'][0]['hops']), PATH)
        self.assertEqual(v3_path(exact_out['branches'][0]['hops'], True), REVERSE)
        self.assertEqual(exact_in['branches'][0]['amountIn'], '123')
        self.assertEqual(exact_out['branches'][0]['amountIn'], '0')
        self.assertEqual(exact_out['outputAmount'], '123')

    def test_executable_skeleton_needs_no_observed_metadata(self):
        plan = self.plan()
        normalized = RoutePlan.model_validate(plan).model_dump(exclude_none=True)
        self.assertEqual(normalized, plan)
        for hop in plan['branches'][0]['hops']:
            self.assertNotIn('address', hop['pool'])
            self.assertNotIn('tickSpacing', hop['pool'])
            self.assertNotIn('decimals', hop['pool']['token0'])
            self.assertNotIn('chainId', hop['pool']['token0'])
        self.assertTrue(encode_route(plan, LEGACY))
        self.assertTrue(encode_route(plan, MULTI))

    def test_core_both_adapters_preserve_historical_whole_path_both_modes(self):
        codec = Web3().codec
        for mode, path in (('exactIn', PATH), ('exactOut', REVERSE)):
            plan = self.plan(mode)
            expected = Web3.to_hex(codec.encode(['bytes', 'uint256', 'uint256', 'bool'], [
                bytes.fromhex(path[2:]), 456, 789, mode == 'exactIn']))
            self.assertEqual(encode_route(plan, LEGACY), expected)
            self.assertEqual(encode_route(plan, MULTI), expected)
            self.assertEqual(codec.decode(['bytes', 'uint256', 'uint256', 'bool'],
                bytes.fromhex(expected[2:])), (bytes.fromhex(path[2:]), 456, 789, mode == 'exactIn'))

    def test_market_retains_typed_wire_both_modes_and_legacy_adapter_is_explicit(self):
        codec = Web3().codec
        for mode in ('exactIn', 'exactOut'):
            plan = self.plan(mode, 'helpers-market')
            encoded = encode_route(plan, MULTI)
            self.assertEqual(encoded, encode_adapter(plan))
            value, = codec.decode([ADAPTER_TYPE], bytes.fromhex(encoded[2:]))
            self.assertEqual(value[:3], (mode == 'exactIn', 456, 789))
            self.assertEqual(value[3][0][0], 123 if mode == 'exactIn' else 0)
            self.assertEqual([hop[1] for hop in value[3][0][1]], [B, C])
            self.assertNotEqual(encode_route(plan, LEGACY), encoded)

    def test_non_v3_and_split_core_keep_typed_allocations_without_mutation(self):
        plan = self.plan()
        plan['branches'][0]['hops'][0]['pool']['protocol'] = 'v2'
        before = deepcopy(plan)
        self.assertEqual(encode_route(plan, MULTI), encode_adapter(plan))
        self.assertEqual(plan, before)
        with self.assertRaisesRegex(ValueError, 'Historical V3 adapter'):
            encode_route(plan, LEGACY)
        split = self.plan()
        split['branches'][0]['amountIn'] = '60'
        split['branches'].append(deepcopy(split['branches'][0]))
        split['branches'][1]['amountIn'] = '63'
        decoded, = Web3().codec.decode([ADAPTER_TYPE], bytes.fromhex(encode_route(split, MULTI)[2:]))
        self.assertEqual([branch[0] for branch in decoded[3]], [60, 63])

    def test_v3_identity_is_independent_of_observed_fields_and_path_case(self):
        lower = v3_branches(PATH, 'exact-in', 1)
        upper = v3_branches('0x'+PATH[2:].upper(), 'exactIn', 1, 31338)
        for a, b in zip(lower[0]['hops'], upper[0]['hops'], strict=True):
            self.assertEqual(a['pool']['id'], b['pool']['id'])
            self.assertEqual(b['pool']['token0']['chainId'], 31338)
            self.assertNotIn('decimals', b['pool']['token0'])
        enriched = deepcopy(upper)
        for hop in enriched[0]['hops']:
            hop['pool'].update(id='observed-id', address=MULTI, tickSpacing=10)
            hop['pool']['token0']['decimals'] = 6
            hop['pool']['token1']['decimals'] = 18
        self.assertEqual(route_identity(lower), route_identity(enriched))
        enriched[0]['hops'][0]['pool']['feePips'] += 1
        self.assertNotEqual(route_identity(lower), route_identity(enriched))

    def test_v4_key_changes_remain_distinct_from_observation_enrichment(self):
        pool = {'protocol': 'v4', 'token0': {'address': A}, 'token1': {'address': B},
                'feePips': 500, 'tickSpacing': 10, 'hooks': C}
        original = pool_identity(pool)
        self.assertEqual(original, pool_identity({**pool, 'id': 'observed', 'liquidity': '123'}))
        for field, value in (('feePips', 3000), ('tickSpacing', 60), ('hooks', MULTI)):
            self.assertNotEqual(original, pool_identity({**pool, field: value}))

    def test_shared_initial_v3_seeds_preserve_original_coverage_order_and_forward_direction(self):
        target = {'inputAsset': A, 'outputAsset': C, 'amount': '123'}
        exact_in = list(initial_v3_branches(target, 'exact-in', 31338))
        exact_out = list(initial_v3_branches(target, 'exactOut', 31338))
        expected = [(100,), (500,), (500, 500), (3000,), (3000, 500),
            (500, 3000), (3000, 3000), (10000,), (10000, 500),
            (500, 10000), (10000, 3000), (3000, 10000), (10000, 10000)]
        self.assertEqual([tuple(hop['pool']['feePips'] for hop in row[0]['hops']) for row in exact_in], expected)
        self.assertEqual([row[0]['hops'] for row in exact_in], [row[0]['hops'] for row in exact_out])
        self.assertEqual(len(exact_in), 13)
        self.assertTrue(all(row[0]['amountIn'] == '123' for row in exact_in))
        self.assertTrue(all(row[0]['amountIn'] == '0' for row in exact_out))
        self.assertTrue(all(v3_path(row[0]['hops']).startswith('0x'+A[2:]) for row in exact_out))
        weth = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
        self.assertEqual(len(list(initial_v3_branches({**target, 'inputAsset': weth}, 'exact-in'))), 4)
        self.assertEqual(list(initial_v3_branches({**target, 'outputAsset': A}, 'exact-in')), [])


class HeadRpc:
    chain_id = 31338
    quoter = MULTI

    def __init__(self):
        self.heads, self.checks, self.closed = 0, 0, False
        self.reorg = False

    async def block(self, block_hash):
        self.heads += 1
        return BLOCK

    async def assert_canonical(self, block):
        self.checks += 1
        if self.reorg:
            raise SnapshotChanged('changed')

    async def close(self):
        self.closed = True

    def encode(self, request):
        raise AssertionError('Direct API must use the shared engine.')

    async def quote(self, *args):
        raise AssertionError('Direct API must use the shared engine.')


class Engine:
    def __init__(self):
        self.calls = []
        self.semaphore = asyncio.Semaphore(8)
        self.started = asyncio.Event()
        self.blocked = False
        self.cancelled = 0

    async def quote_branches(self, branches, mode, amount, block):
        self.calls.append((deepcopy(branches), mode, amount, block))
        self.started.set()
        if self.blocked:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        return {'amountIn': '234', 'amountOut': '567', 'settled': True, 'fullyFilled': True}


class DirectEngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rpc, self.engine = HeadRpc(), Engine()
        self.service = UniswapQuote(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338'),
            self.rpc, lambda: 'fixture-time', engine=self.engine)

    async def test_both_modes_quote_one_forward_plan_through_injected_shared_engine(self):
        for mode, path, amount in (('exact-in', PATH, '567'), ('exact-out', REVERSE, '234')):
            value = await self.service.get({'mode': mode, 'path': path, 'amount': '123'})
            self.assertEqual(value['result'], {'amount': amount})
            branches, canonical_mode, raw, block = self.engine.calls[-1]
            self.assertEqual(v3_path(branches[0]['hops']), PATH)
            self.assertEqual(canonical_mode, 'exactIn' if mode == 'exact-in' else 'exactOut')
            self.assertEqual((raw, block), (123, BLOCK))
            self.assertEqual(value['context']['blockHash'], BLOCK['hash'])
        self.assertEqual((self.rpc.heads, self.rpc.checks), (2, 2))

    async def test_invalid_uint_and_packed_path_fail_before_head_or_engine(self):
        for amount, path in (('-1', PATH), (str(2**256), PATH), ('1', '0x12'), ('1', PATH+'ff')):
            with self.assertRaises(InvalidPreview):
                await self.service.get({'mode': 'exact-in', 'path': path, 'amount': amount})
        self.assertEqual((self.rpc.heads, self.engine.calls), (0, []))

    async def test_reorg_is_not_a_success_and_cancellation_drains_direct_engine_await(self):
        self.rpc.reorg = True
        with self.assertRaises(SnapshotChanged):
            await self.service.get({'mode': 'exact-in', 'path': PATH, 'amount': '123'})
        self.rpc.reorg = False
        self.engine.blocked = True
        task = asyncio.create_task(self.service.get({'mode': 'exact-in', 'path': PATH, 'amount': '123'}))
        await self.engine.started.wait()
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.engine.cancelled, 1)

    async def test_direct_service_does_not_close_shared_engine(self):
        await self.service.close()
        self.assertTrue(self.rpc.closed)


if __name__ == '__main__':
    unittest.main()
