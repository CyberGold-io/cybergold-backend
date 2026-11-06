"""Saved Market replay owns only its actual preparation dependencies."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.bootstrap import current_bootstrap
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.route_tools import PendingRouteTool
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.quote_flow import Flow, flow_scope
from cybergold_candidate.recovery_rpc import SnapshotChanged
from test_universal_quote import BLOCK, CORE, PAXG, OTHER, WETH, settings, fixture_plan_simulator


REQUEST = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
ASSETS, WEIGHTS = [PAXG, OTHER], [500000, 500000]
POOL = {'id': '0x'+'17'*20, 'address': '0x'+'17'*20, 'protocol': 'v2', 'feePips': 3000,
        'token0': {'address': CORE, 'decimals': 18, 'chainId': 1},
        'token1': {'address': WETH, 'decimals': 18, 'chainId': 1}}
HOPS = [{'pool': POOL, 'zeroForOne': False}]


def fixture_pool(a, b, index):
    a, b = sorted((a.lower(), b.lower()))
    return {'id': '0x'+f'{index:02x}'*20, 'address': '0x'+f'{index:02x}'*20,
        'protocol': 'v2', 'feePips': 3000,
        'token0': {'address': a, 'decimals': 18, 'chainId': 1},
        'token1': {'address': b, 'decimals': 18, 'chainId': 1}}


class Rpc:
    def __init__(self):
        self.heads = self.verifications = 0

    async def block(self, _):
        self.heads += 1
        return deepcopy(BLOCK)

    async def assert_canonical(self, block):
        assert block == BLOCK
        self.verifications += 1


class Fixture(Quoter):
    def __init__(self):
        self.rpc = Rpc()
        # Explicit semantic connectivity replaces the old conversion override,
        # which invented a WETH/Core hop even for unrelated basket currencies.
        rows = [deepcopy(POOL), *(fixture_pool(a, b, index) for index, (a, b) in enumerate(
            ((WETH, PAXG), (WETH, OTHER), (PAXG, CORE), (OTHER, CORE)), 40))]
        registry = SimpleNamespace(chain=1, core=CORE, inventory={row['id']: row for row in rows}, seed=rows[-2])
        registry.get_rpc = lambda: self.rpc
        engine = SimpleNamespace(registry=registry)
        super().__init__(settings(), engine, basis_reader=self.read_basis, preview=self.preview_core,
                         plan_simulator=self.simulate_plan)
        self.selected_calls, self.ordinary_calls, self.previews = [], [], []
        self.seed_calls, self.core_calls, self.market_calls = [], [], []
        self.seeded_assets, self.discovered_assets = [], []
        self.path_started = asyncio.Event()
        self.core_completed = asyncio.Event()
        self.seed_completed = asyncio.Event()
        self.simulated_calls = []

    async def exploration_block(self):
        return deepcopy(BLOCK)

    async def simulate_plan(self, request, selected, **kwargs):
        self.simulated_calls.append((deepcopy(selected), kwargs.get('block'), kwargs.get('pricing', True)))
        return await fixture_plan_simulator(self, request, selected, basis_reader=self.read_basis, **kwargs)

    async def read_basis(self, _):
        return deepcopy(ASSETS), list(WEIGHTS)

    def seed_routes(self, request, assets):
        self.seeded_assets.append(list(assets))

    async def discover(self, request, assets, block):
        self.discovered_assets.append(list(assets))

    async def price_path(self, route, amount, block, bank, canonical):
        self.path_started.set()
        return amount, amount*2

    async def preview_core(self, mode, value, block):
        self.previews.append((mode, deepcopy(value)))
        acquired = list(map(int, value['maximumAmountsIn']))
        return {'netCygldOut': str(sum(acquired)*2), 'amountsInExact': list(map(str, acquired)),
                'orderedCoreAssets': list(ASSETS),
                'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}

    async def candidate(self, request, share, order, block, assets, weights, **options):
        row = (list(assets), list(weights), block)
        selected = options.get('selected')
        saved = bool(selected and selected.get('_fixture_saved_seed'))
        if selected is not None:
            self.selected_calls.append(row)
        (self.seed_calls if saved else self.ordinary_calls).append(row)
        core = (any(item.get('kind') == 0 for item in selected.get('allocations', []))
                if selected is not None else share != 0)
        if not saved:
            (self.core_calls if core else self.market_calls).append(row)
        value = await super().candidate(request, share, order, block, assets, weights, **options)
        if saved:
            self.seed_completed.set()
        elif core:
            self.core_completed.set()
        return value


def seed():
    plan = market_plan(WETH, CORE, HOPS, int(REQUEST['inputs'][0]['amount']))
    plan['_fixture_saved_seed'] = True
    return {'inputs': deepcopy(REQUEST['inputs']), 'plan': plan}


class PreparationOverlapTests(unittest.IsolatedAsyncioTestCase):
    async def test_market_seed_qualifies_with_basis_held_and_is_evaluated_once(self):
        q, entered, drained = Fixture(), asyncio.Event(), asyncio.Event()
        settling, release = asyncio.Event(), asyncio.Event()
        flow = Flow('/api/economic-quotes/stream')
        async def basis(_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                settling.set()
                await release.wait()
                drained.set()
        q.basis_reader = basis
        budget = QuoteBudget()
        async def update(frame):
            self.assertTrue(entered.is_set())
            self.assertEqual(frame['value']['routeFamily'], 'market')
            self.assertFalse(drained.is_set())
            await q.seed_completed.wait()
            budget.finish_selection('best-initial')
        with budget_context(budget), flow_scope(flow):
            async with asyncio.timeout(1):
                task = asyncio.create_task(q.get(REQUEST, update, seed=seed()))
                try:
                    await settling.wait()
                    owner = task.quote_flow
                    while True:
                        snapshot = {row['stage']:row for row in owner.snapshot()['stages']}
                        if any(snapshot.get(name,{}).get('inFlight') for name in (
                                'discovery.owners.settle','discovery.providers.settle',
                                'discovery.providers.close','search.preparation.settle')):
                            break
                        await asyncio.sleep(0)
                    self.assertFalse(task.done(),'ready Market result still owns preparation cancellation')
                    release.set()
                    value = await task
                finally:
                    release.set()
                    if not task.done():task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(value['quotedInput'], '10000')
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(len(q.seed_calls), 1)
        self.assertEqual(q.seed_calls[0][:2], ([], []))
        self.assertTrue(all(row[:2] == ([], []) for row in q.market_calls))
        self.assertFalse(q.core_calls)
        self.assertFalse(q.previews)
        self.assertTrue(drained.is_set())
        self.assertEqual((q.rpc.heads, q.rpc.verifications), (0, 0))
        snapshot = {row['stage']:row for row in owner.snapshot()['stages']}
        for name in ('search.preparation.settle','search.reconstruction.settle','sharing.settle'):
            self.assertGreaterEqual(snapshot[name]['completed'],1)
            self.assertEqual(snapshot[name]['summedCpuMs'],0)
        self.assertTrue(all(row['inFlight']==0 for row in snapshot.values()))

    async def test_market_and_suppliers_start_early_while_core_grid_receives_real_weights(self):
        q, release = Fixture(), asyncio.Event()
        async def basis(_):
            await release.wait()
            return deepcopy(ASSETS), list(WEIGHTS)
        q.basis_reader = basis
        suppliers = []
        class Supplier:
            def __init__(self, name):
                self.name, self.called, self.closed = name, asyncio.Event(), False
            async def discover(self, *_):
                self.called.set()
                return []
            async def close(self):
                self.closed = True
        for name in ('alpha', 'uniroute-local', 'uniroute-api', 'guidestar'):
            suppliers.append(Supplier(name))
        q.route_provider_factory = lambda: [CustomRoutes(q.engine.registry),
            *(PendingRouteTool(supplier) for supplier in suppliers)]
        budget = QuoteBudget()
        async def update(frame):
            if not release.is_set():
                self.assertFalse(release.is_set())
                self.assertEqual(frame['value']['routeFamily'], 'market')
                release.set()
        with budget_context(budget):
            async with asyncio.timeout(1):
                task = asyncio.create_task(q.get(REQUEST, update, seed=seed()))
                await asyncio.gather(q.core_completed.wait(), *(supplier.called.wait() for supplier in suppliers))
                budget.finish_selection('best-initial')
                value = await task
        self.assertTrue(q.ordinary_calls)
        self.assertTrue(q.market_calls)
        self.assertTrue(q.core_calls)
        self.assertTrue(all(row == (ASSETS, WEIGHTS, BLOCK) for row in q.core_calls))
        self.assertEqual(q.seeded_assets, [[], ASSETS])
        self.assertTrue(q.discovered_assets)
        self.assertTrue(all(supplier.closed for supplier in suppliers))
        self.assertGreater(int(value['quotedOutput']), 0)

    async def test_completed_core_and_mixed_seeds_do_not_wait_for_exploration_basis(self):
        for share in (50, 100):
            with self.subTest(share=share):
                q = Fixture()
                original = await q.candidate(REQUEST, share, 'core-first', BLOCK, ASSETS, WEIGHTS, first=True)
                original['plan']['_fixture_saved_seed'] = True
                q.selected_calls.clear()
                q.ordinary_calls.clear()
                q.core_calls.clear()
                q.market_calls.clear()
                entered, drained = asyncio.Event(), asyncio.Event()
                async def basis(_):
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        drained.set()
                q.basis_reader = basis
                budget = QuoteBudget()
                async def update(frame):
                    self.assertFalse(drained.is_set())
                    if q.seed_completed.is_set():
                        budget.finish_selection('best-initial')
                with budget_context(budget):
                    async with asyncio.timeout(1):
                        task = asyncio.create_task(q.get(REQUEST, update, seed=original))
                        await entered.wait()
                        value = await task
                self.assertGreaterEqual(int(value['quotedOutput']), int(original['quotedOutput']))
                self.assertEqual(len(q.seed_calls), 1)
                self.assertFalse(q.core_calls)
                self.assertTrue(drained.is_set())

    async def test_sdk_basis_disproof_during_drain_does_not_retract_helpers_qualification(self):
        q, entered = Fixture(), asyncio.Event()
        async def basis(_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                raise SnapshotChanged('preparation disproved pinned head')
        q.basis_reader = basis
        budget = QuoteBudget()
        async def update(frame):
            self.assertTrue(entered.is_set())
            budget.finish_selection('best-initial')
        with budget_context(budget):
            async with asyncio.timeout(1):
                value = await q.get(REQUEST, update, seed=seed())
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(q.rpc.verifications, 0)

    async def test_caller_cancellation_drains_basis_and_early_market_replay(self):
        q = Fixture()
        entered, replaying, basis_drained, replay_drained = (asyncio.Event() for _ in range(4))
        async def basis(_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                basis_drained.set()
        async def path(*_):
            replaying.set()
            try:
                await asyncio.Event().wait()
            finally:
                replay_drained.set()
        q.basis_reader, q.price_path = basis, path
        async with asyncio.timeout(1):
            task = asyncio.create_task(q.get(REQUEST, seed=seed()))
            await asyncio.gather(entered.wait(), replaying.wait())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(basis_drained.is_set())
        self.assertTrue(replay_drained.is_set())
        self.assertEqual(q.rpc.verifications, 0)

    async def test_sdk_basis_disproof_does_not_cancel_pending_helpers_seed(self):
        q = Fixture()
        replaying, release, disproved, drained = (asyncio.Event() for _ in range(4))
        async def basis(_):
            await replaying.wait()
            disproved.set()
            raise SnapshotChanged('basis disproved pinned head')
        async def path(_route, amount, *_):
            replaying.set()
            try:
                await release.wait()
                return amount, amount*2
            finally:
                drained.set()
        q.basis_reader, q.price_path = basis, path
        async with asyncio.timeout(1):
            task = asyncio.create_task(q.get(REQUEST, seed=seed()))
            await disproved.wait()
            self.assertFalse(task.done())
            self.assertFalse(drained.is_set())
            release.set()
            value = await task
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertTrue(drained.is_set())

    async def test_sdk_candidate_disproof_does_not_cancel_pending_helpers_seed(self):
        q, replaying, disproved = Fixture(), asyncio.Event(), asyncio.Event()
        candidate = q.candidate
        async def exploratory(*args, **kwargs):
            if kwargs.get('selected') is None:
                await replaying.wait()
                disproved.set()
                raise SnapshotChanged('SDK candidate observation changed')
            return await candidate(*args, **kwargs)
        async def path(_route, amount, *_):
            replaying.set()
            await disproved.wait()
            return amount, amount*2
        q.candidate, q.price_path = exploratory, path
        budget = QuoteBudget()
        async def update(frame):
            self.assertTrue(disproved.is_set())
            self.assertEqual(frame['value']['searchCoverage']['selectedPhase'], 'saved-plan')
            budget.finish_selection('best-initial')
        with budget_context(budget):
            async with asyncio.timeout(1):
                value = await q.get(REQUEST, update, seed=seed())
        self.assertGreater(int(value['quotedOutput']), 0)

    async def test_nomination_provider_disproof_does_not_cancel_pending_helpers_seed(self):
        q, simulating, disproved = Fixture(), asyncio.Event(), asyncio.Event()
        class Supplier:
            name = 'controlled-sdk-nomination'
            closed = False
            async def discover(self, *_):
                await simulating.wait()
                disproved.set()
                raise SnapshotChanged('nomination observations changed')
            async def close(self):
                self.closed = True
        supplier = Supplier()
        q.route_provider_factory = lambda: [PendingRouteTool(supplier)]
        original_candidate, original_simulation = q.candidate, q.plan_simulator
        async def candidates(*args, **kwargs):
            if kwargs.get('selected') is None:
                current_bootstrap().offer_feeds(WETH, CORE, 10000, BLOCK)
                raise RuntimeError('SDK exploration has no completed candidate')
            return await original_candidate(*args, **kwargs)
        async def simulation(request, selected, **kwargs):
            simulating.set()
            await disproved.wait()
            return await original_simulation(request, selected, **kwargs)
        q.candidate, q.plan_simulator = candidates, simulation
        budget = QuoteBudget()
        async def update(frame):
            self.assertTrue(disproved.is_set())
            self.assertEqual(frame['value']['searchCoverage']['selectedPhase'], 'saved-plan')
            budget.finish_selection('best-initial')
        with budget_context(budget):
            async with asyncio.timeout(1):
                value = await q.get(REQUEST, update, seed=seed())
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertTrue(supplier.closed)

    async def test_ordinary_basis_error_does_not_reject_independent_market_seed(self):
        q = Fixture()
        async def basis(_):
            raise OSError('Core basket unavailable')
        q.basis_reader = basis
        async with asyncio.timeout(1):
            value = await q.get(REQUEST, seed=seed())
        self.assertEqual(value['routeFamily'], 'market')
        self.assertEqual(len(q.seed_calls), 1)
        self.assertFalse(q.core_calls)

    async def test_basis_error_without_independent_plan_preserves_original_error(self):
        q = Fixture()
        async def basis(_):
            raise OSError('Core basket unavailable')
        q.basis_reader = basis
        q.engine.registry.inventory.clear()
        with self.assertRaisesRegex(OSError, 'Core basket unavailable'):
            await q.get(REQUEST)

    async def test_malformed_optional_seed_leaves_ordinary_search_available(self):
        q, budget = Fixture(), QuoteBudget()
        malformed = {'inputs': deepcopy(REQUEST['inputs']), 'plan': {
            'allocations': [{}], '_fixture_saved_seed': True}}
        async def update(frame):
            self.assertNotEqual(frame['value']['searchCoverage']['selectedPhase'], 'saved-plan')
            budget.finish_selection('best-initial')
        with budget_context(budget):
            async with asyncio.timeout(1):
                value = await q.get(REQUEST, update, seed=malformed)
        self.assertTrue(q.ordinary_calls)
        self.assertEqual(len(q.seed_calls), 1)
        self.assertGreater(int(value['quotedOutput']), 0)

    async def test_selected_market_replay_omits_unused_basis(self):
        q = Fixture()
        async def unnecessary(_):
            raise AssertionError('Market replay must not read basket basis')
        q.basis_reader = unnecessary
        value = await q.evaluate_selected(REQUEST, seed()['plan'])
        self.assertEqual(value['routeFamily'], 'market')
        self.assertEqual(q.selected_calls, [])
        self.assertEqual([(block, pricing) for _, block, pricing in q.simulated_calls], [(None, False)])
        self.assertFalse(q.previews)
        self.assertEqual((q.rpc.heads, q.rpc.verifications), (0, 0))

    async def test_direct_basket_uses_request_identities_without_exploratory_basis(self):
        q, budget = Fixture(), QuoteBudget()
        async def unnecessary(_):
            raise AssertionError('Direct basket identities already belong to the request')
        q.basis_reader = unnecessary
        request = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '100'},
            {'currency': OTHER, 'amount': '200'}], 'outputCurrency': CORE}
        async def update(_frame):
            budget.finish_selection('best-initial')
        with budget_context(budget):
            async with asyncio.timeout(1):
                value = await q.get(request, update)
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertTrue(q.ordinary_calls)
        self.assertTrue(all(row[:2] == (ASSETS, []) for row in q.ordinary_calls))
        self.assertEqual(len(value['plan']['body']['continuations']), len(request['inputs']))
        self.assertEqual((q.rpc.heads, q.rpc.verifications), (0, 0))


if __name__ == '__main__':
    unittest.main()
