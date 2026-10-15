"""Serving consumers share canonical routes, ordinary fallback and one budget.

Native Quoter replies are inert boundary values; Helpers previews use the
existing shipped-ABI fixture. Existing SDK/provider tests own swap arithmetic,
shared-pool execution ordering, native currency and the full 5/15 clock matrix.
"""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from web3 import Web3

from cybergold_candidate import runtime
from cybergold_candidate.app import create_app
from cybergold_candidate.environment import load_environment
from cybergold_candidate.market_swap import MarketQuotes
from cybergold_candidate.quote_budget import QuoteBudget, budget_context
from cybergold_candidate.route_encoding import ADAPTER_TYPE, encode_route
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.uniswap_quote import UniswapQuote
from cybergold_candidate.uniswap_routes import RoutePlan, v3_path
from cybergold_candidate.uniswap_state import PoolRegistry, ZERO
from test_quote_intent import (ADAPTER, ASSET_A, ASSET_B, CORE, HASH, SETTINGS,
                               QuoteWire, request as core_request, service as core_service)
from cybergold_candidate.route_search import WETH

BLOCK = {'number': 101, 'hash': HASH}


class NativeQuoterRpc:
    """Successful V3 reads remain usable without optional registry metadata."""
    chain_id = 1
    factory = '0x'+'6'*40
    v2_factory = '0x'+'7'*40
    quoter = SETTINGS.NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS

    def __init__(self, *, held_tail=False):
        self.w3 = Web3()
        self.wire = QuoteWire()
        self.calls = []
        self.held_tail = held_tail
        self.release = asyncio.Event()
        self.fast, self.tail, self.typed = (asyncio.Event() for _ in range(3))
        self.drained = set()
        self.canonical = 0

    async def block(self, _hash):
        return BLOCK

    async def assert_canonical(self, block):
        assert block == BLOCK
        self.canonical += 1

    async def read_function(self, address, signature, inputs, args, outputs, block):
        assert block == BLOCK
        self.calls.append((address, signature, deepcopy(args)))
        if signature in ('quoteExactInput(bytes,uint256)', 'quoteExactOutput(bytes,uint256)'):
            path = args[0]
            if len(path) == 43 and int.from_bytes(path[20:23]) == 100:
                self.fast.set()
                data = Web3.to_hex(Web3.keccak(text=signature)[:4] + self.w3.codec.encode(inputs, args))
                response = await self.wire.send(httpx.Request('POST', 'http://fixture.invalid', json=[{
                    'jsonrpc': '2.0', 'id': 0, 'method': 'eth_call', 'params': [
                        {'to': address, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}]}]))
                return self.w3.codec.decode(outputs, bytes.fromhex(response.json()[0]['result'][2:]))
            if self.held_tail:
                self.tail.set()
                try:
                    await self.release.wait()
                finally:
                    self.drained.add('v3')
            raise ValueError('No Quoter result for this fixture path')
        if signature == 'getReserves()' and self.held_tail:
            self.typed.set()
            try:
                await self.release.wait()
            finally:
                self.drained.add('typed')
        if signature == 'getPair(address,address)':
            return (ZERO,)
        raise OSError('Optional fixture pool/token observation unavailable')

    async def close(self):
        self.release.set()


class UnifiedRoutePipelineTests(unittest.IsolatedAsyncioTestCase):
    def engine(self, *, held_tail=False):
        rpc = NativeQuoterRpc(held_tail=held_tail)
        registry = PoolRegistry(SETTINGS, rpc=rpc)
        registry.inventory = {}
        engine = MarketQuotes(SETTINGS, registry)
        self.addAsyncCleanup(registry.close)
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(rpc.release.set)
        return engine, registry, rpc

    def market_request(self):
        return {'side': 'buy', 'mode': 'exact-in', 'counterToken': WETH,
                'amount': '100', 'adapter': ADAPTER, 'recipient': ASSET_B,
                'deadline': '2000000000', 'slippageBps': 100}

    async def test_configured_runtime_connects_all_consumers_to_one_engine(self):
        class Database:
            closed = False
            async def close(self):
                self.closed = True
        settings = load_environment({'NEXT_PUBLIC_CHAIN_ID': '1',
            'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': CORE,
            'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS': ASSET_A,
            'NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS': ASSET_B,
            'NEXT_PUBLIC_RPC_URL': 'http://fixture.invalid'})
        services = {}
        def observe(**values):
            services.update(values)
            return create_app(**values)
        database = Database()
        async with httpx.AsyncClient() as client:
            with patch.object(runtime, 'create_app', side_effect=observe):
                app = runtime.create_configured_app(settings, database, client)
            engine = services['market_quotes']
            self.assertIsInstance(engine, RouteQuoteEngine)
            self.assertIs(services['route_search'].engine, engine)
            self.assertIs(services['quote_intent'].service.routes.engine, engine)
            self.assertIs(services['trade_quotes'].market, engine)
            self.assertIs(services['uniswap_quote'].engine, engine)
            async with app.router.lifespan_context(app):
                pass
        self.assertTrue(database.closed)

    async def test_core_market_and_selected_direct_route_keep_canonical_plans_without_metadata(self):
        engine, registry, rpc = self.engine()
        intent, provider, routes, _wire = core_service()
        routes.engine = engine
        self.addAsyncCleanup(routes.close)
        self.addAsyncCleanup(intent.close)
        frames = []
        core = await intent.get(core_request('issue-exact-in'),
                                lambda value: asyncio.sleep(0, result=frames.append(value)))
        self.assertTrue(core['quotes'])
        self.assertTrue(any(name.startswith('previewIssueFrom') for name, *_ in provider.contract_calls))
        for leg in core['quotes']:
            plan = RoutePlan.model_validate(leg['routePlan']).model_dump(exclude_none=True)
            self.assertEqual(plan['executionContext'], 'helpers-core')
            self.assertEqual(leg['data'], encode_route(plan, ADAPTER))
            self.assertEqual(plan['branches'][0]['hops'][0]['pool']['protocol'], 'v3')
        market = await engine.get(self.market_request())
        plan = RoutePlan.model_validate(market['plan']['route']).model_dump(exclude_none=True)
        self.assertEqual(plan['executionContext'], 'helpers-market')
        self.assertEqual(market['adapterData'], encode_route(plan, ADAPTER))
        encoded, = Web3().codec.decode([ADAPTER_TYPE], bytes.fromhex(market['adapterData'][2:]))
        self.assertTrue(encoded[0])
        selected = core['quotes'][0]['routePlan']
        path = v3_path(selected['branches'][0]['hops'])
        before = len(rpc.calls)
        direct = UniswapQuote(SETTINGS, rpc, engine=engine)
        result = await direct.get({'mode': 'exact-in', 'path': path,
                                   'amount': selected['inputAmount']})
        self.assertEqual(result['result']['amount'], selected['outputAmount'])
        self.assertEqual(result['context']['blockHash'], HASH)
        self.assertTrue(any(name == 'quoteExactInput(bytes,uint256)' for _, name, _ in rpc.calls[before:]))

    async def test_core_exact_output_preserves_sdk_overdelivery_without_raising_helpers_minimum(self):
        class SdkRpc(NativeQuoterRpc):
            async def read_function(self, address, signature, inputs, args, outputs, block):
                if signature == 'getReserves()':
                    # Existing V2 fixture reserves, oriented WETH -> Core asset.
                    return 200_000, 100_000, 0
                if signature.startswith('quoteExact'):
                    raise ValueError('Native Quoter unavailable in this SDK fixture')
                return await super().read_function(address, signature, inputs, args, outputs, block)
        rpc = SdkRpc()
        registry = PoolRegistry(SETTINGS, rpc=rpc)
        registry.inventory = {}
        for index, asset in enumerate((ASSET_A, ASSET_B), 6):
            identity = '0x'+str(index)*40
            registry.inventory[identity] = {'id': identity, 'address': identity, 'protocol': 'v2',
                'feePips': 3000, 'token0': {'address': asset, 'decimals': 18, 'chainId': 1},
                'token1': {'address': WETH, 'decimals': 18, 'chainId': 1}}
        sdk = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'),
                         str(Path('src/uniswap-sdk/worker.ts').resolve())])
        engine = MarketQuotes(SETTINGS, registry, sdk)
        async def no_connectors(*_args):
            pass
        engine.connector_inventory = no_connectors
        self.addAsyncCleanup(registry.close)
        self.addAsyncCleanup(engine.close)
        intent, provider, routes, _wire = core_service()
        routes.engine = engine
        self.addAsyncCleanup(routes.close)
        self.addAsyncCleanup(intent.close)
        value = core_request('issue-exact-out')
        result = await intent.get(value, lambda _frame: asyncio.sleep(0))
        for leg in result['quotes']:
            plan = leg['routePlan']
            target = int(leg['minimumAmountOut'])
            raw = await engine.quote_branches(plan['branches'], 'exactOut', target, BLOCK)
            self.assertGreater(int(raw['amountOut']), target, 'Fixture must cross a real SDK rounding plateau')
            self.assertEqual(plan['inputAmount'], raw['amountIn'])
            self.assertEqual(plan['outputAmount'], raw['amountOut'])
            self.assertEqual(plan['limit'], str(target))
            encoded, = Web3().codec.decode([ADAPTER_TYPE], bytes.fromhex(leg['data'][2:]))
            self.assertEqual(encoded[1], target)
        previews = [args for name, args, _block in provider.contract_calls
                    if name == 'previewIssueFromTokenExactOut']
        self.assertTrue(previews)
        final = previews[-1]
        self.assertEqual(final['params']['netCygldOut'], int(value['amount']))
        self.assertEqual([leg['minimumAmountOut'] for leg in final['legs']],
                         [int(leg['minimumAmountOut']) for leg in result['quotes']])

    async def test_fast_v3_market_qualification_does_not_wait_for_slow_v3_typed_or_connector_tail(self):
        engine, registry, rpc = self.engine(held_tail=True)
        # A real cached typed route competes with the original V3 skeletons.
        registry.inventory = {'fixture-v2': {'id': 'fixture-v2', 'protocol': 'v2',
            'address': ASSET_A, 'feePips': 3000,
            'token0': {'address': min(CORE, WETH), 'decimals': 18, 'chainId': 1},
            'token1': {'address': max(CORE, WETH), 'decimals': 18, 'chainId': 1}}}
        connector_started, connector_drained = asyncio.Event(), asyncio.Event()
        async def connectors(*_args):
            connector_started.set()
            try:
                await rpc.release.wait()
            finally:
                connector_drained.set()
        engine.connector_inventory = connectors
        budget = QuoteBudget(.1, .2)
        frames = []
        with budget_context(budget):
            task = asyncio.create_task(engine.get(self.market_request(),
                lambda value: asyncio.sleep(0, result=frames.append(deepcopy(value)))))
        try:
            async with asyncio.timeout(2):
                result = await task
            self.assertTrue(rpc.fast.is_set())
            self.assertTrue(rpc.tail.is_set())
            self.assertTrue(rpc.typed.is_set())
            self.assertTrue(connector_started.is_set())
            self.assertFalse(rpc.release.is_set())
            self.assertEqual(budget.reason, 'best-initial')
            self.assertLess(budget.first_qualified, budget.initial)
            self.assertLess(budget.selected, budget.deadline)
            self.assertTrue(any(frame['type'] == 'qualified' for frame in frames))
            self.assertEqual(result['plan']['route']['branches'][0]['hops'][0]['pool']['protocol'], 'v3')
            self.assertGreater(rpc.canonical, 0)
            self.assertTrue(connector_drained.is_set())
            self.assertEqual(rpc.drained, {'v3', 'typed'})
            self.assertEqual(registry.pending.pending, {})
        finally:
            rpc.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
