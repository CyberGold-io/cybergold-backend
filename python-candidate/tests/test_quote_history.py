"""Captured Helpers parity, organic learning, optional-task lifetime and history."""
import asyncio
from copy import deepcopy
from fractions import Fraction as F
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.basket_arithmetic import BasketArithmetic, wire
from cybergold_candidate.quote_history import QuoteHistory, economic_path, route_key
from cybergold_candidate.quote_cache import VerifiedGrossSeed, IntentSharing
from cybergold_candidate.quote_intent import QuoteIntent
from cybergold_candidate.quote_models import PoolBaseline
from cybergold_candidate.uniswap_routes import v3_plan
from test_quote_intent import SETTINGS, request, service


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_retires_untagged_and_changed_banks_only(self):
        history = QuoteHistory(SETTINGS)
        banks = (history.routes, history.families, history.baselines, history.states, history.facts)
        for bank in banks:
            bank['old'] = {'state': 'old'}
        self.assertFalse(await history.observe_generation(None))
        self.assertTrue(all(banks))
        self.assertTrue(await history.observe_generation('first'))
        self.assertEqual(history.epoch, 1)
        self.assertFalse(any(banks))
        for bank in banks:
            bank['current'] = {'state': 'current'}
        self.assertFalse(await history.observe_generation('first'))
        self.assertFalse(await history.observe_generation(None))
        self.assertTrue(all(banks))
        self.assertTrue(await history.observe_generation('second'))
        self.assertEqual(history.epoch, 2)
        self.assertFalse(any(banks))

    async def test_optional_reset_does_not_remove_a_new_same_key_task(self):
        history = QuoteHistory(SETTINGS)
        self.addAsyncCleanup(history.close)
        started, retired, finish_old, finish_new = (asyncio.Event() for _ in range(4))
        async def old():
            started.set()
            try:
                await finish_old.wait()
            except asyncio.CancelledError:
                retired.set()
                await finish_old.wait()
        history.launch('same-key', old)
        await started.wait()
        self.assertTrue(await history.observe_generation('new'))
        await retired.wait()
        history.launch('same-key', finish_new.wait)
        new = history.tasks['same-key']
        finish_old.set()
        await asyncio.gather(*history.retiring_tasks)
        self.assertIs(history.tasks['same-key'], new)
        finish_new.set()
        await new
        self.assertFalse(history.tasks)

    async def test_state_and_pool_acquisition_cannot_restore_a_retired_epoch(self):
        history = QuoteHistory(SETTINGS)
        await history.observe_generation('old')
        epoch = history.epoch
        context = {'chainId': 31338, 'blockNumber': '100', 'blockHash': 'hash'}
        history.facts['hash'] = {'basket': {'assets': {'value': ['asset']},
            'targetsPpm': {'value': [1_000_000]}, 'cygldPerUnitFp18': {'value': [10**18]}},
            'fees': {'issuancePpm': {'value': '0'}, 'helpersPpm': {'value': '0'}}}
        history.batch = AsyncMock(side_effect=[[1, 10, 10, 0, [], False], [{'activeAvailableRaw': 100}]])
        async def canonical(_):
            await history.observe_generation('new')
        rpc = SimpleNamespace(assert_canonical=canonical)
        await history.acquire_state(rpc, {'hash': 'hash'}, context, epoch)
        self.assertFalse(history.states)
        rpc = SimpleNamespace(assert_canonical=AsyncMock())
        provider = SimpleNamespace(route_baseline=AsyncMock(return_value=PoolBaseline(F(1), F(9995, 10000))),
                                   registry=SimpleNamespace(get_rpc=lambda: rpc))
        tokens = [request('issue-exact-in')['quoteToken'].lower(), request('issue-exact-in')['orderedAssets'][0].lower()]
        plan = v3_plan('0x'+tokens[0][2:]+'0001f4'+tokens[1][2:], 'exact-in', 1)
        await history.acquire_route(provider, plan, {'hash': 'hash'}, context, epoch)
        self.assertFalse(history.baselines)

    async def test_reset_retires_foreground_models_without_canceling_exact_quote(self):
        intent, provider, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        history = QuoteHistory(SETTINGS)
        self.addAsyncCleanup(history.close)
        await history.observe_generation('old')
        intent.history = history
        history.acquire_state = AsyncMock()
        history.acquire_route = AsyncMock()
        provider.finish_final = asyncio.Event()
        frames = []
        task = asyncio.create_task(intent.get(request('issue-exact-in'),
            lambda frame: asyncio.sleep(0, result=frames.append(frame))))
        await provider.final_started.wait()
        await history.observe_generation('new')
        frames.clear()
        provider.finish_final.set()
        result = await task
        self.assertEqual(result['displayAmount'], '200')
        self.assertFalse([frame for frame in frames if frame['type'] == 'model'])
        self.assertFalse(history.families)
        self.assertFalse(history.tasks)
        fresh = await intent.get(request('issue-exact-in'), lambda frame: asyncio.sleep(0))
        self.assertEqual(fresh['displayAmount'], result['displayAmount'])
        self.assertTrue(history.families)

    async def test_reset_during_final_model_delivery_skips_old_optional_scheduling(self):
        intent, _, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        history = QuoteHistory(SETTINGS)
        self.addAsyncCleanup(history.close)
        await history.observe_generation('old')
        intent.history = history
        history.acquire_state = AsyncMock()
        history.acquire_route = AsyncMock()
        models = []
        async def update(frame):
            if frame['type'] == 'model':
                models.append(frame)
                if len(models) == 2:
                    # The unified provider may already have launched the same
                    # optional early model work for a historical V3 adapter.
                    # This assertion concerns scheduling after retirement.
                    history.acquire_state.reset_mock()
                    history.acquire_route.reset_mock()
                    await history.observe_generation('new')
        result = await intent.get(request('issue-exact-in'), update)
        self.assertEqual(result['displayAmount'], '200')
        self.assertFalse(history.families)
        self.assertFalse(history.tasks)
        history.acquire_state.assert_not_called()
        history.acquire_route.assert_not_called()

    async def test_reset_during_shared_head_wait_preserves_old_model_epoch(self):
        intent, provider, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        history = QuoteHistory(SETTINGS)
        await history.observe_generation('old')
        intent.history = history
        shared = IntentSharing(intent)
        self.addAsyncCleanup(shared.close)
        provider.hold_chain = asyncio.Event()
        frames = []
        task = asyncio.create_task(shared.get(request('issue-exact-in'),
            lambda frame: asyncio.sleep(0, result=frames.append(frame))))
        while not provider.calls:
            await asyncio.sleep(0)
        await history.observe_generation('new')
        frames.clear()
        provider.hold_chain.set()
        result = await task
        self.assertEqual(result['displayAmount'], '200')
        self.assertFalse([frame for frame in frames if frame['type'] == 'model'])
        self.assertFalse(history.families)
        self.assertFalse(history.tasks)

    async def test_sandbox_model_state_reuses_head_until_actual_math_contradicts(self):
        fixture = json.loads(Path(__file__).with_name('fixtures').joinpath('basket-model.json').read_text())
        case = next(c for c in fixture['cases'] if c['request']['mode'] == 'issue-exact-out')
        history = QuoteHistory(SETTINGS)
        self.addAsyncCleanup(history.close)
        context = {'chainId': 31338, 'blockHash': 'hash', 'blockNumber': '1', 'observedAt': 'now'}
        history.states['hash'] = {'state': wire(fixture['state']), 'context': context}
        value = request('issue-exact-out')
        result = {'context': context, 'executionAmount': case['request']['netCygldOut'],
                  'basketPreview': case['actual'], 'displayAmount': '1'}
        history.observe(value, result, [])
        self.assertIn('hash', history.states)
        rpc = SimpleNamespace(chain_id=31338)
        history.ensure_state(rpc, {'hash': 'hash'}, context)
        self.assertFalse(history.tasks)
        changed = deepcopy(result)
        changed['basketPreview']['amountsInExact'][0] = str(int(changed['basketPreview']['amountsInExact'][0])+1)
        history.observe(value, changed, [])
        self.assertNotIn('hash', history.states)
        started = asyncio.Event()
        async def acquisition(*_):
            started.set()
        history.acquire_state = acquisition
        history.ensure_state(rpc, {'hash': 'hash'}, context)
        await asyncio.wait_for(started.wait(), 1)

    def test_retirement_uses_rounded_prediction_not_fractional_dust(self):
        from cybergold_candidate.quote_models import LegModel
        model = LegModel([(1000, 1998)], PoolBaseline(F(2), F(9995,10000)))
        model.observe(50, 99)
        self.assertEqual(model.retired, 0)
        self.assertIn((1000, 1998), model.points)
        model.observe(50, 98)
        self.assertNotIn((1000, 1998), model.points)

    async def test_route_baseline_uses_shared_engine_for_minimal_v3_and_other_protocols(self):
        history = QuoteHistory(SETTINGS)
        rpc = SimpleNamespace(assert_canonical=AsyncMock())
        baseline = PoolBaseline(F(2), F(9995, 10000), F(1, 1000))
        provider = SimpleNamespace(route_baseline=AsyncMock(return_value=baseline),
                                   registry=SimpleNamespace(get_rpc=lambda: rpc))
        tokens = [request('issue-exact-in')['quoteToken'].lower(), request('issue-exact-in')['orderedAssets'][0].lower()]
        context = {'chainId': 1, 'blockNumber': '1', 'blockHash': 'hash', 'observedAt': 'now'}
        for protocol in ('v3', 'v2', 'v4'):
            plan = v3_plan('0x'+tokens[0][2:]+'0001f4'+tokens[1][2:], 'exact-in', 1)
            pool = plan['branches'][0]['hops'][0]['pool']
            pool['protocol'] = protocol
            if protocol == 'v4':
                pool.update(tickSpacing=10, hooks='0x'+'0'*40)
            await history.acquire_route(provider, plan, {'hash': 'hash'}, context)
            provider.route_baseline.assert_awaited_with(plan, {'hash': 'hash'})
            key = (*route_key(plan), 'hash')
            self.assertIs(history.baselines[key][0], baseline)
            self.assertEqual(history.baselines[key][1], context)
            self.assertEqual(history.routes[route_key(plan)]['routePlan'], plan)
        self.assertEqual(rpc.assert_canonical.await_count, 3)
        self.assertEqual(len(history.baselines), 3)
        self.assertFalse(history.reads)
        self.assertFalse(history.envelopes)

    async def test_historical_packet_does_not_wait_for_head_rpc(self):
        _, provider, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        history = QuoteHistory(SETTINGS)
        shared = IntentSharing(QuoteIntent(SETTINGS, routes, history=history))
        self.addAsyncCleanup(shared.close)
        provider.hold_chain = asyncio.Event()
        frames = []
        task = asyncio.create_task(shared.get(request('issue-exact-in'), lambda e: asyncio.sleep(0, result=frames.append(e))))
        await asyncio.sleep(.01)
        self.assertEqual(frames[0]['type'], 'model')
        self.assertFalse(task.done())
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(shared.pending)

    async def test_verified_seed_is_identical_mainnet_math_only_and_keeps_original_age(self):
        intent, _, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        clock = [0]
        seeds = VerifiedGrossSeed(now=lambda: clock[0])
        intent.seeds = seeds
        value = request('redeem-exact-out')
        first = await intent.get(value, lambda e: asyncio.sleep(0))
        second = await intent.get({**value, 'deadline': str(int(value['deadline'])+1)}, lambda e: asyncio.sleep(0))
        self.assertEqual(second['executionAmount'], first['executionAmount'])
        self.assertIsNone(second['initialPreview'])
        self.assertEqual(second['metrics']['iterations'], 0)
        context = first['context']
        changed = deepcopy(value)
        changed['targets'][0]['amount'] = str(int(changed['targets'][0]['amount'])+1)
        self.assertIsNone(seeds.suggest(changed, context))
        self.assertIsNone(seeds.suggest(value, {**context, 'chainId': 31338}))
        self.assertIsNone(seeds.suggest(value, {**context, 'blockHash': 'new'}))
        clock[0] = 10
        self.assertIsNone(seeds.suggest(value, context))
        self.assertFalse(seeds.rows)

    def test_integer_models_match_captured_live_helpers(self):
        fixture = json.loads(Path(__file__).with_name('fixtures').joinpath('basket-model.json').read_text())
        model = BasketArithmetic(fixture['state'])
        for case in fixture['cases']:
            value = case['request']
            if value['mode'] == 'issue-exact-in':
                predicted = model.issue_in(list(map(int, value['maximumAmountsIn'])))
            elif value['mode'] == 'issue-exact-out':
                predicted = model.issue(int(value['netCygldOut']), includes_helper=True)
            elif value['mode'] == 'redeem-exact-in':
                predicted = model.redeem_in(int(value['grossCygldIn']))
            else:
                predicted = model.redeem_out([int(row['minimumAmount']) for row in value['minimumOutputs']])
            self.assertEqual(wire(predicted), case['actual'])

    def test_mixed_recovery_value_and_fees(self):
        state = {'assets': ['asset'], 'weights': [1_000_000], 'conversions': [10**18],
                 'issueFee': 1000, 'helperFee': 2000, 'redeemFee': 3000,
                 'supply': 1000, 'maxSupply': 10000, 'effectiveCap': 5000,
                 'available': [800], 'recoveryShares': [400], 'recoveryValues': [300],
                 'descriptors': [{'kind': 0, 'token': 'asset', 'id': '0'},
                                 {'kind': 1, 'token': 'core', 'id': '123'}]}
        model = BasketArithmetic(state)
        self.assertEqual(model.denominator, 1100)
        output = model.redeem_in(500)
        self.assertEqual(output['fees'], {'protocolFeeCygld': 1, 'helperFeeCygld': 1})
        self.assertEqual([row['amount'] for row in output['projectedCoreOutputs']], [362, 181])
        self.assertEqual(model.redeem_out([362, 181])['grossCygldIn'], 499)
        with self.assertRaises(ValueError):
            model.issue(5000, includes_helper=True)

    async def test_packets_train_only_after_exact_canonical_completion_and_background_does_not_delay(self):
        old, provider, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        history = QuoteHistory(SETTINGS, limit=2)
        self.addAsyncCleanup(history.close)
        finish = asyncio.Event()
        async def optional(*_):
            await finish.wait()
        history.acquire_state = optional
        history.acquire_route = optional
        intent = QuoteIntent(SETTINGS, routes, history=history)
        frames = []
        result = await asyncio.wait_for(intent.get(request('issue-exact-in'), lambda e: asyncio.sleep(0, result=frames.append(e))), 2)
        packets = [e['value'] for e in frames if e['type'] == 'model']
        self.assertFalse(packets[0]['whole'])
        self.assertEqual(len(packets[-1]['whole']), 1)
        self.assertEqual(packets[-1]['whole'][0]['display'], result['displayAmount'])
        self.assertTrue(history.tasks)
        before = deepcopy(history.packet(request('issue-exact-in')))
        provider.reorg = True
        with self.assertRaises(Exception):
            await intent.get({**request('issue-exact-in'), 'amount': '101'}, lambda e: asyncio.sleep(0))
        self.assertEqual(history.packet(request('issue-exact-in')), before)
        await history.close()
        self.assertFalse(history.tasks)

    def test_direction_rate_fee_and_contradiction_retirement(self):
        history = QuoteHistory(SETTINGS)
        value = request('issue-exact-in')
        context = {'chainId': 1, 'blockNumber': '100', 'blockHash': 'hash', 'observedAt': 'now'}
        a, b = value['quoteToken'].lower(), value['orderedAssets'][0].lower()
        path = '0x'+a[2:]+'0001f4'+b[2:]
        tokens, fees = economic_path(path, 'exact-in')
        self.assertEqual(economic_path('0x'+b[2:]+'0001f4'+a[2:], 'exact-out'), (tokens, fees))
        key = (*route_key(v3_plan(path, 'exact-in', 1)), 'hash')
        history.baselines[key] = (PoolBaseline(F(2), F(9995,10000)), context, 0)
        result = {'context': context, 'displayAmount': '100'}
        def wave(amount, output):
            return [('exact-in', [{'target': {'amount': str(amount)}, 'best': {'path': path, 'quote': str(output)}}])]
        history.observe(value, result, wave(1000, 1900))
        history.observe(value, result, wave(50, 80))
        packet = history.packet(value)
        self.assertEqual(history.retired, 1)
        self.assertEqual([(p['input'], p['output']) for p in packet['routes'][0]['points']], [('50', '80')])
        self.assertEqual(len(next(iter(history.routes.values()))['observations']), 2)
        self.assertEqual(packet['routes'][0]['exchangeRate'], {'numerator': '2', 'denominator': '1'})
        self.assertNotIn('quotes', packet)


class CanonicalHistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.history = QuoteHistory(SETTINGS)
        self.addAsyncCleanup(self.history.close)
        self.request = request('issue-exact-in')
        self.a = self.request['quoteToken'].lower()
        self.b = self.request['orderedAssets'][0].lower()
        self.path = '0x'+self.a[2:]+'0001f4'+self.b[2:]
        self.plan = v3_plan(self.path, 'exact-in', 100)
        self.context = {'chainId': 31338, 'blockNumber': '100', 'blockHash': 'hash', 'observedAt': 'now'}
        self.block = {'hash': 'hash', 'number': 100}
        self.result = {'context': self.context, 'displayAmount': '100'}

    def wave(self, plan, amount=100, output=190):
        return [('exact-in', [{'target': {'amount': str(amount)},
            'best': {'quote': str(output), 'routePlan': plan}}])]

    def provider(self, baseline=None):
        rpc = SimpleNamespace(assert_canonical=AsyncMock())
        registry = SimpleNamespace(get_rpc=lambda: rpc)
        provider = SimpleNamespace(registry=registry,
            route_baseline=AsyncMock(return_value=baseline or PoolBaseline(F(2), F(9995, 10000))))
        return provider, rpc

    async def test_legacy_entry_and_enriched_canonical_plan_share_one_observed_route(self):
        legacy = [('exact-in', [{'target': {'amount': '100'},
            'best': {'path': self.path, 'quote': '190'}}])]
        self.history.observe(self.request, self.result, legacy)
        rich = deepcopy(self.plan)
        pool = rich['branches'][0]['hops'][0]['pool']
        pool.update(id='observed-registry-pool', address='0x'+'7'*40, tickSpacing=10)
        pool['token0'].update(decimals=6, chainId=31338)
        pool['token1'].update(decimals=18, chainId=31338)
        rich['branches'][0]['amountIn'] = '50'
        self.history.observe(self.request, self.result, self.wave(rich, 50, 80))
        self.assertEqual(len(self.history.routes), 1)
        entry = next(iter(self.history.routes.values()))
        self.assertEqual(entry['routePlan'], rich)
        self.assertEqual(entry['model'].points, [(50, 80)])
        self.assertEqual(self.history.retired, 1)
        self.assertEqual(len(entry['observations']), 2)
        self.assertEqual(self.history.packet(self.request)['routes'][0]['protocols'], ['v3'])

    def test_model_identity_keeps_allocation_proportions_and_protocols(self):
        first = deepcopy(self.plan)
        first['branches'][0]['amountIn'] = '25'
        first['branches'].append(deepcopy(first['branches'][0]))
        first['branches'][1]['amountIn'] = '75'
        resized = deepcopy(first)
        resized['branches'][0]['amountIn'] = '50'
        resized['branches'][1]['amountIn'] = '150'
        self.assertEqual(route_key(first), route_key(resized))
        resized['branches'][0]['amountIn'] = '100'
        self.assertNotEqual(route_key(first), route_key(resized))
        other_protocol = deepcopy(self.plan)
        other_protocol['branches'][0]['hops'][0]['pool']['protocol'] = 'v2'
        self.assertNotEqual(route_key(self.plan), route_key(other_protocol))
        exact_out = v3_plan('0x'+self.b[2:]+'0001f4'+self.a[2:], 'exact-out', 100)
        self.assertEqual(route_key(self.plan), route_key(exact_out))

    async def test_optional_baseline_coalesces_skeleton_and_rich_identity_without_mutation(self):
        provider, rpc = self.provider()
        started, finish = asyncio.Event(), asyncio.Event()
        captured = []
        async def baseline(plan, block):
            captured.append(deepcopy(plan))
            started.set()
            await finish.wait()
            return PoolBaseline(F(2), F(9995, 10000))
        provider.route_baseline.side_effect = baseline
        rich = deepcopy(self.plan)
        rich['branches'][0]['hops'][0]['pool'].update(id='observed', address='0x'+'7'*40)
        self.history.ensure_route(provider, self.plan, self.block, self.context)
        self.history.ensure_route(provider, rich, self.block, self.context)
        await started.wait()
        self.plan['branches'][0]['hops'][0]['pool']['feePips'] = 10000
        finish.set()
        while self.history.tasks:
            await asyncio.gather(*tuple(self.history.tasks.values()))
        self.assertEqual(provider.route_baseline.await_count, 1)
        self.assertEqual(captured[0]['branches'][0]['hops'][0]['pool']['feePips'], 500)
        self.assertEqual(rpc.assert_canonical.await_count, 1)
        self.assertEqual(len(self.history.baselines), 1)
        self.assertNotIn('decimals', captured[0]['branches'][0]['hops'][0]['pool']['token0'])

    async def test_legacy_ensure_pool_delegates_using_current_engine_binding(self):
        provider, _ = self.provider()
        rpc = SimpleNamespace(route_engine=provider)
        self.history.ensure_pool(rpc, '0x'+self.b[2:]+'0001f4'+self.a[2:],
            'exact-out', self.block, self.context)
        while self.history.tasks:
            await asyncio.gather(*tuple(self.history.tasks.values()))
        self.assertEqual(provider.route_baseline.await_count, 1)
        plan, block = provider.route_baseline.await_args.args
        self.assertEqual((plan['mode'], plan['tokenIn'], plan['tokenOut']), ('exactOut', self.a, self.b))
        self.assertEqual(block, self.block)
        self.assertEqual(len(self.history.baselines), 1)

    async def test_baseline_failure_is_optional_and_reorg_cannot_publish_a_model(self):
        provider, rpc = self.provider()
        provider.route_baseline.side_effect = ValueError('Optional state unavailable')
        self.history.ensure_route(provider, self.plan, self.block, self.context)
        while self.history.tasks:
            await asyncio.gather(*tuple(self.history.tasks.values()))
        self.assertFalse(self.history.baselines)
        self.history.observe(self.request, self.result, self.wave(self.plan))
        self.assertEqual(next(iter(self.history.routes.values()))['model'].points, [(100, 190)])
        provider.route_baseline.side_effect = None
        rpc.assert_canonical.side_effect = ValueError('changed canonical snapshot')
        with self.assertRaisesRegex(ValueError, 'changed canonical'):
            await self.history.acquire_route(provider, self.plan, self.block, self.context)
        self.assertFalse(self.history.baselines)
        self.assertIsNone(next(iter(self.history.routes.values()))['model'].baseline)

    async def test_known_models_include_v3_and_legacy_adapter_keeps_only_executable_routes(self):
        provider, _ = self.provider()
        pools = []
        for protocol in ('v2', 'v3', 'v4'):
            pool = deepcopy(self.plan['branches'][0]['hops'][0]['pool'])
            pool.update(protocol=protocol, id=protocol, tickSpacing=10)
            pools.append(pool)
        provider.registry.ensure_loaded = AsyncMock()
        provider.registry.inventory = {pool['id']: pool for pool in pools}
        self.history.ensure_known_routes(provider, self.request, self.block, self.context)
        while self.history.tasks:
            await asyncio.gather(*tuple(self.history.tasks.values()))
        self.assertEqual(provider.route_baseline.await_count, 3)
        self.assertEqual(len(self.history.routes), 3)
        self.assertTrue(all(not entry['model'].points for entry in self.history.routes.values()))
        legacy = {**self.request, 'adapter': '0x4edb8190232a47e45d861003672938eb7ee84a15'}
        self.assertEqual(self.history.packet(legacy)['routes'][0]['protocols'], ['v3'])

    def test_original_observation_context_survives_canonical_normalization(self):
        source = {**self.context, 'blockHash': 'source-hash', 'observedAt': 'source-time'}
        wave = self.wave(self.plan)[0]
        self.history.observe(self.request, self.result, [(*wave, source)])
        entry = next(iter(self.history.routes.values()))
        self.assertEqual(entry['observations'][0]['context'], source)
        self.assertEqual(entry['context'], self.context)
        packet = self.history.packet(self.request)
        self.assertEqual(packet['routes'][0]['points'][0]['context'], source)
        self.assertNotIn('quotes', packet)


if __name__ == '__main__':
    unittest.main()
