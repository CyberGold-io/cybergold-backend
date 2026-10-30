"""Generic discovery identity, actual optional selection and repair integration."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from cybergold_candidate.quoter.discovery import families, market_plan, route_identity
from cybergold_candidate.quoter import Quoter
from quoter_fixture import historical_service, historical_data, historical_route, service, synthetic_pool
from test_universal_quote import BLOCK, CORE, PAXG, WETH


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
        q = Quoter(config, engine)
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


if __name__ == '__main__':
    unittest.main()
