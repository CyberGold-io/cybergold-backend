"""Captured Helpers parity, organic learning, optional-task lifetime and history."""
import asyncio
from copy import deepcopy
from fractions import Fraction as F
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
from web3 import Web3

from cybergold_candidate.basket_arithmetic import BasketArithmetic, wire
from cybergold_candidate.quote_history import QuoteHistory, economic_path
from cybergold_candidate.quote_cache import VerifiedGrossSeed, IntentSharing
from cybergold_candidate.quote_intent import QuoteIntent
from cybergold_candidate.quote_models import PoolBaseline
from cybergold_candidate.pool_producer import ABI as POOL_ABI
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
        contract = SimpleNamespace(encode_abi=Mock(return_value='0x'))
        rpc = SimpleNamespace(assert_canonical=AsyncMock(),
            w3=SimpleNamespace(codec=SimpleNamespace(decode=Mock(side_effect=[('0x'+'7'*40,),
                (2**96, 0, 0, 0, 0, 0, False), (1_000_000,)]))),
            pool_batch=AsyncMock(side_effect=[([{'result': '0x'}], {'issued': 1}),
                ([{'result': '0x'}, {'result': '0x'}], {'issued': 2})]),
            pools=SimpleNamespace(factory='0x'+'6'*40, pool_contracts={'factory': contract, 'pool': contract}))
        tokens = [request('issue-exact-in')['quoteToken'].lower(), request('issue-exact-in')['orderedAssets'][0].lower()]
        await history.acquire_pool(rpc, tokens, [500], {'hash': 'hash'}, context, (tuple(tokens), (500,), 'hash'), epoch)
        self.assertFalse(history.baselines)

    async def test_reset_retires_foreground_models_without_canceling_exact_quote(self):
        intent, provider, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        history = QuoteHistory(SETTINGS)
        self.addAsyncCleanup(history.close)
        await history.observe_generation('old')
        intent.history = history
        history.acquire_state = AsyncMock()
        history.acquire_pool = AsyncMock()
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
        history.acquire_pool = AsyncMock()
        models = []
        async def update(frame):
            if frame['type'] == 'model':
                models.append(frame)
                if len(models) == 2:
                    await history.observe_generation('new')
        result = await intent.get(request('issue-exact-in'), update)
        self.assertEqual(result['displayAmount'], '200')
        self.assertFalse(history.families)
        self.assertFalse(history.tasks)
        history.acquire_state.assert_not_called()
        history.acquire_pool.assert_not_called()

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

    async def test_pool_baseline_uses_real_factory_abi_checksums_and_batched_state(self):
        history = QuoteHistory(SETTINGS)
        w3 = Web3()
        contracts = {key: w3.eth.contract(abi=value) for key, value in POOL_ABI.items()}
        async def pool_batch(calls, _block, counts):
            counts['issued'] = len(calls)
            rows = []
            for _, data in calls:
                for contract in contracts.values():
                    try:
                        function, _ = contract.decode_function_input(data)
                        break
                    except ValueError:
                        continue
                outputs = function.abi['outputs']
                if function.fn_name == 'getPool':
                    values = ['0x'+'7'*40]
                elif function.fn_name == 'liquidity':
                    values = [1_000_000]
                else:
                    values = [2**96] + [False if output['type'] == 'bool' else 0 for output in outputs[1:]]
                rows.append({'result': '0x'+w3.codec.encode([output['type'] for output in outputs], values).hex()})
            return rows, counts
        async def canonical(_):
            pass
        rpc = SimpleNamespace(w3=w3, pool_batch=pool_batch, assert_canonical=canonical,
                              pools=SimpleNamespace(factory='0x'+'6'*40, pool_contracts=contracts))
        tokens = [request('issue-exact-in')['quoteToken'].lower(), request('issue-exact-in')['orderedAssets'][0].lower()]
        context = {'chainId': 1, 'blockNumber': '1', 'blockHash': 'hash', 'observedAt': 'now'}
        key = (tuple(tokens), (500,), 'hash')
        await history.acquire_pool(rpc, tokens, [500], {'hash': 'hash'}, context, key)
        self.assertEqual(history.baselines[key][0].exchange, F(1))
        self.assertEqual(history.baselines[key][0].fee_retention, F(9995,10000))
        self.assertEqual(history.reads, 3)
        self.assertEqual(history.envelopes, 2)

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
        history.acquire_pool = optional
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
        key = (tuple(tokens), tuple(fees), 'hash')
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


if __name__ == '__main__':
    unittest.main()
