"""Selected-plan preparation shares the existing finite-body priority lane."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from cybergold_candidate import route_work_slots as work
from cybergold_candidate import tx_preparation
from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.route_work_slots import bootstrap_priority, engine_work
from cybergold_candidate.tx_preparation import TransactionPreparation
from test_quoter_plan_simulation import fixture, market, measured, encoded, stage, decode, CORE, WETH, USER


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


class PreparationReplayPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def setup_preparation(self):
        request, plan = market()
        response = encoded(measured(20000, stages=[stage(0, WETH, CORE, 10000, 20000)]))
        _, quoter, rpc, provider = fixture(response)
        self.addAsyncCleanup(quoter.close)
        selected = await quoter.evaluate_selected(request, plan)
        provider.calls.clear()
        provider.responses = [deepcopy(response)]
        provider.entered, provider.drained = asyncio.Event(), asyncio.Event()
        payload = {'quote': selected, 'sender': USER, 'recipient': USER,
                   'acceptedBounds': {'inputs': deepcopy(selected['inputs']), 'minimumOutput': '19800'}}
        return quoter, rpc, provider, payload

    def assert_released(self, slots):
        self.assertEqual((slots._value, len(slots._ordinary), len(slots._priority), len(slots._spans)),
                         (8, 0, 0, 0))
        self.assertFalse(work._bootstrap.get())

    async def test_service_replay_follows_earlier_priority_and_precedes_queued_sdk_work(self):
        quoter, rpc, provider, payload = await self.setup_preparation()
        slots, order = quoter.engine.semaphore, []
        for _ in range(8):
            await slots.acquire()
        held = 8
        scope_entered, scope_release = asyncio.Event(), asyncio.Event()
        earlier_entered, earlier_release = asyncio.Event(), asyncio.Event()
        provider.release = asyncio.Event()
        contexts = []
        async def observe_scope():
            contexts.append(('scope', work._bootstrap.get()))
            scope_entered.set()
            await scope_release.wait()
        async def sdk(index):
            async with engine_work(slots):
                order.append('sdk-'+str(index))
        async def earlier_priority():
            with bootstrap_priority():
                async with engine_work(slots):
                    order.append('earlier-priority')
                    earlier_entered.set()
                    await earlier_release.wait()
        original_request, original_compile = provider.make_request, tx_preparation.compile_execution
        async def make_request(method, params):
            contexts.append(('rpc', work._bootstrap.get()))
            order.append('helpers')
            return await original_request(method, params)
        def compile_execution(*args, **kwargs):
            contexts.append(('compile', work._bootstrap.get()))
            return original_compile(*args, **kwargs)
        provider.make_request = make_request
        competitors = [asyncio.create_task(sdk(index)) for index in range(8)]
        older = asyncio.create_task(earlier_priority())
        preparation = asyncio.create_task(TransactionPreparation(quoter, now=lambda: 1000,
            observe_scope=observe_scope).prepare(payload))
        try:
            await scope_entered.wait()
            await until(lambda: len(slots._ordinary) == 8 and len(slots._priority) == 1)
            self.assertEqual(provider.calls, [])
            scope_release.set()
            await until(lambda: len(slots._priority) == 2)
            slots.release()
            held -= 1
            await earlier_entered.wait()
            self.assertEqual(order, ['earlier-priority'])
            self.assertEqual(provider.calls, [])
            earlier_release.set()
            await provider.entered.wait()
            self.assertEqual(order, ['earlier-priority', 'helpers'])
            self.assertEqual((slots._value, len(slots._ordinary)), (0, 8))
            provider.release.set()
            with patch.object(tx_preparation, 'compile_execution', side_effect=compile_execution):
                result = await preparation
            await asyncio.gather(older, *competitors)
            self.assertEqual(contexts, [('scope', False), ('rpc', True), ('compile', False)])
            self.assertEqual(result['economicQuote']['quotedOutput'], payload['quote']['quotedOutput'])
            self.assertEqual(result['economicQuote']['inputs'], payload['quote']['inputs'])
            self.assertEqual((result['outputMinimum'], result['plan']['deadline']), ('19800', '1600'))
            self.assertEqual(result['plan']['inputs'], payload['quote']['inputs'])
            method, _, tag, _, _, values = decode(provider)
            self.assertEqual((method, tag, values['plan']['minimumOutput'], values['plan']['recipient']),
                             ('eth_call', 'latest', 19800, USER))
            self.assertEqual((len(provider.calls), result['economicQuote']['pricingEvidence']['rpcCalls']), (1, 1))
            self.assertEqual((rpc.heads, rpc.verifications), ([], []))
            quoter.engine.quote_sdk_branches.assert_not_called()
        finally:
            scope_release.set()
            earlier_release.set()
            provider.release.set()
            for task in (preparation, older, *competitors):
                task.cancel()
            await asyncio.gather(preparation, older, *competitors, return_exceptions=True)
            for _ in range(held):
                slots.release()
        self.assert_released(slots)

    async def test_cancellation_before_grant_removes_only_preparations_waiter(self):
        quoter, _, provider, payload = await self.setup_preparation()
        slots = quoter.engine.semaphore
        for _ in range(8):
            await slots.acquire()
        async def ordinary():
            async with engine_work(slots):
                pass
        competitor = asyncio.create_task(ordinary())
        preparation = asyncio.create_task(TransactionPreparation(quoter).prepare(payload))
        try:
            await until(lambda: len(slots._priority) == 1 and len(slots._ordinary) == 1)
            preparation.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await preparation
            self.assertEqual((slots._value, len(slots._priority), len(slots._ordinary)), (0, 0, 1))
            self.assertEqual(provider.calls, [])
        finally:
            preparation.cancel()
            competitor.cancel()
            await asyncio.gather(preparation, competitor, return_exceptions=True)
            for _ in range(8):
                slots.release()
        self.assert_released(slots)

    async def test_cancellation_after_grant_drains_helpers_and_restores_context(self):
        quoter, rpc, provider, payload = await self.setup_preparation()
        provider.release = asyncio.Event()
        contexts = []
        async def prepare():
            try:
                return await TransactionPreparation(quoter).prepare(payload)
            finally:
                contexts.append(work._bootstrap.get())
        task = asyncio.create_task(prepare())
        await provider.entered.wait()
        self.assertEqual(quoter.engine.semaphore._value, 7)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.drained.is_set())
        self.assertEqual(contexts, [False])
        self.assertEqual((len(provider.calls), rpc.heads, rpc.verifications), (1, [], []))
        self.assert_released(quoter.engine.semaphore)

    async def test_rpc_failure_preserves_error_and_restores_capacity_and_context(self):
        quoter, _, provider, payload = await self.setup_preparation()
        failure = RuntimeError('fixture Helpers transport failed')
        provider.responses = [failure]
        with self.assertRaisesRegex(RuntimeError, 'fixture Helpers transport failed'):
            await TransactionPreparation(quoter).prepare(payload)
        self.assertEqual(len(provider.calls), 1)
        self.assert_released(quoter.engine.semaphore)

    async def test_current_output_cannot_relax_captured_minimum_and_priority_does_not_leak(self):
        quoter, _, provider, payload = await self.setup_preparation()
        provider.responses = [encoded(measured(100, stages=[stage(0, WETH, CORE, 10000, 100)]))]
        with self.assertRaisesRegex(InvalidPreview, 'Accepted scalar output minimum cannot be met'):
            await TransactionPreparation(quoter).prepare(payload)
        self.assertEqual(decode(provider)[-1]['plan']['minimumOutput'], 19800)
        self.assertEqual(len(provider.calls), 1)
        self.assert_released(quoter.engine.semaphore)


if __name__ == '__main__':
    unittest.main()
