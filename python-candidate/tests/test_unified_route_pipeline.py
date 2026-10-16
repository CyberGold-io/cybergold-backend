"""One engine/format/budget, with explicit controller-only SDK boundary values.

Programmable SDK replies below are opaque timing/economic fixtures, never AMM
arithmetic evidence or contract pricing. The separate real SDK V2 test retains
its actual worker, pinned pool state and Helpers ABI rounding assertions.
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
                               request as core_request, service as core_service)
from cybergold_candidate.route_search import WETH

BLOCK = {'number': 101, 'hash': HASH}


class PipelineFixtureRpc:
    """State transport plus an explicitly programmable SDK price oracle."""
    chain_id = 1
    factory = '0x'+'6'*40
    v2_factory = '0x'+'7'*40
    quoter = SETTINGS.NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS

    def __init__(self, *, held_tail=False):
        self.w3 = Web3()
        self.calls, self.sdk_prices = [], []
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

    async def price_v3(self, path, mode, amount, block):
        """Opaque SDK callback; never dispatched as a contract/RPC quote."""
        assert block == BLOCK
        self.sdk_prices.append((path, mode, amount))
        if len(path) == 43 and int.from_bytes(path[20:23]) == 100:
            self.fast.set()
            return amount*2 if mode == 'exactIn' else (amount+1)//2
        if self.held_tail:
            self.tail.set()
            try:
                await self.release.wait()
            finally:
                self.drained.add('v3')
        raise ValueError('No programmable SDK result for this fixture path')

    async def read_function(self, address, signature, inputs, args, outputs, block):
        assert block == BLOCK
        self.calls.append((address, signature, deepcopy(args)))
        if signature.startswith('quoteExact') or signature.startswith('getAmounts'):
            raise AssertionError('Contract pricing is retired')
        if signature == 'getReserves()' and self.held_tail:
            self.typed.set()
            try:
                await self.release.wait()
            finally:
                self.drained.add('typed')
        if signature == 'getPair(address,address)':
            return (ZERO,)
        raise OSError('No fixture pool/token observation')

    async def close(self):
        self.release.set()


class ProgrammablePipelineSdk:
    """Controller tests inject results at the SDK worker boundary only."""
    def __init__(self, rpc):
        self.rpc, self.reply = rpc, None
        self.payloads = []

    async def request(self, payload, on_state=None):
        self.payloads.append(deepcopy(payload))
        if self.reply is not None:
            return await self.reply(payload)
        pools = {pool['id']: pool for pool in payload['pools']}
        mode, total_in, total_out = payload['mode'], 0, 0
        for branch in payload['route']['branches']:
            hops = [{'pool': pools[hop['poolId']], 'zeroForOne': hop['zeroForOne']}
                for hop in branch['hops']]
            path = bytes.fromhex(v3_path(hops, mode == 'exactOut')[2:])
            amount = int(branch['amountIn']) if mode == 'exactIn' else int(payload['amount'])
            quoted = await self.rpc.price_v3(path, mode, amount, pools[hops[0]['pool']['id']]['_fixtureBlock'])
            total_in += amount if mode == 'exactIn' else quoted
            total_out += quoted if mode == 'exactIn' else amount
        return {'amountIn': str(total_in), 'amountOut': str(total_out), 'settled': True,
            'fullyFilled': True, 'postState': deepcopy(payload['pools'])}

    async def close(self):
        pass


def install_programmable_sdk_snapshot(registry):
    """Only controller fixtures use these opaque V3 state placeholders."""
    snapshot = registry.snapshot
    async def fixture(pool, block, **kwargs):
        if pool['protocol'] == 'v3':
            return {**deepcopy(pool), '_fixtureBlock': deepcopy(block)}
        return await snapshot(pool, block, **kwargs)
    registry.snapshot = fixture


class UnifiedRoutePipelineTests(unittest.IsolatedAsyncioTestCase):
    def engine(self, *, held_tail=False):
        rpc = PipelineFixtureRpc(held_tail=held_tail)
        registry = PoolRegistry(SETTINGS, rpc=rpc)
        registry.inventory = {}
        install_programmable_sdk_snapshot(registry)
        engine = MarketQuotes(SETTINGS, registry, ProgrammablePipelineSdk(rpc))
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
            for retired in ('quote_hop', 'quote_v3_path', 'quote_fallback_branches'):
                self.assertFalse(hasattr(engine, retired))
            self.assertIs(services['route_search'].engine, engine)
            self.assertIs(services['quote_intent'].service.routes.engine, engine)
            self.assertIs(services['trade_quotes'].market, engine)
            self.assertIs(services['uniswap_quote'].engine, engine)
            async with app.router.lifespan_context(app):
                pass
        self.assertTrue(database.closed)

    async def test_core_market_and_selected_direct_route_keep_canonical_plans_through_sdk(self):
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
        before = len(rpc.sdk_prices)
        direct = UniswapQuote(SETTINGS, rpc, engine=engine)
        result = await direct.get({'mode': 'exact-in', 'path': path,
                                   'amount': selected['inputAmount']})
        self.assertEqual(result['result']['amount'], selected['outputAmount'])
        self.assertEqual(result['context']['blockHash'], HASH)
        self.assertGreater(len(rpc.sdk_prices), before)

    async def test_core_exact_output_preserves_sdk_overdelivery_without_raising_helpers_minimum(self):
        class SdkRpc(PipelineFixtureRpc):
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
