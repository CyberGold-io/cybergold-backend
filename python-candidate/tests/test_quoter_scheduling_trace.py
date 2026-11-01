"""Serving regressions use real SDK pricing, complete plans and owned HTTP."""
import os
import unittest

from quoter_scheduling_trace import run_fixture


NODE = os.environ.get('CYBERGOLD_TEST_NODE', 'node')
PROVIDERS = {'cybergold-custom', 'uniswap-alpharouter', 'uniroute-local',
             'uniroute-api', 'uniswap-guidestar'}


class ServingSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def verify_case(self, *, core_preview):
        row = await run_fixture(node=NODE, core_preview=core_preview)
        self.assertEqual(row['status'], 'completed', row.get('failureType'))
        self.assertEqual(row['output'], row['independentReference']['output'],
                         'Ready same-funding canonical plan was not evaluated before ordinary selection stopped.')
        self.assertEqual(row['funding'], row['independentReference']['funding'])
        self.assertEqual(row['selectedKinds'], [0 if core_preview else 1])
        self.assertTrue(row['replaySameOutput'])
        self.assertEqual(row['configuration']['optionalLimit'], 16)
        self.assertEqual(row['configuration']['engineSlots'], 8)
        suppliers = row['metrics']['routeDiscovery']['providers']
        self.assertEqual(set(suppliers), PROVIDERS)
        self.assertTrue(all(suppliers[name]['started'] for name in PROVIDERS))
        self.assertGreater(row['searchServerRpc']['httpEnvelopes'], 0)
        # Ordinary seeded fee tiers include absent pools. Their real RPC
        # failures are counted; no unsupported ABI getter is substituted.
        self.assertLessEqual(set(row['searchServerRpc']['unsupported']), {'unknown-pool'})
        self.assertEqual(row['rpcReconciliation']['clientAttemptsMinusServerEnvelopes'], 0)
        self.assertEqual(row['rpcReconciliation']['clientMembersMinusServerMembers'], 0)
        self.assertTrue(row['allSuppliersClosed'])
        self.assertTrue(all(row['supplierChildrenRetired'].values()))
        self.assertTrue(row['sdkChildRetired'])
        self.assertEqual(row['liveHttpClients'], 0)
        self.assertFalse(row['sourceContentChangedDuringRun'])
        self.assertTrue(any(e['event'] == 'fixture-rpc-delay-start' for e in row['events']))
        self.assertTrue(any(e['event'] == 'sdk-exchange-enter' for e in row['events']))
        return row

    async def test_cold_market_ready_canonical_state_is_not_blocked_by_other_initial_reads(self):
        await self.verify_case(core_preview=False)

    async def test_later_better_acquisition_is_priced_as_a_complete_core_plan(self):
        row = await self.verify_case(core_preview=True)
        self.assertIn('0:acquire:0', row['origins']['conversions'])


if __name__ == '__main__':
    unittest.main()
