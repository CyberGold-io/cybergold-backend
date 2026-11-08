"""Probe integrity: real SDK replay, native semantics and existing budget drain."""
import asyncio
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteTool
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.route_observations import physical_rpc_exchange
from cybergold_candidate.routing_encoding import ZERO
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.shared_reads import SharedReads
from quoter_fixture import Registry, synthetic_pool
from test_universal_quote import BLOCK, settings
import probe_hosted_route_discovery as probe


NODE = os.environ.get('CYBERGOLD_TEST_NODE', 'node')


class ProbeReplayTests(unittest.IsolatedAsyncioTestCase):
    def engine(self, pools):
        registry = Registry(pools)
        engine = RouteQuoteEngine(settings(), registry,
            sdk=SdkWorker([NODE, str(probe.ROOT / 'src/uniswap-sdk/worker.ts')]))
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.pending.close)
        return engine

    def branch(self, pool, amount, source=probe.WETH):
        return {'amountIn': str(amount), 'hops': [{'pool': pool,
            'zeroForOne': pool['token0']['address'].lower() == source.lower()}]}

    async def test_runtime_remainder_and_shared_pool_replay_match_actual_sdk(self):
        pool = synthetic_pool(probe.WETH, probe.USDC, 970, 'v2')
        engine = self.engine([pool])
        # Nomination amounts express 1:2 weights; Helpers funding is 3 + 7.
        nominated = [self.branch(pool, 1), self.branch(pool, 2)]
        normalized, _ = next(probe.normalized_candidates(nominated,
            probe.WETH, probe.USDC, 'uniroute-local'))
        quote = await probe.price_candidate(engine, normalized, probe.WETH, probe.USDC, 10, BLOCK)
        expected = await engine.quote_branches([self.branch(pool, 3), self.branch(pool, 7)],
            'exactIn', 10, BLOCK)
        self.assertEqual(quote['runtimeBranchFunding'], [3, 7])
        self.assertTrue(quote['fullyFilled'])
        self.assertEqual(quote['amountIn'], '10')
        self.assertEqual(quote['amountOut'], expected['amountOut'])
        self.assertEqual(probe.candidate_key(nominated), probe.candidate_key(
            [self.branch(pool, 100), self.branch(pool, 200)]))

    async def test_leading_wrap_is_helpers_funding_not_an_sdk_pool_hop(self):
        pool = synthetic_pool(probe.WETH, probe.USDC, 971, 'v2')
        engine = self.engine([pool])
        nominated = [self.branch(pool, 10000)]
        # Shared graph normalization restores this semantic transition from
        # the requested native source even when the provider only sent pools.
        normalized, _ = next(probe.normalized_candidates(nominated, ZERO, probe.USDC, 'uniroute-api'))
        self.assertEqual(normalized[0]['hops'][0]['kind'], 'wrap')
        quote = await probe.price_candidate(engine, normalized, ZERO, probe.USDC, 10000, BLOCK)
        expected = await engine.quote_branches(nominated, 'exactIn', 10000, BLOCK)
        self.assertTrue(quote['fullyFilled'])
        self.assertEqual(quote['physicalInputCurrency'].lower(), probe.WETH.lower())
        self.assertEqual(quote['amountOut'], expected['amountOut'])

    async def test_leading_unwrap_into_native_v4_matches_actual_sdk(self):
        pool = synthetic_pool(ZERO, probe.USDC, 972, 'v4', liquidity=10**10)
        engine = self.engine([pool])
        physical = [self.branch(pool, 10000, source=ZERO)]
        normalized, _ = next(probe.normalized_candidates(physical,
            probe.WETH, probe.USDC, 'uniswap-guidestar'))
        self.assertEqual(normalized[0]['hops'][0]['kind'], 'unwrap')
        quote = await probe.price_candidate(engine, normalized, probe.WETH, probe.USDC, 10000, BLOCK)
        expected = await engine.quote_branches(physical, 'exactIn', 10000, BLOCK)
        self.assertEqual(quote['physicalInputCurrency'], ZERO)
        self.assertEqual(quote['amountOut'], expected['amountOut'])
        self.assertTrue(quote['fullyFilled'])

    async def test_existing_budget_stops_and_drains_pending_provider(self):
        class Rpc:
            async def block(self, *_):
                return deepcopy(BLOCK)
            async def assert_canonical(self, *_):
                pass
        class Pending(RouteTool):
            name = 'uniroute-api'
            def __init__(self):
                self.cancelled, self.closed = False, False
            def discover(self, _):
                async def waiting():
                    try:
                        await asyncio.Event().wait()
                    finally:
                        self.cancelled = True
                return CandidateFeed(pending=waiting())
            async def close(self):
                self.closed = True
        class EmptyRegistry:
            def __init__(self, *_):
                self.inventory, self.observed = {}, {}
                self.pending = SharedReads()
            def get_rpc(self):
                return Rpc()
            async def close(self):
                await self.pending.close()
        pending = Pending()
        budget = QuoteBudget(initial=.02, extension=.02)
        with patch.object(probe, 'PoolRegistry', EmptyRegistry), \
             patch.object(probe, 'route_providers', return_value=[pending]), budget_context(budget):
            row = await budget.produce(probe.trial(settings(), BLOCK, 'hosted-only', 10, 1, NODE))
        self.assertEqual(row['status'], 'no-fully-funded-quote')
        self.assertEqual(budget.reason, 'timeout')
        self.assertTrue(pending.cancelled)
        self.assertTrue(pending.closed)
        self.assertTrue(row['allResourcesClosed'])
        self.assertTrue(row['canonicalityVerified'])
        self.assertEqual(row['physicalRpc']['requests'], 0)

    async def test_first_canonical_route_qualifies_existing_initial_window_and_drains_late_tool(self):
        pool = synthetic_pool(probe.WETH, probe.USDC, 973, 'v2')
        branch = self.branch(pool, 10000)
        class TrialRegistry(Registry):
            def __init__(self, *_):
                super().__init__([pool])
            async def close(self):
                await self.pending.close()
        class Ready(RouteTool):
            name = 'uniroute-api'
            def discover(self, _):
                return CandidateFeed(available=[[deepcopy(branch)]])
        class Late(RouteTool):
            name = 'uniswap-guidestar'
            def __init__(self):
                self.cancelled = False
            def discover(self, _):
                async def waiting():
                    try:
                        await asyncio.Event().wait()
                    finally:
                        self.cancelled = True
                return CandidateFeed(pending=waiting())
        late = Late()
        budget = QuoteBudget(initial=.5, extension=.5)
        with patch.object(probe, 'PoolRegistry', TrialRegistry), \
             patch.object(probe, 'route_providers', return_value=[Ready(), late]), budget_context(budget):
            row = await budget.produce(probe.trial(settings(), BLOCK, 'hosted-only', 10000, 1, NODE))
        self.assertEqual(row['status'], 'completed')
        self.assertIsNotNone(row['best'])
        self.assertIsNotNone(budget.first_qualified)
        self.assertEqual(budget.reason, 'best-initial')
        self.assertTrue(late.cancelled)
        self.assertTrue(row['canonicalityVerified'])
        self.assertTrue(row['allResourcesClosed'])

    async def test_failed_context_retains_attempt_counts_without_exception_text(self):
        private = 'test-only-private-failure-value'
        class FailingRpc:
            closed = False
            def __init__(self, *_):
                pass
            async def block(self, *_):
                with physical_rpc_exchange({'method': 'eth_getBlockByNumber'}):
                    raise RuntimeError(private)
            async def close(self):
                FailingRpc.closed = True
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'failed-context.json'
            arguments = ['probe', '--mode', 'paired-rpc', '--node', NODE, '--output', str(path)]
            output = io.StringIO()
            with patch.object(probe, 'UniswapRpc', FailingRpc), \
                 patch('sys.argv', arguments), \
                 patch.dict(os.environ, {'MAINNET_RPC_URL': 'http://127.0.0.1:1'}), \
                 redirect_stdout(output):
                await probe.main()
            document = path.read_text()
            report = json.loads(document)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['failureType'], 'RuntimeError')
            self.assertEqual(report['contextAcquisitionPhysicalRpc']['requests'], 1)
            self.assertEqual(report['contextAcquisitionPhysicalRpc']['errors'], 1)
            self.assertEqual(report['contextAcquisitionPhysicalRpc']['methods'],
                {'eth_getBlockByNumber': 1})
            self.assertTrue(FailingRpc.closed)
            self.assertNotIn(private, document + output.getvalue())

    async def test_async_batch_qualifies_before_terminal_work_and_retains_callback_counts(self):
        pool = synthetic_pool(probe.WETH, probe.USDC, 974, 'v2')
        branch = self.branch(pool, 10000)
        class TrialRegistry(Registry):
            def __init__(self, *_):
                super().__init__([pool])
            async def close(self):
                await self.pending.close()
        class Streaming(RouteTool):
            name = 'uniroute-api'
            diagnostics = {'workerQueries': 1, 'quoteCallbacks': 2,
                'quoteCallbackFailures': 0, 'quoteCallbackMs': 3.5}
            def __init__(self):
                self.drained = False
            def discover(self, _):
                async def batches():
                    try:
                        yield [[deepcopy(branch)]]
                        await asyncio.Event().wait()
                    finally:
                        self.drained = True
                return CandidateFeed(updates=batches())
        stream = Streaming()
        budget = QuoteBudget(initial=.5, extension=.5)
        with patch.object(probe, 'PoolRegistry', TrialRegistry), \
             patch.object(probe, 'route_providers', return_value=[stream]), budget_context(budget):
            row = await budget.produce(probe.trial(settings(), BLOCK, 'hosted-only', 10000, 1, NODE))
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(budget.reason, 'best-initial')
        self.assertIsNotNone(row['best'])
        self.assertTrue(stream.drained)
        self.assertTrue(row['allResourcesClosed'])
        self.assertEqual(row['sources'][stream.name]['batches'], 1)
        self.assertEqual(row['sources'][stream.name]['quoteCallbacks'], 2)
        self.assertEqual(row['sources'][stream.name]['quoteCallbackMs'], 3.5)


class ProbeConfigurationTests(unittest.TestCase):
    def test_selected_settings_remain_data_and_projection_contains_no_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'probe.env'
            marker = Path(directory) / 'must-not-execute'
            private = 'test-only-private-value'
            path.write_text(f'export CYBERGOLD_UNISWAP_API_KEY="{private}"\n'
                f'IGNORED_SETTING=$(touch {marker})\n')
            config = probe.selected_settings(path, environment={})
            self.assertEqual(config.CYBERGOLD_UNISWAP_API_KEY, private)
            self.assertFalse(marker.exists())
            self.assertNotIn(private, json.dumps(probe.configuration(config, path)))
            self.assertEqual(probe.selected_settings(path,
                environment={'CYBERGOLD_UNISWAP_API_KEY': 'replacement'}).CYBERGOLD_UNISWAP_API_KEY,
                'replacement')


if __name__ == '__main__':
    unittest.main()
