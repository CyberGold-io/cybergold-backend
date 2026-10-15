"""Experimental sharing lifetimes, cancellation and exact-result invariants."""
from legacy_quote_wire_fixture import SharingQuoterRpc
import asyncio
from copy import deepcopy
from fractions import Fraction as F
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from web3 import AsyncWeb3

from cybergold_candidate.quote_experiments import BasketMath, GrossSeeds, IntentSharing, bracket_step, midpoint_step, ceil_scale_step, upper_secant_step, local_secant_step
from cybergold_candidate.quote_correction import delayed_local_step
from cybergold_candidate.quote_intent import QuoteIntent
from cybergold_candidate.quote_models import LegModel, PoolBaseline, hybrid_legs
from cybergold_candidate.quote_history import QuoteHistory
from cybergold_candidate.route_search import RouteSearch
from test_quote_intent import Provider, QuoteWire, SETTINGS, request, service


class Experiments(unittest.IsolatedAsyncioTestCase):
    async def test_generation_retires_only_old_models_waiting_in_http_queue(self):
        from cybergold_candidate.quote_intent import handle_quote_intent
        history = QuoteHistory(SETTINGS)
        await history.observe_generation('old')
        entered, release = asyncio.Event(), asyncio.Event()
        async def get(_request, update):
            await update({'type': 'progress', 'stage': 'fixture'})
            await update({'type': 'model', 'value': {'protocol': {'old': True}}})
            entered.set()
            await release.wait()
            return {'exact': True}
        service = SimpleNamespace(history=history, get=get)
        response = await handle_quote_intent(SimpleNamespace(json=AsyncMock(return_value=request('issue-exact-out'))), service)
        stream = response.body_iterator
        self.assertEqual(json.loads(await anext(stream))['type'], 'progress')
        await entered.wait()
        await history.observe_generation('new')
        release.set()
        frames = [json.loads(frame) async for frame in stream]
        self.assertEqual(frames, [{'type': 'complete', 'value': {'exact': True}}])

    async def test_subscriber_suppresses_exact_model_replay_without_ordering_independent_revisions(self):
        intent, provider, routes, _ = service(); self.addAsyncCleanup(routes.close)
        class History:
            epoch = 0
            def packet(self, request): return {'revision': 5, 'whole': []}
        intent.history = History()
        async def get(request, update, *, block=None, model_epoch=None):
            await update({'type':'model','value':{'revision':5,'whole':[]}})
            await update({'type':'model','value':{'revision':1,'whole':[{'display':'1'}]}})
            return {'result':True}
        intent.get = get
        shared = IntentSharing(intent)
        frames = []
        result = await shared.get(request('issue-exact-out'), lambda frame: asyncio.sleep(0,result=frames.append(frame)))
        self.assertTrue(result['result'])
        self.assertEqual([f['value']['revision'] for f in frames], [5,1])

    async def test_generation_retires_shared_model_replay_and_queued_delivery_only(self):
        intent, provider, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        history = QuoteHistory(SETTINGS)
        await history.observe_generation('old')
        intent.history = history
        entered, release, slow, drain = (asyncio.Event() for _ in range(4))
        producer_epochs = []
        async def produce(_request, update, *, block=None, model_epoch=None):
            producer_epochs.append(model_epoch)
            await update({'type': 'progress', 'stage': 'fixture'})
            await update({'type': 'model', 'value': {'revision': 1, 'protocol': {'old': True}}})
            entered.set()
            await release.wait()
            await update({'type': 'qualified', 'value': {'exact': True}})
            return {'exact': True}
        intent.get = produce
        shared = IntentSharing(intent)
        self.addAsyncCleanup(shared.close)
        one_frames, two_frames = [], []
        async def consume_one(frame):
            if frame['type'] == 'progress':
                slow.set()
                await drain.wait()
            one_frames.append(frame)
        one = asyncio.create_task(shared.get(request('issue-exact-out'), consume_one))
        await entered.wait()
        await slow.wait()
        await history.observe_generation('new')
        one_frames.clear()
        two = asyncio.create_task(shared.get(request('issue-exact-out'),
            lambda frame: asyncio.sleep(0, result=two_frames.append(frame))))
        while not shared.joined:
            await asyncio.sleep(0)
        drain.set()
        release.set()
        self.assertEqual(await one, {'exact': True})
        self.assertEqual(await two, {'exact': True})
        self.assertEqual(shared.started, 1)
        self.assertEqual(producer_epochs, [1])
        self.assertFalse([frame for frame in one_frames if frame['type'] == 'model'])
        self.assertFalse([frame for frame in two_frames if frame['type'] == 'model' and frame['value'].get('protocol')])
        self.assertTrue(any(frame['type'] == 'qualified' for frame in two_frames))
    async def test_identical_intents_join_replay_cancel_independently_and_do_not_retain(self):
        intent, provider, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        provider.finish_final = asyncio.Event()
        shared = IntentSharing(intent)
        self.addAsyncCleanup(shared.close)
        one = asyncio.create_task(shared.get(request('issue-exact-out'), lambda e: asyncio.sleep(0)))
        await provider.final_started.wait()
        frames = []
        two = asyncio.create_task(shared.get(request('issue-exact-out'), lambda e: asyncio.sleep(0, result=frames.append(e))))
        for _ in range(100):
            if shared.joined:
                break
            await asyncio.sleep(.001)
        one.cancel()
        await asyncio.gather(one, return_exceptions=True)
        provider.finish_final.set()
        result = await two
        self.assertTrue(frames)
        self.assertEqual(shared.started, 1)
        self.assertEqual(result['mode'], 'issue-exact-out')
        await shared.get(request('issue-exact-out'), lambda e: asyncio.sleep(0))
        self.assertEqual(shared.started, 2)
        self.assertFalse(shared.pending)

    async def test_deadline_distinction_and_last_disconnect(self):
        intent, provider, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        provider.finish_final = asyncio.Event()
        shared = IntentSharing(intent)
        self.addAsyncCleanup(shared.close)
        a, b = request('issue-exact-out'), request('issue-exact-out')
        b['deadline'] = str(int(a['deadline'])+1)
        jobs = [asyncio.create_task(shared.get(r, lambda e: asyncio.sleep(0))) for r in (a,b)]
        await provider.final_started.wait()
        for _ in range(100):
            if shared.started == 2:
                break
            await asyncio.sleep(.001)
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        self.assertEqual(shared.started, 2)
        self.assertFalse(shared.pending)

    async def test_quoter_overlap_counts_and_no_completed_reuse(self):
        provider, wire = Provider(), QuoteWire()
        rpc = SharingQuoterRpc(SETTINGS, AsyncWeb3(provider), httpx.AsyncClient(transport=httpx.MockTransport(wire.send)))
        self.addAsyncCleanup(rpc.close)
        wire.hold = asyncio.Event()
        original = wire.send
        async def held(req):
            await wire.hold.wait()
            return await original(req)
        await rpc.client.aclose()
        rpc.client = httpx.AsyncClient(transport=httpx.MockTransport(held))
        data = rpc.encode({'mode': 'exact-in', 'path': '0x'+'1'*40+'0001f4'+'2'*40, 'amount': '10'})
        block = {'hash':'0x'+'a'*64, 'number':101}
        jobs = [asyncio.create_task(rpc.quote_batch('exact-in', [data], block)) for _ in range(3)]
        await asyncio.sleep(.01)
        wire.hold.set()
        values = await asyncio.gather(*jobs)
        self.assertEqual(values[0], values[1])
        self.assertEqual(rpc.counts['issued'], 1)
        self.assertEqual(rpc.counts['coalesced'], 2)
        await rpc.quote_batch('exact-in', [data], block)
        self.assertEqual(rpc.counts['issued'], 2)

    async def test_basket_ttl_original_age_failure_and_sandbox(self):
        clock = [0]
        cache = BasketMath(now=lambda: clock[0])
        self.addAsyncCleanup(cache.close)
        calls = []
        async def read():
            calls.append(1)
            return {'grossCygldIn': '10'}
        args = (1, {'hash':'abc'}, 'helpers', 'data', read)
        await cache.read(*args)
        clock[0] = 9
        await cache.read(*args)
        clock[0] = 10
        await cache.read(*args)
        self.assertEqual(len(calls), 2)
        await cache.read(31338, *args[1:])
        await cache.read(31338, *args[1:])
        self.assertEqual(len(calls), 4)
        async def fail():
            raise ValueError('ordinary failure')
        for _ in range(2):
            with self.assertRaises(ValueError):
                await cache.read(1, {'hash':'changed'}, 'helpers', 'data', fail)

    async def test_completed_quoter_math_excludes_failure_and_sandbox(self):
        provider, wire = Provider(), QuoteWire()
        rpc = SharingQuoterRpc(SETTINGS,AsyncWeb3(provider),httpx.AsyncClient(transport=httpx.MockTransport(wire.send)),completed=True)
        self.addAsyncCleanup(rpc.close)
        data = rpc.encode({'mode':'exact-in','path':'0x'+'1'*40+'0001f4'+'2'*40,'amount':'10'})
        block = {'hash':'0x'+'a'*64,'number':101}
        await rpc.quote_batch('exact-in',[data],block)
        await rpc.quote_batch('exact-in',[data],block)
        self.assertEqual(rpc.counts['issued'],1)
        self.assertEqual(rpc.counts['reused'],1)
        rpc.chain_id = 31338
        await rpc.quote_batch('exact-in',[data],block)
        await rpc.quote_batch('exact-in',[data],block)
        self.assertEqual(rpc.counts['issued'],3)
        rpc.chain_id = 1
        for key,(_,value) in list(rpc.completed_quotes.items()):
            rpc.completed_quotes[key] = (time.monotonic()-11,value)
        await rpc.quote_batch('exact-in',[data],block)
        self.assertEqual(rpc.counts['issued'],4)
        await rpc.client.aclose()
        async def failure(_):
            return httpx.Response(200,json=[{'jsonrpc':'2.0','id':0,'error':{'code':3,'message':'fixture'}}])
        rpc.client = httpx.AsyncClient(transport=httpx.MockTransport(failure))
        other = rpc.encode({'mode':'exact-in','path':'0x'+'1'*40+'0001f4'+'2'*40,'amount':'20'})
        for _ in range(2):
            self.assertEqual((await rpc.quote_batch('exact-in',[other],block))[0]['status'],'failure')
        self.assertEqual(rpc.counts['issued'],6)

    async def test_neighbors_keep_exact_interval_and_fallback_budget(self):
        intent, _, routes, _ = service()
        self.addAsyncCleanup(routes.close)
        seeds = GrossSeeds()
        intent.seeds = seeds
        first = await intent.get(request('redeem-exact-out'), lambda e: asyncio.sleep(0))
        new = deepcopy(request('redeem-exact-out'))
        new['amount'] = str(int(new['amount'])+2)
        for target in new['targets']:
            target['amount'] = str(int(target['amount'])+1)
        result = await intent.get(new, lambda e: asyncio.sleep(0))
        self.assertIsNone(result['initialPreview'])
        self.assertGreaterEqual(int(result['preview']['minimumAmountOut']), int(new['amount']))
        self.assertLess(result['metrics']['candidateCalls'], first['metrics']['candidateCalls'])
        class BadSeed:
            def suggest(self, *_): return 2000
            def observe(self, *_): pass
        intent.seeds = BadSeed()
        correction_calls = [0]
        def bad_first_trial(points, target, proposed):
            correction_calls[0] += 1
            return 2000 if correction_calls[0] <= 1 else proposed
        intent.correction = bad_first_trial
        result = await intent.get(new, lambda e: asyncio.sleep(0))
        self.assertIsNotNone(result['initialPreview'])  # Exactly one legacy fallback.
        self.assertGreaterEqual(result['metrics']['iterations'], 1)
        self.assertLessEqual(result['metrics']['iterations'], 10)
        self.assertGreaterEqual(int(result['preview']['minimumAmountOut']),int(new['amount']))

    def test_models_keep_rate_fee_impact_distinct_and_round_inverse(self):
        baseline = PoolBaseline(F(2), F(99,100), F(1,10000))
        model = LegModel([(100,196),(1000,1801)], baseline)
        predicted = model.predict(300, 'anchored')
        self.assertGreater(predicted, 0)
        inverse = model.predict(predicted, 'anchored', True)
        self.assertGreater(inverse, 0)
        model.observe(50, 80)
        self.assertEqual(model.retired, 2)  # Lower size contradicted older impact.
        self.assertEqual(model.baseline, baseline)
        self.assertIsNone(model.predict(1000000000,'local',True))
        self.assertEqual(bracket_step([(100,90),(200,190)],150,170),160)
        self.assertEqual(midpoint_step([(10000,9900)],10000,10101),10151)
        rebased = model.rebased(PoolBaseline(F(4),F(99,100)))
        self.assertEqual(rebased.points,[(50,160)])
        mixed = hybrid_legs([50,50],[model,model],{0:80})
        self.assertEqual(mixed[0],80)
        self.assertGreater(mixed[1],0)
        model.observe(50,90)
        model.observe(0,0)
        self.assertEqual([p for p in model.points if p[0]==50],[(50,90)])


def evaluate_correction(curve, target, seed, correction=None):
    """Exercise the accepted output interval and eleven-forward-check budget."""
    gross, points = seed, []
    upper = (target*101+99)//100
    for iteration in range(11):
        quoted = curve(gross)
        points.append((gross, quoted))
        if target <= quoted <= upper:
            return points, True
        if iteration == 10 or quoted <= 0 or gross <= 0:
            break
        proposed = gross*target//quoted
        proposed = proposed if proposed != gross else gross+(1 if quoted < target else -1)
        gross = correction(points, target, proposed) if correction else proposed
    return points, False


class UpperQuoteCorrection(unittest.TestCase):
    def test_delayed_correction_preserves_fast_results_and_fixes_stalled_quantities(self):
        for curve, target, seed in ((lambda g: g*2, 100, 100), (lambda g: g, 100, 101),
                                    (lambda g: g*3//2, 100, 90)):
            ordinary = evaluate_correction(curve, target, seed)
            self.assertLessEqual(len(ordinary[0]), 3)
            self.assertEqual(evaluate_correction(curve, target, seed, delayed_local_step), ordinary)
        curve = lambda g: 291246*g//1000000+14736*(g//77836)
        ordinary, ordinary_valid = evaluate_correction(curve, 1317000, 2802115)
        corrected, valid = evaluate_correction(curve, 1317000, 2802115, delayed_local_step)
        self.assertFalse(ordinary_valid)
        self.assertTrue(valid)
        self.assertEqual(corrected[:3], ordinary[:3])
        self.assertLess(len(corrected), len(ordinary))

    def test_delayed_correction_handles_unattainable_plateaus_switching_routes_and_abi_overflow(self):
        for curve, target, seed in ((lambda g: g//100*100, 1, 100), (lambda g: 17, 100, 1000)):
            _, valid = evaluate_correction(curve, target, seed, delayed_local_step)
            self.assertFalse(valid)
        self.assertEqual(delayed_local_step([(1, 1), (2, 2), (3, 3)], 2**256, 4), 4)

    def test_local_slope_handles_unchanged_coarse_basket_quantity(self):
        # The upper has 36 units of asset 2; subsequent lower points have 35.
        # Average output/gross includes this locally fixed leg, while the paid
        # local slope describes asset 1's response to an increased gross.
        curve = lambda g: 291246*g//1000000+14736*(g//77836)
        target, seed = 1317000, 2802115
        legacy, legacy_valid = evaluate_correction(curve, target, seed)
        corrected, corrected_valid = evaluate_correction(curve, target, seed, local_secant_step)
        _, bracket_valid = evaluate_correction(curve, target, seed, upper_secant_step)
        self.assertFalse(legacy_valid)
        self.assertEqual(len(legacy), 11)
        self.assertFalse(bracket_valid)  # Whole bracket spans the coarse step.
        self.assertTrue(corrected_valid)
        self.assertLess(len(corrected), len(legacy))
        self.assertLessEqual(len(corrected), 11)
        self.assertEqual([g//77836 for g, _ in corrected], [36, 35, 35, 35, 35])
        self.assertGreaterEqual(corrected[-1][1], target)
        self.assertLessEqual(corrected[-1][1], (target*101+99)//100)
        # Rounding recovery near target, not a policy aiming at +0.5%.
        self.assertLess(corrected[-1][1]-target, target//10000)

    def test_ceiling_recovers_integer_edge_without_midpoint_spend(self):
        curve = lambda g: ((g-g*321//1000000)//10**12)*997//1000*99//100
        target, seed = 10000, 10034891200075223
        legacy, legacy_valid = evaluate_correction(curve, target, seed)
        corrected, corrected_valid = evaluate_correction(curve, target, seed, ceil_scale_step)
        self.assertTrue(legacy_valid and corrected_valid)
        self.assertLess(len(corrected), len(legacy))
        self.assertEqual(corrected[-1][1], target)
        self.assertLess(corrected[-1][0], legacy[-1][0])

    def test_unattainable_integer_output_is_never_accepted(self):
        # No gross produces target 1..2: outputs are multiples of 100.
        for correction in (None, ceil_scale_step, upper_secant_step, local_secant_step):
            with self.subTest(correction=correction):
                points, valid = evaluate_correction(lambda g: g//100*100, 1, 100, correction)
                self.assertFalse(valid)
                self.assertLessEqual(len(points), 11)

    def test_upper_model_does_not_certify_convex_or_switching_routes(self):
        # A tested upper cannot certify a smaller proposal after a shape change.
        proposed = ceil_scale_step([(64, 4096)], 1024, 16)
        self.assertLess(proposed*proposed, 1024)
        points, valid = evaluate_correction(lambda g: g*g, 1024, 64, local_secant_step)
        self.assertTrue(valid)
        self.assertEqual(points[-1][1], 1024)
        self.assertGreater(len(points), 2)
        # An envelope of concave routes need not be concave between endpoints.
        curve = lambda g: max(100*g//(1+g), 2*g)
        observed = [(25, curve(25)), (100, curve(100))]
        for correction in (upper_secant_step, local_secant_step):
            proposed = correction(observed, 150, 75)
            self.assertLess(curve(proposed), 150)

    def test_degenerate_outputs_keep_ordinary_bounded_failure(self):
        for correction in (ceil_scale_step, upper_secant_step, local_secant_step):
            with self.subTest(correction=correction):
                points, valid = evaluate_correction(lambda g: 17, 100, 1000, correction)
                self.assertFalse(valid)
                self.assertEqual(len(points), 11)

    def test_large_integer_units_remain_exact_without_float_conversion(self):
        quantum, target = 10**30, 2**100
        curve = lambda g: (g//quantum)*997//1000
        root_hint = ((target*1000+996)//997)*quantum
        for correction in (ceil_scale_step, upper_secant_step, local_secant_step):
            points, valid = evaluate_correction(curve, target, root_hint*99//100, correction)
            self.assertTrue(valid)
            gross, quoted = points[-1]
            self.assertIsInstance(gross, int)
            self.assertIsInstance(quoted, int)
            self.assertGreater(gross, 2**128)
            self.assertGreaterEqual(quoted, target)
            self.assertLessEqual(quoted, (target*101+99)//100)


if __name__ == '__main__':
    unittest.main()
