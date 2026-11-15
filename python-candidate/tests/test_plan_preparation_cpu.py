"""Real ABI-worker bytes, policy capture and job/subscriber ownership."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from web3 import Web3

from cybergold_candidate.helpers_execution import ABI
from cybergold_candidate.quote_flow import Flow, flow_scope
from cybergold_candidate.quoter import plan_call
from cybergold_candidate.quoter.cpu import CpuWorkers
from cybergold_candidate.quoter.plan_transport import simulation_scope
from test_quoter_plan_simulation import (
    BLOCK, CORE, HELPERS, OTHER, PAXG, USER, WETH, ZERO,
    encoded, fixture, market, measured, route, stage,
)
from test_quoter_topology_reuse import pool


class PlanPreparationCpuTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cpu = CpuWorkers()
        self.addAsyncCleanup(self.cpu.close)
        await self.cpu.start()
        self.contract = Web3().eth.contract(abi=ABI)

    def options(self, **options):
        return dict(chain=31338, helpers=HELPERS, core=CORE,
                    contract=self.contract) | options

    def sync(self, request, plan, **options):
        return plan_call.compile_call(request, plan, **self.options(**options))

    async def compile(self, request, plan, **options):
        return await plan_call.compile_call_async(request, plan, cpu=self.cpu,
                                                **self.options(**options))

    async def test_real_encoder_matches_market_core_continuation_and_recovery_bytes(self):
        cases = [(*market(intent, native=native), {})
                 for intent, native in ((0, False), (0, True), (1, False))]
        request, plan = market(native=True)
        plan['body']['branches'][0] = {'kind': 0, 'amountIn': '10000', 'data': {
            'basketAssets': [PAXG],
            'acquisitions': [{'amountIn': '10000', 'route': route(WETH, PAXG, split=True)}],
            'continuations': [{'route': route(PAXG, CORE), 'feeCygld': '7'}]}}
        cases.append((request, plan, {}))
        request = {'intent': 1, 'inputs': [{'currency': CORE, 'amount': '100'}], 'outputCurrency': PAXG}
        output = {'kind': 1, 'token': OTHER, 'id': '3', 'minimumAmount': '9'}
        plan = {'body': {'branches': [{'kind': 0, 'amountIn': '100', 'data': {
            'expectedOutputs': [output], 'conversions': []}}]}}
        cases.extend([(request, plan, {}), (request, plan, {'pricing': False, 'accepted_core': [output]})])
        cases.append(({'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '100'}], 'outputCurrency': CORE},
            {'body': {'continuations': [{'route': route(PAXG, CORE), 'feeCygld': '12'}]}}, {}))
        cases.append(({'intent': 3, 'inputs': [{'currency': PAXG, 'amount': '100'}], 'outputCurrency': ZERO},
            {'body': {'expectedOutputs': [output]}}, {'pricing': False, 'recipient': USER}))
        for index, (request, plan, options) in enumerate(cases):
            with self.subTest(index=index):
                before = deepcopy((request, plan))
                for block in (None, BLOCK):
                    expected = self.sync(request, plan, block=block, **options)
                    actual = await self.compile(request, plan, block=block, **options)
                    self.assertEqual(actual, expected)
                self.assertEqual((request, plan), before)

    async def test_queued_job_keeps_request_plan_block_and_fee_at_capture(self):
        workers = [await self.cpu.available.get() for _ in range(2)]
        request, plan = market(1)
        block = deepcopy(BLOCK)
        with patch.object(plan_call, 'get_market_fee_rate', return_value=1000) as fee:
            expected = self.sync(request, plan, block=block)
            task = asyncio.create_task(self.compile(request, plan, block=block))
            await asyncio.sleep(0)
            request['inputs'][0]['amount'] = '20000'
            plan['body']['branches'][0]['amountIn'] = '20000'
            block['hash'] = '0x'+'99'*32
            fee.return_value = 9999
            for worker in workers:
                self.cpu.available.put_nowait(worker)
            self.assertEqual(await task, expected)
            self.assertEqual(fee.call_count, 2, 'Worker does not reevaluate parent fee policy')

    async def test_concurrent_equivalent_misses_encode_once_with_private_exports(self):
        request, plan = market(native=True)
        flow = Flow('fixture')
        async with plan_call.async_preparation_scope() as cache:
            with flow_scope(flow), patch.object(self.cpu, 'encode_plan', wraps=self.cpu.encode_plan) as encode:
                values = await asyncio.gather(*(self.compile(request, plan) for _ in range(12)))
                expected = deepcopy(values[-1])
                values[0].params[0]['data'] = 'private mutation'
                values[0].plan['body'].clear()
                values[0].params[2].clear()
                self.assertTrue(all(value == expected for value in values[1:]))
                self.assertEqual(await self.compile(request, plan), expected)
                self.assertEqual(encode.call_count, 1)
                self.assertEqual(len(cache), 1)
        self.assertFalse(cache)
        rows = {(row['stage'], row['kind']): row for row in flow.snapshot()['stages']}
        self.assertEqual(rows['plan.worker', 'worker-cpu']['completed'], 1)
        self.assertGreater(rows['plan.worker', 'worker-cpu']['summedCpuMs'], 0)
        self.assertEqual(rows['plan.encode', 'await']['completed'], 1)
        self.assertEqual(rows['plan.encode', 'await']['summedCpuMs'], 0)

    async def test_exact_execution_changes_and_nested_scopes_remain_distinct(self):
        request, plan = market()
        async with plan_call.async_preparation_scope():
            with patch.object(self.cpu, 'encode_plan', wraps=self.cpu.encode_plan) as encode:
                await self.compile(request, plan)
                for options in ({'minimum': 2}, {'recipient': USER}, {'pricing': False}, {'block': BLOCK}):
                    self.assertNotEqual((await self.compile(request, plan, **options)).params,
                                        (await self.compile(request, plan)).params)
                with plan_call.preparation_scope():
                    await self.compile(request, plan)
                async with plan_call.async_preparation_scope():
                    await self.compile(request, plan)
                await self.compile(request, plan)
                self.assertEqual(encode.call_count, 7)

    async def test_cancelled_subscriber_does_not_close_another_subscribers_worker(self):
        request, plan = market()
        worker = self.cpu.workers[0]
        process = worker.process
        entered, release = asyncio.Event(), asyncio.Event()
        original = worker.packet
        async def paused():
            entered.set()
            await release.wait()
            return await original()
        async with plan_call.async_preparation_scope():
            with patch.object(worker, 'packet', paused), patch.object(
                    self.cpu, 'encode_plan', wraps=self.cpu.encode_plan) as encode:
                first = asyncio.create_task(self.compile(request, plan))
                second = asyncio.create_task(self.compile(request, plan))
                await asyncio.wait_for(entered.wait(), 10)
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                self.assertIsNone(process.returncode)
                release.set()
                self.assertEqual(await second, self.sync(request, plan))
                self.assertEqual(encode.call_count, 1)

    async def test_last_subscriber_cancellation_reaps_only_its_worker_without_retaining(self):
        request, plan = market()
        worker = self.cpu.workers[0]
        process = worker.process
        sibling = self.cpu.workers[1].process
        entered = asyncio.Event()
        async def paused():
            entered.set()
            await asyncio.Future()
        async with plan_call.async_preparation_scope() as cache:
            with patch.object(worker, 'packet', paused):
                task = asyncio.create_task(self.compile(request, plan))
                await asyncio.wait_for(entered.wait(), 10)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertIsNotNone(process.returncode)
            self.assertIsNone(sibling.returncode)
            self.assertFalse(cache)
            self.assertFalse(self.cpu.jobs)
            self.assertEqual(self.cpu.available.qsize(), 2)
            self.assertEqual(await self.compile(request, plan), self.sync(request, plan))

    async def test_unscoped_work_and_queued_cancellation_keep_existing_capacity(self):
        workers = [await self.cpu.available.get() for _ in range(2)]
        request, plan = market()
        task = asyncio.create_task(self.compile(request, plan))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(all(worker.process.returncode is None for worker in workers))
        self.assertFalse(self.cpu.jobs)
        for worker in workers:
            self.cpu.available.put_nowait(worker)
        with patch.object(self.cpu, 'encode_plan', wraps=self.cpu.encode_plan) as encode:
            self.assertEqual(await self.compile(request, plan), await self.compile(request, plan))
            self.assertEqual(encode.call_count, 2, 'No scope means no completed reuse')
        self.assertEqual(self.cpu.available.qsize(), 2)

    async def test_scope_close_drains_pending_job_and_cancels_its_reader(self):
        request, plan = market()
        worker = self.cpu.workers[0]
        process, sibling = worker.process, self.cpu.workers[1].process
        entered = asyncio.Event()
        async def paused():
            entered.set()
            await asyncio.Future()
        with patch.object(worker, 'packet', paused):
            async with plan_call.async_preparation_scope() as cache:
                task = asyncio.create_task(self.compile(request, plan))
                await asyncio.wait_for(entered.wait(), 10)
            result, = await asyncio.gather(task, return_exceptions=True)
        self.assertIsInstance(result, asyncio.CancelledError)
        self.assertIsNotNone(process.returncode)
        self.assertIsNone(sibling.returncode)
        self.assertFalse(cache)
        self.assertFalse(self.cpu.jobs)
        self.assertEqual(self.cpu.available.qsize(), 2)

    async def test_discovery_and_encoding_share_existing_processes_and_keep_protocols_separate(self):
        request, plan = market()
        processes = [worker.process for worker in self.cpu.workers]
        rows = [pool(PAXG, CORE, 10, 'v3')]
        for _ in range(2):
            call, paths = await asyncio.gather(self.compile(request, plan),
                self.cpu.paths(rows, PAXG, CORE, WETH, 3))
            self.assertEqual(call, self.sync(request, plan))
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0][0][0], 0)
        self.assertEqual([worker.process for worker in self.cpu.workers], processes)
        self.assertEqual(self.cpu.available.qsize(), 2)

    async def test_ordinary_encoder_errors_keep_types_and_arguments_and_are_not_cached(self):
        request, plan = market()
        broken = deepcopy(plan)
        del broken['body']['branches'][0]['data']['route']['routes']
        for candidate, options in ((plan, {'minimum': -1}), (broken, {})):
            with self.subTest(options=options):
                try:
                    self.sync(request, candidate, **options)
                except Exception as expected:
                    expected_type, expected_args = type(expected), expected.args
                else:
                    self.fail('Fixture must produce an ordinary ABI error')
                async with plan_call.async_preparation_scope() as cache:
                    for _ in range(2):
                        with self.assertRaises(expected_type) as caught:
                            await self.compile(request, candidate, **options)
                        self.assertEqual(caught.exception.args, expected_args)
                    self.assertFalse(cache)
        self.assertEqual(await self.compile(request, plan), self.sync(request, plan))

    async def test_large_wire_frames_keep_bytes_and_reuse_processes(self):
        request, plan = market()
        template = plan['body']['branches'][0]['data']['route']
        template['routes'] *= 512
        before = [worker.process for worker in self.cpu.workers]
        value = await self.compile(request, plan)
        self.assertGreater(len(value.params[0]['data']), 65536)
        self.assertEqual(value, self.sync(request, plan))
        self.assertEqual([worker.process for worker in self.cpu.workers], before)

    async def test_async_simulation_retains_single_rpc_fees_and_latest_fresh_preparation(self):
        request, plan = market()
        response = encoded(measured(100000, stages=[stage(0, WETH, CORE, 10000, 100000)]))
        simulation, _, rpc, provider = fixture(response, response)
        simulation.cpu = self.cpu
        async with simulation_scope():
            first, second = await asyncio.gather(simulation(request, plan), simulation(request, plan))
            for field in ('quotedOutput', 'plan', 'context', 'fees', 'inputs'):
                self.assertEqual(first[field], second[field])
            self.assertEqual(first['pricingEvidence']['rpcCalls'] + second['pricingEvidence']['rpcCalls'], 1)
            self.assertEqual(len(provider.calls), 1)
            await simulation(request, plan, pricing=False)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual([params[1] for _, params in provider.calls], ['latest', 'latest'])
        self.assertEqual((rpc.heads, rpc.verifications), ([], []))


if __name__ == '__main__':
    unittest.main()
