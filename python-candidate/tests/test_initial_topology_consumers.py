"""Shared initial queries must not defer a whole Core plan to the full graph."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from web3 import Web3

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.cooperative import CHECKPOINT
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.evaluate import evaluate_candidate
from cybergold_candidate.route_work_slots import PricingSlots
from cybergold_candidate.rpc_block_context import LATEST_BLOCK


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/quoter-acquired/shared-initial-core.json').read_text())
CORE = FIXTURE['request']['outputCurrency']


class InitialTopologyConsumersTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_initial_consumer_qualifies_without_entering_full_graph(self):
        for cold in (False, True):
            with self.subTest(cold_seed_only=cold):
                seed = deepcopy(FIXTURE['seed'])
                pools = {seed['id']: seed}
                if not cold:
                    pools.update({row['id']: deepcopy(row) for row in FIXTURE['pools']})
                calls, full_walks = [], []
                self_outer = self

                class Provider:
                    async def make_request(self, method, params):
                        self_outer.assertEqual(method, 'eth_call')
                        # The complete ABI call, latest tag and funding overrides
                        # match the captured live-qualified call byte for byte.
                        self_outer.assertEqual(params, FIXTURE['params'])
                        calls.append(deepcopy(params))
                        return deepcopy(FIXTURE['response'])

                rpc = SimpleNamespace(w3=SimpleNamespace(codec=Web3().codec, provider=Provider()))
                registry = SimpleNamespace(chain=31338, inventory=pools, seed=seed, get_rpc=lambda: rpc)
                engine = SimpleNamespace(registry=registry, semaphore=PricingSlots(8))
                settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
                    NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=FIXTURE['params'][0]['to'],
                    CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS=FIXTURE['adapter'])
                q = Quoter(settings, engine)
                request, assets, weights = deepcopy(FIXTURE['request']), FIXTURE['assets'], FIXTURE['weights']
                q.seed_routes(request, [])
                q.seed_routes(request, assets)
                session = RouteBootstrap([CustomRoutes(registry)], catalog=registry)
                graph_entered, graph_release = asyncio.Event(), asyncio.Event()

                def blocked_graph(_pools, source, target, *_args):
                    full_walks.append((source, target))
                    graph_entered.set()
                    while not graph_release.is_set():
                        yield CHECKPOINT
                    return []

                full_task = graph_wait = None
                try:
                    with bootstrap_scope(session), patch('cybergold_candidate.quoter.custom_routes.path_steps', blocked_graph):
                        # An earlier initial grid body registers the shared
                        # residual amount-1 queries, but publishes no ready hint.
                        await evaluate_candidate(q, request, 25, 'core-first', LATEST_BLOCK,
                                                 assets, weights, first=True)
                        owners = {(asset.lower(), CORE.lower(), 1): session._queries[asset.lower(), CORE.lower(), 1]
                                  for asset in assets}
                        attempts = {key: [entry['attempt'] for entry in entries] for key, entries in owners.items()}
                        self.assertTrue(all(not entry['offers'] for entries in owners.values() for entry in entries))
                        self.assertFalse(session._completed_offers)
                        full_task = asyncio.create_task(q.candidate(request, 100, 'core-first', LATEST_BLOCK,
                                                                   assets, weights, first=True))
                        graph_wait = asyncio.create_task(graph_entered.wait())
                        async with asyncio.timeout(3):
                            await asyncio.wait((full_task, graph_wait), return_when=asyncio.FIRST_COMPLETED)
                        self.assertTrue(full_task.done(), 'repeated initial consumer entered the blocked full graph')
                        value = await full_task
                        self.assertEqual(value['quotedOutput'], FIXTURE['expected']['quotedOutput'])
                        self.assertEqual(value['fees'], FIXTURE['expected']['fees'])
                        self.assertFalse(full_walks)
                        self.assertEqual(len(calls), 1)
                        for key, entries in owners.items():
                            self.assertIs(session._queries[key], entries)
                            for entry, attempt in zip(entries, attempts[key], strict=True):
                                self.assertIs(entry['attempt'], attempt)
                        self.assertEqual(session.revision, 0)
                        self.assertEqual(engine.semaphore._value, 8)
                finally:
                    for task in (full_task, graph_wait):
                        if task is not None:
                            task.cancel()
                    await asyncio.gather(*(task for task in (full_task, graph_wait) if task is not None),
                                         return_exceptions=True)
                    await session.close()
                    await q.close()


if __name__ == '__main__':
    unittest.main()
