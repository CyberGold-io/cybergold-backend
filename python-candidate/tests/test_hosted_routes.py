"""Hosted responses nominate canonical topology, never remote execution terms."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from cybergold_candidate.quoter.bootstrap import ProviderUnavailable
from cybergold_candidate.quoter.hosted_routes import (
    HostedCandidates, HostedRouteError, QUOTE_URL, UniRouteApiProvider, UniswapApiProvider,
    topology_identifiers)
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.uniswap_v4 import v4_pool_id
from cybergold_candidate.uniswap_api_queue import UniswapApiQueue
from cybergold_candidate.uniswap_routes import pool_identity


A, B, C, D, HELPERS, CANONICAL_V2, CANONICAL_V3, MANAGER, FAKE = (
    '0x' + value * 40 for value in '123456789')
ZERO = '0x' + '0' * 40
WETH = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
BLOCK = {'number': 1234, 'hash': '0x' + 'a' * 64}
AMOUNT = 100000000000000000007


def settings(**updates):
    return SimpleNamespace(**{
        'NEXT_PUBLIC_CHAIN_ID': '1', 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS': HELPERS,
        'CYBERGOLD_UNISWAP_API_KEY': 'fixture-account-credential', **updates})


def token(address):
    return {'address': address, 'decimals': '255', 'chainId': 999, 'symbol': 'UNTRUSTED'}


def standard_pool(protocol, source, target, **extra):
    return {'type': protocol + '-pool', 'address': FAKE, 'tokenIn': token(source),
            'tokenOut': token(target), 'amountIn': str(2**255), 'amountOut': str(2**256 - 1),
            'sqrtRatioX96': '1', 'liquidity': str(2**255), 'tickCurrent': 0, **extra}


def packed(tokens, fees):
    return '0x' + tokens[0][2:] + ''.join(f'{fee:06x}' + address[2:]
        for fee, address in zip(fees, tokens[1:], strict=True))


class Registry:
    chain = 1
    generation = 'fixture-generation'
    factory = '0x' + 'a' * 40
    v2_factory = '0x' + 'b' * 40
    pool_manager = MANAGER

    def __init__(self):
        self.inventory, self.lookups, self.lookup_anchors = {}, {}, {}
        self.lookup_month = datetime.now(timezone.utc).strftime('%Y-%m')
        self.pending, self.calls, self.metadata_calls = SharedReads(), [], []

    def get_rpc(self):
        return self

    async def read_function(self, address, signature, inputs, arguments, outputs, block):
        self.calls.append((address, signature, arguments, deepcopy(block)))
        if signature == 'getPair(address,address)':
            return (CANONICAL_V2,)
        if signature == 'getPool(address,address,uint24)':
            return (CANONICAL_V3,)
        if signature == 'tickSpacing()':
            return (60,)
        raise AssertionError('Unexpected RPC operation: ' + signature)

    async def token_metadata(self, address, block, publish=False):
        self.metadata_calls.append((address, deepcopy(block), publish))
        return {'address': address, 'decimals': 6, 'chainId': self.chain}

    def token(self, address, decimals):
        return {'address': address, 'decimals': decimals, 'chainId': self.chain}


class FixtureTransport(httpx.AsyncBaseTransport):
    def __init__(self, document=None, status=200, handler=None):
        self.document, self.status, self.handler = document, status, handler
        self.requests, self.closed = [], False

    async def handle_async_request(self, request):
        self.requests.append(request)
        if self.handler:
            await self.handler(request)
        return httpx.Response(self.status, json=self.document, request=request)

    async def aclose(self):
        self.closed = True


def make_provider(document, *, guidestar=False, config=None, registry=None, status=200, handler=None,
                  resolver=None, uniroute=False):
    registry = registry or Registry()
    transport = FixtureTransport(document, status, handler)
    created = []
    def client_factory():
        value = httpx.AsyncClient(transport=transport, timeout=None)
        created.append(value)
        return value
    provider_type = UniRouteApiProvider if uniroute else UniswapApiProvider
    provider = provider_type(SimpleNamespace(registry=registry, uniswap_api_queue=UniswapApiQueue()), config or settings(),
        **({} if uniroute else {'guidestar': guidestar}),
        client_factory=client_factory, resolver=resolver)
    return provider, registry, transport, created


class HostedRoutesTest(unittest.IsolatedAsyncioTestCase):
    def many_paths(self):
        source, target = '0x'+'11'*20, '0x'+'ee'*20
        middles = ['0x'+format(index, '040x') for index in range(101, 106)]
        def row(a, b, fee):
            return standard_pool('v3', a, b, fee=fee, amountIn='10000')
        routes = [[row(source, target, fee)] for fee in (100, 500, 3000, 10000)]
        routes.extend([row(source, middle, left), row(middle, target, right)]
            for middle in middles for left in (100, 500, 3000, 10000) for right in (100, 500, 3000, 10000))
        return source, target, {'quote': {'route': routes, 'routeCandidates': [{}]}}

    async def test_cooperative_batches_preserve_full_prechange_candidate_digest_and_one_http(self):
        source, target, document = self.many_paths()
        provider, registry, transport, clients = make_provider(document, uniroute=True)
        batches, candidates = [], []
        try:
            async for batch in provider.discover_batches(source, target, 10000, BLOCK):
                self.assertIsInstance(batch, HostedCandidates)
                self.assertEqual(batch.engine_attribution, {'engine': 'uniroute', 'evidence': 'route-candidates'})
                batches.append(batch)
                candidates.extend(batch)
            def shape(candidate):
                return [[int(row['amountIn']), [list(pool_identity(hop['pool']))+[hop['zeroForOne']]
                    if 'pool' in hop else [hop['kind'], hop['currencyOut'].lower()]
                    for hop in row['hops']]] for row in candidate]
            observed = hashlib.sha256(json.dumps([shape(row) for row in candidates],
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            # Captured from the prechange eager provider using this finite
            #84-path fixture: includes ordered remote weights and every split.
            self.assertEqual(len(candidates), 10543)
            self.assertEqual(observed, '47f68e065d2712f0322816dc80e9adae77e2e31a2c0c5c8800a33b5227781321')
            self.assertEqual(len(batches), 2)
            self.assertEqual(len(transport.requests), 1)
            self.assertEqual((registry.calls, registry.metadata_calls), ([], []))
        finally:
            await provider.close()
        self.assertTrue(clients[0].is_closed)

    async def test_first_hosted_batch_precedes_split_tail_and_closing_drains_iterator(self):
        from cybergold_candidate.quoter.discovery import route_candidates
        source, target, document = self.many_paths()
        provider, registry, transport, clients = make_provider(document)
        made, closed = 0, False
        def counted(*args):
            nonlocal made, closed
            try:
                for candidate in route_candidates(*args):
                    made += 1
                    yield candidate
            finally:
                closed = True
        feed = provider.discover_batches(source, target, 10000, BLOCK)
        probe = asyncio.create_task(asyncio.sleep(0))
        try:
            with patch('cybergold_candidate.quoter.hosted_routes.route_candidates', counted):
                first = await anext(feed)
                self.assertTrue(probe.done(), 'cooperative graph work must let another ready task progress')
                self.assertTrue(first)
                self.assertLess(made, 10542)
                self.assertFalse(closed)
                await feed.aclose()
                self.assertTrue(closed)
            self.assertEqual(len(transport.requests), 1)
            self.assertEqual((registry.calls, registry.metadata_calls), ([], []))
        finally:
            await feed.aclose()
            await probe
            await provider.close()
        self.assertTrue(clients[0].is_closed and transport.closed)

    async def test_uniroute_api_has_explicit_integration_source_and_optional_engine_evidence(self):
        document = {'routing': 'CLASSIC', 'quote': {'route': [[standard_pool('v3', A, B, fee=3000)]],
            'routeCandidates': [{'routeString': 'NEVER PARSE THIS', 'quoteAmount': str(2**255)}]}}
        provider, _, transport, _ = make_provider(document, uniroute=True)
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(A, B, 101, BLOCK)
        self.assertEqual(provider.name, 'uniroute-api')
        self.assertIsInstance(candidates, HostedCandidates)
        self.assertEqual(candidates.engine_attribution, {'engine': 'uniroute', 'evidence': 'route-candidates'})
        self.assertEqual(candidates[0][0]['amountIn'], '101')
        self.assertEqual(len(candidates), 1)
        request, = transport.requests
        self.assertTrue(json.loads(request.content)['includeRouteCandidates'])
        self.assertNotIn('x-api-experimental', request.headers)
        self.assertNotIn('routingEngine', json.loads(request.content))
        self.assertEqual(len(transport.requests), 1)

    async def test_missing_or_empty_engine_metadata_does_not_reject_api_candidates(self):
        results = []
        for metadata in ({}, {'routeCandidates': []}):
            document = {'quote': {'route': [[standard_pool('v2', A, B)]], **metadata}}
            provider, _, _, _ = make_provider(document, uniroute=True)
            self.addAsyncCleanup(provider.close)
            result = await provider.discover(A, B, 101, BLOCK)
            self.assertTrue(result)
            self.assertEqual(result.engine_attribution, {'engine': 'unverified', 'evidence': 'not-disclosed'})
            results.append(result)
        self.assertEqual(results[0], results[1])

    async def test_api_source_uses_actual_swap_steps_and_does_not_claim_uniroute_engine(self):
        document = {'quote': {'route': [], 'swapSteps': [
            {'type': 'V3_SWAP_EXACT_IN', 'amountIn': str(2**255),
             'path': packed([A, B], [500]), 'amountOutMin': str(2**255)}]}}
        provider, _, _, _ = make_provider(document, uniroute=True)
        self.addAsyncCleanup(provider.close)
        result = await provider.discover(A, B, 101, BLOCK)
        self.assertEqual(provider.name, 'uniroute-api')
        self.assertTrue(result)
        self.assertEqual(result.engine_attribution, {'engine': 'guidestar', 'evidence': 'swap-steps'})
        self.assertNotIn(str(2**255), repr(result))

    async def test_ambiguous_metadata_does_not_change_candidate_admission(self):
        document = {'quote': {'route': [], 'swapSteps': [
            {'type': 'V2_SWAP_EXACT_IN', 'path': [A, B]}],
            'routeCandidates': [{'routeString': 'DO NOT PARSE', 'quoteAmount': '999999'}]}}
        provider, _, _, _ = make_provider(document, uniroute=True)
        self.addAsyncCleanup(provider.close)
        result = await provider.discover(A, B, 101, BLOCK)
        self.assertTrue(result)
        self.assertEqual(result.engine_attribution, {'engine': 'unverified', 'evidence': 'ambiguous'})

    async def test_engine_observations_belong_to_each_response_not_shared_provider_state(self):
        def response(request):
            amount = json.loads(request.content)['amount']
            quote = {'route': [[standard_pool('v2', A, B)]]}
            if amount == '101':
                quote['routeCandidates'] = [{'routeString': 'NOT PARSED', 'quoteAmount': '1234'}]
            return httpx.Response(200, json={'quote': quote})
        provider = UniRouteApiProvider(SimpleNamespace(registry=Registry(), uniswap_api_queue=UniswapApiQueue()), settings(),
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(response), timeout=None))
        self.addAsyncCleanup(provider.close)
        first, second = await asyncio.gather(provider.discover(A, B, 101, BLOCK),
                                             provider.discover(A, B, 202, BLOCK))
        self.assertEqual(first.engine_attribution['engine'], 'uniroute')
        self.assertEqual(second.engine_attribution['engine'], 'unverified')
        self.assertEqual([first[0][0]['amountIn'], second[0][0]['amountIn']], ['101', '202'])

    async def test_standard_mixed_topology_is_immediate_semantic_identity_without_getter_dependencies(self):
        document = {'routing': 'CLASSIC', 'quote': {'output': {'amount': str(2**255)}, 'route': [[
            standard_pool('v2', A, B), standard_pool('v3', B, C, fee='3000'),
            standard_pool('v4', C, D, fee='500', tickSpacing=10, hooks=ZERO)]],
            'routeCandidates': [{'routeString': 'DO NOT PARSE', 'quoteAmount': str(2**255)}]}}
        provider, registry, transport, clients = make_provider(document)
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(A, D, AMOUNT, BLOCK)
        self.assertEqual(len(candidates), 1)
        branch, = candidates[0]
        self.assertEqual(branch['amountIn'], str(AMOUNT))
        pools = [hop['pool'] for hop in branch['hops']]
        self.assertEqual([pool['protocol'] for pool in pools], ['v2', 'v3', 'v4'])
        self.assertTrue(all('address' not in pool for pool in pools[:2]))
        self.assertEqual(pools[2]['poolManager'], MANAGER)
        self.assertEqual(pools[2]['id'], v4_pool_id((C, D, 500, 10, ZERO)))
        self.assertTrue(all('decimals' not in pool['token0'] for pool in pools))
        self.assertFalse(registry.calls)
        self.assertFalse(registry.metadata_calls)
        self.assertFalse(any(name in pool for pool in pools for name in ('liquidity', 'sqrtRatioX96', 'amountOut')))
        self.assertTrue(all(call[3] == BLOCK for call in registry.calls))
        self.assertTrue(all(call[0].lower() != FAKE for call in registry.calls))
        self.assertEqual(registry.inventory, {})
        request, = transport.requests
        payload = json.loads(request.content)
        self.assertEqual(str(request.url), QUOTE_URL)
        self.assertEqual(payload['amount'], str(AMOUNT))
        self.assertEqual(payload['protocols'], ['V2', 'V3', 'V4'])
        self.assertTrue(payload['includeRouteCandidates'])
        self.assertEqual(payload['swapper'], HELPERS)
        self.assertNotIn('x-api-experimental', request.headers)
        self.assertFalse(clients[0].is_closed)
        await provider.close()
        self.assertTrue(clients[0].is_closed and transport.closed)

    async def test_guidestar_empty_route_native_and_balance_sentinel_are_topology_only(self):
        document = {'routing': 'CLASSIC', 'quote': {'route': [], 'routeString': 'NOT PARSED',
            'output': {'amount': str(2**256 - 1)}, 'swapSteps': [
                {'type': 'WRAP_ETH', 'recipient': FAKE, 'amount': str(2**255)},
                {'type': 'V3_SWAP_EXACT_IN', 'recipient': FAKE, 'amountIn': str(2**255),
                 'amountOutMin': str(2**255), 'path': packed([WETH, B], [500])}]}}
        provider, _, transport, _ = make_provider(document, guidestar=True)
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(ZERO, B, AMOUNT, BLOCK)
        branch, = candidates[0]
        self.assertEqual(branch['amountIn'], str(AMOUNT))
        self.assertEqual(branch['hops'][0], {'kind': 'wrap', 'currencyOut': WETH.lower()})
        self.assertEqual(branch['hops'][1]['pool']['feePips'], 500)
        self.assertNotIn('amountOutMin', repr(candidates))
        self.assertNotIn(str(2**255), repr(candidates))
        self.assertEqual(transport.requests[0].headers['x-api-experimental'], 'true')
        self.assertEqual(transport.requests[0].headers['x-universal-router-swapsteps'], 'true')

    async def test_guidestar_v4_multihop_and_single_actions_preserve_keys(self):
        document = {'routing': 'CLASSIC', 'quote': {'route': [], 'swapSteps': [
            {'type': 'V4_SWAP', 'v4Actions': [
                {'action': 'SWAP_EXACT_IN', 'currencyIn': A, 'amountIn': str(2**255),
                 'amountOutMinimum': '1', 'path': [
                    {'intermediateCurrency': B, 'fee': 500, 'tickSpacing': 10, 'hooks': ZERO, 'hookData': '0x'},
                    {'intermediateCurrency': C, 'fee': 3000, 'tickSpacing': 60, 'hooks': ZERO, 'hookData': '0x'}]},
                {'action': 'SWAP_EXACT_IN_SINGLE', 'amountIn': '0', 'zeroForOne': False,
                 'poolKey': {'currency0': C, 'currency1': D, 'fee': 100, 'tickSpacing': 1, 'hooks': ZERO}},
                {'action': 'SETTLE', 'currency': A, 'amount': str(2**255), 'payerIsUser': True},
                {'action': 'TAKE', 'currency': D, 'recipient': FAKE, 'amount': '0'}]}]}}
        provider, _, _, _ = make_provider(document, guidestar=True)
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(A, D, 101, BLOCK)
        branch, = candidates[0]
        self.assertEqual(branch['amountIn'], '101')
        self.assertEqual([hop['pool']['feePips'] for hop in branch['hops']], [500, 3000, 100])
        self.assertTrue(all(hop['pool']['poolManager'] == MANAGER for hop in branch['hops']))

    async def test_v2_step_and_duplicate_pool_aliases_do_not_duplicate_paths(self):
        document = {'quote': {'route': [], 'swapSteps': [
            {'type': 'V2_SWAP_EXACT_IN', 'path': [A, B, C], 'amountIn': str(2**255)},
            {'type': 'V2_SWAP_EXACT_IN', 'path': [C, B, A], 'amountIn': '1'}]}}
        provider, registry, _, _ = make_provider(document, guidestar=True)
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(A, C, 100, BLOCK)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0][0]['hops']), 2)
        self.assertFalse(registry.calls)

    async def test_missing_key_is_unavailable_without_http_or_rpc(self):
        provider, registry, transport, clients = make_provider({},
            config=settings(CYBERGOLD_UNISWAP_API_KEY=None))
        self.addAsyncCleanup(provider.close)
        with self.assertRaises(ProviderUnavailable):
            await provider.discover(A, B, 100, BLOCK)
        self.assertEqual((clients, transport.requests, registry.calls), ([], [], []))

    async def test_optional_metadata_does_not_delay_or_disprove_semantic_nomination(self):
        registry = Registry()
        async def changed(*_args, **_kwargs):
            raise SnapshotChanged('Optional metadata is not needed for route construction')
        registry.token_metadata = changed
        provider, _, _, _ = make_provider({'quote': {'route': [[standard_pool('v2', A, B)]]}}, registry=registry)
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(A, B, 100, BLOCK)
        self.assertTrue(candidates)
        self.assertFalse(registry.calls)
        self.assertFalse(registry.metadata_calls)
        self.assertEqual(registry.inventory, {})

    async def test_http_error_is_independent_while_fork_nomination_uses_explicit_parent_chain(self):
        registry = Registry()
        registry.chain = 31338
        provider, _, transport, _ = make_provider({'error': 'secret supplier detail'},
            guidestar=True, registry=registry, status=400)
        self.addAsyncCleanup(provider.close)
        with self.assertRaises(HostedRouteError) as failure:
            await provider.discover(A, B, 100, BLOCK)
        self.assertEqual(str(failure.exception), 'Uniswap route provider returned HTTP 400')
        self.assertNotIn('secret', str(failure.exception))
        self.assertEqual(len(transport.requests), 1)
        payload = json.loads(transport.requests[0].content)
        self.assertEqual((payload['tokenInChainId'], payload['tokenOutChainId']), (1, 1))
        self.assertEqual(registry.calls, [])

    async def test_http_cancellation_closes_owned_client_without_retry(self):
        entered, retired = asyncio.Event(), asyncio.Event()
        async def blocked(_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                retired.set()
        provider, _, transport, clients = make_provider({}, handler=blocked)
        self.addAsyncCleanup(provider.close)
        task = asyncio.create_task(provider.discover(A, B, 100, BLOCK))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(retired.is_set())
        self.assertFalse(clients[0].is_closed)
        await provider.close()
        self.assertTrue(transport.closed and clients[0].is_closed)
        self.assertEqual(provider.clients, set())
        self.assertEqual(len(transport.requests), 1)
        await provider.close()

    async def test_optional_resolver_is_not_a_prerequisite_for_known_structured_paths(self):
        class Resolver:
            async def resolve(self, identifier, block):
                raise AssertionError('Semantic nomination must not await resolver')
        document = {'quote': {'route': [[standard_pool('v2', A, B), standard_pool('v2', B, C)]]}}
        provider, registry, _, _ = make_provider(document, resolver=Resolver())
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(A, C, 100, BLOCK)
        self.assertTrue(candidates)
        self.assertFalse(registry.calls)

    async def test_malformed_structured_route_is_not_recovered_from_debug_strings(self):
        document = {'quote': {'route': [], 'routeString': 'A -> B',
            'swapSteps': [{'type': 'V3_SWAP_EXACT_IN', 'path': '0x1234'}],
            'routeCandidates': [{'routeString': 'A -> B', 'quoteAmount': str(2**255)}]}}
        provider, registry, transport, _ = make_provider(document, guidestar=True)
        self.addAsyncCleanup(provider.close)
        with self.assertRaises(ValueError):
            await provider.discover(A, B, 100, BLOCK)
        self.assertEqual(registry.calls, [])
        await provider.close()
        self.assertTrue(transport.closed)
        with self.assertRaises(ValueError):
            topology_identifiers(document)
        without_steps = deepcopy(document)
        without_steps['quote'].pop('swapSteps')
        self.assertEqual(topology_identifiers(without_steps), [])


class HostedForkAndSplitTests(unittest.IsolatedAsyncioTestCase):
    async def test_fork_market_segment_uses_parent_nomination_and_local_anchor_both_directions(self):
        for sale in (False, True):
            with self.subTest(sale=sale):
                registry = Registry()
                registry.chain, registry.core = 31338, D
                registry.seed = {'id': v4_pool_id((B, D, 100, 1, ZERO)), 'protocol': 'v4',
                    'token0': {'address': B, 'chainId': 31338}, 'token1': {'address': D, 'chainId': 31338},
                    'feePips': 100, 'tickSpacing': 1, 'hooks': ZERO, 'poolManager': MANAGER}
                source, target = (B, A) if sale else (A, B)
                document = {'quote': {'route': [[standard_pool('v3', source, target, fee=500)]]}}
                provider, _, transport, _ = make_provider(document, registry=registry, uniroute=True)
                prefix_calls = []
                async def prefix_quote(branches, mode, amount, block, **options):
                    prefix_calls.append((deepcopy(branches), mode, amount, block, options))
                    return {'amountOut': '67'}
                provider.engine.semaphore = asyncio.Semaphore(8)
                provider.engine.quote_sdk_branches = prefix_quote
                self.addAsyncCleanup(provider.close)
                candidates = await provider.discover(D if sale else A, A if sale else D, 101, BLOCK)
                payload = json.loads(transport.requests[0].content)
                self.assertEqual((payload['tokenInChainId'], payload['tokenOutChainId']), (1, 1))
                self.assertEqual((payload['tokenIn'].lower(), payload['tokenOut'].lower()), (source, target))
                self.assertNotIn(D, (payload['tokenIn'].lower(), payload['tokenOut'].lower()))
                self.assertEqual(payload['amount'], '67' if sale else '101')
                self.assertEqual(candidates[0][0]['amountIn'], '101')
                self.assertEqual(len(prefix_calls), int(sale))
                if sale:
                    self.assertEqual(prefix_calls[0][1:4], ('exactIn', 101, BLOCK))
                    self.assertEqual(prefix_calls[0][0][0]['hops'][0]['pool']['id'], registry.seed['id'])
                hops = candidates[0][0]['hops']
                self.assertEqual([hop['pool']['protocol'] for hop in hops], ['v4', 'v3'] if sale else ['v3', 'v4'])
                self.assertEqual(hops[0 if sale else -1]['pool']['id'], registry.seed['id'])
                self.assertTrue(all(hop['pool'][token]['chainId'] == 31338 for hop in hops for token in ('token0', 'token1')))
                self.assertFalse(registry.calls)
                self.assertFalse(registry.metadata_calls)

    async def test_real_sdk_prefix_output_is_the_hosted_market_input_not_core_units(self):
        from cybergold_candidate.route_quote_engine import RouteQuoteEngine
        from quoter_fixture import Registry as OfflineRegistry, synthetic_pool
        seed = synthetic_pool(B, D, 7905, 'v2')
        seed.update(reserve0='2000000', reserve1='1000000')
        for token in ('token0', 'token1'):
            seed[token]['chainId'] = 31338
        registry = OfflineRegistry([seed])
        registry.chain, registry.core = 31338, D
        engine = RouteQuoteEngine(settings(NEXT_PUBLIC_CHAIN_ID='31338'), registry)
        self.addAsyncCleanup(engine.close)
        transport = FixtureTransport({'quote': {'route': [[standard_pool('v2', B, A)]]}})
        provider = UniRouteApiProvider(engine, settings(),
            client_factory=lambda: httpx.AsyncClient(transport=transport))
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(D, A, 101, BLOCK)
        expected = 101*997*2000000//(1000000*1000+101*997)
        payload = json.loads(transport.requests[0].content)
        self.assertEqual(payload['amount'], str(expected))
        self.assertNotEqual(expected, 101)
        self.assertEqual((payload['tokenIn'].lower(), payload['tokenInChainId']), (B, 1))
        self.assertEqual(candidates[0][0]['amountIn'], '101')
        self.assertEqual(candidates[0][0]['hops'][0]['pool']['id'], seed['id'])

    async def test_both_hosted_sources_share_the_observed_local_prefix_quantity(self):
        from cybergold_candidate.search_observations import search_observation_scope
        registry = Registry()
        registry.chain, registry.core = 31338, D
        registry.seed = {'id': v4_pool_id((B, D, 100, 1, ZERO)), 'protocol': 'v4',
            'token0': {'address': B, 'chainId': 31338}, 'token1': {'address': D, 'chainId': 31338},
            'feePips': 100, 'tickSpacing': 1, 'hooks': ZERO, 'poolManager': MANAGER}
        api, _, standard, _ = make_provider({'quote': {'route': [[standard_pool('v3', B, A, fee=500)]]}},
                                            registry=registry, uniroute=True)
        guide, _, experimental, _ = make_provider({'quote': {'route': [], 'swapSteps': [
            {'type': 'V3_SWAP_EXACT_IN', 'path': packed([B, A], [500]), 'amountIn': '67'}]}},
            registry=registry, guidestar=True)
        self.addAsyncCleanup(api.close)
        self.addAsyncCleanup(guide.close)
        calls = []
        async def prefix_quote(branches, mode, amount, block, **options):
            calls.append((branches, mode, amount, block, options))
            await asyncio.sleep(0)
            return {'amountOut': '67'}
        for provider in (api, guide):
            provider.engine.semaphore = asyncio.Semaphore(8)
            provider.engine.quote_sdk_branches = prefix_quote
        async with search_observation_scope():
            candidates = await asyncio.gather(*(provider.discover(D, A, 101, BLOCK) for provider in (api, guide)))
        self.assertEqual(len(calls), 1)
        for transport, offers in zip((standard, experimental), candidates, strict=True):
            request = json.loads(transport.requests[0].content)
            self.assertEqual((request['tokenIn'], request['amount']), (B, '67'))
            self.assertEqual(offers[0][0]['amountIn'], '101')
            self.assertEqual(offers[0][0]['hops'][0]['pool']['id'], registry.seed['id'])

    async def test_standard_proposed_split_weights_survive_alongside_graph_alternatives(self):
        routes = [[{**standard_pool('v3', A, B, fee=fee), 'amountIn': str(weight)}]
                  for fee, weight in ((500, 35), (3000, 65))]
        provider, registry, _, _ = make_provider({'quote': {'route': routes}}, uniroute=True)
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(A, B, AMOUNT, BLOCK)
        proposed = candidates[0]
        self.assertEqual([branch['amountIn'] for branch in proposed], ['350000', '650000'])
        self.assertEqual([branch['hops'][0]['pool']['feePips'] for branch in proposed], [500, 3000])
        self.assertTrue(any(len(candidate) == 1 for candidate in candidates))
        self.assertNotIn(str(2**255), repr(candidates))
        self.assertFalse(registry.calls)

    async def test_guidestar_proposed_v3_splits_preserve_weights_and_native_transition(self):
        document = {'quote': {'route': [], 'swapSteps': [
            {'type': 'V3_SWAP_EXACT_IN', 'path': packed([WETH, B], [fee]), 'amountIn': str(weight)}
            for fee, weight in ((500, 35), (3000, 65))]}}
        provider, _, _, _ = make_provider(document, guidestar=True)
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(ZERO, B, 101, BLOCK)
        self.assertEqual([branch['amountIn'] for branch in candidates[0]], ['350000', '650000'])
        self.assertTrue(all(branch['hops'][0]['kind'] == 'wrap' for branch in candidates[0]))

    async def test_guidestar_v4_structured_split_weights_do_not_use_settlement_commands(self):
        document = {'quote': {'route': [], 'swapSteps': [{'type': 'V4_SWAP', 'v4Actions': [
            {'action': 'SWAP_EXACT_IN_SINGLE', 'poolKey': {'currency0': A, 'currency1': B,
                'fee': fee, 'tickSpacing': spacing, 'hooks': ZERO}, 'zeroForOne': True, 'amountIn': str(weight)}
            for fee, spacing, weight in ((500, 10, 35), (3000, 60, 65))]}]}}
        provider, registry, _, _ = make_provider(document, guidestar=True)
        self.addAsyncCleanup(provider.close)
        candidates = await provider.discover(A, B, 101, BLOCK)
        self.assertEqual([branch['amountIn'] for branch in candidates[0]], ['350000', '650000'])
        self.assertEqual([branch['hops'][0]['pool']['tickSpacing'] for branch in candidates[0]], [10, 60])
        self.assertFalse(registry.calls)

    async def test_concurrent_queries_reuse_one_owned_client_and_cancel_independently(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def handler(request):
            if json.loads(request.content)['amount'] == '101':
                entered.set()
                await release.wait()
        provider, _, transport, clients = make_provider({'quote': {'route': [[standard_pool('v3', A, B, fee=500)]]}}, handler=handler)
        self.addAsyncCleanup(provider.close)
        first = asyncio.create_task(provider.discover(A, B, 101, BLOCK))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            second = await asyncio.wait_for(provider.discover(A, B, 202, BLOCK), 1)
            self.assertTrue(second)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            self.assertEqual(len(clients), 1)
            self.assertFalse(clients[0].is_closed)
            self.assertFalse(transport.closed)
        finally:
            release.set()
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        await provider.close()
        self.assertTrue(clients[0].is_closed and transport.closed)


if __name__ == '__main__':
    unittest.main()
