"""Legacy Core quotes observe latest without manufacturing a canonical head."""
import asyncio
from fractions import Fraction
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from web3 import AsyncWeb3

from cybergold_candidate.issuance_capacity import read_supply_capacity, exhausted_capacity_error
from cybergold_candidate.quote_cache import BasketMath, GrossSeeds, IntentSharing, VerifiedGrossSeed
from cybergold_candidate.quote_history import QuoteHistory, route_key
from cybergold_candidate.quote_models import PoolBaseline
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
from cybergold_candidate.uniswap_routes import v3_plan
from test_quote_intent import ASSET_A, HASH, SETTINGS, WETH, request, service
from test_exhausted_issuance_capacity import Provider as CapacityProvider, SETTINGS as CAPACITY_SETTINGS


async def discard(_):
    pass


def latest_context():
    return {'chainId': 1, 'blockHash': None, 'blockNumber': None, 'blockTag': 'latest',
            'verification': 'quote-observation', 'observedAt': 'now'}


def plan():
    return v3_plan('0x' + WETH[2:].lower() + '0001f4' + ASSET_A[2:].lower(), 'exact-in', 100)


class CoreLatestTests(unittest.IsolatedAsyncioTestCase):
    def assert_latest_context(self, context):
        self.assertIsNone(context['blockNumber'])
        self.assertIsNone(context['blockHash'])
        self.assertEqual(context['blockTag'], 'latest')
        self.assertEqual(context['verification'], 'quote-observation')

    def assert_latest_wire(self, provider, wire):
        self.assertTrue(provider.calls)
        self.assertTrue(all(method == 'eth_call' for method, _ in provider.calls), provider.calls)
        self.assertTrue(all(params[1] == 'latest' for _, params in provider.calls))
        batches = wire.batches + wire.capacity_batches
        self.assertTrue(batches)
        self.assertTrue(all(row['method'] == 'eth_call' and row['params'][1] == 'latest'
                            for batch in batches for row in batch))

    async def test_all_core_modes_and_native_variants_use_only_latest_contract_reads(self):
        expected = {'issue-exact-in': '200', 'issue-exact-out': '52',
                    'redeem-exact-in': '200', 'redeem-exact-out': '102'}
        for mode, output in expected.items():
            for native in (False, True):
                with self.subTest(mode=mode, native=native):
                    intent, provider, routes, wire = service()
                    try:
                        result = await intent.get(request(mode, native), discard)
                        self.assertEqual(result['displayAmount'], output)
                        self.assert_latest_context(result['context'])
                        self.assert_latest_wire(provider, wire)
                        self.assertGreater(result['metrics']['candidateCalls'], 0)
                    finally:
                        await routes.close()

    async def test_latest_business_final_probe_is_completed_and_does_not_claim_canonicality(self):
        for mode in ('issue-exact-in', 'issue-exact-out', 'redeem-exact-in', 'redeem-exact-out'):
            with self.subTest(mode=mode):
                intent, provider, routes, wire = service()
                self.addAsyncCleanup(routes.close)
                shared = IntentSharing(intent)
                self.addAsyncCleanup(shared.close)
                result = await asyncio.wait_for(shared.get(request(mode), discard), 2)
                diagnostics = result['quoteDiagnostics']
                evidence = diagnostics['providerQualifications']
                final = next(row for row in evidence['rows'] if row['attempt'] == evidence['selectedAttempt'])
                self.assertEqual((diagnostics['phase'], final['stage'], final['outcome']),
                                 ('final-preview', 'tolerance', 'qualified'))
                self.assertEqual(final['executionAmount'], result['executionAmount'])
                self.assertGreaterEqual(final['completedMs'], final['startedMs'])
                self.assertEqual(evidence['pending'], 0)
                self.assertFalse(any(row['outcome'] == 'running' for row in evidence['rows']))
                self.assertFalse(any(row['stage'] == 'canonicality' for row in evidence['rows']))
                self.assert_latest_context(result['context'])
                self.assert_latest_wire(provider, wire)

    async def test_latest_stopped_business_quote_drains_pending_probe_before_final_evidence(self):
        from test_issue_candidate_updates import IssueCandidateUpdates
        from cybergold_candidate.quote_budget import QuoteBudget, budget_context
        intent, routes, control, trace = IssueCandidateUpdates.prepare(self, hold_later=True)
        provider = routes.rpc.w3.provider
        budget = QuoteBudget()
        async def run():
            with budget_context(budget):
                return await budget.produce(intent.get(request('issue-exact-in'), trace.emit))
        operation = asyncio.create_task(run())
        try:
            await asyncio.wait_for(trace.later_started.wait(), 2)
            self.assertTrue(trace.first.is_set())
            budget.finish_selection('best-initial')
            result = await asyncio.wait_for(operation, 2)
        finally:
            control.release.set()
            trace.release_later.set()
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        self.assertEqual(result['executionAmount'], '200')
        evidence = result['quoteDiagnostics']['providerQualifications']
        self.assertEqual(evidence['pending'], 0)
        self.assertEqual(evidence['cancelled'], 1)
        self.assertFalse(any(row['outcome'] == 'running' for row in evidence['rows']))
        final = next(row for row in evidence['rows'] if row['attempt'] == evidence['selectedAttempt'])
        self.assertEqual((final['stage'], final['outcome']), ('tolerance', 'qualified'))
        self.assert_latest_context(result['context'])
        self.assertTrue(all(method == 'eth_call' and params[1] == 'latest' for method, params in provider.calls))
        self.assertEqual(routes.engine.semaphore._value, 8)

    async def test_latest_sharing_has_no_context_prerequisite_and_no_completed_quote_reuse(self):
        intent, provider, routes, wire = service()
        self.addAsyncCleanup(routes.close)
        provider.finish_final = asyncio.Event()
        shared = IntentSharing(intent)
        self.addAsyncCleanup(shared.close)
        one = asyncio.create_task(shared.get(request('issue-exact-out'), discard))
        await provider.final_started.wait()
        two = asyncio.create_task(shared.get(request('issue-exact-out'), discard))
        while not shared.joined:
            await asyncio.sleep(0)
        one.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await one
        provider.finish_final.set()
        value = await two
        self.assert_latest_context(value['context'])
        self.assertEqual((shared.started, shared.joined), (1, 1))
        self.assertFalse(shared.pending)
        await shared.get(request('issue-exact-out'), discard)
        self.assertEqual(shared.started, 2)
        self.assert_latest_wire(provider, wire)

    async def test_explicit_pin_retains_real_context_and_canonical_disproof(self):
        intent, provider, routes, wire = service()
        self.addAsyncCleanup(routes.close)
        block = {'number': 101, 'hash': HASH}
        value = await intent.get(request('issue-exact-in'), discard, block=block)
        self.assertEqual(value['context']['blockHash'], HASH)
        self.assertEqual(value['context']['blockNumber'], '101')
        self.assertNotIn('blockTag', value['context'])
        self.assertTrue(any(method.startswith('eth_getBlock') for method, _ in provider.calls))
        self.assertTrue(all(params[1] == {'blockHash': HASH, 'requireCanonical': True}
                            for method, params in provider.calls if method == 'eth_call'))
        provider.reorg = True
        with self.assertRaises(SnapshotChanged):
            await intent.get(request('issue-exact-in'), discard, block=block)

    async def test_latest_basket_math_shares_overlap_but_reloads_changed_completed_values(self):
        cache, started, release = BasketMath(), asyncio.Event(), asyncio.Event()
        values = []
        async def produce():
            values.append(len(values) + 1)
            started.set()
            await release.wait()
            return {'raw': values[-1]}
        args = (1, LATEST_BLOCK, 'asset', 'data', produce)
        one = asyncio.create_task(cache.read(*args))
        await started.wait()
        two = asyncio.create_task(cache.read(*args))
        await asyncio.sleep(0)
        release.set()
        self.assertEqual(await one, {'raw': 1})
        self.assertEqual(await two, {'raw': 1})
        self.assertEqual(values, [1])
        self.assertEqual(await cache.read(*args), {'raw': 2})
        self.assertFalse(cache.completed)
        self.assertFalse(cache.pending.pending)

    async def test_latest_supply_fallback_keeps_actual_exhaustion_constraint(self):
        provider = CapacityProvider(capacity=(250, 250, 1000))
        rpc = SimpleNamespace(w3=AsyncWeb3(provider))
        values = await read_supply_capacity(rpc, CAPACITY_SETTINGS, LATEST_BLOCK)
        self.assertEqual(values, (250, 250, 1000))
        error = exhausted_capacity_error(values)
        self.assertEqual(error.code, 'issuance-cap-exceeded')
        self.assertTrue(all(params[1] == 'latest' for params in provider.calls))

    async def test_latest_gross_hints_never_become_pinned_exact_proofs(self):
        value, context = request('redeem-exact-out'), latest_context()
        result = {'context': context, 'executionAmount': '103'}
        advisory, verified = GrossSeeds(), VerifiedGrossSeed()
        advisory.observe(value, result)
        self.assertEqual(advisory.suggest(value, context), 103)
        verified.observe(value, result)
        self.assertIsNone(verified.suggest(value, context))
        self.assertFalse(verified.rows)
        marker = {**context, 'blockHash': 'latest', 'blockNumber': '0'}
        marker.pop('blockTag')
        verified.observe(value, {**result, 'context': marker})
        self.assertIsNone(verified.suggest(value, marker))
        self.assertFalse(verified.rows)
        pinned = {**context, 'blockHash': HASH, 'blockNumber': '101'}
        pinned.pop('blockTag')
        verified.observe(value, {**result, 'context': pinned})
        self.assertEqual(verified.suggest(value, pinned), 103)
        self.assertIsNone(verified.suggest(value, context))

    async def test_latest_history_baselines_and_observations_remain_advisory_without_headers(self):
        history = QuoteHistory(SETTINGS)
        self.addAsyncCleanup(history.close)
        context, route = latest_context(), plan()
        rpc = SimpleNamespace(assert_canonical=AsyncMock(side_effect=AssertionError('header read')))
        provider = SimpleNamespace(route_baseline=AsyncMock(return_value=PoolBaseline(Fraction(2), Fraction(9995, 10000))),
                                   registry=SimpleNamespace(get_rpc=lambda: rpc))
        await history.acquire_route(provider, route, LATEST_BLOCK, context)
        value = request('issue-exact-in')
        result = {'context': context, 'displayAmount': '200', 'executionAmount': '100'}
        history.observe(value, result, [('exact-in', [{'target': {'amount': '100'},
                            'best': {'routePlan': route, 'quote': '200'}}])])
        packet = history.packet(value)
        self.assertEqual(len(packet['routes']), 1)
        self.assert_latest_context(packet['routes'][0]['context'])
        self.assert_latest_context(packet['routes'][0]['exchangeContext'])
        self.assert_latest_context(packet['whole'][0]['context'])
        self.assertIn((*route_key(route), None), history.baselines)
        rpc.assert_canonical.assert_not_called()

    async def test_latest_state_and_fact_acquisition_have_null_public_identity(self):
        history, context = QuoteHistory(SETTINGS), latest_context()
        self.addAsyncCleanup(history.close)
        facts = {'context': context, 'basket': {'assets': {'status': 'success', 'value': [ASSET_A]},
            'targetsPpm': {'status': 'success', 'value': [1000000]},
            'cygldPerUnitFp18': {'status': 'success', 'value': [10**18]}},
            'fees': {'issuancePpm': {'status': 'success', 'value': '0'},
                     'helpersPpm': {'status': 'success', 'value': '0'}}}
        history.facts_observed(facts)
        self.assert_latest_context(history.facts[None]['context'])
        history.batch = AsyncMock(side_effect=[[1, 10, 10, 0, [], False], [{'activeAvailableRaw': 100}]])
        rpc = SimpleNamespace(assert_canonical=AsyncMock(side_effect=AssertionError('header read')))
        await history.acquire_state(rpc, LATEST_BLOCK, context)
        self.assert_latest_context(history.protocol_model()['context'])
        self.assertEqual(history.states[None]['state']['available'], ['100'])
        rpc.assert_canonical.assert_not_called()
        history.ensure_state(rpc, LATEST_BLOCK, context)
        self.assertFalse(history.tasks)


if __name__ == '__main__':
    unittest.main()
