"""Ownership, lossless publication, cancellation and exact retained-state reuse."""
import asyncio
from contextlib import aclosing
from copy import deepcopy
import json
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from cybergold_candidate.prepared_values import freeze, exact_key, FrozenList
from cybergold_candidate.pool_snapshot import (PrivatePoolBank, fork_pool_bank,
    copy_pool_snapshot, merge_private_coverage)
from cybergold_candidate.quoter.bootstrap import RouteBootstrap
from cybergold_candidate.quoter.cpu import CpuWorkers
from cybergold_candidate.quoter.prepared_nomination import prepare_rows
from cybergold_candidate.quoter import prepared_nomination
from cybergold_candidate.quoter.route_tools import RouteTool, CandidateFeed
from cybergold_candidate.route_work_slots import PricingSlots
from cybergold_candidate.sdk_simulation import simulate_sdk
from cybergold_candidate.search_observations import search_observation_scope
from cybergold_candidate.uniswap_state import PoolRegistry

A, B = ('0x'+f'{n:040x}' for n in (1, 2))
BLOCK = {'number': 1, 'hash': '0x'+'ab'*32}


def rows(count=1):
    pool = {'id': A, 'address': A, 'protocol': 'v3', 'feePips': 500, 'tickSpacing': 10,
        'token0': {'address': A, 'chainId': 31338, 'decimals': 18},
        'token1': {'address': B, 'chainId': 31338, 'decimals': 6}}
    return [[{'amountIn': str(index+1), 'hops': [{'pool': pool, 'zeroForOne': True}]}]
            for index in range(count)]


class EmptyTool(RouteTool):
    name = 'prepared-control'
    def discover(self, query):
        return CandidateFeed()


class PreparedValueTests(unittest.TestCase):
    def test_equal_already_frozen_pools_are_reused_without_reconstruction(self):
        source = rows(3)
        for row in source:
            row[0]['hops'][0]['pool'] = freeze(deepcopy(row[0]['hops'][0]['pool']))
        first = source[0][0]['hops'][0]['pool']
        prepared = list(prepare_rows(source))
        self.assertTrue(all(row[0]['hops'][0]['pool'] is first for row, _ in prepared))
        self.assertTrue(all(identities is not None for _, identities in prepared))

    def test_unavailable_reuse_key_keeps_ordinary_nomination_preparation(self):
        source = rows(3)
        expected = deepcopy(source)
        with patch.object(prepared_nomination.pickle, 'dumps', side_effect=ValueError('fixture key unavailable')):
            prepared = list(prepare_rows(source))
        self.assertEqual([row for row, _ in prepared], expected)
        self.assertTrue(all(identities is not None for _, identities in prepared))

    def test_separately_copied_equal_pool_values_share_immutable_preparation(self):
        source = rows(3)
        for index, row in enumerate(source):
            row[0]['hops'][0]['pool'] = deepcopy(row[0]['hops'][0]['pool'])
            row[0]['hops'][0]['pool']['ticks'] = [{'index': 1, 'liquidityNet': '7'}]
        expected = deepcopy(source)
        prepared = list(prepare_rows(source))
        first = prepared[0][0][0]['hops'][0]['pool']
        self.assertTrue(all(row[0]['hops'][0]['pool'] is first for row, _ in prepared))
        self.assertEqual([row for row, _ in prepared], expected)
        with self.assertRaises(TypeError):
            first['ticks'][0]['liquidityNet'] = 'mutation'
        left, right = deepcopy(prepared[0][0]), deepcopy(prepared[1][0])
        left[0]['hops'][0]['pool']['ticks'][0]['liquidityNet'] = 'private'
        self.assertEqual(right[0]['hops'][0]['pool']['ticks'][0]['liquidityNet'], '7')
        self.assertEqual(first['ticks'][0]['liquidityNet'], '7')

    def test_full_pool_values_and_scalar_types_keep_distinct_preparations(self):
        source = rows(6)
        for index, row in enumerate(source):
            pool = deepcopy(row[0]['hops'][0]['pool'])
            pool['observed'] = [True, 1, 1.0, '1', {'block': 1}, {'block': 2}][index]
            row[0]['hops'][0]['pool'] = pool
        prepared = list(prepare_rows(deepcopy(source)))
        pools = [row[0]['hops'][0]['pool'] for row, _ in prepared]
        self.assertEqual(len({id(pool) for pool in pools}), len(source))
        self.assertEqual([type(pool['observed']) for pool in pools],
                         [bool, int, float, str, type(freeze({})), type(freeze({}))])
        self.assertEqual([row for row, _ in prepared], source)

    def test_pool_key_order_and_malformed_nominations_keep_ordinary_values(self):
        source = rows(3)
        original = deepcopy(source[0][0]['hops'][0]['pool'])
        source[0][0]['hops'][0]['pool'] = original
        source[1][0]['hops'][0]['pool'] = dict(reversed(list(original.items())))
        source[2][0]['hops'][0]['pool'] = {'ordinaryMalformedPool': True}
        expected = deepcopy(source)
        prepared = list(prepare_rows(source))
        self.assertEqual([row for row, _ in prepared], expected)
        left, right = (prepared[index][0][0]['hops'][0]['pool'] for index in (0, 1))
        self.assertIsNot(left, right)
        self.assertEqual(list(left), list(expected[0][0]['hops'][0]['pool']))
        self.assertEqual(list(right), list(expected[1][0]['hops'][0]['pool']))
        self.assertIsNone(prepared[2][1])

    def test_capture_and_exports_retain_independent_mutation(self):
        source = {'ticks': [{'index': 1, 'liquidityNet': '7'}], 'nested': {'a': [1]}}
        prepared = freeze(source)
        encoded = json.dumps(source, sort_keys=True)
        source['ticks'][0]['liquidityNet'] = '99'
        self.assertEqual(json.dumps(prepared, sort_keys=True), encoded)
        with self.assertRaises(TypeError):
            prepared['ticks'][0]['liquidityNet'] = 'bad'
        exported = deepcopy(prepared)
        exported['ticks'][0]['liquidityNet'] = 'private'
        exported['nested']['a'].append(2)
        self.assertEqual(prepared['ticks'][0]['liquidityNet'], '7')
        self.assertEqual(pickle.loads(pickle.dumps(prepared)), prepared)

    def test_keys_match_json_equivalence_and_preserve_relevant_changes(self):
        pairs = [({'a': [1, True]}, {'a': (1, True)}),
                 ({1: 'x'}, {'1': 'x'}), ({None: 1}, {'null': 1})]
        for left, right in pairs:
            self.assertEqual(json.dumps(left, sort_keys=True), json.dumps(right, sort_keys=True))
            self.assertEqual(exact_key(left), exact_key(right))
        self.assertNotEqual(exact_key(True), exact_key(1))
        self.assertNotEqual(exact_key(1), exact_key(1.0))
        source = {'context': {'blockHash': A}, 'ticks': [{'index': 1, 'liquidityNet': '7'}]}
        prepared = freeze(source)
        self.assertEqual(exact_key(prepared), exact_key(source))
        first = exact_key(prepared)
        self.assertIs(exact_key(prepared), first)
        source['ticks'][0]['liquidityNet'] = '8'
        self.assertNotEqual(exact_key(source), first)

    def test_private_scalars_share_coverage_but_exports_remain_mutable(self):
        source = PrivatePoolBank({A: {'liquidity': '1', 'ticks': [{'index': 1, 'liquidityNet': '7'}]}})
        left, right = fork_pool_bank(source), fork_pool_bank(source)
        self.assertIs(left[A]['ticks'], right[A]['ticks'])
        left[A]['liquidity'] = '2'
        self.assertEqual(right[A]['liquidity'], '1')
        exported = copy_pool_snapshot(left[A])
        exported['ticks'][0]['liquidityNet'] = 'private'
        self.assertEqual(right[A]['ticks'][0]['liquidityNet'], '7')
        original = left[A]['ticks']
        merge_private_coverage(left[A], right[A])
        self.assertIs(left[A]['ticks'], original)
        merge_private_coverage(left[A], {'ticks': [{'index': 2, 'liquidityNet': '8'}]})
        self.assertEqual([row['index'] for row in left[A]['ticks']], [2, 1])
        self.assertEqual(len(right[A]['ticks']), 1)


class PreparedAsyncTests(unittest.IsolatedAsyncioTestCase):
    def session(self, cpu=None):
        session = RouteBootstrap([EmptyTool()], cpu=cpu)
        session.offer_feeds(A, B, 100, BLOCK)
        entry = session._queries[A, B, 100][0]
        self.addAsyncCleanup(session.close)
        return session, entry, entry['attempt']

    async def test_worker_stream_preserves_shared_objects_and_large_frames(self):
        workers = CpuWorkers()
        self.addAsyncCleanup(workers.close)
        await workers.start()
        source = rows(130)
        source[0][0]['hops'][0]['pool']['largeMetadata'] = 'x'*100000
        expected = deepcopy(source)
        stream = workers.prepare(source)
        source[0][0]['amountIn'] = 'source changed after capture'
        result = []
        async with aclosing(stream):
            async for chunk in stream:
                self.assertLessEqual(len(chunk), 64)
                result.extend(chunk)
        self.assertEqual([value for value, _ in result], expected)
        self.assertIs(result[0][0][0]['hops'][0]['pool'], result[-1][0][0]['hops'][0]['pool'])
        self.assertEqual(workers.available.qsize(), 2)

    async def test_worker_interns_copied_pool_values_across_chunks_without_sharing_exports(self):
        workers = CpuWorkers()
        self.addAsyncCleanup(workers.close)
        await workers.start()
        source = rows(130)
        seed = source[0][0]['hops'][0]['pool']
        seed['ticks'] = [{'index': n, 'liquidityNet': str(n+7)} for n in range(400)]
        for row in source:
            row[0]['hops'][0]['pool'] = deepcopy(seed)
        expected = deepcopy(source)
        result = []
        stream = workers.prepare(source)
        source[0][0]['hops'][0]['pool']['ticks'][0]['liquidityNet'] = 'later source'
        async with aclosing(stream):
            async for chunk in stream:
                self.assertLessEqual(len(chunk), 64)
                result.extend(chunk)
        self.assertEqual([row for row, _ in result], expected)
        first = result[0][0][0]['hops'][0]['pool']
        self.assertTrue(all(row[0]['hops'][0]['pool'] is first for row, _ in result))
        left, right = deepcopy(result[0][0]), deepcopy(result[-1][0])
        left[0]['hops'][0]['pool']['ticks'][0]['liquidityNet'] = 'private export'
        self.assertEqual(right[0]['hops'][0]['pool']['ticks'][0]['liquidityNet'], '7')
        self.assertEqual(first['ticks'][0]['liquidityNet'], '7')
        self.assertEqual(workers.available.qsize(), 2)

    async def test_internal_tick_results_keep_public_hook_and_private_exports(self):
        registry = PoolRegistry(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A), rpc=SimpleNamespace(close=AsyncMock()))
        self.addAsyncCleanup(registry.close)
        state = {'id': A, 'ticks': [{'index': 1, 'liquidityNet': '7'}]}
        registry._tick_fill = AsyncMock(return_value=fork_pool_bank({A: state})[A])
        original = registry.extend_ticks
        calls = []
        async def observed(*args):
            calls.append(args)
            return await original(*args)
        registry.extend_ticks = observed
        private = await registry.private_ticks(state, [], BLOCK)
        public = await registry.extend_ticks(state, [], BLOCK)
        self.assertEqual(len(calls), 2)
        self.assertIsInstance(private['ticks'], FrozenList)
        public['ticks'][0]['liquidityNet'] = 'private caller mutation'
        self.assertEqual(private['ticks'][0]['liquidityNet'], '7')

    async def test_atomic_publication_and_cancellation_own_prepared_chunks(self):
        entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Held:
            def prepare(self, source):
                captured = pickle.loads(pickle.dumps(source))
                async def stream():
                    try:
                        yield list(prepare_rows(captured[:1]))
                        entered.set()
                        await release.wait()
                        yield list(prepare_rows(captured[1:]))
                    finally:
                        closed.set()
                return stream()
        session, entry, attempt = self.session(Held())
        task = asyncio.create_task(session._prepare_and_publish(rows(2), entry, attempt))
        await entered.wait()
        self.assertEqual(entry['offers'], [])
        self.assertFalse(session._known_offers or session._offer_origins)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(closed.is_set())
        self.assertEqual(entry['offers'], [])
        self.assertEqual(attempt['batches'], 0)
        release.set()
        await session._prepare_and_publish(rows(2), entry, attempt)
        self.assertEqual(len(entry['offers']), 2)
        self.assertEqual(len(set(entry['offer_revisions'])), 1)

    async def test_cancelled_transfer_retires_only_its_worker_and_reuses_capacity(self):
        workers = CpuWorkers()
        self.addAsyncCleanup(workers.close)
        await workers.start()
        before = {worker.process.pid for worker in workers.workers}
        stream = workers.prepare(rows(1000))
        first = await anext(stream)
        self.assertEqual(len(first), 64)
        await stream.aclose()
        survivors = {worker.process.pid for worker in workers.workers if worker.process is not None}
        self.assertEqual(len(survivors & before), 1)
        self.assertFalse(workers.jobs)
        self.assertEqual(workers.available.qsize(), 2)
        async with aclosing(workers.prepare(rows(1))) as following:
            self.assertEqual(len(await anext(following)), 1)

    async def test_ready_continuation_runs_and_sibling_origins_are_not_lost(self):
        session, entry, attempt = self.session()
        source = rows(130)
        sibling = {'branches': deepcopy(source[-1]), 'origins': ['sibling']}
        task = asyncio.create_task(session._prepare_and_publish(source, entry, attempt))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        session._remember_offer((A, B, 100), sibling)
        await task
        identity = session._nomination_identity(sibling['branches'], lots=False)
        self.assertEqual(session._offer_origins[A, B][identity], {'sibling', attempt['provider']})
        self.assertEqual([offer['branches'] for offer in entry['offers']], source)

    async def test_unchanged_duplicate_reads_do_not_starve_batch_registration(self):
        session, entry, attempt = self.session()
        source = rows(130)
        duplicate = {'branches': deepcopy(source[0]), 'origins': [attempt['provider']]}
        session._remember_offer((A, B, 100), duplicate)
        stopped = False
        async def repeats():
            while not stopped:
                session._remember_offer((A, B, 100), duplicate)
                await asyncio.sleep(0)
        task = asyncio.create_task(repeats())
        try:
            await asyncio.wait_for(session._prepare_and_publish(source, entry, attempt), 1)
            self.assertEqual(len(entry['offers']), 130)
        finally:
            stopped = True
            await task

    async def test_cache_hit_does_not_traverse_frozen_coverage_and_mutations_miss(self):
        calls = []
        class Sdk:
            async def request(self, payload):
                calls.append(deepcopy(payload))
                return {'amountOut': '7'}
        pool = freeze({'liquidity': '1', 'ticks': [{'index': n, 'liquidityNet': '7'} for n in range(1000)]})
        engine = SimpleNamespace(sdk=Sdk(), semaphore=PricingSlots(8))
        payload = {'amount': '1', 'pools': [dict(pool)]}
        async with search_observation_scope():
            first = await simulate_sdk(engine, payload)
            with patch.object(FrozenList, '__iter__', side_effect=AssertionError('unchanged coverage traversed')):
                second = await simulate_sdk(engine, payload)
            self.assertEqual(await simulate_sdk(engine, deepcopy(payload)), first)
            self.assertEqual(first, second)
            second['amountOut'] = 'private'
            payload['pools'][0]['liquidity'] = '2'
            await simulate_sdk(engine, payload)
            payload['amount'] = '2'
            await simulate_sdk(engine, payload)
            payload['pools'][0]['ticks'] = [{'index': 1, 'liquidityNet': 'changed'}]
            await simulate_sdk(engine, payload)
        self.assertEqual(len(calls), 4)
        self.assertEqual(engine.semaphore._value, 8)


if __name__ == '__main__':
    unittest.main()
