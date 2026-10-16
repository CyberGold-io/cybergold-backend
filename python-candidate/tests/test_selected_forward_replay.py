"""Selected Core replay ownership; fixed paths and programmable SDK, no live I/O."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.market_swap import MarketQuotes
from cybergold_candidate.quote_errors import RpcTimeout
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.basket_preview import BasketPreviewRpc, InvalidPreview
from cybergold_candidate.token_preview import TokenPreviewRpc
from cybergold_candidate.quote_revalidation import revalidate, RetainedPlanChanged, core_bounds
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.shared_reads import SharedReads
import test_quote_intent as intent_fixture
from test_quote_intent import ASSET_A, ASSET_B, ASSET_C, WETH, CORE


class SelectedForwardReplayTests(unittest.IsolatedAsyncioTestCase):
    fixture = intent_fixture.EarlyProtectedRedemptionPointTests.fixture
    start = intent_fixture.EarlyProtectedRedemptionPointTests.start
    wait = intent_fixture.EarlyProtectedRedemptionPointTests.wait
    assert_checked_points = intent_fixture.EarlyProtectedRedemptionPointTests.assert_checked_points

    def actual_engine_fixture(self, *, disjoint=False, **options):
        intent, provider, control, value = intent_fixture.RepeatedProtectedRedemptionPointTests.concave_fixture(
            self, typed=True, **options)
        fixture_engine = intent.routes.engine
        # The old duck receiver intentionally supports the original interface.
        # This fixture uses the actual producer class so new shared dispatch is
        # exercised, with the same fixed-path programmable SDK price oracle.
        registry = SimpleNamespace(inventory=fixture_engine.registry.inventory,
            pending=SharedReads(), get_rpc=lambda: intent.routes.rpc,
            chain=31338, core=intent.settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS)
        class Sdk:
            async def close(self):
                pass
        engine = MarketQuotes(intent.settings, registry, Sdk())
        engine.quote_sdk_branches = fixture_engine.quote_sdk_branches
        engine.search_routes = fixture_engine.search_routes
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.pending.close)
        if disjoint:
            reserve = engine.search_routes
            async def search(values, block, on_update=None):
                async def update(rows):
                    rows = deepcopy(rows)
                    # A direct B/WETH route shares no pool with A/C/WETH.
                    pool = deepcopy(rows[1]['best']['routePlan']['branches'][0]['hops'][-1]['pool'])
                    pool['id'] = pool['address'] = '0x' + f'{21:040x}'
                    pool['token0']['address'], pool['token1']['address'] = sorted((ASSET_B, WETH), key=str.lower)
                    registry.inventory[pool['id']] = deepcopy(pool)
                    rows[1]['best']['routePlan']['branches'][0]['hops'] = [
                        {'pool': pool, 'zeroForOne': pool['token0']['address'].lower() == ASSET_B.lower()}]
                    if on_update:
                        await on_update(rows)
                return await reserve(values, block, update)
            engine.search_routes = search
        intent.routes.engine = engine
        return intent, provider, control, value, engine

    async def test_shared_token_native_remains_available_when_discarded_isolated_price_fails(self):
        for native in (False, True):
            with self.subTest(native=native):
                intent, provider, control, value, engine = self.actual_engine_fixture(native=native)
                isolated_calls, selected = [], []
                async def unavailable(*args):
                    isolated_calls.append(args)
                    raise RpcTimeout()
                engine.quote_branches = unavailable
                original = engine.quote_sdk_branches
                async def sdk(branches, mode, amount, block, **kwargs):
                    if amount > 50 and isinstance(kwargs.get('candidate'), dict):
                        hop = branches[0]['hops'][0]
                        source = hop['pool']['token0' if hop['zeroForOne'] else 'token1']['address']
                        selected.append((amount, source.lower()))
                    return await original(branches, mode, amount, block, **kwargs)
                engine.quote_sdk_branches = sdk
                task, frames, ready = self.start(intent, value)
                await self.wait(ready)
                self.assertFalse(task.done())
                self.assertEqual(isolated_calls, [])
                self.assertEqual((frames[0]['executionAmount'], frames[0]['preview']['minimumAmountOut']), ('230', '202'))
                self.assertGreaterEqual(len(selected), 2)
                self.assertEqual([asset for _amount, asset in selected],
                    [asset.lower() for _ in range(len(selected)//2) for asset in (ASSET_A, ASSET_B)])
                self.assert_checked_points(provider, value, frames)
                control.release.set()
                self.assertEqual((await task)['executionAmount'], '230')
                self.assertEqual(engine.semaphore._value, 8)

    async def test_early_issue_input_probe_uses_same_shared_selected_pricing(self):
        for native in (False, True):
            with self.subTest(native=native):
                intent, _provider, routes, control = intent_fixture.EarlyCheckedIssueTests.fixture(self, shape='shared')
                previous = routes.engine
                registry = SimpleNamespace(inventory=previous.registry.inventory,
                    pending=SharedReads(), get_rpc=lambda: routes.rpc,
                    chain=31338, core=CORE)
                class Sdk:
                    async def close(self):
                        pass
                engine = MarketQuotes(intent.settings, registry, Sdk())
                engine.quote_sdk_branches, engine.search_routes = previous.quote_sdk_branches, previous.search_routes
                self.addAsyncCleanup(engine.close)
                self.addAsyncCleanup(registry.pending.close)
                routes.engine = engine
                isolated = []
                async def unavailable(*args):
                    isolated.append(args)
                    raise RpcTimeout()
                engine.quote_branches = unavailable
                value = intent_fixture.request('issue-exact-in', native)
                value['targets'].reverse()
                task, frames, ready = self.start(intent, value)
                try:
                    await self.wait(ready)
                    self.assertEqual(isolated, [])
                    self.assertFalse(task.done())
                    result = frames[0]
                    self.assertEqual((result['executionAmount'], result['maximumInputAmount'], result['expectedInputAmount']), ('196', '100', '99'))
                    self.assertEqual([row['outputAsset'] for row in result['quotes']], [ASSET_A, ASSET_B])
                    self.assertEqual([row['minimumAmountOut'] for row in result['quotes']], ['98', '98'])
                    self.assertEqual([row for row in control.composition_calls if row[0] == 'exactOut'][:2],
                        [('exactOut', ASSET_A, 98, 0), ('exactOut', ASSET_B, 98, 1)])
                    control.fail_tail = True
                    control.release.set()
                    self.assertEqual((await task)['quotes'], result['quotes'])
                finally:
                    control.release.set()

    async def test_disjoint_selected_legs_keep_concurrency_and_drain_error_or_cancel(self):
        for failure in (None, 'read', 'cancel'):
            with self.subTest(failure=failure):
                intent, _provider, control, value, engine = self.actual_engine_fixture(disjoint=True)
                bank = SharedReads()
                self.addAsyncCleanup(bank.close)
                entered, release, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
                original = engine.quote_branches
                started = cancelled = 0
                async def read():
                    await release.wait()
                    return 123
                async def quote(*args):
                    nonlocal started, cancelled
                    started += 1
                    first = started == 1
                    if started == 2:
                        entered.set()
                    if first and failure == 'read':
                        await entered.wait()
                        raise RpcTimeout()
                    try:
                        await bank.one('selected-read', read)
                    except asyncio.CancelledError:
                        cancelled += 1
                        drained.set()
                        raise
                    return await original(*args)
                engine.quote_branches = quote
                foreign = asyncio.create_task(bank.one('selected-read', read))
                task, frames, ready = self.start(intent, value)
                try:
                    await self.wait(entered)
                    self.assertEqual(started, 2)
                    self.assertEqual(frames, [])
                    if failure == 'cancel':
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                        self.assertEqual(cancelled, 2)
                    elif failure == 'read':
                        await self.wait(drained)
                        control.release.set()
                        with self.assertRaises(TimeoutError):
                            await task
                        self.assertEqual(cancelled, 1)
                    else:
                        release.set()
                        await self.wait(ready)
                        control.release.set()
                        await task
                    self.assertEqual(engine.semaphore._value, 8)
                    if failure:
                        self.assertEqual(frames, [])
                        self.assertFalse(foreign.done())
                    release.set()
                    self.assertEqual(await foreign, 123)
                    self.assertEqual(bank.pending, {})
                finally:
                    release.set()
                    control.release.set()
                    await asyncio.gather(foreign, return_exceptions=True)

    async def test_shared_unsettled_final_replay_and_helpers_rejection_never_qualify(self):
        for failure in ('unsettled', 'helpers'):
            with self.subTest(failure=failure):
                intent, _provider, control, value, engine = self.actual_engine_fixture(rejected=failure == 'helpers')
                original = engine.quote_sdk_branches
                rejected = asyncio.Event()
                async def sdk(branches, mode, amount, block, **kwargs):
                    result = await original(branches, mode, amount, block, **kwargs)
                    if failure == 'unsettled' and amount > 50 and isinstance(kwargs.get('candidate'), dict):
                        rejected.set()
                        return {**result, 'settled': False}
                    return result
                engine.quote_sdk_branches = sdk
                task, frames, _ready = self.start(intent, value)
                await self.wait(rejected if failure == 'unsettled' else control.refined)
                control.release.set()
                with self.assertRaises(TimeoutError):
                    await task
                self.assertEqual(frames, [])
                self.assertEqual(engine.semaphore._value, 8)

    async def test_shared_snapshot_disproof_retires_context_before_ordinary_tail(self):
        intent, _provider, control, value, engine = self.actual_engine_fixture()
        original = engine.quote_sdk_branches
        invalidated, qualified = asyncio.Event(), []
        async def sdk(branches, mode, amount, block, **kwargs):
            if amount > 50 and isinstance(kwargs.get('candidate'), dict):
                raise SnapshotChanged('Synthetic final required read disproves the pinned snapshot')
            return await original(branches, mode, amount, block, **kwargs)
        engine.quote_sdk_branches = sdk
        async def update(frame):
            if frame['type'] == 'invalidated':
                invalidated.set()
            elif frame['type'] == 'qualified':
                qualified.append(frame['value'])
        task = asyncio.create_task(intent.get(value, update))
        try:
            await self.wait(invalidated)
            control.release.set()
            with self.assertRaises(SnapshotChanged):
                await task
            self.assertEqual(qualified, [])
            self.assertEqual(engine.semaphore._value, 8)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_shared_replay_cancellation_keeps_foreign_retained_read_user(self):
        intent, _provider, _control, value, engine = self.actual_engine_fixture()
        bank = SharedReads()
        self.addAsyncCleanup(bank.close)
        entered, release = asyncio.Event(), asyncio.Event()
        original = engine.quote_sdk_branches
        cancelled = 0
        async def read():
            await release.wait()
            return 123
        async def sdk(branches, mode, amount, block, **kwargs):
            nonlocal cancelled
            if amount > 50 and isinstance(kwargs.get('candidate'), dict):
                entered.set()
                try:
                    await bank.one('required-composed-read', read)
                except asyncio.CancelledError:
                    cancelled += 1
                    raise
            return await original(branches, mode, amount, block, **kwargs)
        engine.quote_sdk_branches = sdk
        foreign = asyncio.create_task(bank.one('required-composed-read', read))
        task, frames, _ready = self.start(intent, value)
        try:
            await self.wait(entered)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual((cancelled, frames, engine.semaphore._value), (1, [], 8))
            self.assertFalse(foreign.done())
            release.set()
            self.assertEqual(await foreign, 123)
            self.assertEqual(bank.pending, {})
        finally:
            release.set()
            await asyncio.gather(foreign, return_exceptions=True)

    async def test_selected_vector_is_resolved_again_after_pricing_permit_grant(self):
        intent, _provider, control, value, engine = self.actual_engine_fixture()
        entered, grant, rejected = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = engine.resolve_branches
        def resolve(*args):
            try:
                return original(*args)
            except Exception:
                rejected.set()
                raise
        engine.resolve_branches = resolve
        class Permit:
            def __init__(self):
                self.inner, self.blocked = asyncio.Semaphore(8), False
            @property
            def _value(self):
                return self.inner._value
            async def acquire(self):
                if control.first_gross is not None and not self.blocked:
                    self.blocked = True
                    entered.set()
                    await grant.wait()
                await self.inner.acquire()
                return True
            def release(self):
                self.inner.release()
            async def __aenter__(self):
                await self.acquire()
                return self
            async def __aexit__(self, *_args):
                self.release()
        engine.semaphore = Permit()
        task, frames, _ready = self.start(intent, value)
        try:
            await self.wait(entered)
            calls_before = len(control.calls)
            engine.registry.inventory.clear()
            grant.set()
            await self.wait(rejected)
            control.release.set()
            with self.assertRaises(TimeoutError):
                await task
            self.assertEqual(len(control.calls), calls_before)
            self.assertEqual(frames, [])
            self.assertEqual(engine.semaphore._value, 8)
        finally:
            grant.set()


class RetainedSelectedVectorTests(unittest.IsolatedAsyncioTestCase):
    async def selected_fixture(self, mode, native=False, *, fault=None):
        intent, provider, routes, _wire = intent_fixture.service(31338)
        self.addAsyncCleanup(routes.close)
        self.addAsyncCleanup(intent.close)
        issue = mode.startswith('issue')
        inventory, paths = {}, {}
        def hop(source, target, number):
            left, right = sorted((source, target), key=str.lower)
            identity = '0x' + f'{number:040x}'
            pool = {'id': identity, 'address': identity, 'protocol': 'v2', 'feePips': 3000,
                'token0': {'address': left, 'decimals': 18, 'chainId': 31338},
                'token1': {'address': right, 'decimals': 18, 'chainId': 31338}}
            inventory[identity] = pool
            return {'pool': pool, 'zeroForOne': left.lower() == source.lower()}
        trunk = hop(WETH, ASSET_C, 20) if issue else hop(ASSET_C, WETH, 20)
        for index, asset in enumerate((ASSET_A, ASSET_B)):
            leg = hop(ASSET_C, asset, 30 + index) if issue else hop(asset, ASSET_C, 30 + index)
            paths[asset.lower()] = [deepcopy(trunk), leg] if issue else [leg, deepcopy(trunk)]
        registry = SimpleNamespace(inventory=inventory, pending=SharedReads(),
            get_rpc=lambda: routes.rpc, chain=31338, core=CORE)
        class Sdk:
            async def close(self):
                pass
        engine = MarketQuotes(intent.settings, registry, Sdk())
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(registry.pending.close)
        routes.engine = routes.rpc.route_engine = engine
        calls, isolated = [], []
        async def quote_sdk(branches, swap_mode, amount, block, **kwargs):
            candidate = kwargs.get('candidate')
            self.assertIsInstance(candidate, dict)
            order = candidate.get('fixture-order', 0)
            candidate['fixture-order'] = order + 1
            calls.append((swap_mode, amount, order, deepcopy(branches)))
            if fault == 'transport':
                raise RpcTimeout()
            if fault == 'snapshot':
                raise SnapshotChanged('Inert final retained read disproves the pinned snapshot')
            if fault == 'contract':
                raise QuoteFailure('quote-contract-reverted')
            return {'amountIn': str((amount + 1)//2 + order if issue else amount),
                'amountOut': str(amount if issue else amount*2-order),
                'settled': fault != 'unsettled', 'fullyFilled': fault != 'unfilled'}
        async def discarded(*args):
            isolated.append(args)
            raise RpcTimeout()
        engine.quote_sdk_branches, engine.quote_branches = quote_sdk, discarded
        request = intent_fixture.request(mode, native)
        request['amount'] = '200' if mode == 'issue-exact-in' else '80' if mode == 'redeem-exact-out' else '100'
        swap_mode = 'exactOut' if issue else 'exactIn'
        quotes = []
        for asset in (ASSET_A, ASSET_B):
            plan = {'version': 1, 'executionContext': 'helpers-core', 'mode': swap_mode,
                'tokenIn': WETH if issue else asset, 'tokenOut': asset if issue else WETH,
                'inputAmount': '50', 'outputAmount': '50' if issue else '100',
                'limit': '50' if issue else '40', 'deadline': request['deadline'],
                'branches': [{'amountIn': '0' if issue else '50', 'hops': deepcopy(paths[asset.lower()])}]}
            quotes.append({'adapter': request['adapter'], 'minimumAmountOut': '50' if issue else '40',
                'routePlan': plan, **({'outputAsset': asset, 'amountIn': '100'} if issue else {'inputAsset': asset, 'inputAmount': '50'})})
        outputs = [{'kind': 0, 'token': asset, 'id': '0', 'amount': '50'} for asset in (ASSET_A, ASSET_B)] + [
            {'kind': 1, 'token': CORE, 'id': str(int(ASSET_C, 16)), 'amount': '100'}]
        previous = {'executionAmount': '100', 'maximumInputAmount': '200' if issue else '0',
            'quotes': quotes, 'slippageBps': 100, 'preview': {'minimumAmountOut': '80', 'projectedCoreOutputs': outputs},
            'expectedCoreOutputs': core_bounds(outputs)}
        block = await routes.rpc.block(None)
        basket, token = BasketPreviewRpc(intent.settings, routes.rpc.w3), TokenPreviewRpc(intent.settings, routes.rpc.w3)
        if fault == 'helpers':
            original = provider.make_request
            async def read(method, params):
                if method == 'eth_call' and params[0]['to'].lower() != CORE.lower():
                    function, _args = provider.contract.decode_function_input(params[0]['data'])
                    if function.fn_name not in ('previewIssueFromBasketExactOut', 'previewRedeemToBasketExactIn'):
                        return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 3, 'message': 'Inert final Helpers rejection'}}
                return await original(method, params)
            provider.make_request = read
        async def preview(service, value):
            return await service.preview(value['mode'], service.encode(value), block)
        metrics = {'candidateCalls': 0}
        async def operation():
            return await revalidate(request, previous, routes.rpc, block, basket, token, preview, metrics)
        return SimpleNamespace(operation=operation, engine=engine, provider=provider, previous=previous,
            request=request, calls=calls, isolated=isolated, metrics=metrics)

    async def test_all_four_retained_intent_modes_token_native_skip_discarded_prices(self):
        for mode in ('issue-exact-in', 'issue-exact-out', 'redeem-exact-in', 'redeem-exact-out'):
            for native in (False, True):
                with self.subTest(mode=mode, native=native):
                    fixture = await self.selected_fixture(mode, native)
                    original = deepcopy(fixture.previous)
                    result = await fixture.operation()
                    self.assertEqual(fixture.isolated, [])
                    self.assertEqual([(row[0], row[1], row[2]) for row in fixture.calls],
                        [('exactOut' if mode.startswith('issue') else 'exactIn', 50, index) for index in (0, 1)])
                    self.assertEqual(fixture.metrics['candidateCalls'], 2)
                    self.assertEqual(fixture.previous, original)
                    self.assertEqual(result['executionAmount'], '100')
                    self.assertEqual(fixture.engine.semaphore._value, 8)
                    if mode.startswith('issue'):
                        self.assertEqual(result['expectedInputAmount'], '51')
                        self.assertLessEqual(sum(int(row['amountIn']) for row in result['quotes']), int(original['maximumInputAmount']))
                    else:
                        self.assertEqual(result['preview']['minimumAmountOut'], '80')
                        self.assertEqual(result['expectedCoreOutputs'], original['expectedCoreOutputs'])

    async def test_required_retained_replay_and_helpers_errors_keep_stage_ownership(self):
        for mode in ('issue-exact-out', 'redeem-exact-in'):
            for fault, expected in (('unsettled', InvalidPreview), ('transport', RpcTimeout),
                    ('snapshot', SnapshotChanged), ('contract', QuoteFailure), ('helpers', QuoteFailure)):
                with self.subTest(mode=mode, fault=fault):
                    fixture = await self.selected_fixture(mode, fault=fault)
                    with self.assertRaises(expected) as raised:
                        await fixture.operation()
                    self.assertNotIsInstance(raised.exception, RetainedPlanChanged)
                    self.assertEqual(fixture.isolated, [])
                    self.assertGreaterEqual(len(fixture.calls), 1)
                    self.assertEqual(fixture.engine.semaphore._value, 8)
        fixture = await self.selected_fixture('issue-exact-out', fault='unfilled')
        with self.assertRaises(InvalidPreview) as raised:
            await fixture.operation()
        self.assertNotIsInstance(raised.exception, RetainedPlanChanged)

    async def test_retained_selected_resolution_converts_only_fresh_plan_failure(self):
        for mode in ('issue-exact-out', 'redeem-exact-in'):
            with self.subTest(mode=mode):
                fixture = await self.selected_fixture(mode)
                semaphore = fixture.engine.semaphore
                class Permit:
                    async def acquire(self):
                        await semaphore.acquire()
                        fixture.engine.registry.inventory.clear()
                        return True
                    def release(self):
                        semaphore.release()
                    @property
                    def _value(self):
                        return semaphore._value
                    async def __aenter__(self):
                        await self.acquire()
                    async def __aexit__(self, *_args):
                        self.release()
                fixture.engine.semaphore = Permit()
                with self.assertRaises(RetainedPlanChanged):
                    await fixture.operation()
                self.assertEqual(fixture.calls, [])
                self.assertEqual(fixture.isolated, [])
                self.assertEqual(semaphore._value, 8)

    async def test_retained_execution_bounds_still_reject_final_shared_prices(self):
        for mode in ('issue-exact-out', 'redeem-exact-in'):
            with self.subTest(mode=mode):
                fixture = await self.selected_fixture(mode)
                for leg in fixture.previous['quotes']:
                    leg['amountIn' if mode.startswith('issue') else 'minimumAmountOut'] = '20' if mode.startswith('issue') else '101'
                with self.assertRaises(RetainedPlanChanged):
                    await fixture.operation()
                self.assertEqual(len(fixture.calls), 2)
                self.assertEqual(fixture.isolated, [])
                self.assertEqual(fixture.engine.semaphore._value, 8)

    async def test_optional_later_malformed_plan_preserves_sequential_error_precedence(self):
        fixture = await self.selected_fixture('redeem-exact-in')
        fixture.previous['quotes'][1]['routePlan']['mode'] = 'exactOut'
        with self.assertRaises(RpcTimeout):
            await fixture.operation()
        self.assertEqual(len(fixture.isolated), 1)
        self.assertEqual(fixture.calls, [])
        self.assertEqual(fixture.engine.semaphore._value, 8)

    async def test_retained_shared_cancel_keeps_foreign_required_read(self):
        for mode in ('issue-exact-out', 'redeem-exact-in'):
            with self.subTest(mode=mode):
                fixture = await self.selected_fixture(mode)
                bank = SharedReads()
                self.addAsyncCleanup(bank.close)
                entered, release = asyncio.Event(), asyncio.Event()
                async def read():
                    await release.wait()
                    return 123
                async def sdk(*_args, **_kwargs):
                    entered.set()
                    await bank.one('retained-required-read', read)
                fixture.engine.quote_sdk_branches = sdk
                foreign = asyncio.create_task(bank.one('retained-required-read', read))
                task = asyncio.create_task(fixture.operation())
                try:
                    await asyncio.wait_for(entered.wait(), 15)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertFalse(foreign.done())
                    self.assertEqual(fixture.engine.semaphore._value, 8)
                    release.set()
                    self.assertEqual(await foreign, 123)
                    self.assertEqual(bank.pending, {})
                finally:
                    release.set()
                    task.cancel()
                    await asyncio.gather(task, foreign, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
