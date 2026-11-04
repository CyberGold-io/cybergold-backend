"""Known L1 bodies retain the established cached-route priority before coalescing."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from cybergold_candidate import route_work_slots as work
from cybergold_candidate.route_work_slots import engine_work
from test_quoter_plan_simulation import fixture, market, measured, encoded, stage, CORE, WETH, PAXG
from cybergold_candidate.helpers_execution import ABI
from web3 import Web3


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


class RetainedBootstrapPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def setup_quote(self, *, amount=10000):
        request, _ = market()
        request['inputs'][0]['amount'] = str(amount)
        historical_request, historical_plan = market()
        for row in (historical_request['inputs'][0], historical_plan['allocations'][0],
                    historical_plan['body']['branches'][0]):
            row['amount' if 'amount' in row else 'amountIn'] = '5000'
        _, quoter, rpc, provider = fixture()
        self.addAsyncCleanup(quoter.close)
        quoter.seed_routes = lambda *_: None
        quoter.basis_reader = lambda *_: asyncio.sleep(0, result=([], []))
        quoter.discover = lambda *_: asyncio.sleep(0)
        quoter.route_provider_factory = lambda: []
        selected, ordinary = [], []
        original = quoter.candidate
        async def candidate(request, *args, selected=None, **kwargs):
            if selected is None:
                ordinary.append(work._bootstrap.get())
                await asyncio.Event().wait()
            selected_calls.append(deepcopy(request['inputs']))
            return await original(request, *args, selected=selected, **kwargs)
        selected_calls = selected
        quoter.candidate = candidate
        order = []
        original_request = provider.make_request
        def response(_method, params):
            _, values = Web3().eth.contract(abi=ABI).decode_function_input(params[0]['data'])
            funded = int(values['plan']['inputs'][0]['amount'])
            return encoded(measured(funded * 2, stages=[stage(0, WETH, CORE, funded, funded * 2)]))
        provider.responses = [response, response]
        async def make_request(method, params):
            order.append('helpers')
            return await original_request(method, params)
        provider.make_request = make_request
        historical = {'request': historical_request, 'inputs': deepcopy(historical_request['inputs']),
                      'plan': historical_plan, 'quotedOutput': '9990'}
        return request, quoter, rpc, provider, historical, selected, ordinary, order

    async def test_l1_original_and_budget_body_own_priority_before_sql_coalesces(self):
        request, quoter, rpc, provider, historical, selected, ordinary, order = await self.setup_quote()
        slots = quoter.engine.semaphore
        for _ in range(8):
            await slots.acquire()
        async def competitor(index):
            async with engine_work(slots):
                order.append('sdk-'+str(index))
        competitors = [asyncio.create_task(competitor(index)) for index in range(8)]
        await until(lambda: len(slots._ordinary) == 8)
        sql_release = asyncio.Event()
        async def neighbors():
            await sql_release.wait()
            return [{'family': 'market', 'side': 'lower', 'quote': historical}]
        observations = []
        async def observe(frame):
            observations.append(deepcopy(frame['value']))
        task = asyncio.create_task(quoter.quote(request, neighbors=neighbors,
            route_seeds=[historical], on_candidate=observe))
        released = False
        try:
            await until(lambda: len(selected) == 2 and len(slots._priority) == 2)
            self.assertEqual(len(slots._ordinary), 8)
            self.assertEqual(provider.calls, [])
            sql_release.set()
            await until(lambda: len(selected) == 4)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual((len(slots._ordinary), len(slots._priority)), (8, 2),
                             'SQL subscribers must coalesce behind the original priority owners')
            for _ in range(8):
                slots.release()
            released = True
            await until(lambda: len(observations) == 4)
            await asyncio.gather(*competitors)
            self.assertEqual(order[:2], ['helpers', 'helpers'])
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual({(row['inputs'][0]['amount'], row['quotedOutput']) for row in observations},
                             {('5000', '9990'), ('10000', '19980')})
            self.assertEqual(sum(row['pricingEvidence']['rpcCalls'] for row in observations), 2)
            self.assertEqual(sum(row['pricingEvidence']['coalesced'] for row in observations), 2)
            self.assertTrue(ordinary, 'ordinary exploration still starts alongside retained bodies')
            self.assertFalse(any(ordinary), 'retained priority must not elevate ordinary SDK exploration')
            self.assertEqual(rpc.heads, [])
            quoter.engine.quote_sdk_branches.assert_not_called()
        finally:
            sql_release.set()
            task.cancel()
            for competitor_task in competitors:
                competitor_task.cancel()
            await asyncio.gather(task, *competitors, return_exceptions=True)
            if not released:
                for _ in range(8):
                    slots.release()
        self.assertEqual((slots._value, len(slots._ordinary), len(slots._priority)), (8, 0, 0))

    async def test_cancelled_l1_body_owners_leave_no_waiter_or_rpc(self):
        request, quoter, rpc, provider, historical, selected, ordinary, order = await self.setup_quote()
        slots = quoter.engine.semaphore
        for _ in range(8):
            await slots.acquire()
        task = asyncio.create_task(quoter.quote(request, route_seeds=[historical]))
        try:
            await until(lambda: len(selected) == 2 and len(slots._priority) == 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual((slots._value, len(slots._ordinary), len(slots._priority)), (0, 0, 0))
            self.assertEqual(provider.calls, [])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for _ in range(8):
                slots.release()
        self.assertEqual(slots._value, 8)

    async def test_failed_cached_body_does_not_pass_priority_to_sdk_recovery(self):
        request, quoter, rpc, provider, historical, selected, ordinary, order = await self.setup_quote(amount=5000)
        provider.responses = [{'error': {'code': 3, 'message': 'execution reverted',
            'data': '0xdb8b21c4'+rpc.w3.codec.encode(['address', 'uint256'], [PAXG, 7]).hex()}}]
        recovered = asyncio.Event()
        priorities = []
        async def compose(*_args, **_kwargs):
            priorities.append(work._bootstrap.get())
            return None
        async def recover(*_args, **_kwargs):
            priorities.append(work._bootstrap.get())
            recovered.set()
            return []
        with patch('cybergold_candidate.quoter.core_market_recovery.compose_core_market', side_effect=compose), \
                patch('cybergold_candidate.quoter.capacity_recovery.recover_selected', side_effect=recover):
            task = asyncio.create_task(quoter.quote(request, route_seeds=[historical]))
            try:
                await asyncio.wait_for(recovered.wait(), 3)
                self.assertEqual(priorities, [False, False])
                self.assertEqual(len(provider.calls), 1)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(quoter.engine.semaphore._value, 8)


if __name__ == '__main__':
    unittest.main()
