"""Contract-rejected Core plans can offer measured retained-residual bodies."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from web3 import Web3

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.bootstrap import current_bootstrap
from cybergold_candidate.quoter.cooperative import CHECKPOINT
from cybergold_candidate.quoter.dormant_routes import with_dormant_routes
from cybergold_candidate.quoter.plan_call import compile_call
from cybergold_candidate.quoter.residual_retention import residual_retention_proposal
from cybergold_candidate.quoter.reuse_routes import proposal_identity, funded_route_identity
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.quote_errors import QuoteFailure, public_quote_error
from cybergold_candidate.route_work_slots import PricingSlots
from cybergold_candidate.tx_preparation import TransactionPreparation


FIXTURES = Path(__file__).parent / 'fixtures/quoter-acquired'
FIXTURE = json.loads((FIXTURES / 'shared-initial-core.json').read_text())
CAPTURED = json.loads((FIXTURES / 'core-residual-retention.json').read_text())
FAILED, RETAINED = CAPTURED['failed'], CAPTURED['retained']


class Harness:
    def __init__(self, case, *, error=None, hold_retention=False):
        self.calls, self.graph, self.sessions, self.pending = [], [], [], set()
        self.retaining_started, self.release = asyncio.Event(), asyncio.Event()
        self.error = error or FAILED['response']
        outer = self

        class Provider:
            async def make_request(self, method, params):
                case.assertEqual(method, 'eth_call')
                # Only the exact captured complete body receives a success.
                # Fresh preparation separately asserts the accepted call.
                retaining = params[0]['data'] == RETAINED['params'][0]['data']
                outer.calls.append({'retaining': retaining, 'params': deepcopy(params)})
                if not retaining:
                    return deepcopy(outer.error)
                case.assertEqual(params[0], RETAINED['params'][0])
                case.assertEqual(params[2], RETAINED['params'][2])
                case.assertEqual(params[1], 'latest')
                outer.retaining_started.set()
                if hold_retention:
                    task = asyncio.current_task()
                    outer.pending.add(task)
                    try:
                        await outer.release.wait()
                    finally:
                        outer.pending.remove(task)
                return deepcopy(RETAINED['response'])

        self.rpc = SimpleNamespace(w3=SimpleNamespace(codec=Web3().codec, provider=Provider()))
        seed = deepcopy(FIXTURE['seed'])
        registry = SimpleNamespace(chain=31338,
            inventory={row['id']: deepcopy(row) for row in FIXTURE['pools']},
            seed=seed, get_rpc=lambda: self.rpc)
        registry.inventory[seed['id']] = seed
        self.slots = PricingSlots(8)
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=FIXTURE['request']['outputCurrency'],
            NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=FIXTURE['params'][0]['to'],
            CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS=FIXTURE['adapter'])

        async def basis(_block):
            return deepcopy(FIXTURE['assets']), deepcopy(FIXTURE['weights'])

        self.q = Quoter(settings, SimpleNamespace(registry=registry, semaphore=self.slots), basis_reader=basis)

        async def discover(*_):
            self.sessions.append(current_bootstrap())
            await self.release.wait()

        self.q.discover = discover
        self.case = case

    def blocked_graph(self, _pools, source, target, *_):
        self.graph.append((source, target))
        while not self.release.is_set():
            yield CHECKPOINT
        return []

    def seed(self):
        return self.q.plan_simulator.project(deepcopy(FIXTURE['request']), deepcopy(FAILED['plan']),
            {**deepcopy(FIXTURE['response']), 'observedAt': '2026-11-05T10:00:00Z'},
            {'issued': 1, 'coalesced': 0, 'reused': 0}, rpc=self.rpc,
            tag='latest', block=None, pricing=True, candidate=None)

    def assert_drained(self):
        self.case.assertEqual(self.slots._value, 8)
        self.case.assertFalse(self.slots._ordinary)
        self.case.assertFalse(self.slots._priority)
        self.case.assertFalse(self.pending)
        for session in self.sessions:
            self.case.assertTrue(session._closed)
            self.case.assertTrue(session._close_task.done())
            self.case.assertTrue(all(task.done() for task in session._tasks))


class ResidualRetentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_body_identity_and_missing_description(self):
        original, request = deepcopy(FAILED['plan']), deepcopy(FIXTURE['request'])
        proposal = residual_retention_proposal(request, original)
        self.assertEqual(original, FAILED['plan'])
        self.assertEqual(proposal['inputs'], request['inputs'])
        self.assertEqual(proposal['plan']['allocations'], original['allocations'])
        self.assertEqual(proposal['plan']['body']['branches'][0]['data']['acquisitions'],
                         original['body']['branches'][0]['data']['acquisitions'])
        self.assertNotEqual(proposal_identity(proposal),
                            proposal_identity({'inputs': request['inputs'], 'plan': original}))
        self.assertIsNone(residual_retention_proposal(request, proposal['plan']))
        value = {'request': request, 'inputs': request['inputs'], 'plan': proposal['plan']}
        self.assertEqual(with_dormant_routes(value, FIXTURE['seed'])['plan'], proposal['plan'])
        body_only = deepcopy(original)
        body_only.pop('conversions')
        minimal = residual_retention_proposal(request, body_only)
        self.assertEqual(minimal['plan']['body'], proposal['plan']['body'])
        self.assertEqual(set(minimal['plan']['conversions']), {'0:residual:0', '0:residual:1'})

    async def test_search_invalidates_original_and_prepares_distinct_retaining_plan(self):
        h, budget, events = Harness(self), QuoteBudget(), []
        old = h.seed()
        original_id = funded_route_identity(old)

        async def event(row):
            events.append(deepcopy(row))
            qualified = any(row.get('value', {}).get('searchCoverage', {}).get('selectedPhase')
                == 'residual-retention' for row in events if row.get('value'))
            invalidated = any(row.get('_replacesIdentity') == original_id and row.get('value') is None
                              for row in events)
            if qualified and invalidated:
                budget.finish_selection('qualified-and-invalidated')

        try:
            with budget_context(budget), patch('cybergold_candidate.quoter.custom_routes.path_steps', h.blocked_graph):
                async with asyncio.timeout(3):
                    value = await h.q.get(FIXTURE['request'], core_only=True, seed=old, on_candidate=event)
            self.assertEqual(value['quotedOutput'], '7535050530876000')
            self.assertEqual(value['estimatedRetainedInputCharges'], [{'branch': 0, 'stage': 2,
                'currency': FIXTURE['request']['inputs'][0]['currency'], 'amount': '305492812575'}])
            self.assertEqual(value['searchCoverage']['selectedPhase'], 'residual-retention')
            self.assertNotEqual(funded_route_identity(value), original_id)
            self.assertTrue(any(row.get('_replacesIdentity') == original_id and row.get('value') is None
                and row.get('code') == 'quote-contract-reverted' for row in events))
            self.assertEqual(sum(row['retaining'] for row in h.calls), 1)
            self.assertTrue(any(row['params'][0]['data'] == FAILED['params'][0]['data'] for row in h.calls))
            self.assertEqual(with_dormant_routes(value, FIXTURE['seed'])['plan'], value['plan'])
            h.assert_drained()

            # Fresh preparation uses the selected routes and accepted minimum;
            # it cannot invoke the search fallback or insert dormant AMM hops.
            user, minimum = '0x0000000000000000000000000000000000000077', '7400000000000000'
            compiled = compile_call(value['request'], value['plan'], chain=31338,
                helpers=h.q.helpers, core=h.q.core, contract=h.q.plan_simulator.contract,
                pricing=False, minimum=int(minimum), accepted_core=[], recipient=user)

            async def replay(method, params):
                self.assertEqual(method, 'eth_call')
                self.assertEqual(params, compiled.params)
                return deepcopy(RETAINED['response'])

            with patch.object(h.rpc.w3.provider, 'make_request', replay):
                prepared = await TransactionPreparation(h.q, now=lambda: 1234).prepare({
                    'quote': value, 'sender': user, 'recipient': user,
                    'acceptedBounds': {'inputs': value['inputs'], 'minimumOutput': minimum}})
            self.assertEqual(prepared['outputMinimum'], minimum)
            self.assertEqual(prepared['economicQuote']['plan'], value['plan'])
            for row in prepared['planDescription']['branches'][0]['data']['continuations']:
                self.assertEqual(row['route']['routes'], [])
                self.assertEqual(row['route']['minimumOutput'], '0')
            self.assertEqual(prepared['economicQuote']['estimatedRetainedInputCharges'],
                             value['estimatedRetainedInputCharges'])

            # Accepting the old routed plan still returns its own ordinary
            # rejection, rather than substituting an unaccepted execution body.
            calls = []

            async def reject(method, params):
                calls.append(deepcopy(params))
                return deepcopy(FAILED['response'])

            with patch.object(h.rpc.w3.provider, 'make_request', reject):
                with self.assertRaises(QuoteFailure) as raised:
                    await TransactionPreparation(h.q).prepare({'quote': old, 'sender': user, 'recipient': user})
            self.assertEqual(raised.exception.code, 'quote-contract-reverted')
            self.assertEqual(len(calls), 1)
        finally:
            await h.q.close()

    async def test_cancel_drains_owned_retention_and_ordinary_work(self):
        h, task = Harness(self, hold_retention=True), None
        try:
            with patch('cybergold_candidate.quoter.custom_routes.path_steps', h.blocked_graph):
                task = asyncio.create_task(h.q.get(FIXTURE['request'], core_only=True))
                async with asyncio.timeout(3):
                    await h.retaining_started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            h.assert_drained()
            self.assertEqual(sum(row['retaining'] for row in h.calls), 1)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await h.q.close()

    async def test_transport_and_typed_contract_errors_do_not_nominate_retention(self):
        errors = [({'error': {'code': -32001, 'message': 'temporarily unavailable'}}, 'rpc-unavailable'),
            ({'error': {'code': 3, 'data': Web3.to_hex(Web3.keccak(text='InsufficientReserveBalance()'))[:10]}},
             'insufficient-reserve-balance')]
        for error, code in errors:
            with self.subTest(code=code):
                h, budget = Harness(self, error=error), QuoteBudget(initial=0.04, extension=0)
                try:
                    with budget_context(budget), patch('cybergold_candidate.quoter.custom_routes.path_steps', h.blocked_graph):
                        with self.assertRaises(Exception) as raised:
                            await h.q.get(FIXTURE['request'], core_only=True)
                    self.assertEqual(public_quote_error(raised.exception)['code'], code)
                    self.assertTrue(h.calls)
                    self.assertFalse(any(row['retaining'] for row in h.calls))
                    h.assert_drained()
                finally:
                    await h.q.close()


if __name__ == '__main__':
    unittest.main()
