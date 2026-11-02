"""Covered bound proofs and ordinary/seed/exploration lifecycle behavior."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, patch

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.policy import dominated, output_upper_bound
from cybergold_candidate.quoter.ranking import prefer_completed
from cybergold_candidate.recovery_rpc import SnapshotChanged
from quoter_fixture import historical_service, historical_data, historical_route
from test_universal_quote import Engine, Quotes, request


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_bound_uses_the_exact_replay_base_despite_same_hash_registry_change(self):
        from quoter_fixture import service, synthetic_pool
        from test_universal_quote import WETH, CORE, BLOCK
        pool = synthetic_pool(WETH, CORE, 42, 'v2'); q = service(self, [pool])
        route = [{'pool': pool, 'zeroForOne': False}]
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        base = {pool['id']: deepcopy(pool)}
        q.engine.registry.observed[pool['id']]['reserve0'] = '1'
        fresh_registry_bound = output_upper_bound(q.engine.registry, request, route, BLOCK)
        replay_base_bound = output_upper_bound(q.engine.registry, request, route, BLOCK, observations=base)
        self.assertGreater(replay_base_bound, fresh_registry_bound)
        self.assertIsNone(output_upper_bound(q.engine.registry, request, route, BLOCK, observations={}))
        _, output = await q.price_path(route, 10000, BLOCK, {}, base)
        from cybergold_candidate.market_fee import quoted_fee
        self.assertGreaterEqual(replay_base_bound, output - quoted_fee(output, 1000))

    async def test_exhaustive_sdk_catalog_bound_proofs_and_pruning(self):
        # Exhaustive component proof; runtime exploration uses its clock/slots.
        for name, count in [('buy500', 39), ('buy100', 39), ('sale1', 34)]:
            q, case = historical_service(self, name)
            block = historical_data()['anchor']; best = pruned_best = None; skipped = 0
            for row in case['routes']:
                route = historical_route(q, row)
                bound = output_upper_bound(q.engine.registry, case['request'], route, block)
                value = await q.candidate(case['request'], 0, 'core-first', block, *case['basis'],
                    selected=market_plan(case['request']['inputs'][0]['currency'], case['request']['outputCurrency'],
                        route, int(case['request']['inputs'][0]['amount'])))
                self.assertEqual(value['quotedOutput'], row['output'])
                self.assertIsNotNone(bound)
                self.assertGreaterEqual(bound, int(value['quotedOutput']))
                if prefer_completed(value, best, scalar=True):
                    best = value
                if dominated(bound, pruned_best):
                    skipped += 1
                elif prefer_completed(value, pruned_best, scalar=True):
                    pruned_best = value
            self.assertEqual(len(case['routes']), count)
            self.assertEqual(pruned_best['quotedOutput'], best['quotedOutput'])
            self.assertGreater(skipped, 0)
            self.assertFalse(dominated(int(best['quotedOutput']), best))

    async def test_invalid_and_budget_ineligible_seeds_leave_ordinary_search(self):
        for seed in [{}, {'inputs': [{'currency': 'bad', 'amount': '1'}]},
                     {'inputs': [{'currency': request()['inputs'][0]['currency'], 'amount': '999999999'}], 'plan': {}}]:
            q = Quotes(Engine())
            value = await Quoter.get(q, request(), seed=seed)
            self.assertGreater(int(value['quotedOutput']), 0)
            self.assertGreater(value['metrics']['optionalSearch']['starts'], 0)

    async def test_seed_replay_error_releases_optional_work(self):
        q = Quotes(Engine()); seed = await Quoter.get(q, request())
        candidate = q.candidate
        async def unavailable(*args, **kwargs):
            if kwargs.get('selected') is not None:
                raise OSError('selected replay unavailable')
            return await candidate(*args, **kwargs)
        q.candidate = unavailable
        value = await Quoter.get(q, request(), seed=seed)
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertGreater(value['metrics']['optionalSearch']['starts'], 0)

    async def test_changed_funding_work_is_owned_and_optional_disproof_keeps_the_measured_quote(self):
        from test_quoter_plan_simulation import fixture, encoded, measured, stage, market
        from test_universal_quote import WETH, CORE
        for disproof in [False, True]:
            economic, selected = market()
            _, q, rpc, provider = fixture(encoded(measured(100000,
                stages=[stage(0, WETH, CORE, 10000, 100000, consumed=7000, returned=3000)],
                retained=[(0, 0, WETH, 3000)])))
            q.basis_reader = AsyncMock(side_effect=OSError('Optional Core construction unavailable'))
            q.discover, q.seed_routes = AsyncMock(), lambda *_: None
            entered, drained = asyncio.Event(), asyncio.Event()
            original = provider.make_request
            async def held(method, params):
                if provider.calls:
                    entered.set()
                    try:
                        if disproof:
                            raise SnapshotChanged('optional exploratory reconstruction changed')
                        await asyncio.Event().wait()
                    finally:
                        drained.set()
                return await original(method, params)
            provider.make_request = held
            task = asyncio.create_task(q.quote(economic, seed={'inputs': economic['inputs'], 'plan': selected}))
            try:
                async with asyncio.timeout(2):
                    await entered.wait()
                    if disproof:
                        value = await task
                        self.assertEqual(value['quotedOutput'], '99900')
                    else:
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertTrue(drained.is_set())
            self.assertEqual(q.engine.semaphore._value, 8)
            self.assertEqual((rpc.heads, rpc.verifications), ([], []))

    async def test_concurrent_sessions_and_cancellation_do_not_share_events(self):
        q = Quotes(Engine())
        one, two = await asyncio.gather(Quoter.get(q, request(), seed={}), Quoter.get(q, request()))
        self.assertIsNotNone(one['metrics']['optionalSearch']['randomSeed'])
        self.assertIsNone(two['metrics']['optionalSearch']['randomSeed'])
        self.assertNotIn('session', vars(q))
        q.engine.assert_canonical = AsyncMock(side_effect=AssertionError('Quote lookup cannot verify a block'))
        result = await Quoter.get(q, request(), seed={})
        self.assertGreater(int(result['quotedOutput']), 0)
        self.assertIsNotNone(result['metrics']['optionalSearch']['randomSeed'])
        q.engine.assert_canonical.assert_not_awaited()
        self.assertNotIn('session', vars(q))


if __name__ == '__main__':
    unittest.main()
