"""Independent acquisition overlaps without parallel private-state mutation."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.uniswap_routes import pool_identity
from cybergold_candidate.quote_history import QuoteHistory

A, B, C = ('0x'+format(i, '040x') for i in (1, 2, 3))


def fixture():
    pools = [{'id': name, 'protocol': 'v2', 'address': address,
        'token0': {'address': a, 'decimals': 18}, 'token1': {'address': b, 'decimals': 18},
        'feePips': 3000, 'reserve0': '1000', 'reserve1': '1000', 'ticks': [], 'bitmapWords': []}
        for name, address, a, b in [('first', A, A, B), ('second', B, B, C)]]
    registry = SimpleNamespace(chain=1, inventory={}, pending=SharedReads())
    engine = RouteQuoteEngine(SimpleNamespace(), registry, SimpleNamespace(close=AsyncMock()))
    branches = [{'amountIn': '10', 'hops': [{'pool': p, 'zeroForOne': True} for p in pools]}]
    return engine, registry, pools, branches


class ReadFanoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_distinct_baseline_snapshots_start_together_and_supplied_states_need_no_rpc(self):
        engine, registry, pools, branches = fixture()
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.pending.close)
        entered, release = [], asyncio.Event()
        async def snapshot(pool, block):
            entered.append(pool['id'])
            if len(entered) == 2:
                release.set()
            await release.wait()
            return deepcopy(pool)
        registry.snapshot = AsyncMock(side_effect=snapshot)
        baseline = await asyncio.wait_for(engine.route_baseline({'branches': branches}, LATEST_BLOCK), 1)
        self.assertEqual(entered, ['first', 'second'])
        self.assertEqual(baseline.exchange, 1)
        registry.snapshot.reset_mock()
        supplied = {pool_identity(pool): pool for pool in pools}
        self.assertEqual(await engine.route_baseline({'branches': branches}, LATEST_BLOCK, supplied), baseline)
        registry.snapshot.assert_not_awaited()

    async def test_sdk_multi_pool_fills_start_together_and_are_consumed_in_route_order(self):
        engine, registry, pools, branches = fixture()
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.pending.close)
        entered, release, observed = [], asyncio.Event(), []
        async def extend(snapshot, requests, block):
            entered.append(snapshot['id'])
            if len(entered) == 2:
                release.set()
            await release.wait()
            return {**snapshot, 'bitmapWords': [{'wordPosition': 0, 'bitmap': '1'}]}
        registry.extend_ticks = extend
        async def request(payload, on_state):
            observed.extend(await on_state([{'poolId': p['id'], 'wordPositions': [0]} for p in pools]))
            return {'amountIn': '10', 'amountOut': '9', 'postState': []}
        engine.sdk.request = request
        canonical = {p['id']: deepcopy(p) for p in pools}
        private = {pools[0]['id']: {**deepcopy(pools[0]), 'reserve0': '999'}}
        await asyncio.wait_for(engine.quote_sdk_branches(branches, 'exactIn', 10,
            LATEST_BLOCK, canonical=canonical, candidate=private), 1)
        self.assertEqual(entered, ['first', 'second'])
        self.assertEqual([row['id'] for row in observed], ['first', 'second'])
        self.assertEqual(private['first']['reserve0'], '999')

    async def test_disproved_multi_pool_fill_drains_its_pending_sibling(self):
        engine, registry, pools, branches = fixture()
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.pending.close)
        started, drained = asyncio.Event(), asyncio.Event()
        async def extend(snapshot, requests, block):
            if snapshot['id'] == 'first':
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            await started.wait()
            raise SnapshotChanged('second pool disproved')
        registry.extend_ticks = extend
        async def request(payload, on_state):
            return await on_state([{'poolId': p['id'], 'wordPositions': [0]} for p in pools])
        engine.sdk.request = request
        canonical = {p['id']: deepcopy(p) for p in pools}
        # Cancellation owns the parked first read; an already observed disproof
        # from the other required read retains its existing fatal owner effect.
        task = asyncio.create_task(engine.quote_sdk_branches(branches, 'exactIn', 10,
            LATEST_BLOCK, canonical=canonical))
        await started.wait()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaisesRegex(SnapshotChanged, 'second pool disproved'):
            await task
        self.assertTrue(drained.is_set())

    async def test_advisory_state_observer_reuses_existing_capture_and_cannot_veto_it(self):
        history = QuoteHistory(SimpleNamespace(NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=A,
            NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=B))
        self.addAsyncCleanup(history.close)
        history.facts[None] = {'basket': {'assets': {'value': [A]},
            'targetsPpm': {'value': [1_000_000]}, 'cygldPerUnitFp18': {'value': [10**18]}},
            'fees': {'issuancePpm': {'value': '0'}, 'helpersPpm': {'value': '0'}}}
        history.batch = AsyncMock(side_effect=[[1, 10, 10, 0, [], False], [{'activeAvailableRaw': 100}]])
        rows = []
        def observer(row):
            rows.append(row)
            row['state']['available'][0] = '999'
            raise ValueError('optional observer failed')
        history.state_observer = observer
        await history.acquire_state(SimpleNamespace(), LATEST_BLOCK,
            {'chainId': 1, 'blockNumber': None, 'blockHash': None, 'blockTag': 'latest'})
        self.assertEqual(len(rows), 1)
        self.assertEqual(history.states[None]['state']['available'], ['100'])
        self.assertEqual(history.batch.await_count, 2)


if __name__ == '__main__':
    unittest.main()
