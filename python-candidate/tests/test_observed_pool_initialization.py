"""Only current canonical zero-price observations remove route combinations.

These controls exercise canonical snapshot recording and the ordinary lazy
path/hint producers. No chain/API traffic, SDK process, wall-time gate or
amount solver is used here; the serving SDK control is run separately.
"""
import asyncio
from copy import deepcopy
from itertools import combinations
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from cybergold_candidate import search_observations
from cybergold_candidate.pool_initialization import record_pool_initialization, observed_uninitialized
from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter import candidate_hints
from cybergold_candidate.quoter.candidate_hints import normalize_hints
from cybergold_candidate.quoter.discovery import (TopologyCache, topology_scope, paths,
    route_candidates, route_candidate_steps, route_available)
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
from cybergold_candidate.routing_encoding import ZERO
from cybergold_candidate.search_observations import search_observation_scope
from cybergold_candidate.uniswap_routes import pool_identity
from cybergold_candidate.uniswap_state import PoolRegistry
from cybergold_candidate.uniswap_v4 import v4_pool_id
from cybergold_candidate.wallet_balances import TOKENS
from test_latest_uniswap_state import Rpc
from test_hint_union_reuse import crossed, expected_union, signature, A as CROSS_SOURCE, D as CROSS_TARGET


A, B, C, CORE, MANAGER, OTHER_MANAGER, ADDRESS = (
    '0x' + format(index, '040x') for index in range(1, 8))
PIN = {'number': 10, 'hash': '0x' + 'ab' * 32}
NEXT = {'number': 11, 'hash': '0x' + 'cd' * 32}
WETH = dict(TOKENS)['weth']


def pool(source=A, target=B, number=20, *, protocol='v3', fee=500, decimals=(18, 18)):
    tokens = sorted(({'address': source.lower(), 'decimals': decimals[0]},
                     {'address': target.lower(), 'decimals': decimals[1]}), key=lambda row: row['address'])
    row = {'id': '0x' + format(number, '040x'), 'protocol': protocol,
           'token0': tokens[0], 'token1': tokens[1], 'feePips': fee,
           'tickSpacing': 10, 'hooks': ZERO}
    if protocol == 'v4':
        row['poolManager'] = MANAGER
        row['id'] = v4_pool_id((tokens[0]['address'], tokens[1]['address'], fee, 10, ZERO))
    else:
        row['address'] = row['id']
    return row


def route(row, source):
    return [{'pool': row, 'zeroForOne': row['token0']['address'] == source.lower()}]


def state(row, sqrt='0', *, liquidity='0'):
    return {**deepcopy(row), 'sqrtRatioX96': sqrt, 'tick': 0, 'liquidity': liquidity,
            'bitmapWords': [], 'ticks': [], 'context': {'chainId': 1,
                'blockNumber': str(PIN['number']), 'blockHash': PIN['hash']}}


def registry():
    rpc = SimpleNamespace(pool_manager=MANAGER)
    return SimpleNamespace(chain=1, generation='first', inventory={},
                           get_rpc=lambda: rpc, metadata={})


class InitializationFactsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.observations = await self.enterAsyncContext(search_observation_scope())
        self.registry = registry()

    def record(self, row, sqrt='0', *, block=PIN, generation=None, liquidity='0'):
        record_pool_initialization(self.registry, state(row, sqrt, liquidity=liquidity), block,
            self.registry.generation if generation is None else generation)

    async def test_only_canonical_integer_or_decimal_zero_disproves_v3_and_v4(self):
        for protocol in ('v3', 'v4'):
            for value, expected in ((0, True), ('0', True), (None, False), ('bad', False),
                                    (False, False), (0.0, False), ('0x0', False), ('0.0', False),
                                    ('1', False), (2**96, False)):
                with self.subTest(protocol=protocol, value=repr(value)):
                    row = pool(protocol=protocol)
                    self.observations.pool_initializations.clear()
                    self.record(row, value)
                    self.assertEqual(observed_uninitialized(self.registry, row, PIN), expected)

    async def test_nomination_metadata_and_unknown_state_are_not_observations(self):
        row = pool(protocol='v4')
        row.update(sqrtRatioX96='0', liquidity='0')
        self.assertFalse(observed_uninitialized(self.registry, row, PIN))
        self.assertEqual(self.observations.pool_initializations, {})
        v2 = pool(protocol='v2')
        self.record(v2)
        self.assertFalse(observed_uninitialized(self.registry, v2, PIN))

    async def test_positive_initialized_price_supersedes_zero_even_with_no_active_liquidity(self):
        for protocol in ('v3', 'v4'):
            row = pool(protocol=protocol)
            self.record(row)
            self.assertTrue(observed_uninitialized(self.registry, row, PIN))
            self.record(row, str(2**96), liquidity='0')
            self.assertFalse(observed_uninitialized(self.registry, row, PIN))

    async def test_facts_are_search_owned_cleared_and_not_global_outside_scope(self):
        row = pool(protocol='v4')
        self.record(row)
        async with search_observation_scope() as other:
            self.assertFalse(observed_uninitialized(self.registry, row, PIN))
            self.assertEqual(other.pool_initializations, {})
        self.assertTrue(observed_uninitialized(self.registry, row, PIN))
        await self.observations.close()
        self.assertEqual(self.observations.pool_initializations, {})
        token = search_observations._current.set(None)
        try:
            self.record(row)
            self.assertFalse(observed_uninitialized(self.registry, row, PIN))
        finally:
            search_observations._current.reset(token)

    async def test_same_pool_isolated_by_registry_and_chain(self):
        row = pool(protocol='v4')
        self.record(row)
        self.assertFalse(observed_uninitialized(registry(), row, PIN))
        self.registry.chain = 31338
        self.assertFalse(observed_uninitialized(self.registry, row, PIN))
        self.registry.chain = 1
        self.assertTrue(observed_uninitialized(self.registry, row, PIN))

    async def test_new_block_or_fork_generation_does_not_inherit_zero_proof(self):
        row = pool(protocol='v4')
        self.record(row)
        self.assertFalse(observed_uninitialized(self.registry, row, NEXT))
        self.assertFalse(observed_uninitialized(self.registry, row, LATEST_BLOCK))
        self.registry.generation = 'replacement-fork'
        self.assertFalse(observed_uninitialized(self.registry, row, PIN))
        self.record(row, str(2**96))
        self.assertFalse(observed_uninitialized(self.registry, row, PIN))

    async def test_late_old_generation_record_cannot_disprove_current_fork(self):
        row = pool(protocol='v4')
        self.registry.generation = 'replacement-fork'
        self.record(row, generation='first')
        self.assertFalse(observed_uninitialized(self.registry, row, PIN))

    async def test_v4_authority_matches_explicit_default_but_not_another_manager(self):
        row = pool(protocol='v4')
        self.record(row)
        implicit = deepcopy(row)
        implicit.pop('poolManager')
        self.assertTrue(observed_uninitialized(self.registry, implicit, PIN))
        self.assertFalse(observed_uninitialized(self.registry,
            {**row, 'poolManager': OTHER_MANAGER}, PIN))
        self.assertFalse(observed_uninitialized(self.registry, {**row, 'feePips': 3000}, PIN))

    async def test_v3_explicit_addresses_and_unresolved_alias_are_not_conflated(self):
        row = pool()
        self.record(row)
        self.assertTrue(observed_uninitialized(self.registry, {**row, 'id': 'alias'}, PIN))
        self.assertFalse(observed_uninitialized(self.registry, {**row, 'address': ADDRESS}, PIN))
        implicit = deepcopy(row)
        implicit.pop('address')
        self.assertFalse(observed_uninitialized(self.registry, implicit, PIN))


class InitializationRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.observations = await self.enterAsyncContext(search_observation_scope())
        self.registry = registry()
        self.cache = TopologyCache(pool_available=lambda row:
            not observed_uninitialized(self.registry, row, PIN))

    def record(self, row, sqrt='0'):
        record_pool_initialization(self.registry, state(row, sqrt), PIN, self.registry.generation)

    def contains(self, rows, unwanted):
        return any(pool_identity(hop['pool']) == pool_identity(unwanted)
                   for row in rows for hop in row['hops'] if 'pool' in hop)

    async def test_known_zero_is_removed_before_pair_combinations_and_inputs_stay_private(self):
        for protocol in ('v3', 'v4'):
            with self.subTest(protocol=protocol):
                bad = pool(number=21, protocol=protocol, fee=100)
                good = [pool(number=22, fee=500), pool(number=23, fee=3000)]
                routes = [route(row, A) for row in (bad, *good)]
                original = deepcopy(routes)
                self.record(bad)
                paired_inputs = []
                def pairs(offered, size):
                    selected = list(offered)
                    paired_inputs.append(selected)
                    self.assertTrue(all(route_available(row) for row in selected))
                    return combinations(selected, size)
                with topology_scope(self.cache), patch(
                        'cybergold_candidate.quoter.discovery.combinations', side_effect=pairs):
                    values = list(route_candidates(routes, 100))
                self.assertEqual(len(values), 5)  # Two singles and three quarter splits.
                self.assertTrue(paired_inputs)
                self.assertFalse(any(self.contains(rows, bad) for rows in values))
                self.assertTrue(all(sum(int(row['amountIn']) for row in rows) == 100 for rows in values))
                self.assertEqual(routes, original)

    async def test_old_lazy_feed_rechecks_zero_observed_between_single_and_split_consumption(self):
        bad, first, second = pool(fee=100), pool(number=22), pool(number=23, fee=3000)
        with topology_scope(self.cache):
            iterator = route_candidates([route(row, A) for row in (bad, first, second)], 100)
            try:
                self.assertTrue(self.contains(next(iterator), bad))  # State is still unknown.
                self.record(bad)
                remainder = list(iterator)
            finally:
                iterator.close()
        self.assertEqual(len(remainder), 5)
        self.assertFalse(any(self.contains(rows, bad) for rows in remainder))

    async def test_late_zero_between_split_allocations_keeps_all_valid_sibling_lots(self):
        bad, first, second = pool(fee=100), pool(number=22), pool(number=23, fee=3000)
        routes = [route(row, A) for row in (bad, first, second)]
        original = deepcopy(routes)
        with topology_scope(self.cache):
            iterator = route_candidates(routes, 100)
            try:
                for _ in routes:
                    next(iterator)
                self.assertTrue(self.contains(next(iterator), bad))
                self.record(bad)
                remainder = list(iterator)
            finally:
                iterator.close()
        expected = [[{'amountIn': str(left), 'hops': route(first, A)},
                     {'amountIn': str(right), 'hops': route(second, A)}]
                    for left, right in ((25, 75), (50, 50), (75, 25))]
        self.assertEqual(remainder, expected)
        self.assertEqual(routes, original)

    async def test_warmed_topology_walks_recheck_current_zero_observation(self):
        bad, good = pool(fee=100), pool(number=22)
        with topology_scope(self.cache):
            self.assertEqual(len(paths([bad, good], A, B)), 2)
            self.assertTrue(self.cache.walks)
            self.record(bad)
            current = paths([bad, good], A, B)
            self.assertEqual(current, [route(good, A)])
            self.assertTrue(all(route_available(row) for row in current))

    async def test_split_hint_keeps_good_leg_as_full_budget_alternative(self):
        bad, good = pool(fee=100), pool(number=22)
        offered = {'branches': [{'amountIn': '40', 'hops': route(bad, A)},
                                 {'amountIn': '60', 'hops': route(good, A)}],
                   'origins': ['supplier-before-observation']}
        original = deepcopy(offered)
        self.record(bad)
        with topology_scope(self.cache):
            values = list(normalize_hints([offered], A, B))
        self.assertTrue(values)
        self.assertFalse(any(self.contains(rows, bad) for rows, _ in values))
        self.assertIn(([{'amountIn': '100', 'hops': route(good, A)}], offered['origins']), values)
        self.assertEqual(offered, original)

    async def test_ready_quick_prefix_created_before_observation_uses_live_bootstrap_predicate(self):
        bad, good = pool(fee=100), pool(number=22)
        self.registry.inventory = {row['id']: row for row in (bad, good)}
        self.registry.seed = good
        adapter = CyberGoldAmmAdapter(SimpleNamespace(registry=self.registry), CORE)
        session = RouteBootstrap([], catalog=self.registry, block=PIN)
        key = A.lower(), B.lower(), 100
        session._queries[key] = []
        offers = [{'branches': [{'amountIn': '100', 'hops': route(row, A)}],
                   'origins': [label]} for row, label in ((bad, 'old-bad'), (good, 'old-good'))]
        try:
            with bootstrap_scope(session):
                async def consume():
                    feeds = session.offer_feeds(A, B, 100, PIN)
                    self.record(bad)
                    # These exact feed objects predate the observation.
                    values = []
                    for offered in feeds:
                        values.extend(normalize_hints(offered, A, B))
                    return values
                values = await session._arrival_pass(consume, None, {key: offers})
                self.assertEqual(values, [([{'amountIn': '100', 'hops': route(good, A)}], ['old-good'])])
                async def adapted():
                    return list(adapter.nominations(A, B, 100, PIN))
                self.assertEqual(await session._arrival_pass(adapted, None, {key: offers}), values)
        finally:
            await session.close()

    async def test_zero_learned_during_second_cooperative_walk_preserves_full_budget_good_leg(self):
        good, bad = pool(number=22), pool(fee=100)
        offered = {'branches': [{'amountIn': '60', 'hops': route(good, A)},
                                 {'amountIn': '40', 'hops': route(bad, A)}],
                   'origins': ['cooperative-arrival']}
        original_walk = candidate_hints.path_steps
        walks = []
        def walking(*args, **kwargs):
            walks.append(1)
            steps = original_walk(*args, **kwargs)
            try:
                first = True
                while True:
                    try:
                        value = next(steps)
                    except StopIteration as done:
                        return done.value
                    yield value
                    if len(walks) == 2 and first:
                        # The first good alternative already exists; an
                        # observation arrives across the next walk checkpoint.
                        self.record(bad)
                    first = False
            finally:
                steps.close()
        with topology_scope(self.cache), patch.object(candidate_hints, 'path_steps', walking):
            values = list(normalize_hints([offered], A, B))
        self.assertIn(([{'amountIn': '100', 'hops': route(good, A)}], offered['origins']), values)
        self.assertFalse(any(self.contains(rows, bad) for rows, _ in values))

    async def test_mid_fill_zero_observation_does_not_poison_structural_pattern_memo(self):
        offered = crossed(origin='before')
        for row in offered['branches']:
            for hop in row['hops']:
                hop['pool']['address'] = hop['pool']['id']
        expected = expected_union(offered)
        bad = offered['branches'][0]['hops'][1]['pool']
        with topology_scope(self.cache), patch.object(candidate_hints, 'route_candidate_steps',
                                                     wraps=route_candidate_steps) as expansion:
            iterator = iter(normalize_hints([offered], CROSS_SOURCE, CROSS_TARGET))
            try:
                next(iterator)
                self.record(bad)
                remainder = list(iterator)
                self.assertFalse(any(self.contains(rows, bad) for rows, _ in remainder))
            finally:
                iterator.close()
            self.record(bad, str(2**96))
            current = deepcopy(offered)
            current['origins'] = ['initialized-again']
            restored = list(normalize_hints([current], CROSS_SOURCE, CROSS_TARGET))
            self.assertEqual(expansion.call_count, 1, 'The fully drained structural pattern set is reusable')
        self.assertEqual([signature(rows) for rows, _ in restored], expected)
        self.assertTrue(all(origins == ['initialized-again'] for _, origins in restored))

    async def test_native_lossless_wrap_and_unwrap_remain_eligible(self):
        bad = pool(ZERO, B, protocol='v4')
        good = pool(WETH, B)
        self.record(bad)
        with topology_scope(self.cache):
            forward = paths([bad, good], ZERO, B)
            reverse = paths([bad, good], B, ZERO)
        self.assertEqual(len(forward), 1)
        self.assertEqual(len(reverse), 1)
        self.assertEqual(forward[0][0], {'kind': 'wrap', 'currencyOut': WETH.lower()})
        self.assertEqual(reverse[0][-1], {'kind': 'unwrap', 'currencyOut': ZERO})
        self.assertFalse(self.contains([{'hops': row} for row in forward + reverse], bad))

    async def test_currency_and_decimal_families_share_the_same_observed_identity_rule(self):
        sources = [(WETH, 18), (dict(TOKENS)['usdc'], 6), (dict(TOKENS)['usdt'], 6),
                   (C, 18), (CORE, 18)]
        for source, decimals in sources:
            with self.subTest(source=source, decimals=decimals):
                bad = pool(source, B, protocol='v4', fee=100, decimals=(decimals, 18))
                good = pool(source, B, number=22, decimals=(decimals, 18))
                self.record(bad)
                with topology_scope(self.cache):
                    self.assertEqual(paths([bad, good], source, B), [route(good, source)])
                    self.assertEqual(paths([bad, good], B, source), [route(good, B)])
                self.assertEqual(next(t['decimals'] for t in (good['token0'], good['token1'])
                                      if t['address'] == source.lower()), decimals)

    async def test_unknown_and_initialized_zero_liquidity_routes_remain_eligible(self):
        unknown, empty = pool(fee=100), pool(number=22)
        unknown['sqrtRatioX96'] = '0'  # Supplier metadata, not a canonical observation.
        self.record(empty, str(2**96))
        with topology_scope(self.cache):
            values = list(route_candidates(paths([unknown, empty], A, B), 100))
        self.assertEqual(len(values), 5)
        self.assertTrue(any(self.contains(rows, unknown) for rows in values))
        self.assertTrue(any(self.contains(rows, empty) for rows in values))


class CanonicalInitializationRecordingTests(unittest.IsolatedAsyncioTestCase):
    def registry(self, rpc):
        store = SimpleNamespace(save=AsyncMock())
        row = PoolRegistry(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE), rpc=rpc, store=store)
        self.addAsyncCleanup(row.close)
        return row

    async def test_actual_pinned_and_latest_snapshots_record_zero_without_extra_reads(self):
        class ZeroRpc(Rpc):
            price = 0
            async def read_function(inner, address, signature, types, args, outputs, block):
                if signature == 'slot0()':
                    inner.calls.append((signature, deepcopy(args), deepcopy(block)))
                    return inner.price, 0, 0, 0, 0, 0, True
                if signature.startswith('getSlot0('):
                    inner.calls.append((signature, deepcopy(args), deepcopy(block)))
                    return inner.price, 0, 0, 500
                return await super().read_function(address, signature, types, args, outputs, block)
        for protocol in ('v3', 'v4'):
            for block in (PIN, LATEST_BLOCK):
                with self.subTest(protocol=protocol, block=block):
                    rpc = ZeroRpc()
                    rpc.pool_manager = MANAGER
                    reg, identity = self.registry(rpc), pool(protocol=protocol)
                    original = deepcopy(identity)
                    async with search_observation_scope():
                        observed = await reg.snapshot(identity, block, publish=False)
                        self.assertEqual(observed['sqrtRatioX96'], '0')
                        self.assertTrue(observed_uninitialized(reg, identity, block))
                        calls = len(rpc.calls)
                        for _ in range(4):
                            self.assertTrue(observed_uninitialized(reg, identity, block))
                        self.assertEqual(len(rpc.calls), calls)
                    self.assertEqual(identity, original)
                    # A fresh latest search can observe initialization at the
                    # same header; prior proof has no authority in this scope.
                    rpc.price = 2**96
                    async with search_observation_scope():
                        self.assertFalse(observed_uninitialized(reg, identity, block))
                        if block is LATEST_BLOCK:
                            current = await reg.snapshot(identity, block, publish=False)
                            self.assertEqual(current['sqrtRatioX96'], str(2**96))
                            self.assertFalse(observed_uninitialized(reg, identity, block))

    async def test_actual_factory_alias_resolution_records_only_the_proven_alias(self):
        class ResolvingRpc(Rpc):
            async def read_function(inner, address, signature, types, args, outputs, block):
                if signature == 'getPool(address,address,uint24)':
                    inner.calls.append((signature, deepcopy(args), deepcopy(block)))
                    return (ADDRESS,)
                if signature == 'slot0()':
                    inner.calls.append((signature, deepcopy(args), deepcopy(block)))
                    return 0, 0, 0, 0, 0, 0, True
                return await super().read_function(address, signature, types, args, outputs, block)
        reg, identity = self.registry(ResolvingRpc()), pool()
        identity.pop('address')
        async with search_observation_scope():
            observed = await reg.snapshot(identity, PIN, publish=False)
            self.assertEqual(observed['address'], ADDRESS)
            self.assertTrue(observed_uninitialized(reg, identity, PIN))
            self.assertTrue(observed_uninitialized(reg, observed, PIN))
            different = {**observed, 'address': MANAGER}
            record_pool_initialization(reg, {**different, 'sqrtRatioX96': str(2**96)}, PIN, reg.generation)
            self.assertFalse(observed_uninitialized(reg, identity, PIN),
                             'An unknown alias remains eligible when explicit authorities disagree')
            self.assertTrue(observed_uninitialized(reg, observed, PIN))
            self.assertFalse(observed_uninitialized(reg, different, PIN))

    async def test_failed_canonical_read_keeps_ordinary_error_and_records_no_zero_fact(self):
        expected = OSError('inert canonical read failure')
        class FailingRpc(Rpc):
            async def read_function(self, *_):
                raise expected
        reg, identity = self.registry(FailingRpc()), pool()
        async with search_observation_scope() as observations:
            with self.assertRaises(OSError) as raised:
                await reg.snapshot(identity, PIN, publish=False)
            self.assertIs(raised.exception, expected)
            self.assertFalse(observed_uninitialized(reg, identity, PIN))
            self.assertEqual(observations.pool_initializations, {})

    async def test_old_read_finishing_after_generation_change_cannot_mark_new_generation(self):
        entered, release = asyncio.Event(), asyncio.Event()
        class HeldRpc(Rpc):
            async def read_function(inner, address, signature, types, args, outputs, block):
                if signature == 'slot0()':
                    entered.set()
                    await release.wait()
                    return 0, 0, 0, 0, 0, 0, True
                return await super().read_function(address, signature, types, args, outputs, block)
        reg, identity = self.registry(HeldRpc()), pool()
        reg.generation = 'old'
        async with search_observation_scope():
            task = asyncio.create_task(reg.snapshot(identity, PIN, publish=False))
            try:
                await asyncio.wait_for(entered.wait(), 3)
                reg.generation = 'new'
                release.set()
                await task
                self.assertFalse(observed_uninitialized(reg, identity, PIN))
            finally:
                release.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
