"""Depth experiment integrity: equal fallback and failed/funding comparisons."""
from types import MethodType, SimpleNamespace
import unittest

from benchmark_uniroute_depth import MODES, summary, tools_for_mode
from test_universal_quote import settings
from cybergold_candidate.uniswap_api_queue import UniswapApiQueue
from cybergold_candidate.route_quote_engine import RouteQuoteEngine


class DepthComparisonTests(unittest.TestCase):
    def row(self, mode, *, status='completed', output='100', funding='100', callbacks=0):
        return {'case': 'fixture', 'cacheMode': 'cold', 'repeat': 1, 'strategy': mode,
            'status': status, 'netOutput': output,
            'funding': [{'currency': '0x'+'11'*20, 'amount': funding}],
            'samePinnedStateSha256': 'fixture', 'canonicalCacheBefore': {'observations': 0},
            'catalogBeforeSearch': {'inventoryPools': 5}, 'wallToResultMs': 5,
            'metrics': {'timeToFirstWholePlanMs': 1, 'routeDiscovery': {
                'physicalRpc': {'requests': 2, 'jsonRpcMembers': 3}}},
            'providerWork': {'uniroute-local': {'quoteCallbacks': callbacks}},
            'serverRpc': {'httpEnvelopes': 2}}

    def test_failed_mode_remains_in_comparisons_and_callback_denominators(self):
        rows = [self.row('finder-only'), self.row('deep-25', callbacks=10),
            self.row('deep-5', output='110', callbacks=20),
            self.row('parallel', status='failed', callbacks=30)]
        result = summary(rows)
        self.assertEqual(result['attemptedTrials'], 4)
        self.assertEqual(result['attemptedComparisons'], 3)
        self.assertEqual(result['outcomes'], {'equal': 1, 'improved': 1, 'baseline-only': 1})
        failed = next(row for row in result['groups'] if row['mode'] == 'parallel')
        self.assertEqual(failed['completionRate'], 0)
        self.assertEqual(failed['physicalRpcAttempts'], 2)
        self.assertEqual(failed['providerWorkTotals']['quoteCallbacks'], 30)
        self.assertNotIn('outputDeltaRaw', next(row for row in result['comparisons']
            if row['mode'] == 'parallel'))

    def test_equal_output_lower_funding_uses_whole_plan_comparator(self):
        result = summary([self.row('finder-only'), self.row('deep-5', funding='99')])
        comparison = result['comparisons'][0]
        self.assertEqual(comparison['outcome'], 'improved')
        self.assertEqual(comparison['outputDeltaRaw'], '0')
        self.assertEqual(comparison['fundingDeltaRaw'], '-1')

    def test_all_isolated_modes_keep_equal_custom_fallback_and_no_other_supplier(self):
        engine = SimpleNamespace(registry=SimpleNamespace(), uniswap_api_queue=UniswapApiQueue(),
                                 _route_optimizers={})
        engine.route_optimizer = MethodType(RouteQuoteEngine.route_optimizer, engine)
        for mode in MODES[:-1]:
            tools = tools_for_mode(settings(), engine, mode=mode)
            self.assertEqual([tool.name for tool in tools], ['cybergold-custom', 'uniroute-local'])
            self.assertEqual(len(tools[1].provider.command), 3)
        parallel = tools_for_mode(settings(), engine, mode='parallel')
        self.assertEqual({tool.name for tool in parallel}, {'cybergold-custom', 'uniswap-alpharouter',
            'uniroute-local', 'uniroute-api', 'uniswap-guidestar'})
        self.assertTrue(all(not getattr(getattr(tool, 'provider', tool), 'api_key', None)
            for tool in parallel))


if __name__ == '__main__':
    unittest.main()
