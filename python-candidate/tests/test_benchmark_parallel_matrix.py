"""Benchmark integrity: real acquisition, independent counts and failed pairs."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import unittest

from cybergold_candidate.route_observations import RouteObservations, route_observation_scope
from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.rpc_transport import rpc_provider
from benchmark_matrix_fixture import BLOCK, MatrixService, LoopbackState, matrix_cases
from benchmark_parallel_matrix import difference, selected_request, selected_topology, summary


ROOT = Path(__file__).resolve().parents[2]
NODE = os.environ.get('CYBERGOLD_TEST_NODE', 'node')


class MatrixAcquisitionTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self, case):
        transport = await LoopbackState(case.pools).start()
        self.addAsyncCleanup(transport.close)
        service = MatrixService(case, transport, NODE, ROOT)
        self.addAsyncCleanup(service.close)
        return service, transport

    async def test_actual_loopback_v2_v3_v4_getters_and_tick_coverage_match_source(self):
        case = next(row for row in matrix_cases() if row.name == 'market-split-capacity')
        service, transport = await self.fixture(case)
        recorder = RouteObservations()
        with route_observation_scope(recorder):
            for expected in case.pools:
                pool = service.registry.inventory[expected['id']]
                observed = await service.registry.snapshot(pool, BLOCK)
                if pool['protocol'] == 'v2':
                    self.assertEqual(observed['reserve0'], expected['reserve0'])
                    self.assertEqual(observed['reserve1'], expected['reserve1'])
                else:
                    self.assertEqual(observed['sqrtRatioX96'], expected['sqrtRatioX96'])
                    self.assertEqual(observed['liquidity'], expected['liquidity'])
                    covered = await service.registry.extend_ticks(observed, [{
                        'wordPositions': [-1, 0], 'ticks': [-60, 60]}], BLOCK)
                    self.assertEqual(sorted(covered['ticks'], key=lambda row: row['index']), expected['ticks'])
                    words = {row['wordPosition']: row['bitmap'] for row in expected['bitmapWords']}
                    self.assertEqual({row['wordPosition']: row['bitmap'] for row in covered['bitmapWords']},
                                     {word: words[word] for word in (-1, 0)})
                count = recorder.metrics['requests']
                # Registry same-hash canonical observations and typed getter
                # caches remove real HTTP; this is not a fabricated RPC count.
                self.assertEqual(await service.registry.snapshot(pool, BLOCK),
                                 service.registry.observation(pool))
                self.assertEqual(recorder.metrics['requests'], count)
        self.assertGreater(recorder.metrics['requests'], 0)
        self.assertEqual(recorder.metrics['requests'], transport.counts()['httpEnvelopes'])
        self.assertEqual(recorder.metrics['jsonRpcMembers'], transport.counts()['jsonRpcMembers'])
        self.assertEqual(transport.counts()['rejectedMembers'], 0)
        self.assertEqual(transport.counts()['unsupported'], {})

    async def test_full_core_acquisitions_replay_shared_physical_state(self):
        case = next(row for row in matrix_cases() if row.name == 'core-shared-acquisition')
        service, transport = await self.fixture(case)
        assets, weights = await service.quoter.basis(BLOCK)
        value = await service.quoter.candidate(deepcopy(case.request), 50, 'core-first', BLOCK,
                                               assets, weights, first=True)
        topology = selected_topology(value)
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(value['routeFamily'], 'mixed')
        self.assertGreater(service.preview_calls, 0)
        self.assertTrue(topology['sharedPhysicalPools'])
        replay = await service.quoter.evaluate_selected(case.request, value['plan'])
        self.assertEqual(replay['quotedOutput'], value['quotedOutput'])
        self.assertEqual(transport.counts()['unsupported'], {})

    async def test_full_native_market_candidate_uses_v4_and_replays(self):
        case = next(row for row in matrix_cases() if row.name == 'market-native-v4')
        service, transport = await self.fixture(case)
        assets, weights = await service.quoter.basis(BLOCK)
        value = await service.quoter.candidate(deepcopy(case.request), 0, 'core-first', BLOCK,
                                               assets, weights, first=True)
        self.assertEqual(value['routeFamily'], 'market')
        self.assertGreater(int(value['quotedOutput']), 0)
        replay = await service.quoter.evaluate_selected(case.request, value['plan'])
        self.assertEqual(replay['quotedOutput'], value['quotedOutput'])
        self.assertGreater(transport.counts()['getterCalls']['getSlot0(bytes32)'], 0)
        self.assertEqual(transport.counts()['unsupported'], {})

    async def test_lower_funded_selected_plan_replays_declared_acquisition(self):
        case = next(row for row in matrix_cases() if row.name == 'market-two-hop')
        service, _ = await self.fixture(case)
        funded = deepcopy(case.request)
        funded['inputs'][0]['amount'] = '3000'
        assets, weights = await service.quoter.basis(BLOCK)
        value = await service.quoter.candidate(funded, 0, 'core-first', BLOCK,
                                               assets, weights, first=True)
        self.assertLess(int(value['inputs'][0]['amount']), int(case.request['inputs'][0]['amount']))
        with self.assertRaisesRegex(InvalidPreview, 'Selected allocations do not match declared funding'):
            await service.quoter.evaluate_selected(case.request, value['plan'])
        request = selected_request({**case.request, 'benchmarkMetadata': 'retained'}, value)
        self.assertEqual(request['benchmarkMetadata'], 'retained')
        self.assertEqual(request['inputs'], value['inputs'])
        replay = await service.quoter.evaluate_selected(request, value['plan'])
        self.assertEqual(replay['quotedOutput'], value['quotedOutput'])
        self.assertEqual(value['fees'].keys(), {'coreProtocolFeeCygld', 'coreHelpersFeeCygld', 'marketFeeCygld'})

    async def test_received_members_are_counted_before_delay_and_caller_cancellation(self):
        case = next(row for row in matrix_cases() if row.name == 'market-narrow-prefix')
        transport = await LoopbackState(case.pools, delay_ms=100).start()
        self.addAsyncCleanup(transport.close)
        provider = rpc_provider(transport.url)
        self.addAsyncCleanup(provider.disconnect)
        recorder = RouteObservations()
        pool = case.pools[0]
        with route_observation_scope(recorder):
            task = asyncio.create_task(provider.make_request('eth_call', [
                {'to': pool['address'], 'data': '0x0902f1ac'},
                {'blockHash': BLOCK['hash'], 'requireCanonical': True}]))
            async with asyncio.timeout(1):
                while transport.counts()['httpEnvelopes'] == 0:
                    await asyncio.sleep(0)
            # The HTTP body has been received, but its getter is still waiting
            # behind this fixture's declared transport latency.
            self.assertEqual(transport.counts()['jsonRpcMembers'], 1)
            self.assertEqual(transport.counts()['methods'], {'eth_call': 1})
            self.assertEqual(transport.counts()['getterCalls'], {})
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(recorder.metrics['requests'], transport.counts()['httpEnvelopes'])
        self.assertEqual(recorder.metrics['jsonRpcMembers'], transport.counts()['jsonRpcMembers'])
        self.assertEqual(recorder.metrics['cancelled'], 1)

    async def test_narrow_concentrated_anchor_selects_smaller_funded_prefix_and_replays(self):
        case = next(row for row in matrix_cases() if row.name == 'market-narrow-prefix')
        service, transport = await self.fixture(case)
        value = await service.quoter.get(deepcopy(case.request))
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertLess(int(value['inputs'][0]['amount']), int(case.request['inputs'][0]['amount']))
        self.assertEqual(value['searchCoverage']['selectedPhase'], 'backward-prefix')
        self.assertGreater(transport.counts()['getterCalls']['tickBitmap(int16)'], 0)
        replay = await service.quoter.evaluate_selected(selected_request(case.request, value), value['plan'])
        self.assertEqual(replay['quotedOutput'], value['quotedOutput'])
        self.assertEqual(transport.counts()['unsupported'], {})


class MatrixSummaryTests(unittest.TestCase):
    def row(self, strategy, *, status='completed', output='100', repeat=1, wall=1):
        return {'case': 'fixture', 'cacheMode': 'cold', 'repeat': repeat, 'strategy': strategy,
                'status': status, 'netOutput': output,
                'funding': [{'currency': '0x'+'11'*20, 'amount': '100'}],
                'samePinnedStateSha256': 'synthetic', 'canonicalCacheBefore': {'observations': 0},
                'wallToResultMs': wall, 'metrics': {'timeToFirstWholePlanMs': 1,
                    'routeDiscovery': {'physicalRpc': {'requests': 2, 'jsonRpcMembers': 3}}},
                'serverRpc': {'httpEnvelopes': 2}}

    def test_failed_attempts_stay_in_pairs_transport_and_wall_denominators(self):
        rows = [self.row('custom-only', repeat=1), self.row('parallel', repeat=1, output='110'),
                self.row('custom-only', repeat=2), self.row('parallel', repeat=2, status='failed', wall=15)]
        result = summary(rows)
        self.assertEqual(result['attemptedPairs'], 2)
        self.assertEqual(result['pairedOutcomes'], {'improved': 1, 'baseline-only': 1})
        parallel = result['allStrategies']['parallel']
        self.assertEqual(parallel['attempted'], 2)
        self.assertEqual(parallel['completed'], 1)
        self.assertEqual(parallel['completionRate'], .5)
        self.assertEqual(parallel['medianWallToResultMs'], 8)
        self.assertEqual(parallel['physicalRpcAttempts'], 4)
        self.assertEqual(parallel['physicalRpcMembers'], 6)
        self.assertEqual(result['paired'][0]['outputDeltaRaw'], '10')
        self.assertNotIn('outputDeltaRaw', result['paired'][1])

    def test_two_failures_remain_observable_and_cache_difference_is_diagnostic(self):
        left, right = self.row('custom-only', status='failed'), self.row('parallel', status='failed')
        right['canonicalCacheBefore'] = {'observations': 1}
        result = summary([left, right])
        self.assertEqual(result['pairedOutcomes'], {'neither-completed': 1})
        self.assertFalse(result['paired'][0]['sameStartingCanonicalCache'])
        self.assertEqual(result['allStrategies']['parallel']['physicalRpcAttempts'], 2)

    def test_server_counter_difference_excludes_primer(self):
        prior = {'httpEnvelopes': 4, 'getterCalls': {'slot0()': 2}, 'unsupported': {}}
        after = {'httpEnvelopes': 5, 'getterCalls': {'slot0()': 2, 'liquidity()': 1}, 'unsupported': {}}
        self.assertEqual(difference(after, prior), {
            'httpEnvelopes': 1, 'getterCalls': {'liquidity()': 1}, 'unsupported': {}})

    def test_equal_output_lower_funding_uses_current_whole_plan_comparator(self):
        left, right = self.row('custom-only'), self.row('parallel')
        right['funding'][0]['amount'] = '90'
        pair = summary([left, right])['paired'][0]
        self.assertEqual(pair['outcome'], 'improved')
        self.assertEqual(pair['outputDeltaRaw'], '0')
        self.assertEqual(pair['fundingDeltaRaw'], '-10')


if __name__ == '__main__':
    unittest.main()
