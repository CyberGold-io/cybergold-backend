"""Cold exact-output seeds need a fresh protected tuple before readiness."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.market_swap import MarketQuotes
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.sdk_worker import SdkWorkerError
from cybergold_candidate.uniswap_routes import candidate_branches
from cybergold_candidate.uniswap_state import PoolRegistry
from test_quote_intent import service, request, ASSET_A, ASSET_B, ASSET_C, WETH
from test_unified_route_pipeline import NativeQuoterRpc, SETTINGS


class ColdSeedQualification(unittest.IsolatedAsyncioTestCase):
    async def ready(self, event):
        await asyncio.wait_for(event.wait(), 2)

    def fixture(self, *, native=False, reject=False, flat=False, reorg=False,
                shared=False, saturated=False, hold_seed=False, hold_forward=False, disproof_during_drain=False):
        state = SimpleNamespace(seed=asyncio.Event(), protected=asyncio.Event(),
            eleven=asyncio.Event(), qualified=asyncio.Event(), invalidated=asyncio.Event(),
            release_seed=asyncio.Event(), completed_update_returned=asyncio.Event(),
            forward=asyncio.Event(), release_forward=asyncio.Event(), forwards=[],
            forward_drained=set(), protected_count=0, composed=[], modes=[], frames=[])
        class Rpc(NativeQuoterRpc):
            async def read_function(self, address, signature, inputs, args, outputs, block):
                if signature.startswith('quoteExact'):
                    path = args[0]
                    direct = len(path) == 43 and int.from_bytes(path[20:23]) == 100
                    if direct and not shared and signature.startswith('quoteExactInput'):
                        source = '0x'+path[:20].hex()
                        state.forwards.append((source, args[1]))
                        if hold_forward:
                            state.forward.set()
                            try:
                                if disproof_during_drain and source.lower() == ASSET_B.lower():
                                    raise SnapshotChanged('Selected forward read disproved')
                                await state.release_forward.wait()
                            finally:
                                state.forward_drained.add(source.lower())
                        if flat:
                            return (100, [], [], 0)
                    if shared and len(path) > 43:
                        amount = args[1]
                        return ((amount+1)//2 if signature.startswith('quoteExactOutput') else amount*2, [], [], 0)
                    if shared and direct:
                        # This fixture's observed liquidity exists only on the
                        # two-hop graph; original direct seeds remain pending.
                        self.tail.set()
                        try:
                            await self.release.wait()
                        finally:
                            self.drained.add('v3')
                        raise ValueError('No direct fixture pool')
                return await super().read_function(address, signature, inputs, args, outputs, block)
        rpc = Rpc(held_tail=True)
        registry = PoolRegistry(SETTINGS, rpc=rpc)
        registry.inventory = {}
        if saturated:
            pairs = [(ASSET_A, WETH), (ASSET_B, WETH), (ASSET_A, ASSET_C),
                     (ASSET_B, ASSET_C), (ASSET_C, WETH)]
            for index, (source, destination) in enumerate(pairs, 40):
                left, right = sorted((source, destination), key=str.lower)
                identity = '0x'+format(index, '040x')
                registry.inventory[identity] = {'id': identity, 'address': identity, 'protocol': 'v2',
                    'feePips': 3000, 'token0': {'address': left, 'decimals': 18, 'chainId': 31338},
                    'token1': {'address': right, 'decimals': 18, 'chainId': 31338}}
        engine = MarketQuotes(SETTINGS, registry)
        state.rpc, state.registry, state.engine = rpc, registry, engine
        connector_started, connector_drained = asyncio.Event(), asyncio.Event()
        state.connector_started, state.connector_drained = connector_started, connector_drained
        async def connectors(*_args):
            connector_started.set()
            try:
                await rpc.release.wait()
            finally:
                connector_drained.set()
        engine.connector_inventory = connectors
        intent, provider, routes, _wire = service(31338)
        routes.engine = engine
        state.intent, state.provider, state.routes = intent, provider, routes
        search = engine.search_routes
        async def observed(values, block, on_update=None):
            state.modes.append(values['mode'])
            async def update(rows):
                await on_update(rows)
                if all(row['best'] for row in rows):
                    state.completed_update_returned.set()
            return await search(values, block, update if on_update else None)
        engine.search_routes = observed
        if shared:
            def hop(source, destination, index):
                left, right = sorted((source, destination), key=str.lower)
                identity = '0x'+format(index, '040x')
                row = {'id': identity, 'address': identity, 'protocol': 'v3', 'feePips': 100,
                    'tickSpacing': 1, 'token0': {'address': left, 'decimals': 18, 'chainId': 31338},
                    'token1': {'address': right, 'decimals': 18, 'chainId': 31338}}
                registry.inventory[identity] = row
                return {'pool': row, 'zeroForOne': left.lower() == source.lower()}
            hop(ASSET_A, ASSET_C, 20)
            hop(ASSET_B, ASSET_C, 21)
            hop(ASSET_C, WETH, 22)
            async def sdk(branches, mode, amount, block, *, candidate=None, canonical=None):
                if any(len(branch['hops']) == 1 for branch in branches):
                    raise SdkWorkerError('No direct fixture observation')
                index = candidate.get('fixture-order', 0) if candidate is not None else 0
                if candidate is not None:
                    candidate['fixture-order'] = index+1
                    first = branches[0]['hops'][0]
                    source = first['pool']['token0' if first['zeroForOne'] else 'token1']['address']
                    state.composed.append((mode, source.lower(), amount, index))
                return {'amountIn': str(amount if mode == 'exactIn' else (amount+1)//2+index),
                    'amountOut': str(amount*2-index if mode == 'exactIn' else amount),
                    'settled': True, 'fullyFilled': True}
            engine.quote_sdk_branches = sdk
        read = provider.make_request
        async def observed_read(method, params):
            function = None
            if method == 'eth_call' and params[0]['to'].lower() != SETTINGS.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS.lower():
                function, _args = provider.contract.decode_function_input(params[0]['data'])
            protected = function and function.fn_name in ('previewRedeemToTokenExactIn', 'previewRedeemToNativeExactIn')
            if protected and reject:
                state.protected_count += 1
                state.protected.set()
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'message': 'fixture Helpers rejects'}}
            value = await read(method, params)
            if function and function.fn_name == 'previewRedeemToBasketExactOut':
                state.seed.set()
                if hold_seed:
                    await state.release_seed.wait()
            if protected:
                state.protected_count += 1
                state.protected.set()
                if state.protected_count == 11:
                    state.eleven.set()
                if reorg:
                    provider.reorg = True
            return value
        provider.make_request = observed_read
        async def publish(frame):
            state.frames.append(deepcopy(frame))
            if frame['type'] == 'qualified':
                state.qualified.set()
            if frame['type'] == 'invalidated':
                state.invalidated.set()
        state.budget = QuoteBudget()
        async def run():
            with budget_context(state.budget):
                return await state.budget.produce(intent.get(request('redeem-exact-out', native), publish))
        state.task = asyncio.create_task(run())
        async def cleanup():
            state.task.cancel()
            await asyncio.gather(state.task, return_exceptions=True)
            state.release_forward.set()
            rpc.release.set()
            await intent.close()
            await routes.close()
            await engine.close()
            await registry.close()
        self.addAsyncCleanup(cleanup)
        return state

    async def test_token_and_native_cold_seed_qualify_without_initial_tail(self):
        for native in (False, True):
            with self.subTest(native=native):
                state = self.fixture(native=native)
                await self.ready(state.qualified)
                first = next(frame['value'] for frame in state.frames if frame['type'] == 'qualified')
                self.assertTrue(state.seed.is_set())
                self.assertFalse(state.rpc.release.is_set())
                self.assertEqual(state.modes, ['exact-out'])
                self.assertEqual(first['initialPreview']['grossCygldIn'], '100')
                self.assertEqual((first['executionAmount'], first['preview']['minimumAmountOut']), ('102', '200'))
                self.assertEqual([leg['inputAmount'] for leg in first['quotes']], ['51', '51'])
                self.assertTrue(all(leg['routePlan']['mode'] == 'exactIn' for leg in first['quotes']))
                self.assertEqual({amount for _asset, amount in state.forwards}, {51})
                state.budget.finish_selection('best-initial')
                result = await asyncio.wait_for(state.task, 2)
                self.assertEqual(result['quotes'], first['quotes'])
                self.assertTrue(state.connector_drained.is_set())
                self.assertEqual(state.registry.pending.pending, {})
                self.assertEqual(state.engine.semaphore._value, 8)

    async def test_cold_qualification_uses_completed_slots_before_more_than_eight_held_tails(self):
        state = self.fixture(saturated=True, hold_seed=True)
        await self.ready(state.seed)
        # A real Helpers read can still be pending after complete seed quotes.
        # The scheduler must retain that completion's free pricing slots for
        # protected qualification before admitting unrelated replacements.
        self.assertFalse(state.completed_update_returned.is_set())
        state.release_seed.set()
        await self.ready(state.qualified)
        self.assertFalse(state.rpc.release.is_set())
        graph_count = 0
        for asset in (ASSET_A, ASSET_B):
            graph_count += sum([1 async for _ in candidate_branches(
                list(state.registry.inventory.values()), asset, WETH, 'exactOut', 100)])
        self.assertGreater(6+graph_count, 8)
        # Qualification used the completed slots first. Continuing exploration
        # may now fill them with these held native/typed candidates.
        await self.ready(state.rpc.typed)
        await self.ready(state.rpc.tail)
        async with asyncio.timeout(2):
            while state.engine.semaphore._value:
                await asyncio.sleep(0)
        self.assertTrue(state.budget.ready)
        self.assertEqual(state.modes, ['exact-out'])
        state.budget.finish_selection('best-initial')
        result = await asyncio.wait_for(state.task, 2)
        self.assertEqual(result['preview']['minimumAmountOut'], '200')
        self.assertEqual(state.engine.semaphore._value, 8)
        self.assertEqual(state.registry.pending.pending, {})

    async def test_completed_seed_and_rejected_helpers_never_mark_ready(self):
        state = self.fixture(reject=True, saturated=True)
        await self.ready(state.protected)
        await self.ready(state.rpc.typed)
        self.assertTrue(state.seed.is_set())
        self.assertFalse(state.budget.ready)
        state.budget.finish_selection('timeout')
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(state.task, 2)
        self.assertFalse(state.qualified.is_set())
        self.assertEqual(state.registry.pending.pending, {})

    async def test_outside_interval_checks_at_most_eleven_forward_points(self):
        state = self.fixture(flat=True)
        await self.ready(state.eleven)
        self.assertFalse(state.budget.ready)
        self.assertFalse(state.qualified.is_set())
        state.budget.finish_selection('timeout')
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(state.task, 2)
        self.assertEqual(state.protected_count, 11)
        self.assertEqual(state.modes, ['exact-out'])

    async def test_shared_forward_vector_is_composed_in_core_order_before_helpers(self):
        state = self.fixture(shared=True)
        await self.ready(state.qualified)
        first = next(frame['value'] for frame in state.frames if frame['type'] == 'qualified')
        forward = [row for row in state.composed if row[0] == 'exactIn']
        self.assertTrue(forward)
        self.assertEqual([(row[1], row[3]) for row in forward[:2]], [(ASSET_A.lower(), 0), (ASSET_B.lower(), 1)])
        self.assertEqual(first['executionAmount'], '103')
        self.assertEqual(first['preview']['minimumAmountOut'], '201')
        self.assertEqual([leg['minimumAmountOut'] for leg in first['quotes']], ['100', '101'])
        state.budget.finish_selection('best-initial')
        await asyncio.wait_for(state.task, 2)

    async def test_snapshot_disproof_after_protected_preview_retires_seed(self):
        state = self.fixture(reorg=True)
        await self.ready(state.invalidated)
        self.assertFalse(state.budget.ready)
        self.assertFalse(state.qualified.is_set())
        with self.assertRaises(SnapshotChanged):
            await asyncio.wait_for(state.task, 2)
        self.assertFalse(state.budget.stop.is_set())

    async def test_caller_cancel_drains_initial_tail_and_fresh_forward_reads(self):
        state = self.fixture(hold_forward=True)
        await self.ready(state.forward)
        state.task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await state.task
        self.assertTrue(state.connector_drained.is_set())
        self.assertEqual(state.forward_drained, {ASSET_A.lower(), ASSET_B.lower()})
        self.assertEqual(state.registry.pending.pending, {})
        self.assertFalse(state.budget.stop.is_set())

    async def test_completed_forward_read_disproof_survives_policy_drain(self):
        state = self.fixture(hold_forward=True, disproof_during_drain=True)
        await self.ready(state.forward)
        # Both reads were started in Core order; the later one disproves the
        # pinned context while the first still waits for its owned result.
        while ASSET_B.lower() not in state.forward_drained:
            await asyncio.sleep(0)
        state.budget.finish_selection('timeout')
        with self.assertRaises(SnapshotChanged):
            await asyncio.wait_for(state.task, 2)
        self.assertFalse(state.qualified.is_set())
        self.assertEqual(state.registry.pending.pending, {})


class ActualSdkColdSeedQualification(unittest.IsolatedAsyncioTestCase):
    async def test_rich_sdk_seed_and_fresh_forward_terms_qualify_before_held_graph_tail(self):
        import os
        from pathlib import Path
        from web3 import Web3
        from cybergold_candidate.sdk_worker import SdkWorker
        from cybergold_candidate.uniswap_state import ZERO

        intent, provider, routes, _wire = service(31338)
        release, tail, qualified = asyncio.Event(), asyncio.Event(), asyncio.Event()
        discovery, discovery_drained = asyncio.Event(), asyncio.Event()
        native_calls, drained, frames, sdk_values = [], set(), [], []
        connector = '0x'+'4'*40
        pairs = [(ASSET_A, WETH), (ASSET_B, WETH), (ASSET_A, ASSET_C),
                 (ASSET_B, ASSET_C), (ASSET_C, WETH), (ASSET_A, connector),
                 (ASSET_B, connector), (connector, WETH)]
        pools = []
        for index, (source, destination) in enumerate(pairs, 60):
            left, right = sorted((source, destination), key=str.lower)
            identity = '0x'+format(index, '040x')
            pools.append({'id': identity, 'address': identity, 'protocol': 'v2',
                'feePips': 3000, 'token0': {'address': left, 'decimals': 18, 'chainId': 31338},
                'token1': {'address': right, 'decimals': 18, 'chainId': 31338}})
        healthy = {pool['address'] for pool in pools[:2]}
        class Rpc:
            chain_id = 31338
            factory = ASSET_C
            w3 = Web3()
            async def read_function(self, address, signature, _inputs, _args, _outputs, _block):
                if signature == 'getPool(address,address,uint24)':
                    return (ZERO,)
                if signature.startswith('quoteExact'):
                    native_calls.append(signature)
                    raise AssertionError('This fixture has SDK-priced V2 liquidity only')
                if signature == 'getReserves()':
                    if address not in healthy:
                        tail.set()
                        try:
                            await release.wait()
                        finally:
                            drained.add(address)
                    return (1000000, 2000000, 0)
                raise OSError('No optional V3 state in this fixture')
            async def close(self):
                pass
        registry = PoolRegistry(intent.settings, Rpc())
        registry.inventory = {pool['id']: pool for pool in pools}
        sdk = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'),
                         str(Path('src/uniswap-sdk/worker.ts').resolve())])
        engine = MarketQuotes(intent.settings, registry, sdk)
        routes.engine = engine
        self.addAsyncCleanup(registry.close)
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(routes.close)
        self.addAsyncCleanup(intent.close)
        async def connectors(*_args):
            discovery.set()
            try:
                await release.wait()
            finally:
                discovery_drained.set()
        engine.connector_inventory = connectors
        request_sdk = sdk.request
        async def actual_sdk(payload):
            value = await request_sdk(payload)
            sdk_values.append((payload['mode'], deepcopy(value)))
            return value
        sdk.request = actual_sdk
        async def publish(frame):
            frames.append(deepcopy(frame))
            if frame['type'] == 'qualified':
                qualified.set()
        budget = QuoteBudget()
        async def run():
            with budget_context(budget):
                return await budget.produce(intent.get(request('redeem-exact-out'), publish))
        task = asyncio.create_task(run())
        try:
            await asyncio.wait_for(qualified.wait(), sdk.timeout)
            first = next(frame['value'] for frame in frames if frame['type'] == 'qualified')
            self.assertTrue(discovery.is_set())
            self.assertTrue(tail.is_set())
            self.assertFalse(release.is_set())
            self.assertLess(budget.first_qualified, budget.initial)
            self.assertEqual(first['initialPreview']['grossCygldIn'], '102')
            self.assertEqual((first['executionAmount'], first['preview']['minimumAmountOut']), ('104', '202'))
            self.assertEqual([leg['inputAmount'] for leg in first['quotes']], ['52', '52'])
            self.assertEqual([leg['minimumAmountOut'] for leg in first['quotes']], ['101', '101'])
            self.assertTrue(all(leg['routePlan']['mode'] == 'exactIn' for leg in first['quotes']))
            self.assertTrue(all(hop['pool']['protocol'] == 'v2' for leg in first['quotes']
                for branch in leg['routePlan']['branches'] for hop in branch['hops']))
            self.assertTrue(any(mode == 'exactOut' and value['amountIn'] == '51'
                and value['amountOut'] == '101' for mode, value in sdk_values))
            self.assertTrue(any(mode == 'exactIn' and value['amountIn'] == '52'
                and value['amountOut'] == '103' for mode, value in sdk_values))
            self.assertEqual(native_calls, [])
            budget.finish_selection('best-initial')
            result = await asyncio.wait_for(task, sdk.timeout)
            self.assertEqual(result['quotes'], first['quotes'])
            self.assertTrue(discovery_drained.is_set())
            self.assertTrue(drained)
            self.assertEqual(registry.pending.pending, {})
            self.assertEqual(engine.semaphore._value, 8)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            release.set()


if __name__ == '__main__':
    unittest.main()
