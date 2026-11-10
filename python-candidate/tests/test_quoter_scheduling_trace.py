"""Serving regressions use real SDK pricing, complete plans and owned HTTP."""
import os
import unittest

from quoter_scheduling_trace import run_fixture


NODE = os.environ.get('CYBERGOLD_TEST_NODE', 'node')
PROVIDERS = {'cybergold-custom', 'uniswap-alpharouter', 'uniroute-local',
             'uniroute-api-fastest', 'uniroute-api', 'uniswap-guidestar'}


class ServingSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def verify_case(self, *, core_preview, strategy='parallel'):
        # Repeated per-read delays remain explicit fixture behavior. Scale
        # correctness runs while benchmarks keep their original 6s/7s defaults;
        # readiness before a held tail has separate event-controlled coverage.
        row = await run_fixture(node=NODE, core_preview=core_preview, strategy=strategy,
                                slow_scalar_ms=60, slow_catalog_ms=70)
        self.assertEqual(row['status'], 'completed', row.get('failureType'))
        self.assertEqual(row['output'], row['independentReference']['output'],
                         'Ready same-funding canonical plan was not evaluated before ordinary selection stopped.')
        self.assertEqual(row['funding'], row['independentReference']['funding'])
        self.assertEqual(row['selectedKinds'], [0 if core_preview else 1])
        self.assertTrue(row['replaySameOutput'])
        self.assertIsNone(row['configuration']['optionalLimit'])
        self.assertEqual(row['configuration']['engineSlots'], 8)
        self.assertEqual(row['budgetConfiguration'],
                         {'mode': 'producer-default', 'initialMs': None, 'deadlineMs': None})
        self.assertEqual(row['fixtureDelaysMs'], {'oldScalar': 60, 'unrelatedCatalog': 70})
        suppliers = row['metrics']['routeDiscovery']['providers']
        expected = {'cybergold-custom'} if strategy=='custom-only' else PROVIDERS
        self.assertEqual(set(suppliers), expected)
        self.assertTrue(all(suppliers[name]['started'] for name in expected))
        api = row['metrics']['routeDiscovery'].get('apiRequests', {})
        if strategy in ('custom-only','all-local'):
            self.assertEqual(api.get('requests',0), 0)
            self.assertEqual(row['hostedFixtureReceivedRequests'], {})
        if strategy=='all-local':
            for name in ('uniroute-api-fastest','uniroute-api','uniswap-guidestar'):
                self.assertGreater(suppliers[name]['unavailable'], 0)
        if strategy=='hosted-failure':
            self.assertGreater(api['requests'], 0)
            self.assertEqual(api['errors'], api['requests'])
            self.assertEqual(api['requests'],sum(row['hostedFixtureReceivedRequests'].values()))
            for name in ('uniroute-api-fastest','uniroute-api','uniswap-guidestar'):
                self.assertGreater(suppliers[name]['error'], 0)
        if strategy!='custom-only':
            for name in ('uniroute-local','uniswap-alpharouter'):
                self.assertGreater(suppliers[name]['workerQueries'], 0)
        self.assertGreater(row['searchServerRpc']['httpEnvelopes'], 0)
        # Ordinary seeded fee tiers include absent pools. Their real RPC
        # failures are counted; no unsupported ABI getter is substituted.
        self.assertLessEqual(set(row['searchServerRpc']['unsupported']), {'unknown-pool'})
        physical = row['metrics']['routeDiscovery']['physicalRpc']
        for reported, issued, received in (
            ('clientAttemptsMinusServerEnvelopes','requests','httpEnvelopes'),
            ('clientMembersMinusServerMembers','jsonRpcMembers','jsonRpcMembers')):
            difference=physical[issued]-row['searchServerRpc'][received]
            self.assertEqual(row['rpcReconciliation'][reported], difference)
            self.assertGreaterEqual(difference,0)
            self.assertLessEqual(difference,physical['cancelled']+physical['errors'])
        self.assertTrue(row['allSuppliersClosed'])
        self.assertTrue(all(row['supplierChildrenRetired'].values()))
        self.assertTrue(row['sdkChildRetired'])
        self.assertEqual(row['liveHttpClients'], 0)
        self.assertFalse(row['sourceContentChangedDuringRun'])
        self.assertTrue(any(e['event'] == 'fixture-rpc-delay-start' for e in row['events']))
        self.assertTrue(any(e['event'] == 'sdk-exchange-enter' for e in row['events']))
        self.assertTrue(any(e['event'] == 'whole-plan-start' for e in row['events']))
        self.assertTrue(any(e['event'] == 'whole-plan-priced' for e in row['events']))
        return row

    async def test_cold_market_ready_canonical_state_is_not_blocked_by_other_initial_reads(self):
        await self.verify_case(core_preview=False)

    async def test_later_better_acquisition_is_priced_as_a_complete_core_plan(self):
        row = await self.verify_case(core_preview=True)
        self.assertIn('0:acquire:0', row['origins']['conversions'])

    async def test_custom_only_completed_market_prefix_can_improve_core_acquisition(self):
        await self.verify_case(core_preview=True, strategy='custom-only')

    async def test_actual_local_factory_needs_no_hosted_credentials_for_core_improvement(self):
        await self.verify_case(core_preview=True, strategy='all-local')

    async def test_ordinary_hosted_failures_do_not_remove_local_core_coverage(self):
        await self.verify_case(core_preview=True, strategy='hosted-failure')


if __name__ == '__main__':
    unittest.main()
