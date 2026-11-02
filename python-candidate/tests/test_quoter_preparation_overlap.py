"""Saved Market replay owns only its actual preparation dependencies."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.discovery import market_plan
from cybergold_candidate.quoter.bootstrap import current_bootstrap
from cybergold_candidate.quoter.route_tools import PendingRouteTool
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.recovery_rpc import SnapshotChanged
from test_universal_quote import BLOCK, CORE, PAXG, OTHER, WETH, settings


REQUEST = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
ASSETS, WEIGHTS = [PAXG, OTHER], [500000, 500000]
POOL = {'id': '0x'+'17'*20, 'address': '0x'+'17'*20, 'protocol': 'v2', 'feePips': 3000,
        'token0': {'address': WETH, 'decimals': 18, 'chainId': 1},
        'token1': {'address': CORE, 'decimals': 18, 'chainId': 1}}
HOPS = [{'pool': POOL, 'zeroForOne': True}]


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
        registry = SimpleNamespace(chain=1, core=CORE, inventory={POOL['id']: deepcopy(POOL)}, seed=None)
        registry.get_rpc = lambda: self.rpc
        engine = SimpleNamespace(registry=registry)
        super().__init__(settings(), engine, basis_reader=self.read_basis, preview=self.preview_core)
        self.selected_calls, self.ordinary_calls, self.previews = [], [], []
        self.seeded_assets, self.discovered_assets = [], []
        self.path_started = asyncio.Event()
        self.core_completed = asyncio.Event()

    async def read_basis(self, _):
        return deepcopy(ASSETS), list(WEIGHTS)

    def seed_routes(self, request, assets):
        self.seeded_assets.append(list(assets))

    async def discover(self, request, assets, block):
        self.discovered_assets.append(list(assets))

    async def price_path(self, route, amount, block, bank, canonical):
        self.path_started.set()
        return amount, amount*2

    async def conversion(self, source, target, amount, block, bank, canonical, **options):
        bootstrap = current_bootstrap()
        if bootstrap is not None:
            bootstrap.offer_feeds(source, target, amount, block)
        chosen = market_plan(source, target, HOPS, amount)['conversions']['0:market']
        options.get('capture', {}).update(deepcopy(chosen))
        return deepcopy(chosen['template']), amount*2, []

    async def preview_core(self, mode, value, block):
        self.previews.append((mode, deepcopy(value)))
        acquired = list(map(int, value['maximumAmountsIn']))
        return {'netCygldOut': str(sum(acquired)*2), 'amountsInExact': list(map(str, acquired)),
                'orderedCoreAssets': list(ASSETS),
                'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}

    async def candidate(self, request, share, order, block, assets, weights, **options):
        row = (list(assets), list(weights), block)
        (self.selected_calls if options.get('selected') is not None else self.ordinary_calls).append(row)
        value = await super().candidate(request, share, order, block, assets, weights, **options)
        if options.get('selected') is None and share == 100:
            self.core_completed.set()
        return value


def seed():
    return {'inputs': deepcopy(REQUEST['inputs']),
            'plan': market_plan(WETH, CORE, HOPS, int(REQUEST['inputs'][0]['amount']))}


class PreparationOverlapTests(unittest.IsolatedAsyncioTestCase):
    async def test_market_seed_qualifies_with_basis_held_and_is_evaluated_once(self):
        q, entered, drained = Fixture(), asyncio.Event(), asyncio.Event()
        async def basis(_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        q.basis_reader = basis
        budget = QuoteBudget()
        async def update(frame):
            self.assertTrue(entered.is_set())
            self.assertEqual(frame['value']['searchCoverage']['selectedPhase'], 'saved-plan')
            self.assertFalse(drained.is_set())
            budget.finish_selection('best-initial')
        with budget_context(budget):
            async with asyncio.timeout(1):
                value = await q.get(REQUEST, update, seed=seed())
        self.assertEqual(value['quotedInput'], '10000')
        self.assertGreater(int(value['quotedOutput']), 0)
        self.assertEqual(len(q.selected_calls), 1)
        self.assertEqual(q.selected_calls[0], ([], [], BLOCK))
        self.assertFalse(q.ordinary_calls)
        self.assertFalse(q.previews)
        self.assertTrue(drained.is_set())
        self.assertEqual((q.rpc.heads, q.rpc.verifications), (1, 1))

    async def test_ordinary_core_grid_and_every_supplier_receive_real_preparation(self):
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
                self.assert_prepared()
                self.called.set()
                return []
            def assert_prepared(self):
                assert release.is_set()
            async def close(self):
                self.closed = True
        for name in ('custom', 'alpha', 'uniroute-local', 'uniroute-api', 'guidestar'):
            suppliers.append(Supplier(name))
        q.route_provider_factory = lambda: [PendingRouteTool(supplier) for supplier in suppliers]
        budget = QuoteBudget()
        async def update(frame):
            if frame['value']['searchCoverage']['selectedPhase'] == 'saved-plan':
                self.assertFalse(release.is_set())
                release.set()
        with budget_context(budget):
            async with asyncio.timeout(1):
                task = asyncio.create_task(q.get(REQUEST, update, seed=seed()))
                await asyncio.gather(q.core_completed.wait(), *(supplier.called.wait() for supplier in suppliers))
                budget.finish_selection('best-initial')
                value = await task
        self.assertTrue(q.ordinary_calls)
        self.assertTrue(all(row == (ASSETS, WEIGHTS, BLOCK) for row in q.ordinary_calls))
        self.assertEqual(q.seeded_assets, [ASSETS])
        self.assertTrue(q.discovered_assets)
        self.assertTrue(all(supplier.closed for supplier in suppliers))
        self.assertGreater(int(value['quotedOutput']), 0)

    async def test_core_and_mixed_seeds_wait_for_real_basis(self):
        for share in (50, 100):
            with self.subTest(share=share):
                q = Fixture()
                original = await q.candidate(REQUEST, share, 'core-first', BLOCK, ASSETS, WEIGHTS, first=True)
                q.selected_calls.clear()
                entered, release = asyncio.Event(), asyncio.Event()
                async def basis(_):
                    entered.set()
                    await release.wait()
                    return deepcopy(ASSETS), list(WEIGHTS)
                q.basis_reader = basis
                budget = QuoteBudget()
                async def update(frame):
                    budget.finish_selection('best-initial')
                with budget_context(budget):
                    async with asyncio.timeout(1):
                        task = asyncio.create_task(q.get(REQUEST, update, seed=original))
                        await entered.wait()
                        self.assertFalse(q.selected_calls)
                        release.set()
                        await task
                self.assertTrue(q.selected_calls)
                self.assertEqual(q.selected_calls[0], (ASSETS, WEIGHTS, BLOCK))

    async def test_disproof_from_basis_drain_invalidates_early_market_qualification(self):
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
                with self.assertRaises(SnapshotChanged):
                    await q.get(REQUEST, update, seed=seed())
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

    async def test_basis_disproof_cancels_an_unfinished_market_seed(self):
        q = Fixture()
        replaying, release, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def basis(_):
            await release.wait()
            raise SnapshotChanged('basis disproved pinned head')
        async def path(*_):
            replaying.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        q.basis_reader, q.price_path = basis, path
        async with asyncio.timeout(1):
            task = asyncio.create_task(q.get(REQUEST, seed=seed()))
            await replaying.wait()
            release.set()
            with self.assertRaises(SnapshotChanged):
                await task
        self.assertTrue(drained.is_set())

    async def test_ordinary_basis_error_does_not_reject_independent_market_seed(self):
        q = Fixture()
        async def basis(_):
            raise OSError('Core basket unavailable')
        q.basis_reader = basis
        async with asyncio.timeout(1):
            value = await q.get(REQUEST, seed=seed())
        self.assertEqual(value['routeFamily'], 'market')
        self.assertEqual(len(q.selected_calls), 1)
        self.assertFalse(q.ordinary_calls)

    async def test_basis_error_without_independent_plan_preserves_original_error(self):
        q = Fixture()
        async def basis(_):
            raise OSError('Core basket unavailable')
        q.basis_reader = basis
        with self.assertRaisesRegex(OSError, 'Core basket unavailable'):
            await q.get(REQUEST)

    async def test_malformed_optional_seed_leaves_ordinary_search_available(self):
        q, budget = Fixture(), QuoteBudget()
        malformed = {'inputs': deepcopy(REQUEST['inputs']), 'plan': {'allocations': [{}]}}
        async def update(_):
            budget.finish_selection('best-initial')
        with budget_context(budget):
            async with asyncio.timeout(1):
                value = await q.get(REQUEST, update, seed=malformed)
        self.assertTrue(q.ordinary_calls)
        self.assertFalse(q.selected_calls)
        self.assertGreater(int(value['quotedOutput']), 0)

    async def test_selected_market_replay_omits_unused_basis(self):
        q = Fixture()
        async def unnecessary(_):
            raise AssertionError('Market replay must not read basket basis')
        q.basis_reader = unnecessary
        value = await q.evaluate_selected(REQUEST, seed()['plan'])
        self.assertEqual(value['routeFamily'], 'market')
        self.assertEqual(q.selected_calls, [([], [], BLOCK)])
        self.assertFalse(q.previews)
        self.assertEqual((q.rpc.heads, q.rpc.verifications), (1, 1))
