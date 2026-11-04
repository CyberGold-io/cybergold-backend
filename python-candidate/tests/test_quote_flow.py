"""Diagnostic ownership and timing contracts, independent of quote policy."""
import asyncio
import unittest
from unittest.mock import patch

from cybergold_candidate.quote_flow import (
    Flow, Span, STAGES, current_flow, flow_scope, producer_flow, stage,
)


class FlowClocks(unittest.TestCase):
    def setUp(self):
        self.wall, self.cpu = 0.0, 0.0
        self.flow = Flow('quote', request_id='request', clock=lambda: self.wall,
                         cpu_clock=lambda: self.cpu)

    def rows(self):
        return {row['stage']: row for row in self.flow.snapshot()['stages']}

    def test_wait_cpu_and_queue_ready_are_distinct(self):
        with flow_scope(self.flow):
            with stage('helpers.rpc'):
                self.wall, self.cpu = 3, 2
            with stage('plan.compile', kind='cpu'):
                self.wall, self.cpu = 5, 3
            with stage('helpers.permit', kind='queue') as waiting:
                self.wall = 9
                waiting.ready()
                self.wall = 10
                waiting.ready()  # Repeated observation cannot move the grant.
                self.wall = 11
        rows = self.rows()
        self.assertEqual(rows['helpers.rpc']['summedWallMs'], 3000)
        self.assertEqual(rows['helpers.rpc']['summedCpuMs'], 0)
        self.assertEqual(rows['plan.compile']['summedCpuMs'], 1000)
        wait = rows['helpers.permit']
        self.assertEqual((wait['summedWallMs'], wait['summedReadyWaitMs'],
                          wait['summedResumeDelayMs'], wait['readyMarkers']),
                         (6000, 4000, 2000, 1))

    def test_unmarked_wait_is_explicitly_unmeasured(self):
        with flow_scope(self.flow), stage('publication.queue', kind='queue'):
            self.wall = 1
        row = self.rows()['publication.queue']
        self.assertEqual((row['summedWallMs'], row['readyMarkers']), (1000, 0))

    def test_overlapping_calls_aggregate_without_claiming_serial_latency(self):
        with flow_scope(self.flow):
            with stage('helpers.rpc'):
                self.wall = 1
                with stage('helpers.rpc'):
                    self.wall = 3
                    active = self.rows()['helpers.rpc']
                    self.assertEqual((active['inFlight'], active['activePeriodMs']), (2, 3000))
                self.wall = 4
        row = self.rows()['helpers.rpc']
        self.assertEqual((row['completed'], row['summedWallMs'], row['maxWallMs']), (2, 6000, 4000))
        self.assertEqual(self.flow.snapshot()['elapsedMs'], 4000)
        self.assertNotIn('activePeriodMs', row)

    def test_stage_aggregation_is_bounded_even_with_many_callbacks(self):
        with flow_scope(self.flow):
            for index in range(1000):
                with stage('sdk.decode', kind='cpu'):
                    self.wall += .001
                with stage(f'route-{index}'):
                    pass
        rows = self.rows()
        self.assertEqual(set(rows), {'sdk.decode', 'other'})
        self.assertEqual(rows['sdk.decode']['completed'], 1000)
        self.assertLessEqual(len(rows), len(STAGES))

    def test_failure_and_cancelled_stages_do_not_mask_original_errors(self):
        with self.assertRaisesRegex(ValueError, 'ordinary error'):
            with flow_scope(self.flow), stage('helpers.rpc'):
                raise ValueError('ordinary error')
        with self.assertRaises(asyncio.CancelledError):
            with flow_scope(self.flow), stage('sdk.read'):
                raise asyncio.CancelledError()
        self.assertEqual(self.rows()['helpers.rpc']['failed'], 1)
        self.assertEqual(self.rows()['sdk.read']['cancelled'], 1)

    def test_broken_diagnostic_clocks_sink_or_metrics_cannot_fail_operation(self):
        def broken(*_args):
            raise ValueError('diagnostic failure')
        self.flow.clock = broken
        with flow_scope(self.flow), stage('plan.compile', kind='cpu'):
            result = 7
        self.assertEqual(result, 7)
        self.flow.finish('succeeded')
        sink_flow = Flow('quote', sink=broken)
        with flow_scope(sink_flow), stage('helpers.rpc'):
            result += 1
        sink_flow.finish('succeeded')
        self.assertEqual(result, 8)
        self.assertIsNone(current_flow())

    def test_completed_header_summary_excludes_inflight_work(self):
        with flow_scope(self.flow):
            with stage('plan.compile', kind='cpu'):
                self.wall = 1
            with stage('helpers.rpc'):
                self.wall = 3
                header = self.flow.server_timing()
        self.assertIn('cg_backend_headers;dur=3000.000', header)
        self.assertIn('cg_sum_plan_compile;dur=1000.000', header)
        self.assertNotIn('helpers_rpc', header)


class FlowOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_owner_is_linked_without_merging_clocks_and_terminal_is_once(self):
        records = []
        parent = Flow('quote', request_id='r', attempt_id='a', sink=records.append)
        with flow_scope(parent):
            with producer_flow('search') as owner:
                self.assertIs(current_flow(), owner)
                self.assertIs(asyncio.current_task().quote_flow, owner)
                self.assertNotEqual(owner.flow_id, parent.flow_id)
                parent.link(owner, 'search')
                parent.link(owner, 'search')
                with stage('search.run'):
                    await asyncio.sleep(0)
            self.assertIs(current_flow(), parent)
        owner.finish('failed')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['parentFlowId'], 'r')
        self.assertEqual(records[0]['attemptId'], 'a')
        self.assertEqual(records[0]['outcome'], 'succeeded')
        self.assertEqual(parent.snapshot()['stages'], [])
        self.assertEqual(parent.snapshot()['sharedOwners'], [
            {'flowId': owner.flow_id, 'relation': 'search', 'subscriptions': 2}])

    async def test_cancelled_producer_stays_cancelled_and_emits_own_outcome(self):
        records = []
        parent = Flow('quote', sink=records.append)
        with self.assertRaises(asyncio.CancelledError):
            with flow_scope(parent), producer_flow('search'):
                raise asyncio.CancelledError()
        self.assertEqual(records[0]['outcome'], 'cancelled')
        self.assertIsNone(current_flow())

    async def test_missing_or_failed_recorder_does_not_prevent_producer(self):
        with producer_flow('search') as absent:
            self.assertIsNone(absent)
        parent = Flow('quote')
        with patch('cybergold_candidate.quote_flow.Flow', side_effect=ValueError('diagnostic failure')):
            with flow_scope(parent), producer_flow('search') as absent:
                self.assertIsNone(absent)
                result = 7
        self.assertEqual(result, 7)


if __name__ == '__main__':
    unittest.main()
