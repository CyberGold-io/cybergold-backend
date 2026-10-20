"""Canonical Market routing with actual pinned SDK math and typed ABI payloads.

No live chain is used: pool state, catalog discovery and canonical headers are
explicit fixtures. The worker is the release's actual V2/V3/V4 SDK bridge.
"""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from web3 import Web3

from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.market_swap import MarketQuotes
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.route_encoding import ADAPTER_TYPE, encode_route
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.uniswap_routes import (candidate_branches, initial_market_branches,
    market_routes, pool_identity, supported_route, v4_pool_id)
from cybergold_candidate.uniswap_state import PoolRegistry, ZERO
from cybergold_candidate.wallet_balances import TOKENS

CORE = '0x'+'6'*40
PAXG = dict(TOKENS)['paxg']
COUNTER = '0x'+'9'*40
MID = '0x'+'8'*40
ADAPTER = '0x'+'7'*40
BLOCK = {'number': 123, 'hash': '0x'+'ab'*32}
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE)


def token(address):
    return {'address': address, 'decimals': 18, 'chainId': 31338}


def pool(a, b, protocol='v4', fee=100):
    a, b = sorted((a.lower(), b.lower()))
    key = (a, b, fee, 1, ZERO)
    return {'id': v4_pool_id(key) if protocol == 'v4' else 'v3:'+':'.join((a, b, str(fee))),
        'protocol': protocol, 'token0': token(a), 'token1': token(b), 'feePips': fee,
        'tickSpacing': 1, 'hooks': ZERO, 'poolManager': '0x'+'4'*40}


def snapshot(pool):
    liquidity = 10**18
    return {**deepcopy(pool), 'sqrtRatioX96': str(1 << 96), 'liquidity': str(liquidity),
        'tick': 0, 'lpFee': pool['feePips'], 'protocolFee': 0,
        'bitmapWords': [{'wordPosition': -1, 'bitmap': str(1 << 196)},
                        {'wordPosition': 0, 'bitmap': str(1 << 60)}],
        'ticks': [{'index': -60, 'liquidityGross': str(liquidity), 'liquidityNet': str(liquidity)},
                  {'index': 60, 'liquidityGross': str(liquidity), 'liquidityNet': str(-liquidity)}],
        'context': {'chainId': 31338, 'blockNumber': str(BLOCK['number']), 'blockHash': BLOCK['hash']}}


class CanonicalGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_prefix_suffix_allocation_and_mixed_output_exclusion(self):
        anchor = pool(CORE, PAXG)
        tails = [pool(PAXG, COUNTER), pool(PAXG, COUNTER, 'v3'),
                 pool(PAXG, MID, 'v3'), pool(MID, COUNTER)]
        # A cheaper/direct CYGLD pool cannot replace or sneak behind the anchor.
        inventory = [anchor, *tails, pool(CORE, COUNTER), pool(CORE, MID)]
        for side in ('buy', 'sell'):
            source, output = (CORE, COUNTER) if side == 'sell' else (COUNTER, CORE)
            for mode in ('exactIn', 'exactOut'):
                rows = [row async for row in candidate_branches(inventory, source, output, mode, 101,
                    anchor=anchor, core=CORE)]
                standalone = [row for row in rows if len(row) == 1]
                self.assertEqual(len(standalone), 3 if mode == 'exactIn' else 1)
                for branches in rows:
                    self.assertEqual(sum(int(branch['amountIn']) for branch in branches), 101 if mode == 'exactIn' else 0)
                    for branch in branches:
                        hops = branch['hops']
                        self.assertEqual(pool_identity(hops[0 if side == 'sell' else -1]['pool']), pool_identity(anchor))
                        self.assertEqual(len([hop for hop in hops if CORE.lower() in (
                            hop['pool']['token0']['address'].lower(), hop['pool']['token1']['address'].lower())]), 1)
                        if mode == 'exactOut':
                            self.assertEqual({hop['pool']['protocol'] for hop in hops}, {'v4'})
                if mode == 'exactIn':
                    self.assertTrue(any(len(row) == 2 for row in rows))
                    self.assertTrue(any({hop['pool']['protocol'] for hop in row[0]['hops']} == {'v3', 'v4'} for row in rows))

    async def test_direct_paxg_is_canonical_and_seed_connectors_do_not_require_catalog_metadata(self):
        anchor = pool(CORE, PAXG)
        for source, output in ((CORE, PAXG), (PAXG, CORE)):
            rows = [hops async for hops in market_routes([], source, output, CORE, anchor)]
            self.assertEqual(len(rows), 1)
            self.assertEqual(pool_identity(rows[0][0]['pool']), pool_identity(anchor))
        for source, output in ((CORE, COUNTER), (COUNTER, CORE)):
            target = {'inputAsset': source, 'outputAsset': output, 'amount': '100'}
            rows = list(initial_market_branches(anchor, CORE, target, 'exactIn', 31338))
            self.assertEqual(len(rows), 17)
            self.assertTrue(all(len(row[0]['hops']) <= 3 for row in rows))
            outputs = list(initial_market_branches(anchor, CORE, target, 'exactOut', 31338))
            self.assertEqual(len(outputs), 4)
            self.assertTrue(all({hop['pool']['protocol'] for hop in row[0]['hops']} == {'v4'} for row in outputs))


class CanonicalMarketSdkTests(unittest.IsolatedAsyncioTestCase):
    async def test_cold_v4_keys_use_real_stateview_producer_sdk_and_retained_revalidation(self):
        from cybergold_candidate.uniswap_v4 import STATE_VIEW, POOL_MANAGER
        tail = pool(PAXG, COUNTER, 'v4', 500)
        tail['tickSpacing'] = 10
        tail['id'] = v4_pool_id((tail['token0']['address'], tail['token1']['address'], 500, 10, ZERO))
        class Rpc:
            chain_id, state_view, pool_manager, w3 = 31338, STATE_VIEW, POOL_MANAGER, Web3()
            def __init__(self):
                self.calls, self.known = [], {}
            async def block(self, _): return deepcopy(BLOCK)
            async def assert_canonical(self, block): assert block == BLOCK
            async def close(self): pass
            async def read_function(self, address, signature, inputs, args, outputs, block):
                assert block == BLOCK
                self.calls.append((signature, deepcopy(args)))
                if signature == 'decimals()': return (18,)
                identity = '0x'+args[0].hex()
                known = self.known.get(identity)
                if signature == 'getSlot0(bytes32)':
                    return (1 << 96, 0, 0, known['feePips']) if known else (0, 0, 0, 0)
                if signature == 'getLiquidity(bytes32)': return (10**18 if known else 0,)
                if signature == 'getTickBitmap(bytes32,int16)':
                    return (1 << (196 if args[1] == -1 else 60),)
                if signature == 'getTickLiquidity(bytes32,int24)':
                    return (10**18, 10**18 if args[1] < 0 else -10**18)
                raise AssertionError(signature)
        rpc = Rpc()
        registry = PoolRegistry(SETTINGS, rpc=rpc)
        rpc.known = {registry.seed['id']: registry.seed, tail['id']: tail}
        registry.ensure_loaded = lambda **_: asyncio.sleep(0)
        self.assertEqual(list(registry.inventory), [registry.seed['id']])
        sdk = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'), str(Path('src/uniswap-sdk/worker.ts').resolve())])
        quotes = MarketQuotes(SETTINGS, registry, sdk)
        self.addAsyncCleanup(quotes.close)
        self.addAsyncCleanup(registry.close)
        for side in ('sell', 'buy'):
            request = {'side': side, 'mode': 'exact-out', 'counterToken': COUNTER, 'amount': '1000000',
                'adapter': ADAPTER, 'recipient': COUNTER, 'deadline': '2000000000', 'slippageBps': 100}
            result = await quotes.get(request)
            self.assertEqual(result['qualification'], 'sdk')
            self.assertTrue(any(hop['pool']['id'] == tail['id'] for hop in result['plan']['route']['branches'][0]['hops']))
            self.assertIn(tail['id'], registry.inventory)
            self.assertEqual(registry.inventory[tail['id']]['acquisition'], {'blockNumber': '123', 'blockHash': BLOCK['hash']})
            retained = await quotes.get({**request, 'retainedPlan': result['plan']})
            self.assertEqual(retained['params']['bound'], result['params']['bound'])
        self.assertEqual(set(registry.inventory), {registry.seed['id'], tail['id']})
        probed = {args[0].hex() for signature, args in rpc.calls if signature == 'getSlot0(bytes32)'}
        self.assertGreater(len(probed), 2, 'Uninitialized candidate keys must be observed, not fabricated as pools')

    async def fixture(self, tail_protocol):
        class Rpc:
            chain_id = 31338
            async def block(self, _):
                return deepcopy(BLOCK)
            async def assert_canonical(self, block):
                assert block == BLOCK
            async def close(self):
                pass
        registry = PoolRegistry(SETTINGS, rpc=Rpc())
        anchor = registry.seed
        tail = pool(PAXG, COUNTER, tail_protocol)
        registry.inventory = {row['id']: row for row in (anchor, tail)}
        registry.loaded = True
        async def ensure_loaded(*_args, **_kwargs):
            pass
        registry.ensure_loaded = ensure_loaded
        async def acquire(row, block):
            self.assertEqual(block, BLOCK)
            known = next((known for known in registry.inventory.values() if pool_identity(known) == pool_identity(row)), None)
            if known is None:
                raise ValueError('Fixture has no pool at this execution identity')
            value = snapshot(known)
            registry.observed[known['id']] = deepcopy(value)
            return value
        registry.snapshot = acquire
        sdk = SdkWorker([os.environ.get('CYBERGOLD_TEST_NODE', 'node'), str(Path('src/uniswap-sdk/worker.ts').resolve())])
        quotes = MarketQuotes(SETTINGS, registry, sdk)
        quotes.connector_calls = []
        async def connectors(*args):
            quotes.connector_calls.append(args)
        quotes.connector_inventory = connectors
        self.addAsyncCleanup(quotes.close)
        self.addAsyncCleanup(registry.close)
        return quotes, registry

    async def test_real_sdk_mixed_input_and_homogeneous_v4_output_both_directions(self):
        for tail_protocol, mode in (('v3', 'exact-in'), ('v4', 'exact-out')):
            quotes, registry = await self.fixture(tail_protocol)
            for side in ('buy', 'sell'):
                with self.subTest(tail=tail_protocol, mode=mode, side=side):
                    request = {'side': side, 'mode': mode, 'counterToken': COUNTER, 'amount': '1000000',
                        'adapter': ADAPTER, 'recipient': COUNTER, 'deadline': '2000000000', 'slippageBps': 100}
                    result = await quotes.get(request)
                    route = result['plan']['route']
                    self.assertEqual(result['qualification'], 'sdk')
                    self.assertEqual(result['adapterData'], encode_route(route, ADAPTER))
                    self.assertGreater(int(result['totalInput']), 0)
                    self.assertGreater(int(result['netOutput']), 0)
                    decoded, = Web3().codec.decode([ADAPTER_TYPE], bytes.fromhex(result['adapterData'][2:]))
                    self.assertEqual(decoded[0], mode == 'exact-in')
                    for branch in route['branches']:
                        hops = branch['hops']
                        self.assertEqual(hops[0 if side == 'sell' else -1]['pool']['id'], registry.seed['id'])
                        self.assertEqual(len(hops), 2)
                    protocols = [hop[0] for hop in decoded[3][0][1]]
                    self.assertEqual(protocols, [2, 1] if side == 'sell' and tail_protocol == 'v3'
                        else [1, 2] if tail_protocol == 'v3' else [2, 2])
                    self.assertEqual(result['searchCoverage']['canonicalPosition'], 'first' if side == 'sell' else 'last')
                    self.assertEqual(bool(quotes.connector_calls), mode == 'exact-in')
                    retained = await quotes.get({**request, 'retainedPlan': result['plan']})
                    self.assertEqual(retained['params']['bound'], result['params']['bound'])

    async def test_only_mixed_output_routes_remain_unavailable_and_never_become_adapter_payloads(self):
        quotes, _registry = await self.fixture('v3')
        for side in ('buy', 'sell'):
            request = {'side': side, 'mode': 'exact-out', 'counterToken': COUNTER, 'amount': '1000000',
                'adapter': ADAPTER, 'recipient': COUNTER, 'deadline': '2000000000', 'slippageBps': 100}
            with self.assertRaises(QuoteFailure) as failure:
                await quotes.get(request)
            self.assertEqual(failure.exception.code, 'quote-no-route')

    async def test_retained_unanchored_pool_cannot_bypass_market_route_intent(self):
        quotes, registry = await self.fixture('v4')
        bypass = pool(CORE, COUNTER)
        registry.inventory[bypass['id']] = bypass
        branch = [{'amountIn': '1000', 'hops': [{'pool': bypass,
            'zeroForOne': CORE.lower() == bypass['token0']['address'].lower()}]}]
        with self.assertRaisesRegex(InvalidPreview, 'canonical CYGLD pool'):
            quotes.resolve_market_branches(branch, CORE, COUNTER, 'exactIn', 1000)


if __name__ == '__main__':
    unittest.main()
