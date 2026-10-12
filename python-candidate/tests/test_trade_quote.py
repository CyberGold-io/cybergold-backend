"""Whole-family economics, ordinary failures, retained execution and sharing."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

import httpx
from eth_abi.exceptions import DecodingError
from web3 import Web3

from cybergold_candidate.app import create_app
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.trade_quote import (PAXG, ZERO, TradeQuotes, core_request,
    economics, model_estimate)
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.protocol_facts import ABI as FACTS_ABI
from cybergold_candidate.quote_history import QuoteHistory
from cybergold_candidate.issuance_capacity import ABI as CAPACITY_ABI, read_capacity
from cybergold_candidate.route_search import RouteSearchRpc
from web3 import AsyncWeb3
from test_quote_intent import service, SETTINGS, ASSET_A, ASSET_B, ADAPTER, HASH, Provider, request as old_request
from cybergold_candidate.route_search import WETH, candidates

BLOCK = {'hash': HASH, 'number': 101}
CONTEXT = {'chainId': 1, 'blockNumber': '101', 'blockHash': HASH, 'observedAt': '2026-10-11T00:00:00Z'}
RECIPIENT = '0x'+'8'*40


def request(side='buy', mode='exact-in', **changes):
    return {'side': side, 'mode': mode, 'counterToken': PAXG, 'native': False, 'amount': '100',
        'recipient': RECIPIENT, 'deadline': '2000000000', 'slippageBps': 100, **changes}


def core_quote(side='buy', mode='exact-in', *, amount_in=100, amount_out=190, minimum=170,
               expected_input=100, maximum=110):
    return {'mode': ('issue-' if side == 'buy' else 'redeem-')+mode,
        'context': deepcopy(CONTEXT), 'quotes': [],
        'preview': {'fees': {'protocolFeeCygld': '2', 'helperFeeCygld': '1'},
            **({'orderedCoreAssets': [ASSET_A, ASSET_B]} if side == 'buy' else
               {'minimumAmountOut': str(minimum), 'projectedCoreOutputs': [
                   {'kind': 1, 'token': SETTINGS.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS, 'id': '123', 'amount': '9999'}]})},
        'initialPreview': None, 'basketPreview': {}, 'displayAmount': str(amount_out if mode == 'exact-in' else amount_in),
        'expectedInputAmount': str(expected_input), 'expectedOutputAmount': str(amount_out),
        'executionAmount': str(amount_out if side == 'buy' else amount_in),
        'maximumInputAmount': str(maximum if side == 'buy' else 0), 'slippageBps': 100,
        'expectedCoreOutputs': [], 'metrics': {'totalMs': 1}}


def market_quote(*, amount_in=100, amount_out=180, minimum=175, maximum=110):
    return {'operation': 'market', 'context': deepcopy(CONTEXT), 'totalInput': str(amount_in),
        'netOutput': str(amount_out), 'inputMaximum': str(maximum), 'outputMinimum': str(minimum),
        'fee': {'amount': '1'}, 'params': {'adapter': ADAPTER, 'bound': str(minimum)},
        'plan': {'fee': {'amount': '1'}, 'params': {'adapter': ADAPTER, 'bound': str(minimum)}}}


class Engines:
    def __init__(self, core_value=None, market_value=None):
        self.core_value, self.market_value = core_value or core_quote(), market_value or market_quote()
        self.core_calls, self.market_calls, self.heads, self.models = [], [], 0, 0
        self.core_error = self.market_error = None
        self.hold_core = self.hold_market = None
        self.core_started, self.market_started = asyncio.Event(), asyncio.Event()
        self.core_cancelled, self.market_cancelled = asyncio.Event(), asyncio.Event()
        self.pending = SharedReads()
        self.core = SimpleNamespace(settings=SETTINGS, routes=SimpleNamespace(rpc=object(), rpc_factory=lambda _: object()),
            history=None, get=self.core_get)
        self.market = SimpleNamespace(head=self.head, _get=self.market_get, packet=self.packet,
            estimate=lambda _packet, _request: None, get_model=self.get_model)
        self.quotes = TradeQuotes(SETTINGS, self.core, self.market, request_resolver=self.resolve,
            basis_reader=lambda block: asyncio.sleep(0, result=([ASSET_A, ASSET_B], [500000, 500000], 2)))

    async def resolve(self, value):
        return {**value, 'adapter': value.get('adapter') or ADAPTER}

    async def head(self):
        async def read():
            self.heads += 1
            await asyncio.sleep(0)
            return deepcopy(BLOCK)
        return await self.pending.one('head', read)

    def packet(self, value):
        return {'namespace': 'market', 'family': 'fixture', 'intent': value, 'routes': [], 'feeRatePpm': 1000}

    async def get_model(self, value, *, block):
        self.models += 1
        return self.packet(value)

    async def core_get(self, value, publish, *, block, quoted_ranking):
        self.core_calls.append((deepcopy(value), deepcopy(block), quoted_ranking))
        self.core_started.set()
        try:
            if self.hold_core:
                await self.hold_core.wait()
            if self.core_error:
                raise self.core_error
            await publish({'type': 'qualified', 'value': deepcopy(self.core_value)})
            return deepcopy(self.core_value)
        except asyncio.CancelledError:
            self.core_cancelled.set()
            raise

    async def market_get(self, value, publish, *, block):
        self.market_calls.append((deepcopy(value), deepcopy(block)))
        self.market_started.set()
        try:
            if self.hold_market:
                await self.hold_market.wait()
            if self.market_error:
                raise self.market_error
            await publish({'type': 'qualified', 'value': deepcopy(self.market_value)})
            return deepcopy(self.market_value)
        except asyncio.CancelledError:
            self.market_cancelled.set()
            raise

    async def close(self):
        await self.quotes.close()
        await self.pending.close()


class TradeTests(unittest.IsolatedAsyncioTestCase):
    def engines(self, *args, **kwargs):
        engines = Engines(*args, **kwargs)
        self.addAsyncCleanup(engines.close)
        return engines

    async def test_four_modes_rank_complete_net_economics_not_bound_or_recovery_values(self):
        for side, mode in [('buy', 'exact-in'), ('buy', 'exact-out'), ('sell', 'exact-in'), ('sell', 'exact-out')]:
            with self.subTest(side=side, mode=mode):
                core = core_quote(side, mode, amount_in=105, amount_out=190, minimum=160, expected_input=95, maximum=120)
                market = market_quote(amount_in=100, amount_out=180, minimum=179, maximum=150)
                engines = self.engines(core, market)
                frames = []
                result = await engines.quotes.get(request(side, mode), lambda f: asyncio.sleep(0, result=frames.append(f)))
                # Core sell EO burns105; advisory raw solver95 is not a refund.
                expected = 'market' if side == 'sell' and mode == 'exact-out' else 'core'
                self.assertEqual(result['strategy'], expected)
                self.assertEqual(result['evaluation'], {'core': 'complete', 'market': 'complete'})
                self.assertEqual(engines.heads, 1)
                self.assertTrue(engines.core_calls[0][2])
                self.assertEqual(engines.core_calls[0][1], engines.market_calls[0][1])
                self.assertEqual(result['providerQuote'], market if expected == 'market' else core)

    async def test_equal_economics_choose_core_independent_of_completion_order(self):
        engines = self.engines(core_quote(amount_out=180), market_quote(amount_out=180))
        engines.hold_core = asyncio.Event()
        frames = []
        operation = asyncio.create_task(engines.quotes.get(request(), lambda f: asyncio.sleep(0, result=frames.append(f))))
        await engines.core_started.wait()
        while not any(f['type'] == 'qualified' for f in frames):
            await asyncio.sleep(0)
        self.assertEqual(next(f for f in frames if f['type'] == 'qualified')['value']['strategy'], 'market')
        engines.hold_core.set()
        self.assertEqual((await operation)['strategy'], 'core')

    async def test_first_qualified_survives_slow_failed_competitor(self):
        engines = self.engines()
        engines.hold_market, engines.market_error = asyncio.Event(), TimeoutError()
        frames = []
        operation = asyncio.create_task(engines.quotes.get(request(), lambda f: asyncio.sleep(0, result=frames.append(f))))
        await engines.market_started.wait()
        while not any(f['type'] == 'qualified' for f in frames):
            await asyncio.sleep(0)
        self.assertFalse(operation.done())
        engines.hold_market.set()
        result = await operation
        self.assertEqual(result['strategy'], 'core')
        self.assertEqual(result['evaluation']['market'], 'unavailable')
        self.assertEqual(next(f for f in frames if f['type'] == 'provider-error')['code'], 'quote-timeout')

    async def test_failure_of_each_provider_leaves_other_and_both_errors_remain_ordinary(self):
        for strategy in ('core', 'market'):
            engines = self.engines()
            setattr(engines, strategy+'_error', QuoteFailure('quote-contract-reverted'))
            result = await engines.quotes.get(request(), lambda _: asyncio.sleep(0))
            self.assertNotEqual(result['strategy'], strategy)
        engines = self.engines()
        engines.core_error = engines.market_error = QuoteFailure('rpc-rate-limit')
        with self.assertRaisesRegex(QuoteFailure, 'request limit'):
            await engines.quotes.get(request(), lambda _: asyncio.sleep(0))

    async def test_native_repricing_invalidates_only_that_family_and_replaces_lower_sdk_score(self):
        engines = self.engines(core_quote(amount_out=190), market_quote(amount_out=180))
        async def repriced(value, publish, *, block):
            await publish({'type': 'qualified', 'value': market_quote(amount_out=210)})
            await publish({'type': 'invalidated'})
            await publish({'type': 'qualified', 'value': market_quote(amount_out=180)})
            return market_quote(amount_out=180)
        engines.market._get = repriced
        frames = []
        result = await engines.quotes.get(request(), lambda f: asyncio.sleep(0, result=frames.append(f)))
        self.assertEqual(result['strategy'], 'core')
        self.assertEqual(result['quotedOutput'], '190')
        self.assertTrue(any(f['type'] == 'invalidated' and f['strategy'] == 'market' for f in frames))
        self.assertNotEqual(frames[-1].get('value', {}).get('quotedOutput'), '210')

    async def test_proved_noncanonical_head_retires_both_families_after_early_qualified(self):
        engines = self.engines()
        async def changed(value, publish, *, block):
            await publish({'type': 'qualified', 'value': market_quote(amount_out=210)})
            raise SnapshotChanged('Recovery snapshot changed; restart discovery', retry=1)
        engines.market._get = changed
        frames = []
        with self.assertRaises(SnapshotChanged):
            await engines.quotes.get(request(), lambda f: asyncio.sleep(0, result=frames.append(f)))
        invalidated = next(i for i, f in enumerate(frames) if f['type'] == 'invalidated')
        self.assertFalse(any(f['type'] == 'qualified' for f in frames[invalidated+1:]))

    async def test_actual_core_optional_qualifier_disproof_survives_later_ordinary_tail_timeout(self):
        intent, _provider, routes, _wire = service()
        self.addAsyncCleanup(routes.close)
        engines = self.engines()
        engines.market_error = QuoteFailure('quote-no-route')
        quotes = TradeQuotes(SETTINGS, intent, engines.market, request_resolver=engines.resolve,
            basis_reader=lambda _: asyncio.sleep(0, result=([ASSET_A, ASSET_B], [500000, 500000], 2)))
        self.addAsyncCleanup(quotes.close)
        first, disproved = asyncio.Event(), asyncio.Event()
        checks, frames = [], []
        async def canonical(block):
            checks.append(block)
            if len(checks) >= 2:
                disproved.set()
                raise SnapshotChanged('Recovery snapshot changed; restart discovery', retry=1)
        routes.rpc.assert_canonical = canonical
        async def search(value, on_update, *, block):
            async def update(amount):
                rows = [{'best': {**candidates(target, value['mode'])[0], 'quote': str(amount)},
                    'attempted': 1, 'total': 2, 'succeeded': 1, 'failures': []} for target in value['targets']]
                await on_update({'results': rows})
            await update(25)
            await first.wait()
            await update(20)
            await disproved.wait()
            await asyncio.sleep(0)
            raise TimeoutError('Ordinary later candidate tail deadline')
        routes.get = search
        async def publish(frame):
            frames.append(frame)
            if frame['type'] == 'qualified':
                first.set()
        with self.assertRaises(SnapshotChanged):
            await asyncio.wait_for(quotes.get(request('buy', 'exact-out'), publish), 3)
        self.assertTrue(first.is_set())
        self.assertTrue(disproved.is_set())
        invalidated = next(i for i, frame in enumerate(frames) if frame['type'] == 'invalidated')
        self.assertFalse(any(frame['type'] == 'qualified' for frame in frames[invalidated+1:]))

    async def test_capability_filter_prevents_market_fanout_for_other_token_and_native(self):
        for value in (request(counterToken=ASSET_A), request(native=True, counterToken=ZERO)):
            engines = self.engines()
            result = await engines.quotes.get(value, lambda _: asyncio.sleep(0))
            self.assertEqual(result['evaluation']['market'], 'unsupported')
            self.assertFalse(engines.market_calls)
            self.assertEqual(engines.models, 0)
            if value['native']:
                self.assertEqual(engines.core_calls[0][0]['token'], ZERO)
                self.assertEqual(engines.core_calls[0][0]['quoteToken'].lower(), WETH.lower())
                self.assertEqual(result['tokenIn'], ZERO)

    async def test_historical_adapter_fallback_preserves_core_without_typed_market_fanout(self):
        engines = self.engines()
        legacy = '0x4edb8190232a47e45d861003672938eb7ee84a15'
        async def resolve(value):
            return {**value, 'adapter': legacy}
        engines.quotes.request_resolver = resolve
        result = await engines.quotes.get(request(), lambda _: asyncio.sleep(0))
        self.assertEqual(result['strategy'], 'core')
        self.assertEqual(result['providerRequest']['adapter'], legacy)
        self.assertEqual(result['evaluation']['market'], 'unsupported')
        self.assertFalse(engines.market_calls)
        self.assertEqual(engines.models, 0)

    async def test_retained_plan_selects_same_family_and_literal_limits(self):
        for strategy in ('core', 'market'):
            engines = self.engines()
            if strategy == 'market':
                engines.core_error = QuoteFailure('quote-no-route')
            result = await engines.quotes.get(request(), lambda _: asyncio.sleep(0))
            engines.core_calls.clear()
            engines.market_calls.clear()
            retained = {'strategy': strategy, 'request': result['providerRequest'], 'quote': result['providerQuote']}
            refreshed = await engines.quotes.get(request(deadline='2000000001', retainedPlan=retained), lambda _: asyncio.sleep(0))
            self.assertEqual(refreshed['strategy'], strategy)
            self.assertEqual(len(engines.core_calls), int(strategy == 'core'))
            self.assertEqual(len(engines.market_calls), int(strategy == 'market'))
            provider_request = refreshed['providerRequest']
            self.assertEqual(provider_request['deadline'], '2000000001')
            self.assertEqual(provider_request['adapter'], result['providerRequest']['adapter'])
            if strategy == 'core':
                self.assertEqual(provider_request['retainedPlan']['maximumInputAmount'], result['providerQuote']['maximumInputAmount'])
            else:
                self.assertEqual(provider_request['retainedPlan'], result['providerQuote']['plan'])
            self.assertEqual(engines.models, 1+int(strategy == 'market'))

    async def test_two_subscribers_share_children_and_last_disconnect_cancels_both(self):
        engines = self.engines()
        engines.hold_core, engines.hold_market = asyncio.Event(), asyncio.Event()
        first = asyncio.create_task(engines.quotes.get(request(), lambda _: asyncio.sleep(0)))
        second = asyncio.create_task(engines.quotes.get(request(), lambda _: asyncio.sleep(0)))
        await engines.core_started.wait()
        await engines.market_started.wait()
        while engines.quotes.sharing.joined != 1:
            await asyncio.sleep(0)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        self.assertFalse(engines.core_cancelled.is_set())
        self.assertFalse(engines.market_cancelled.is_set())
        self.assertEqual(len(engines.core_calls), 1)
        self.assertEqual(len(engines.market_calls), 1)
        self.assertEqual(engines.heads, 1)
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        self.assertTrue(engines.core_cancelled.is_set())
        self.assertTrue(engines.market_cancelled.is_set())

    async def test_real_basis_decoder_reads_only_order_and_weights_at_injected_hash(self):
        engines = self.engines()
        reads = []
        contract = Web3().eth.contract(abi=FACTS_ABI['core'])
        async def pool_batch(calls, block, counts):
            rows = []
            for address, data in calls:
                name = contract.decode_function_input(data)[0].fn_name
                reads.append((address, name, block['hash']))
                value = [ASSET_A, ASSET_B] if name == 'basketAssets' else [500000, 500000]
                rows.append({'result': '0x'+Web3().codec.encode(['address[]' if name == 'basketAssets' else 'uint256[]'], [value]).hex()})
            counts['issued'] = len(calls)
            return rows, counts
        engines.core.routes.rpc = SimpleNamespace(w3=Web3(), pool_batch=pool_batch)
        engines.quotes.basis_reader = None
        result = await engines.quotes.get(request(), lambda _: asyncio.sleep(0))
        self.assertEqual([row[1] for row in reads], ['basketAssets', 'basketTargetsPpm'])
        self.assertTrue(all(row[2] == HASH for row in reads))
        self.assertEqual(result['metrics']['targetReads'], 2)

    async def test_basis_model_and_unified_capacity_share_identical_canonical_reads(self):
        engines = self.engines()
        abi = [*CAPACITY_ABI, next(row for row in FACTS_ABI['core'] if row['name'] == 'basketAssets')]
        contract = Web3().eth.contract(abi=abi)
        issued = []
        values = {'basketAssets': [ASSET_A, ASSET_B], 'basketTargetsPpm': [500000, 500000],
            'basketCygldPerUnitFp18': [10**18, 10**18], 'issuanceFeePpm': 1000, 'helperFeePpm': 1000,
            'totalSupply': 1000, 'maxTotalSupply': 1000000, 'effectiveCygldSupplyCap': 1000000}
        async def transport(request):
            rows = []
            for call in json.loads(request.content):
                name = contract.decode_function_input(call['params'][0]['data'])[0].fn_name
                issued.append((name, call['params'][1]))
                out = next(row for row in abi if row['name'] == name)['outputs'][0]['type']
                rows.append({'id': call['id'], 'result': '0x'+Web3().codec.encode([out], [values[name]]).hex()})
            await asyncio.sleep(0)
            return httpx.Response(200, json=rows)
        client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        rpc = RouteSearchRpc(SETTINGS, AsyncWeb3(Provider()), client=client)
        self.addAsyncCleanup(rpc.close)
        engines.core.routes.rpc = rpc
        engines.quotes.basis_reader = None
        history = QuoteHistory(SETTINGS)
        metrics = dict(rpcReads=0, rpcReadsRequested=0, rpcReadsCoalesced=0, rpcReadsReused=0)
        core = SETTINGS.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS
        helper = SETTINGS.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS
        basis, observed, capacity = await asyncio.gather(engines.quotes.read_basis(BLOCK),
            history.batch(rpc, [(core, 'basketAssets', []), (core, 'basketTargetsPpm', []),
                               (helper, 'helperFeePpm', [])], BLOCK, abi),
            read_capacity(rpc, SETTINGS, BLOCK, metrics, shared=True))
        self.assertEqual(basis[:2], ([ASSET_A, ASSET_B], [500000, 500000]))
        self.assertEqual(observed[-1], 1000)
        self.assertEqual(capacity[-1], 1000)
        self.assertEqual(len(issued), 8)  # Twelve requested members, eight distinct calls.
        self.assertTrue(all(row[1] == {'blockHash': HASH, 'requireCanonical': True} for row in issued))
        self.assertGreater(metrics['rpcReadsCoalesced'], 0)
        await client.aclose()

    async def test_malformed_shared_getter_retries_only_failed_typed_observation(self):
        abi = [*CAPACITY_ABI, next(row for row in FACTS_ABI['core'] if row['name'] == 'basketAssets')]
        contract = Web3().eth.contract(abi=abi)
        values = {'basketAssets': [ASSET_A, ASSET_B], 'basketTargetsPpm': [500000, 500000],
            'basketCygldPerUnitFp18': [10**18, 10**18], 'issuanceFeePpm': 1000, 'helperFeePpm': 1000,
            'totalSupply': 1000, 'maxTotalSupply': 1000000, 'effectiveCygldSupplyCap': 1000000}
        for reader, malformed in [('capacity', 'helperFeePpm'), ('history', 'basketTargetsPpm'),
                                  ('basis', 'basketTargetsPpm')]:
            with self.subTest(reader=reader):
                batches = []
                async def transport(request):
                    batch = json.loads(request.content)
                    names = [contract.decode_function_input(call['params'][0]['data'])[0].fn_name for call in batch]
                    batches.append(names)
                    rows = []
                    for call, name in zip(batch, names, strict=True):
                        out = next(row for row in abi if row['name'] == name)['outputs'][0]['type']
                        raw = '0x' if len(batches) == 1 and name == malformed else '0x'+Web3().codec.encode([out], [values[name]]).hex()
                        rows.append({'id': call['id'], 'result': raw})
                    return httpx.Response(200, json=rows)
                client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
                rpc = RouteSearchRpc(SETTINGS, AsyncWeb3(Provider()), client=client)
                try:
                    if reader == 'capacity':
                        metrics = dict(rpcReads=0, rpcReadsRequested=0, rpcReadsCoalesced=0, rpcReadsReused=0)
                        async def read():
                            return await read_capacity(rpc, SETTINGS, BLOCK, metrics, shared=True)
                    elif reader == 'history':
                        history = QuoteHistory(SETTINGS)
                        async def read():
                            return await history.batch(rpc, [(SETTINGS.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS, name, [])
                                for name in ('basketAssets', 'basketTargetsPpm')], BLOCK, abi)
                    else:
                        engines = self.engines()
                        engines.core.routes.rpc = rpc
                        engines.quotes.basis_reader = None
                        read = lambda: engines.quotes.read_basis(BLOCK)
                    with self.assertRaises(DecodingError):
                        await read()
                    observed = await read()
                    self.assertTrue(observed)
                    self.assertEqual(len(batches), 2)
                    self.assertEqual(batches[-1], [malformed])
                    # Successful siblings remain shared; retry is not a full reread.
                    self.assertEqual(len(rpc.pool_reads.completed), len(batches[0]))
                finally:
                    await rpc.close()
                    await client.aclose()

    async def test_cold_lightweight_models_become_useful_and_warm_model_uses_zero_new_reads(self):
        engines = self.engines()
        history = QuoteHistory(SETTINGS)
        self.addAsyncCleanup(history.close)
        engines.core.history, engines.core.now = history, lambda: CONTEXT['observedAt']
        engines.quotes.history = history
        state = {'assets': [PAXG], 'weights': ['1000000'], 'conversions': [str(10**18)],
            'issueFee': '1000', 'helperFee': '1000', 'redeemFee': '1000', 'supply': '100000',
            'maxSupply': '10000000', 'effectiveCap': '10000000', 'available': ['100000'],
            'recoveryShares': [], 'recoveryValues': [], 'descriptors': [{'kind': 0, 'token': PAXG, 'id': '0'}]}
        acquisitions = []
        async def acquire(_rpc, block, context, _epoch):
            acquisitions.append(block)
            history.states[block['hash'].lower()] = {'state': state, 'context': context}
        history.acquire_state = acquire
        cached = {'routes': []}
        def packet(value):
            return {**engines.packet(value), **cached}
        async def model(value, *, block):
            engines.models += 1
            cached['routes'] = [{'route': {}, 'amountIn': '1000', 'amountOut': '2000', 'points': [],
                'exchangeRate': {'numerator': '2', 'denominator': '1'},
                'feeRetention': {'numerator': '1', 'denominator': '1'},
                'localImpact': {'numerator': '0', 'denominator': '1'}}]
            return packet(value)
        engines.market.packet, engines.market.get_model = packet, model
        from cybergold_candidate.market_swap import MarketQuotes
        engines.market.estimate = lambda packet, value: MarketQuotes.estimate(None, packet, value)
        value = {k: request(amount='1000')[k] for k in ('side', 'mode', 'counterToken', 'native', 'amount', 'slippageBps')}
        cold = await engines.quotes.get_model(value)
        self.assertEqual(cold['estimate'], {'strategy': 'market', 'amount': '1998'})
        self.assertEqual({row['strategy'] for row in cold['models']}, {'core', 'market'})
        self.assertEqual((engines.heads, engines.models, len(acquisitions)), (1, 1, 1))
        warm = await engines.quotes.get_model(value)
        self.assertEqual(warm['estimate'], cold['estimate'])
        self.assertEqual((engines.heads, engines.models, len(acquisitions)), (1, 1, 1))

    async def test_retained_core_never_starts_blocked_market_model(self):
        engines = self.engines()
        initial = await engines.quotes.get(request(), lambda _: asyncio.sleep(0))
        async def forbidden(*_args, **_kwargs):
            raise AssertionError('Unrelated market model was acquired')
        engines.market.get_model = forbidden
        retained = {'strategy': 'core', 'request': initial['providerRequest'], 'quote': initial['providerQuote']}
        result = await engines.quotes.get(request(retainedPlan=retained), lambda _: asyncio.sleep(0))
        self.assertEqual(result['strategy'], 'core')
        self.assertEqual(len(engines.market_calls), 1)

    async def test_ordinary_same_provider_tail_failure_preserves_its_qualified_incumbent(self):
        engines = self.engines()
        engines.market_error = QuoteFailure('quote-no-route')
        async def timed_out(value, publish, *, block, quoted_ranking):
            await publish({'type': 'qualified', 'value': engines.core_value})
            raise TimeoutError()
        engines.core.get = timed_out
        result = await engines.quotes.get(request(), lambda _: asyncio.sleep(0))
        self.assertEqual(result['strategy'], 'core')
        self.assertEqual(result['evaluation'], {'core': 'unavailable', 'market': 'unavailable'})

    async def test_actual_core_exact_input_tolerance_changes_protection_not_nominal_output(self):
        # The shipped ABI preview, route producer and unified coordinator all
        # execute. Only tolerance differs; pool price, wallet budget and Core
        # capacity remain identical for each pair of requests.
        for side in ('buy', 'sell'):
            for native in (False, True):
                results = []
                for bps in (0, 100):
                    with self.subTest(side=side, native=native, bps=bps):
                        intent, provider, routes, _ = service()
                        self.addAsyncCleanup(routes.close)
                        if side == 'buy':
                            # A capped fixed target leaves input available for
                            # the existing per-route price cushion and refund.
                            provider.issue_cap = 15000
                        engines = self.engines()
                        quotes = TradeQuotes(SETTINGS, intent, engines.market,
                            request_resolver=engines.resolve,
                            basis_reader=lambda _: asyncio.sleep(0,
                                result=([ASSET_A, ASSET_B], [500000, 500000], 2)))
                        self.addAsyncCleanup(quotes.close)
                        value = request(side, 'exact-in', counterToken=WETH,
                            native=native, amount='10000', slippageBps=bps)
                        result = await quotes.get(value, lambda _: asyncio.sleep(0))
                        self.assertEqual(result['strategy'], 'core')
                        self.assertEqual(result['providerQuote']['slippageBps'], bps)
                        self.assertEqual(result['providerRequest']['amount'], '10000')
                        self.assertEqual(result['providerRequest']['token'], ZERO if native else WETH)
                        self.assertEqual(result['context']['blockHash'], HASH)
                        self.assertFalse(engines.market_calls)
                        results.append(result)
                zero, protected = results
                self.assertEqual(zero['quotedOutput'], protected['quotedOutput'])
                self.assertEqual(zero['quotedInput'], protected['quotedInput'])
                self.assertEqual(zero['inputMaximum'], protected['inputMaximum'])
                if side == 'buy':
                    # Actual fixed mint remains 15000, funded by a 10000 input
                    # ceiling; nominal sourcing costs 7500 in both cases.
                    self.assertEqual(zero['quotedOutput'], '15000')
                    self.assertEqual(zero['providerQuote']['executionAmount'], '15000')
                    self.assertEqual(protected['providerQuote']['executionAmount'], '15000')
                    self.assertEqual(zero['quotedInput'], '7500')
                    self.assertEqual(zero['inputMaximum'], '10000')
                    self.assertEqual(zero['outputMinimum'], protected['outputMinimum'])
                    self.assertEqual(zero['outputMinimum'], '15000')
                    self.assertEqual([q['amountIn'] for q in zero['providerQuote']['quotes']], ['3750', '3750'])
                    self.assertEqual([q['amountIn'] for q in protected['providerQuote']['quotes']], ['3788', '3788'])
                    self.assertLessEqual(sum(int(q['amountIn']) for q in protected['providerQuote']['quotes']), 10000)
                else:
                    # The 10000 fixed burn quotes 20000 output; only routed and
                    # Core output minima incorporate the selected protection.
                    self.assertEqual(zero['quotedInput'], '10000')
                    self.assertEqual(zero['quotedOutput'], '20000')
                    self.assertEqual((zero['outputMinimum'], protected['outputMinimum']), ('20000', '19800'))
                    self.assertEqual([q['minimumAmountOut'] for q in zero['providerQuote']['quotes']], ['10000', '10000'])
                    self.assertEqual([q['minimumAmountOut'] for q in protected['providerQuote']['quotes']], ['9900', '9900'])
                    self.assertEqual([q['minimumAmount'] for q in zero['providerQuote']['expectedCoreOutputs'][:2]], ['5000', '5000'])
                    self.assertEqual([q['minimumAmount'] for q in protected['providerQuote']['expectedCoreOutputs'][:2]], ['4950', '4950'])

    async def test_actual_existing_core_planner_executes_backend_seed_without_app_targets(self):
        for side, mode in [('buy', 'exact-in'), ('buy', 'exact-out'), ('sell', 'exact-in'), ('sell', 'exact-out')]:
            with self.subTest(side=side, mode=mode):
                intent, provider, routes, _ = service()
                self.addAsyncCleanup(routes.close)
                engines = self.engines()
                quotes = TradeQuotes(SETTINGS, intent, engines.market, request_resolver=engines.resolve,
                    basis_reader=lambda _: asyncio.sleep(0, result=([ASSET_A, ASSET_B], [500000, 500000], 2)))
                self.addAsyncCleanup(quotes.close)
                result = await quotes.get(request(side, mode, counterToken=old_request('issue-exact-in')['token']), lambda _: asyncio.sleep(0))
                self.assertEqual(result['strategy'], 'core')
                self.assertEqual(result['providerRequest']['orderedAssets'], [ASSET_A, ASSET_B])
                self.assertTrue(provider.contract_calls)
                names = [row[0] for row in provider.contract_calls]
                self.assertTrue(any('previewIssueFromTokenExactOut' == name for name in names) if side == 'buy'
                    else any('previewRedeemToTokenExactIn' == name for name in names))
                if side == 'sell':
                    self.assertGreater(int(result['providerQuote']['preview']['projectedCoreOutputs'][-1]['amount']), 0)
                    self.assertEqual(result['quotedInput'], result['providerQuote']['executionAmount'])

    async def test_http_stream_and_invalid_input_remain_fixed_unsigned_read_apis(self):
        engines = self.engines()
        app = create_app(trade_quotes=engines.quotes)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            response = await client.post('/api/quotes/trade/stream', json=request())
            self.assertEqual(response.status_code, 200)
            frames = [json.loads(row) for row in response.text.splitlines()]
            self.assertEqual(frames[-1]['type'], 'complete')
            self.assertEqual(frames[-1]['value']['strategy'], 'core')
            rejected = await client.post('/api/quotes/trade/stream', json=request(amount='-1'))
            self.assertEqual(rejected.status_code, 400)
            model = await client.post('/api/quotes/trade/model', json={k: request()[k]
                for k in ('side', 'mode', 'counterToken', 'native', 'amount', 'slippageBps')})
            self.assertEqual(model.status_code, 200)
            self.assertEqual(model.json()['namespace'], 'trade')


class ArithmeticTests(unittest.TestCase):
    def test_one_unit_direct_and_zero_weight_seeds_preserve_existing_app_allocations(self):
        value = {**request('sell', 'exact-out', counterToken=ASSET_A), 'adapter': ADAPTER}
        direct = core_request(value, [ASSET_A, ASSET_B], [1000000, 0])
        self.assertEqual(direct['targets'], [{'inputAsset': ASSET_A, 'outputAsset': ASSET_A, 'amount': '100'}])
        buy = core_request({**value, 'side': 'buy', 'mode': 'exact-in', 'amount': '101'},
                           [ASSET_A, ASSET_B], [500000, 500000])
        self.assertEqual(buy['targets'], [{'inputAsset': ASSET_A, 'outputAsset': ASSET_B, 'amount': '51'}])
        tiny = core_request({**value, 'amount': '1'}, [ASSET_A, ASSET_B], [500000, 500000])
        self.assertEqual(tiny['targets'], [{'inputAsset': ASSET_B, 'outputAsset': ASSET_A, 'amount': '1'}])

    def test_output_targeted_core_full_burn_is_not_unslipped_advisory_input(self):
        result = economics('core', request('sell', 'exact-out'), core_quote('sell', 'exact-out', amount_in=105, expected_input=99))
        self.assertEqual(result['quotedInput'], '105')
        self.assertEqual(result['inputMaximum'], '105')

    def test_actual_core_model_accounts_for_both_fees_and_direct_basket_input(self):
        state = {'assets': [PAXG], 'weights': ['1000000'], 'conversions': [str(10**18)],
            'issueFee': '1000', 'helperFee': '1000', 'redeemFee': '1000', 'supply': '100000',
            'maxSupply': '10000000', 'effectiveCap': '10000000', 'available': ['100000'],
            'recoveryShares': [], 'recoveryValues': [], 'descriptors': [{'kind': 0, 'token': PAXG, 'id': '0'}]}
        for side, mode, expected in [('buy', 'exact-in', '999'), ('buy', 'exact-out', '1002'),
                                      ('sell', 'exact-in', '999'), ('sell', 'exact-out', '1002')]:
            value = {**request(side, mode, amount='1000'), 'adapter': ADAPTER}
            packet = {'protocol': {'state': state}, 'routes': [], 'intent': core_request(value, [PAXG], [1000000])}
            self.assertEqual(model_estimate(packet, value), expected)


if __name__ == '__main__':
    unittest.main()
