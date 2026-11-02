"""Generic discovery identity, actual optional selection and repair integration."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import json
from pathlib import Path
import unittest

from cybergold_candidate.quoter.discovery import families, market_plan, route_identity
from cybergold_candidate.quoter import Quoter
from quoter_fixture import historical_service, historical_data, historical_route, service, synthetic_pool
from test_universal_quote import BLOCK, CORE, PAXG, WETH, fixture_plan_simulator


class FamilyTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_tiny_incident_acquired_state_replays_offline(self):
        from quoter_fixture import expand, Registry
        from cybergold_candidate.route_quote_engine import RouteQuoteEngine
        from cybergold_candidate.sdk_worker import SdkWorker
        from test_universal_quote import settings
        from types import SimpleNamespace
        capture = json.loads((Path(__file__).parent / 'fixtures/quoter-acquired/tiny-original.json').read_text())
        quoted = capture['quote']; block = {'number': int(quoted['context']['blockNumber']), 'hash': quoted['context']['blockHash']}
        registry = Registry(list(capture['inventory'].values()), block)
        registry.core = capture['request']['outputCurrency']
        registry.observed = {key: expand(pool) for key, pool in capture['observed'].items()}
        config = SimpleNamespace(**{**vars(settings()), 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': registry.core})
        engine = RouteQuoteEngine(config, registry, sdk=SdkWorker())
        self.addAsyncCleanup(engine.close); self.addAsyncCleanup(registry.pending.close)
        async def basis(_):
            return deepcopy(capture['basis'])
        async def simulate(request, selected, **kwargs):
            kwargs.setdefault('block', block)
            return await fixture_plan_simulator(q, request, selected, basis_reader=basis, **kwargs)
        q = Quoter(config, engine, plan_simulator=simulate)
        value = await q.candidate(capture['request'], 0, 'core-first', block, *capture['basis'], selected=quoted['plan'])
        self.assertEqual(value['quotedOutput'], '758677485149082')
        self.assertEqual(value['estimatedRetainedInputCharges'], [])
    async def test_metadata_enrichment_preserves_physical_family_route_identity(self):
        q, case = historical_service(self)
        source = case['request']['inputs'][0]['currency']
        before = {route_identity(route) for _, routes in families(q.engine.registry, source, q.core, q.core) for route in routes}
        for pool in q.engine.registry.inventory.values():
            if pool['protocol'] == 'v3':
                pool['discovery'] = {'optional': 'new'}
                pool['token0']['decimalsKnown'] = True
        after = {route_identity(route) for _, routes in families(q.engine.registry, source, q.core, q.core) for route in routes}
        self.assertEqual(after, before)
        self.assertGreater(len(before), 39)

    async def test_acquired_catalog_search_and_seed_replay_use_current_economics(self):
        q, case = historical_service(self, exploration_seed=1700)
        first = await q.get(case['request'])
        # Expanded acquired inventory is the historical no-seed warm condition.
        self.assertGreaterEqual(int(first['quotedOutput']), 3843369604668420324)
        self.assertLessEqual(first['metrics']['optionalSearch']['starts'], 16)
        seed_row = next(row for row in case['routes'] if row['output'] == '3852018735882976112')
        selected = market_plan(case['request']['inputs'][0]['currency'], q.core,
            historical_route(q, seed_row), int(case['request']['inputs'][0]['amount']))
        previous = await q.candidate(case['request'], 0, 'core-first', historical_data()['anchor'],
            *case['basis'], selected=selected)
        previous['quotedOutput'] = '99999999999999999999999'  # Stale numbers are not trusted.
        refreshed = await q.get(case['request'], seed=previous)
        self.assertEqual(refreshed['quotedOutput'], seed_row['output'])
        self.assertEqual(refreshed['metrics']['optionalSearch']['randomSeed'], '1700')

    async def test_optional_linear_repair_is_ranked_only_after_complete_replay(self):
        pools = [synthetic_pool(WETH, PAXG, 101, 'v2'), synthetic_pool(PAXG, CORE, 102, 'v4')]
        q = service(self, pools)
        q.seed_routes = lambda *_: None
        async def discover(*_):
            pass
        q.discover = discover
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
        updates = []
        async def publish(frame):
            updates.append(deepcopy(frame['value']))
        value = await q.get(request, publish)
        self.assertEqual(value['inputs'][0]['amount'], '3025')
        self.assertEqual(value['quotedOutput'], '2992')
        self.assertEqual(value['metrics']['optionalSearch']['repairs'], 1)
        self.assertTrue(updates)
        self.assertTrue(all(int(row['quotedOutput']) > 0 for row in updates))
        self.assertEqual(value['request']['inputs'][0]['amount'], '10000')


class HelpersPrefixFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def run_optional(self, intent, *, rejection=None, allowance=16):
        from cybergold_candidate.quote_budget import QuoteBudget, budget_context
        from cybergold_candidate.quoter.amm import PartialPath
        from cybergold_candidate.quoter.contracts import SearchSession, new_path_trace
        from cybergold_candidate.quoter.exploration import explore
        from cybergold_candidate.rpc_block_context import LATEST_BLOCK
        source, target = (WETH, CORE) if intent == 0 else (CORE, WETH)
        route = [{'pool': synthetic_pool(source, target, 999, 'v2'),
                  'zeroForOne': source.lower() < target.lower()}]
        request = {'intent': intent, 'inputs': [{'currency': source, 'amount': '10001'}],
                   'outputCurrency': target}
        calls, traces = [], []
        async def price(path, amount, block, bank, observations):
            trace = new_path_trace(path, amount)
            self.assertIsNotNone(trace)
            traces.append(trace)
            raise PartialPath(trace)
        quoter = SimpleNamespace(amm=SimpleNamespace(family_offers=lambda *_: [('family', [(route, ['uniroute-local'])])]),
            engine=SimpleNamespace(registry=SimpleNamespace(chain=1)), price_path=AsyncMock(side_effect=price))
        async def evaluate(*args, **options):
            calls.append(options)
            if len(calls) == 1 and rejection is not None:
                raise rejection
            return {'quotedOutput': '123'}
        funding = [{'currency': source, 'amount': '1234'}]
        repaired = market_plan(source, target, route, 1234, origins=['uniroute-local'])
        repair = AsyncMock(return_value=(funding, repaired))
        session = SearchSession(allowance, 0)
        session.discovery_done.set()
        # A high SDK bound/incumbent cannot authenticate latest Helpers output.
        # Those mathematical component functions remain independently tested.
        with patch('cybergold_candidate.quoter.exploration.repair_prefix', repair), \
             patch('cybergold_candidate.quoter.policy.output_upper_bound', side_effect=AssertionError('SDK prune')) as bound, \
             budget_context(QuoteBudget()):
            await explore(quoter, request, LATEST_BLOCK, session, evaluate,
                lambda: {'quotedOutput': '99999999999999999'}, observations={})
        bound.assert_not_called()
        return request, quoter, session, calls, traces, repair, funding, repaired

    async def test_successful_helpers_family_candidate_never_runs_sdk_diagnostics(self):
        for intent in (0, 1):
            with self.subTest(intent=intent):
                _, quoter, session, calls, _, repair, _, _ = await self.run_optional(intent)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['phase'], 'route-family')
                self.assertEqual((session.starts, session.repairs, session.pruned), (1, 0, 0))
                quoter.price_path.assert_not_awaited()
                repair.assert_not_awaited()

    async def test_reverted_helpers_path_uses_sdk_trace_and_requalifies_repaired_funding(self):
        from cybergold_candidate.market_fee import routed_sell_budget
        from cybergold_candidate.quote_errors import QuoteFailure
        for intent in (0, 1):
            with self.subTest(intent=intent):
                request, quoter, session, calls, traces, repair, funding, repaired = await self.run_optional(
                    intent, rejection=QuoteFailure('quote-contract-reverted'))
                self.assertEqual(len(calls), 2)
                self.assertTrue(calls[0]['partial'])
                self.assertEqual(calls[1], {'selected': repaired, 'funding': funding, 'phase': 'backward-prefix'})
                self.assertEqual((session.starts, session.repairs), (2, 1))
                self.assertEqual(len(traces), 1)
                expected = 10001 - routed_sell_budget(10001, 1000)[1] if intent == 1 else 10001
                self.assertEqual(traces[0].funded, expected)
                repair.assert_awaited_once_with(quoter, request, traces[0],
                    {'number': 0, 'hash': 'latest', 'tag': 'latest'}, origins=['uniroute-local'])
                self.assertEqual(calls[1]['selected']['conversions']['0:market']['discoveryOrigins'], ['uniroute-local'])

    async def test_rpc_failure_does_not_launch_sdk_repair_and_existing_allowance_still_applies(self):
        from cybergold_candidate.quote_errors import QuoteFailure
        _, quoter, session, calls, _, repair, _, _ = await self.run_optional(
            0, rejection=QuoteFailure('quote-unavailable'))
        self.assertEqual((len(calls), session.starts, session.repairs), (1, 1, 0))
        quoter.price_path.assert_not_awaited()
        repair.assert_not_awaited()
        _, quoter, session, calls, traces, repair, _, _ = await self.run_optional(
            0, rejection=QuoteFailure('quote-contract-reverted'), allowance=1)
        self.assertEqual((len(calls), session.starts, session.repairs, len(traces)), (1, 1, 0, 1))
        repair.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
