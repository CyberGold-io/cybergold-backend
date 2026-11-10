"""Encoded inverse targets use real SDK replay with mixed token decimals."""
from copy import deepcopy
from types import SimpleNamespace
import asyncio
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter.evaluate import encode_nomination, replay_conversion
from cybergold_candidate.quoter.inverse import inverse_conversion
from cybergold_candidate.quoter.quote_book import QuoteBook
from cybergold_candidate.routing_encoding import ZERO, exact_output_routes, split_runtime
from cybergold_candidate.sdk_worker import SdkWorkerError
from quoter_fixture import service, synthetic_pool
from test_universal_quote import BLOCK, OTHER, PAXG, WETH


USDT = '0xdac17f958d2ee523a2206206994597c13d831ec7'
FUNDED_USDT = 60000 * 10**6
TARGET_PAXG = 4661111320113019730


def pool(a, b, number, reserve_a, reserve_b):
    value = synthetic_pool(a, b, number, 'v2')
    for key in ('token0', 'token1'):
        value[key]['decimals'] = 6 if value[key]['address'] == USDT else 18
    a_is_zero = value['token0']['address'] == a.lower()
    value['reserve0'] = str(reserve_a if a_is_zero else reserve_b)
    value['reserve1'] = str(reserve_b if a_is_zero else reserve_a)
    return value


def hop(value, source):
    return {'pool': value, 'zeroForOne': value['token0']['address'] == source.lower()}


def stablecoin_pools():
    return [pool(USDT, PAXG, 9901, 10**14, 25000 * 10**18),
            pool(USDT, WETH, 9902, 10**14, 50000 * 10**18),
            pool(WETH, PAXG, 9903, 50000 * 10**18, 25000 * 10**18)]


def split_choice(pools, direct_weight):
    return encode_nomination(USDT, PAXG, ([
        {'amountIn': str(FUNDED_USDT * direct_weight // 10**6),
         'hops': [hop(pools[0], USDT)]},
        {'amountIn': str(FUNDED_USDT * (10**6-direct_weight) // 10**6),
         'hops': [hop(pools[1], USDT), hop(pools[2], WETH)]},
    ], []))[1]


def constant_product_output(chosen, amount, preceding, pools):
    """Independent V2 arithmetic, updating every physical occurrence in order."""
    reserves = {value['id']: [int(value['reserve0']), int(value['reserve1'])]
                for value in pools}
    for identity, value in preceding.items():
        reserves[identity] = [int(value['reserve0']), int(value['reserve1'])]
    total = 0
    for branch, funded in zip(chosen['branches'],
            split_runtime(amount, chosen['template']['routes']), strict=True):
        current = funded
        for row in branch['hops']:
            if 'pool' not in row:
                continue
            state = reserves[row['pool']['id']]
            left, right = (0, 1) if row['zeroForOne'] else (1, 0)
            output = current * 997 * state[right] // (state[left] * 1000 + current * 997)
            state[left] += current
            state[right] -= output
            current = output
        total += current
    return total


class ExactOutputAllocationTests(unittest.TestCase):
    def allocation(self, amounts):
        branches = [{'amountIn': str(amount),
                     'hops': [{'kind': 'wrap', 'currencyOut': WETH}]} for amount in amounts]
        original = deepcopy(branches)
        funding, routes = exact_output_routes(branches)
        lots = split_runtime(funding, routes)
        self.assertEqual(len(routes), len(amounts))
        self.assertEqual(sum(lots), funding)
        self.assertEqual(routes[-1]['sharePpm'], 0)
        for amount, lot in zip(amounts, lots, strict=True):
            self.assertGreaterEqual(lot, amount)
        self.assertEqual(branches, original)
        return funding, routes, lots

    def test_sub_ppm_positive_path_receives_a_fundable_share(self):
        funding, routes, _ = self.allocation([1, 10**12])
        self.assertEqual(routes[0]['sharePpm'], 1)
        self.assertEqual(funding, 1_000_001_000_002)

    def test_three_routes_cover_every_independent_input_requirement(self):
        _, routes, _ = self.allocation([3, 5, 7])
        self.assertTrue(all(route['sharePpm'] > 0 for route in routes[:-1]))

    def test_four_routes_preserve_tiny_first_middle_and_final_paths(self):
        _, routes, _ = self.allocation([1, 10**24, 2, 1])
        shares = [route['sharePpm'] for route in routes[:-1]]
        self.assertTrue(all(share > 0 for share in shares))
        self.assertGreater(1_000_000-sum(shares), 0)

    def test_zero_entries_stay_in_their_original_positions(self):
        funding, routes, lots = self.allocation([0, 5, 0, 11])
        self.assertEqual(funding, 16)
        self.assertEqual(lots, [0, 5, 0, 11])
        self.assertEqual([routes[index]['sharePpm'] for index in (0, 2)], [0, 0])

    def test_zero_final_path_still_owns_integer_remainder(self):
        funding, _, lots = self.allocation([1, 2, 3, 0])
        self.assertEqual(funding, 7)
        self.assertEqual(lots, [1, 2, 3, 1])

    def test_single_route_owns_the_entire_input_lot(self):
        funding, _, lots = self.allocation([1234567])
        self.assertEqual(funding, 1234567)
        self.assertEqual(lots, [1234567])


class EncodedInverseRoundingTests(unittest.IsolatedAsyncioTestCase):
    async def test_simple_path_prices_target_from_preceding_bank_without_original_replay(self):
        pools = stablecoin_pools()
        quoter = service(self, pools)
        route = [hop(pools[0], USDT)]
        chosen = encode_nomination(USDT, PAXG,
            ([{'amountIn': str(FUNDED_USDT), 'hops': route}], []))[1]
        bank, canonical = {}, {}
        await quoter.price_path(route, 50000 * 10**6, BLOCK, bank, canonical)
        preceding, original = deepcopy(bank), deepcopy(chosen)
        state = preceding[pools[0]['id']]
        source_key, target_key = ('reserve0', 'reserve1') if route[0]['zeroForOne'] else ('reserve1', 'reserve0')
        expected_input = (int(state[source_key]) * TARGET_PAXG * 1000
                          // ((int(state[target_key])-TARGET_PAXG) * 997) + 1)
        requests = []
        request = quoter.engine.sdk.request

        async def record(payload, *args, **kwargs):
            requests.append(deepcopy(payload))
            return await request(payload, *args, **kwargs)

        with patch.object(quoter.engine.sdk, 'request', record):
            amount, resized = await inverse_conversion(quoter, chosen, USDT, PAXG,
                FUNDED_USDT, TARGET_PAXG, BLOCK, bank, canonical)
        self.assertEqual(requests[0]['operation'], 'simulateRoute')
        self.assertEqual(requests[0]['mode'], 'exactOut')
        self.assertEqual(int(requests[0]['amount']), TARGET_PAXG)
        self.assertFalse(any(row.get('mode') == 'exactIn' and int(row['amount']) == FUNDED_USDT
                             for row in requests))
        self.assertEqual(amount, expected_input)
        independent = deepcopy(preceding)
        _, output, retained = await replay_conversion(quoter, deepcopy(resized), USDT,
            PAXG, amount, BLOCK, independent, canonical)
        self.assertGreaterEqual(output, TARGET_PAXG)
        self.assertEqual(output, constant_product_output(resized, amount, preceding, pools))
        self.assertEqual(retained, [])
        self.assertEqual(bank, independent)
        self.assertEqual(chosen, original)

    async def test_simple_native_and_wrapped_paths_use_identical_physical_funding(self):
        pools = stablecoin_pools()
        quoter = service(self, pools)
        route, funded = [hop(pools[2], WETH)], 30 * 10**18
        wrap = {'kind': 'wrap', 'currencyOut': WETH}
        native = encode_nomination(ZERO, PAXG,
            ([{'amountIn': str(funded), 'hops': [wrap, *route]}], []))[1]
        wrapped = encode_nomination(WETH, PAXG,
            ([{'amountIn': str(funded), 'hops': route}], []))[1]
        originals, native_bank, wrapped_bank, canonical = deepcopy((native, wrapped)), {}, {}, {}
        native_input, native_sized = await inverse_conversion(quoter, native, ZERO,
            PAXG, funded, TARGET_PAXG, BLOCK, native_bank, canonical)
        wrapped_input, wrapped_sized = await inverse_conversion(quoter, wrapped, WETH,
            PAXG, funded, TARGET_PAXG, BLOCK, wrapped_bank, canonical)
        self.assertEqual(native_input, wrapped_input)
        self.assertLess(native_input, funded)
        self.assertEqual(native_sized['inputCurrency'], ZERO)
        self.assertEqual(native_sized['template'], wrapped_sized['template'])
        self.assertEqual(native_sized['template']['inputCurrency'].lower(), WETH.lower())
        self.assertEqual(native_bank, wrapped_bank)
        self.assertGreaterEqual(constant_product_output(native_sized, native_input, {}, pools), TARGET_PAXG)
        self.assertEqual((native, wrapped), originals)

    async def test_internal_unwrap_keeps_the_native_pool_path_available(self):
        connector = stablecoin_pools()[1]
        native_pool = synthetic_pool(ZERO, PAXG, 9941, 'v4', liquidity=10**24)
        quoter = service(self, [connector, native_pool])
        route = [hop(connector, USDT), {'kind': 'unwrap', 'currencyOut': ZERO},
                 hop(native_pool, ZERO)]
        chosen = encode_nomination(USDT, PAXG,
            ([{'amountIn': str(FUNDED_USDT), 'hops': route}], []))[1]
        original, bank, canonical = deepcopy(chosen), {}, {}
        amount, resized = await inverse_conversion(quoter, chosen, USDT, PAXG,
            FUNDED_USDT, TARGET_PAXG, BLOCK, bank, canonical)
        independent = {}
        _, output, retained = await replay_conversion(quoter, deepcopy(resized), USDT,
            PAXG, amount, BLOCK, independent, canonical)
        self.assertGreaterEqual(output, TARGET_PAXG)
        self.assertLess(amount, FUNDED_USDT)
        self.assertEqual(retained, [])
        self.assertEqual(bank, independent)
        self.assertEqual(resized['branches'][0]['hops'][1], route[1])
        self.assertEqual(chosen, original)

    async def test_mixed_single_path_commits_forward_state_for_next_shared_pool(self):
        for protocol in ('v3', 'v4'):
            with self.subTest(protocol=protocol):
                connector = stablecoin_pools()[1]
                tail = synthetic_pool(WETH, PAXG, 9940, protocol, liquidity=10**24)
                quoter = service(self, [connector, tail])
                route = [hop(connector, USDT), hop(tail, WETH)]
                chosen = encode_nomination(USDT, PAXG,
                    ([{'amountIn': str(FUNDED_USDT), 'hops': route}], []))[1]
                bank, canonical, backward_banks = {}, {}, []
                quote = quoter.engine.quote_sdk_branches

                async def observe(branches, mode, amount, block, **kwargs):
                    value = await quote(branches, mode, amount, block, **kwargs)
                    if mode == 'exactOut':
                        backward_banks.append(deepcopy(kwargs['candidate']))
                    return value

                with patch.object(quoter.engine, 'quote_sdk_branches', observe):
                    amount, resized = await inverse_conversion(quoter, chosen, USDT, PAXG,
                        FUNDED_USDT, TARGET_PAXG, BLOCK, bank, canonical)
                independent = {}
                _, output, retained = await replay_conversion(quoter, deepcopy(resized), USDT,
                    PAXG, amount, BLOCK, independent, canonical)
                self.assertGreaterEqual(output, TARGET_PAXG)
                self.assertEqual(retained, [])
                self.assertEqual(bank, independent)
                # The 6-decimal connector's rounding surplus enters the next
                # pool during exactIn execution. Its actual state differs from
                # the backward quote, so later shared operations need replay.
                self.assertNotEqual(bank[tail['id']], backward_banks[0][tail['id']])
                next_route, next_input = [hop(tail, WETH)], 10**18
                _, next_output = await quoter.price_path(next_route, next_input, BLOCK, bank, canonical)
                _, expected = await quoter.price_path(next_route, next_input, BLOCK, independent, canonical)
                _, untouched = await quoter.price_path(next_route, next_input, BLOCK, {}, canonical)
                self.assertEqual(next_output, expected)
                self.assertNotEqual(next_output, untouched)
                self.assertEqual(bank, independent)

    async def assert_split_target(self, direct_weight):
        pools = stablecoin_pools()
        quoter = service(self, pools)
        chosen = split_choice(pools, direct_weight)
        original, bank, canonical = deepcopy(chosen), {}, {}
        amount, resized = await inverse_conversion(quoter, chosen, USDT, PAXG,
            FUNDED_USDT, TARGET_PAXG, BLOCK, bank, canonical)
        independent = {}
        _, output, retained = await replay_conversion(quoter, deepcopy(resized),
            USDT, PAXG, amount, BLOCK, independent, canonical)
        self.assertGreaterEqual(output, TARGET_PAXG)
        self.assertLess(amount, FUNDED_USDT)
        self.assertEqual(output, constant_product_output(resized, amount, {}, pools))
        self.assertEqual(retained, [])
        self.assertEqual(bank, independent)
        self.assertEqual(chosen, original)
        self.assertEqual(quoter.engine.registry.observed, quoter.engine.registry.inventory)
    async def test_one_ppm_direct_path_meets_target(self):
        await self.assert_split_target(1)

    async def test_three_ppm_direct_path_meets_target(self):
        await self.assert_split_target(3)

    async def test_five_ppm_direct_path_meets_target(self):
        await self.assert_split_target(5)

    async def test_one_third_direct_path_covers_required_outputs(self):
        await self.assert_split_target(333333)

    async def test_half_direct_path_covers_required_outputs(self):
        await self.assert_split_target(500000)

    async def test_two_thirds_direct_path_covers_required_outputs(self):
        await self.assert_split_target(666667)

    async def test_one_ppm_indirect_path_covers_required_outputs(self):
        await self.assert_split_target(999999)

    async def test_shared_pool_splits_commit_one_replay_from_preceding_state(self):
        pools = stablecoin_pools()
        quoter = service(self, pools)
        route = [hop(pools[0], USDT)]
        chosen = encode_nomination(USDT, PAXG, ([
            {'amountIn': str(FUNDED_USDT // 2), 'hops': route},
            {'amountIn': str(FUNDED_USDT // 2), 'hops': route},
        ], []))[1]
        bank, canonical = {}, {}
        await quoter.price_path(route, 10000 * 10**6, BLOCK, bank, canonical)
        preceding, original = deepcopy(bank), deepcopy(chosen)
        amount, resized = await inverse_conversion(quoter, chosen, USDT, PAXG,
            FUNDED_USDT, TARGET_PAXG, BLOCK, bank, canonical)
        independent = deepcopy(preceding)
        _, output, retained = await replay_conversion(quoter, deepcopy(resized),
            USDT, PAXG, amount, BLOCK, independent, canonical)
        self.assertGreaterEqual(output, TARGET_PAXG)
        self.assertEqual(output, constant_product_output(resized, amount, preceding, pools))
        self.assertEqual(retained, [])
        self.assertEqual(bank, independent)
        self.assertEqual(chosen, original)
        self.assertEqual(quoter.engine.registry.observed, quoter.engine.registry.inventory)

    async def test_repeated_pool_round_trip_remains_advisory_to_quote_selection(self):
        pools = stablecoin_pools()
        quoter = service(self, pools)
        route = [hop(pools[1], USDT), hop(pools[1], WETH), hop(pools[0], USDT)]
        chosen = encode_nomination(USDT, PAXG,
            ([{'amountIn': str(FUNDED_USDT), 'hops': route}], []))[1]
        bank, canonical = {}, {}
        await quoter.price_path([hop(pools[1], USDT)], 10000 * 10**6, BLOCK, bank, canonical)
        preceding, original = deepcopy(bank), deepcopy(chosen)
        amount, resized = await inverse_conversion(quoter, chosen, USDT, PAXG,
            FUNDED_USDT, TARGET_PAXG, BLOCK, bank, canonical)
        independent = deepcopy(preceding)
        _, output, retained = await replay_conversion(quoter, deepcopy(resized),
            USDT, PAXG, amount, BLOCK, independent, canonical)
        # Captured per-occurrence states nominate inputs. A repeated pool's
        # changed earlier occurrence can alter later output; Helpers still
        # measures whether the changed whole plan preserves Core issuance.
        self.assertGreater(output, 0)
        self.assertLess(output, TARGET_PAXG)
        self.assertEqual(output, constant_product_output(resized, amount, preceding, pools))
        self.assertEqual(retained, [])
        self.assertEqual(bank, independent)
        self.assertEqual(chosen, original)
        self.assertEqual(quoter.engine.registry.observed, quoter.engine.registry.inventory)
        # Selection consumes completed observations. An actually lower output
        # cannot replace the incumbent just because its funding is smaller.
        # Here the observed PAXG quantities supply the scalar selection fixture;
        # this is not a second Core/Helpers simulator or a new admission rule.
        request = {'intent': 0, 'inputs': [{'currency': USDT, 'amount': str(FUNDED_USDT)}],
                   'outputCurrency': PAXG}
        incumbent = {'request': request, 'inputs': deepcopy(request['inputs']),
                     'quotedOutput': str(TARGET_PAXG), 'plan': {'body': {}, 'conversions': {}}}
        candidate = {**deepcopy(incumbent), 'inputs': [{'currency': USDT, 'amount': str(amount)}],
                     'quotedOutput': str(output)}
        book = QuoteBook(request)
        book.observe(incumbent, identity='incumbent')
        book.observe(candidate, identity='advisory')
        self.assertLess(amount, FUNDED_USDT)
        self.assertEqual(book.winner()['inputs'], incumbent['inputs'])
        self.assertEqual(book.winner()['quotedOutput'], incumbent['quotedOutput'])

    async def test_native_split_keeps_logical_funding_and_physical_input(self):
        pools = stablecoin_pools()
        quoter = service(self, pools)
        funded = 30 * 10**18
        wrap = {'kind': 'wrap', 'currencyOut': WETH}
        chosen = encode_nomination(ZERO, PAXG, ([
            {'amountIn': str(funded // 2), 'hops': [wrap, hop(pools[2], WETH)]},
            {'amountIn': str(funded // 2),
             'hops': [wrap, hop(pools[1], WETH), hop(pools[0], USDT)]},
        ], []))[1]
        original, bank, canonical = deepcopy(chosen), {}, {}
        amount, resized = await inverse_conversion(quoter, chosen, ZERO, PAXG,
            funded, TARGET_PAXG, BLOCK, bank, canonical)
        independent = {}
        _, output, retained = await replay_conversion(quoter, deepcopy(resized),
            ZERO, PAXG, amount, BLOCK, independent, canonical)
        self.assertGreaterEqual(output, TARGET_PAXG)
        self.assertLess(amount, funded)
        self.assertEqual(resized['inputCurrency'], ZERO)
        self.assertEqual(resized['template']['inputCurrency'].lower(), WETH.lower())
        self.assertEqual(bank, independent)
        self.assertEqual(retained, [])
        self.assertEqual(chosen, original)

    async def assert_capacity_partial(self, protocol):
        limited = synthetic_pool(WETH, PAXG, 9930, protocol, liquidity=10**6)
        unrelated = synthetic_pool(USDT, OTHER, 9931, 'v2')
        quoter = service(self, [limited, unrelated])
        route = [hop(limited, WETH)]
        chosen = encode_nomination(WETH, PAXG,
            ([{'amountIn': '10000', 'hops': route}], []))[1]
        canonical = {}
        used, capacity = await quoter.price_path(route, 10000, BLOCK, {}, canonical)
        self.assertLess(used, 10000)
        bank = {unrelated['id']: deepcopy(unrelated)}
        preceding, original = deepcopy(bank), deepcopy(chosen)
        amount, resized = await inverse_conversion(quoter, chosen, WETH, PAXG,
            10000, capacity+1, BLOCK, bank, canonical)
        independent = deepcopy(preceding)
        _, output, _ = await replay_conversion(quoter, deepcopy(resized), WETH,
            PAXG, amount, BLOCK, independent, canonical)
        # The SDK can return a first-hop partial even for exact-output pricing.
        # One advisory proposal is returned; no funding search tries to make
        # that physical capacity attainable. The whole-plan caller judges it.
        self.assertEqual(output, capacity)
        self.assertLess(output, capacity+1)
        self.assertLessEqual(amount, 10000)
        self.assertEqual(bank, independent)
        self.assertEqual(bank[unrelated['id']], preceding[unrelated['id']])
        self.assertEqual(chosen, original)
        self.assertEqual(quoter.engine.registry.observed, quoter.engine.registry.inventory)

    async def test_v3_first_hop_capacity_returns_advisory_forward_observation(self):
        await self.assert_capacity_partial('v3')

    async def test_v4_first_hop_capacity_returns_advisory_forward_observation(self):
        await self.assert_capacity_partial('v4')

    async def assert_interrupted_forward_replay(self, *, cancel):
        pools = stablecoin_pools()
        unrelated = synthetic_pool(PAXG, OTHER, 9932, 'v2')
        quoter = service(self, [*pools, unrelated])
        chosen = split_choice(pools, 500000)
        bank, canonical = {unrelated['id']: deepcopy(unrelated)}, {}
        preceding, original = deepcopy(bank), deepcopy(chosen)
        exact_output_completed, replay_entered = asyncio.Event(), asyncio.Event()
        released = asyncio.Event()
        request = quoter.engine.sdk.request

        async def interrupted_request(payload, *args, **kwargs):
            if exact_output_completed.is_set() and payload.get('mode') == 'exactIn':
                replay_entered.set()
                if cancel:
                    await released.wait()
                raise SdkWorkerError('transient pricing failure during forward replay')
            result = await request(payload, *args, **kwargs)
            if payload.get('mode') == 'exactOut':
                exact_output_completed.set()
            return result

        with patch.object(quoter.engine.sdk, 'request', interrupted_request):
            if cancel:
                task = asyncio.create_task(inverse_conversion(quoter, chosen, USDT, PAXG,
                    FUNDED_USDT, TARGET_PAXG, BLOCK, bank, canonical))
                try:
                    async with asyncio.timeout(10):
                        await replay_entered.wait()
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            else:
                with self.assertRaisesRegex(SdkWorkerError,
                        'transient pricing failure during forward replay'):
                    await inverse_conversion(quoter, chosen, USDT, PAXG,
                        FUNDED_USDT, TARGET_PAXG, BLOCK, bank, canonical)
        self.assertTrue(exact_output_completed.is_set())
        self.assertTrue(replay_entered.is_set())
        self.assertEqual(bank, preceding)
        self.assertEqual(chosen, original)
        self.assertEqual(quoter.engine.registry.observed, quoter.engine.registry.inventory)
        # The same SDK/engine remains usable after the interrupted optional work.
        _, output = await quoter.price_path([hop(pools[0], USDT)],
            100 * 10**6, BLOCK, {}, canonical)
        self.assertGreater(output, 0)

    async def test_transient_sdk_error_during_forward_replay_preserves_preceding_state(self):
        await self.assert_interrupted_forward_replay(cancel=False)

    async def test_caller_cancellation_during_forward_replay_preserves_preceding_state(self):
        await self.assert_interrupted_forward_replay(cancel=True)

    async def test_zero_target_does_not_need_routes_or_change_preceding_state(self):
        bank, chosen = {'unrelated': {'value': 'owned'}}, {'unused': 'route'}
        before = deepcopy(bank)
        amount, resized = await inverse_conversion(SimpleNamespace(), chosen, USDT,
            PAXG, FUNDED_USDT, 0, BLOCK, bank, {})
        self.assertEqual(amount, 0)
        self.assertEqual(resized, chosen)
        self.assertIsNot(resized, chosen)
        self.assertEqual(bank, before)

    async def test_identity_target_keeps_raw_units_without_sdk(self):
        bank, chosen = {'unrelated': {'value': 'owned'}}, {'unused': 'route'}
        before = deepcopy(bank)
        amount, resized = await inverse_conversion(SimpleNamespace(), chosen, USDT,
            USDT, FUNDED_USDT, 1234567, BLOCK, bank, {})
        self.assertEqual(amount, 1234567)
        self.assertEqual(resized, chosen)
        self.assertIsNot(resized, chosen)
        self.assertEqual(bank, before)


if __name__ == '__main__':
    unittest.main()
