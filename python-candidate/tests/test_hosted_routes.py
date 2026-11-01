"""Hosted responses nominate canonical topology, never remote execution terms."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest

import httpx

from cybergold_candidate.quoter.bootstrap import ProviderUnavailable
from cybergold_candidate.quoter.hosted_routes import (
    HostedRouteError, QUOTE_URL, UniswapApiProvider, topology_identifiers)
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.uniswap_v4 import v4_pool_id


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
                  resolver=None):
    registry = registry or Registry()
    transport = FixtureTransport(document, status, handler)
    created = []
    def client_factory():
        value = httpx.AsyncClient(transport=transport, timeout=None)
        created.append(value)
        return value
    provider = UniswapApiProvider(SimpleNamespace(registry=registry), config or settings(),
        guidestar=guidestar, client_factory=client_factory, resolver=resolver)
    return provider, registry, transport, created


class HostedRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def test_standard_mixed_topology_resolves_factory_and_v4_key_at_selected_block(self):
        document = {'routing': 'CLASSIC', 'quote': {'output': {'amount': str(2**255)}, 'route': [[
            standard_pool('v2', A, B), standard_pool('v3', B, C, fee='3000'),
            standard_pool('v4', C, D, fee='500', tickSpacing=10, hooks=ZERO)]],
            'routeCandidates': [{'routeString': 'DO NOT PARSE', 'quoteAmount': str(2**255)}]}}
        provider, registry, transport, clients = make_provider(document)
        candidates = await provider.discover(A, D, AMOUNT, BLOCK)
        self.assertEqual(len(candidates), 1)
        branch, = candidates[0]
        self.assertEqual(branch['amountIn'], str(AMOUNT))
        pools = [hop['pool'] for hop in branch['hops']]
        self.assertEqual([pool['protocol'] for pool in pools], ['v2', 'v3', 'v4'])
        self.assertEqual([pool['address'].lower() for pool in pools[:2]], [CANONICAL_V2, CANONICAL_V3])
        self.assertEqual(pools[2]['poolManager'], MANAGER)
        self.assertEqual(pools[2]['id'], v4_pool_id((C, D, 500, 10, ZERO)))
        self.assertTrue(all(pool['token0']['decimals'] == 6 for pool in pools))
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
        self.assertTrue(clients[0].is_closed and transport.closed)
        await provider.close()

    async def test_guidestar_empty_route_native_and_balance_sentinel_are_topology_only(self):
        document = {'routing': 'CLASSIC', 'quote': {'route': [], 'routeString': 'NOT PARSED',
            'output': {'amount': str(2**256 - 1)}, 'swapSteps': [
                {'type': 'WRAP_ETH', 'recipient': FAKE, 'amount': str(2**255)},
                {'type': 'V3_SWAP_EXACT_IN', 'recipient': FAKE, 'amountIn': str(2**255),
                 'amountOutMin': str(2**255), 'path': packed([WETH, B], [500])}]}}
        provider, _, transport, _ = make_provider(document, guidestar=True)
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
        candidates = await provider.discover(A, C, 100, BLOCK)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0][0]['hops']), 2)
        self.assertEqual(sum(call[1] == 'getPair(address,address)' for call in registry.calls), 2)

    async def test_missing_key_is_unavailable_without_http_or_rpc(self):
        provider, registry, transport, clients = make_provider({},
            config=settings(CYBERGOLD_UNISWAP_API_KEY=None))
        with self.assertRaises(ProviderUnavailable):
            await provider.discover(A, B, 100, BLOCK)
        self.assertEqual((clients, transport.requests, registry.calls), ([], [], []))

    async def test_metadata_context_disproof_is_not_optional_display_fallback(self):
        registry = Registry()
        entered, retired = asyncio.Event(), asyncio.Event()
        async def changed(address, *args, **kwargs):
            if address.lower() == A.lower():
                await entered.wait()
                raise SnapshotChanged('Metadata read disproved the selected context')
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                retired.set()
        registry.token_metadata = changed
        provider, _, _, _ = make_provider({'quote': {'route': [[standard_pool('v2', A, B)]]}},
                                         registry=registry)
        with self.assertRaises(SnapshotChanged):
            await provider.discover(A, B, 100, BLOCK)
        self.assertTrue(retired.is_set())
        self.assertEqual(registry.inventory, {})

    async def test_http_error_is_safe_and_unsupported_chain_is_not_relabelled_or_retried(self):
        registry = Registry()
        registry.chain = 31338
        provider, _, transport, _ = make_provider({'error': 'secret supplier detail'},
            guidestar=True, registry=registry, status=400)
        with self.assertRaises(HostedRouteError) as failure:
            await provider.discover(A, B, 100, BLOCK)
        self.assertEqual(str(failure.exception), 'Uniswap route provider returned HTTP 400')
        self.assertNotIn('secret', str(failure.exception))
        self.assertEqual(len(transport.requests), 1)
        payload = json.loads(transport.requests[0].content)
        self.assertEqual((payload['tokenInChainId'], payload['tokenOutChainId']), (31338, 31338))
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
        task = asyncio.create_task(provider.discover(A, B, 100, BLOCK))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(retired.is_set())
        self.assertTrue(transport.closed and clients[0].is_closed)
        self.assertEqual(provider.clients, set())
        self.assertEqual(len(transport.requests), 1)
        await provider.close()

    async def test_resolver_context_disproof_propagates_and_drains_sibling(self):
        second_started, retired = asyncio.Event(), asyncio.Event()
        class Resolver:
            async def resolve(self, identifier, block):
                if identifier['tokenA'].lower() == A:
                    await second_started.wait()
                    raise SnapshotChanged('Canonical block changed')
                second_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    retired.set()
        document = {'quote': {'route': [[standard_pool('v2', A, B), standard_pool('v2', B, C)]]}}
        provider, _, _, _ = make_provider(document, resolver=Resolver())
        with self.assertRaises(SnapshotChanged):
            await provider.discover(A, C, 100, BLOCK)
        self.assertTrue(retired.is_set())

    async def test_malformed_structured_route_is_not_recovered_from_debug_strings(self):
        document = {'quote': {'route': [], 'routeString': 'A -> B',
            'swapSteps': [{'type': 'V3_SWAP_EXACT_IN', 'path': '0x1234'}],
            'routeCandidates': [{'routeString': 'A -> B', 'quoteAmount': str(2**255)}]}}
        provider, registry, transport, _ = make_provider(document, guidestar=True)
        with self.assertRaises(ValueError):
            await provider.discover(A, B, 100, BLOCK)
        self.assertEqual(registry.calls, [])
        self.assertTrue(transport.closed)
        self.assertEqual(topology_identifiers(document), [])


if __name__ == '__main__':
    unittest.main()
