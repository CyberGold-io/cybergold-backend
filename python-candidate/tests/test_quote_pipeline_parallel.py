"""Complete quotes progress independently of Core configuration and SQL hints."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.quote_budget import QuoteBudget, SearchStopped, budget_context
from cybergold_candidate.quoter.contracts import SearchSession
from cybergold_candidate.quoter.exploration import explore
from cybergold_candidate.quoter.search import alongside_bootstrap
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
from cybergold_candidate.search_observations import search_observation_scope
from test_quoter_candidate_bodies import service, request, ASSETS
from test_quoter_plan_simulation import encoded, measured, stage
from test_universal_quote import CORE, WETH


class PipelineParallelTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_weight_basket_asset_needs_no_conversion_to_construct_capacity_proposal(self):
        q, provider = service()
        q.core_state_cache.update({'weights': [1_000_000, 0], 'conversions': [10**18, 0],
            'supply': 90, 'maxSupply': 100, 'effectiveCap': 100})
        req = request(2)
        req['inputs'][0]['amount'], req['inputs'][1]['amount'] = '100', '0'
        funding = await q.direct_basket_funding(req, LATEST_BLOCK)
        self.assertEqual([row['amount'] for row in funding], ['10', '0'])
        self.assertFalse(provider.calls)
        q.preview.assert_not_awaited()
        await q.close()

    async def test_market_prices_before_held_core_basis_with_only_helpers_rpc(self):
        q, provider = service(encoded(measured(77, stages=[stage(0, WETH, CORE, 10000, 77)])))
        entered, release, basis_closed, published = (asyncio.Event() for _ in range(4))
        async def basis(_block):
            entered.set()
            try:
                await release.wait()
                return [], []
            finally:
                basis_closed.set()
        q.basis_reader = basis
        q.discover = AsyncMock(return_value=None)
        values = []
        async def publish(frame):
            values.append(deepcopy(frame['value']))
            published.set()
        task = asyncio.create_task(q.quote(request(), publish))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.wait_for(published.wait(), 1)
            self.assertFalse(release.is_set())
            self.assertEqual(values[0]['routeFamily'], 'market')
            self.assertEqual(values[0]['quotedOutput'], '76')
            self.assertTrue(provider.calls)
            self.assertTrue(all(method == 'eth_call' and params[1] == 'latest'
                and params[0]['to'] == q.helpers for method, params in provider.calls))
            q.preview.assert_not_awaited()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await q.close()
        self.assertTrue(basis_closed.is_set())

    async def test_slow_optional_lookup_does_not_hold_completed_ordinary_work(self):
        entered, closed = asyncio.Event(), asyncio.Event()
        async def lookup():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        async def ordinary():
            await entered.wait()
        await asyncio.wait_for(alongside_bootstrap(ordinary(), lookup(),
            incumbent=lambda: {'quotedOutput': '7'}), 1)
        self.assertTrue(closed.is_set())

    async def test_direct_basket_input_identities_need_no_cached_basis_before_pricing(self):
        xaut = '0x68749665FF8D2d112Fa859AA293F07A622782F38'
        q, provider = service(encoded(measured(190, stages=[
            stage(0, ASSETS[0], CORE, 100, 190), stage(1, xaut, CORE, 100, 0)])))
        q.basis_reader = AsyncMock(side_effect=AssertionError('Input vector already supplies its identities'))
        q.discover = AsyncMock(return_value=None)
        req = request(2)
        req['inputs'][1]['currency'] = xaut
        value = await q.quote(req)
        self.assertEqual(value['quotedOutput'], '190')
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][1][1], 'latest')
        q.basis_reader.assert_not_awaited()
        q.preview.assert_not_awaited()
        await q.close()

    async def test_independent_optional_seed_can_supply_first_quote_after_ordinary_exhaustion(self):
        observed = []
        async def ordinary():
            pass
        async def seed():
            await asyncio.sleep(0)
            observed.append('priced')
        await alongside_bootstrap(ordinary(), seed(), incumbent=lambda: None)
        self.assertEqual(observed, ['priced'])

    async def test_optional_paths_run_before_seed_price_and_beyond_sixteen_attempts(self):
        q, _provider = service()
        source, target = WETH, CORE
        offers = list(q.amm.nominations(source, target, 10000, LATEST_BLOCK, market=True, linear_only=True))
        self.assertTrue(offers)
        base = offers[0][0][0]['hops']
        routes = []
        for index in range(20):
            route = deepcopy(base)
            physical = next(hop['pool'] for hop in route if 'pool' in hop)
            physical['protocol'] = 'v3'
            physical['feePips'] = 100 + index
            routes.append((route, ['cybergold-custom']))
        q.amm.family_offers = lambda *_: [('one-family', routes)]
        session = SearchSession(7)
        session.discovery_done.set()
        priced = []
        async def evaluate(*_args, **options):
            priced.append(options['selected'])
            return {'quotedOutput': '1'}
        with budget_context(QuoteBudget()):
            await asyncio.wait_for(explore(q, request(), LATEST_BLOCK, session, evaluate,
                lambda: None, observations={}, seeded=True), 1)
        self.assertFalse(session.seed_done.is_set())
        self.assertEqual(len(priced), 20)
        self.assertEqual(session.starts, 20)
        await q.close()

    async def test_shared_control_stop_settles_all_subscribers(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def produce():
            entered.set()
            await release.wait()
            raise SearchStopped()
        async with search_observation_scope() as observations:
            first = asyncio.create_task(observations.read('candidate', produce))
            await entered.wait()
            second = asyncio.create_task(observations.read('candidate', produce))
            await asyncio.sleep(0)
            release.set()
            outcomes = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 1)
            self.assertTrue(all(isinstance(error, SearchStopped) for error in outcomes))
            self.assertFalse(observations.reads.pending)


if __name__ == '__main__':
    unittest.main()
