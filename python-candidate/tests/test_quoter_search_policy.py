"""Covered bound proofs and ordinary/seed/exploration lifecycle behavior."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.policy import dominated, output_upper_bound
from cybergold_candidate.quoter.ranking import prefer_completed
from cybergold_candidate.recovery_rpc import SnapshotChanged
from quoter_fixture import historical_service, historical_data, historical_route
from test_universal_quote import Engine, Quotes, request


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_exhaustive_sdk_catalog_bound_proofs_and_pruning(self):
        # Exhaustive proof allowance deliberately differs from the runtime 16.
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
            self.assertLessEqual(value['metrics']['optionalSearch']['starts'], 16)

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

    async def test_post_selection_cancellation_and_disproof_remain_fatal(self):
        import cybergold_candidate.quoter.search as search
        for disproof in [False, True]:
            q = Quotes(Engine()); entered = asyncio.Event()
            async def held(*_):
                entered.set()
                if disproof:
                    raise SnapshotChanged('reconstruction context changed')
                await asyncio.Event().wait()
            with patch.object(search, 'reconstruct', held):
                task = asyncio.create_task(Quoter.get(q, request()))
                await entered.wait()
                if disproof:
                    with self.assertRaises(SnapshotChanged):
                        await task
                else:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
            self.assertEqual(q.engine.semaphore._value, 8)
            self.assertFalse(any(row[0] == 'canonical' for row in q.engine.calls))

    async def test_concurrent_sessions_and_cancellation_do_not_share_events(self):
        q = Quotes(Engine())
        one, two = await asyncio.gather(Quoter.get(q, request(), seed={}), Quoter.get(q, request()))
        self.assertIsNotNone(one['metrics']['optionalSearch']['randomSeed'])
        self.assertIsNone(two['metrics']['optionalSearch']['randomSeed'])
        self.assertNotIn('session', vars(q))
        async def changed(_):
            raise SnapshotChanged('final context changed')
        q.engine.assert_canonical = changed
        with self.assertRaises(SnapshotChanged):
            await Quoter.get(q, request(), seed={})


if __name__ == '__main__':
    unittest.main()
