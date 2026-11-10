"""Immutable synthetic chain served through the production RPC acquisition path.

These are invented pool states and Core producer replies, never live-chain or
historical observations. The loopback server only supplies ABI getter data;
the actual SDK performs pool arithmetic, including shared-pool replay.
"""
import asyncio
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import time
from types import SimpleNamespace

from aiohttp import web
from web3 import Web3

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quote_errors import QuoteFailure
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.uniswap_state import PoolRegistry
from cybergold_candidate.uniswap_v4 import POOL_MANAGER, STATE_VIEW
from cybergold_candidate.routing_encoding import ZERO
from quoter_fixture import synthetic_pool
from test_universal_quote import BLOCK, CORE, PAXG, OTHER, WETH, settings, fixture_plan_simulator


@dataclass(frozen=True)
class MatrixCase:
    name: str
    family: str
    pools: tuple
    request: dict
    core_preview: bool = False
    description: str = ''
    catalog_delay_ms: float = 0

    @property
    def digest(self):
        return hashlib.sha256(json.dumps({
            'pools': self.pools, 'request': self.request, 'block': BLOCK,
            'corePreview': self.core_preview,
            'corePreviewModel': 'two-equal-assets-capped-2000-net-three-per-match-v1',
            'initialCatalog': 'anchor-only' if self.catalog_delay_ms else 'complete',
            'catalogDelayMs': self.catalog_delay_ms,
        }, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def matrix_cases():
    def market(name, pools, *, source=WETH, amount=10000, description=''):
        return MatrixCase(name, 'pure-market', tuple(pools), {
            'intent': 0, 'inputs': [{'currency': source, 'amount': str(amount)}],
            'outputCurrency': CORE}, description=description)

    anchor = synthetic_pool(PAXG, CORE, 900, 'v4', liquidity=10**12)
    standard = synthetic_pool(WETH, PAXG, 901, 'v3', liquidity=10**10)
    split_a = synthetic_pool(WETH, PAXG, 902, 'v3', liquidity=6*10**6)
    split_b = synthetic_pool(WETH, PAXG, 903, 'v2')
    split_b.update(reserve0='80000', reserve1='80000')
    native = synthetic_pool(ZERO, PAXG, 904, 'v4', liquidity=10**10)
    other = synthetic_pool(WETH, OTHER, 905, 'v3', liquidity=10**10)
    bridge = synthetic_pool(PAXG, OTHER, 906, 'v2')
    bridge.update(reserve0='10000000', reserve1='10000000')
    continuation_bridge = synthetic_pool(PAXG, OTHER, 913, 'v3', liquidity=10**10)
    prefix_connector = synthetic_pool(WETH, PAXG, 907, 'v2')
    prefix_connector.update(reserve0=str(10**12), reserve1=str(10**12))
    narrow_anchor = synthetic_pool(PAXG, CORE, 908, 'v3', liquidity=10**6)
    disjoint_pools = []
    for asset, number in ((PAXG, 909), (OTHER, 911)):
        deep = synthetic_pool(WETH, asset, number, 'v3', liquidity=10**12)
        thin = synthetic_pool(WETH, asset, number+1, 'v2')
        # A thin pool has a modestly better initial price than its deep
        # alternative. Its finite reserves, not a supplied quote, make the
        # useful allocation smaller than the existing 25% grid.
        thin['reserve0'], thin['reserve1'] = (
            ('3000', '3300') if thin['token0']['address'].lower() == WETH.lower()
            else ('3300', '3000'))
        disjoint_pools.extend((deep, thin))
    request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}],
               'outputCurrency': CORE}
    return [
        market('market-two-hop', [standard, anchor],
               description='V3 acquisition then the accepted V4 Core market anchor.'),
        MatrixCase('market-delayed-catalog', 'pure-market', (standard, anchor), deepcopy(request),
                   description='Full synthetic chain state, anchor-only initial catalog; ordinary discovery publishes the connector after a controlled 300 ms delay.',
                   catalog_delay_ms=300),
        market('market-split-capacity', [split_a, split_b, anchor], amount=25000,
               description='Narrow V3 plus V2 alternative; split branches share the final V4 anchor.'),
        market('market-native-v4', [native, anchor], source=ZERO,
               description='Native input through V4, without an invented ERC20 native token.'),
        market('market-disconnected', [anchor],
               description='No connection from input to the anchor; attempted failures remain in the denominator.'),
        market('market-narrow-prefix', [prefix_connector, narrow_anchor],
               description='V2 acquisition then narrow V3 Core anchor; on-demand tick coverage and smaller-funded prefix repair.'),
        MatrixCase('market-plus-core', 'market-plus-core', (standard, other, bridge, anchor),
                   deepcopy(request), True,
                   'Both ordinary Market and Core basket acquisition/continuation are evaluated.'),
        MatrixCase('core-shared-acquisition', 'market-plus-core', (standard, bridge, continuation_bridge, anchor),
                   deepcopy(request), True,
                   'The two Core basket acquisitions share WETH/PAXG state; independent V2/V3 bridges allow a compatible OTHER residual continuation.'),
        MatrixCase('core-disjoint-asymmetric-amm', 'market-plus-core', (*disjoint_pools, anchor),
                   {**deepcopy(request), 'inputs': [{'currency': WETH, 'amount': '3000'}]}, True,
                   'Disjoint basket acquisitions each offer a thin V2 pool at a modest price premium and a deep V3 alternative; actual SDK curves expose a finer-than-25% split opportunity below the unchanged synthetic Core cap.'),
    ]


class LoopbackState:
    """Real HTTP JSON-RPC envelopes, immutable ABI responses, bounded diagnostics."""
    def __init__(self, pools, *, delay_ms=0):
        self.pools = deepcopy(pools)
        self.addresses = {pool['address'].lower(): pool for pool in pools if pool.get('address')}
        self.ids = {pool['id'].lower(): pool for pool in pools}
        self.delay_ms = delay_ms
        self.envelopes = self.members = self.rejected = 0
        self.methods = Counter()
        self.selectors = Counter()
        self.unsupported = Counter()
        self.runner = None
        self.codec = Web3().codec
        self.signatures = {}
        self.storage = {}
        for pool in pools:
            if pool['protocol'] != 'v4':
                continue
            root = int.from_bytes(Web3.keccak(self.codec.encode(
                ['bytes32', 'uint256'], [bytes.fromhex(pool['id'][2:]), 6])), 'big')
            for row in pool['bitmapWords']:
                slot = Web3.keccak(self.codec.encode(['int256', 'uint256'], [row['wordPosition'], root+5]))
                self.storage[slot] = int(row['bitmap']).to_bytes(32, 'big')
        for signature, inputs, outputs in (
            ('getReserves()', [], ['uint112', 'uint112', 'uint32']),
            ('slot0()', [], ['uint160', 'int24', 'uint16', 'uint16', 'uint16', 'uint8', 'bool']),
            ('liquidity()', [], ['uint128']), ('tickSpacing()', [], ['int24']),
            ('tickBitmap(int16)', ['int16'], ['uint256']),
            ('ticks(int24)', ['int24'], ['uint128', 'int128', 'uint256', 'uint256', 'int56', 'uint160', 'uint32', 'bool']),
            ('getSlot0(bytes32)', ['bytes32'], ['uint160', 'int24', 'uint24', 'uint24']),
            ('getLiquidity(bytes32)', ['bytes32'], ['uint128']),
            ('getTickBitmap(bytes32,int16)', ['bytes32', 'int16'], ['uint256']),
            ('getTickLiquidity(bytes32,int24)', ['bytes32', 'int24'], ['uint128', 'int128']),
            ('aggregate3((address,bool,bytes)[])', ['(address,bool,bytes)[]'], ['(bool,bytes)[]']),
            ('extsload(bytes32[])', ['bytes32[]'], ['bytes32[]']),
            ('getPool(address,address,uint24)', ['address', 'address', 'uint24'], ['address']),
            ('getPair(address,address)', ['address', 'address'], ['address']),
            ('decimals()', [], ['uint8']), ('totalSupply()', [], ['uint256']),
        ):
            self.signatures[bytes(Web3.keccak(text=signature)[:4])] = (signature, inputs, outputs)

    async def start(self):
        app = web.Application()
        app.router.add_post('/', self.receive)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = f'http://127.0.0.1:{port}/'
        return self

    async def close(self):
        if self.runner is not None:
            await self.runner.cleanup()

    def counts(self):
        return {'httpEnvelopes': self.envelopes, 'jsonRpcMembers': self.members,
                'rejectedMembers': self.rejected, 'methods': dict(self.methods),
                'getterCalls': dict(self.selectors), 'unsupported': dict(self.unsupported)}

    async def receive(self, request):
        import asyncio
        body = await request.json()
        self.envelopes += 1
        rows = body if isinstance(body, list) else [body]
        self.members += len(rows)
        self.methods.update(row.get('method') for row in rows)
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)
        return web.json_response([self.reply(row) for row in body]
                                 if isinstance(body, list) else self.reply(body))

    def reply(self, row):
        method = row.get('method')
        try:
            if method == 'eth_chainId':
                result = '0x1'
            elif method in ('eth_getBlockByNumber', 'eth_getBlockByHash'):
                requested = row['params'][0]
                if requested not in ('latest', hex(BLOCK['number']), BLOCK['hash']):
                    raise ValueError('unavailable-block')
                result = {'number': hex(BLOCK['number']), 'hash': BLOCK['hash'],
                          'parentHash': '0x'+'cd'*32, 'timestamp': '0x65000000',
                          'baseFeePerGas': '0x3b9aca00', 'gasLimit': '0x1c9c380',
                          'gasUsed': '0x0', 'transactions': []}
            elif method == 'eth_call':
                call, context = row['params']
                if context != {'blockHash': BLOCK['hash'], 'requireCanonical': True}:
                    raise ValueError('unpinned-call')
                result = Web3.to_hex(self.call(call['to'], bytes.fromhex(call['data'][2:])))
            else:
                raise ValueError('unsupported-method')
            return {'jsonrpc': '2.0', 'id': row['id'], 'result': result}
        except (KeyError, ValueError) as error:
            self.rejected += 1
            # Only fixed synthetic reasons and method/selector names are kept.
            reason = str(error).strip("'")
            self.unsupported[reason if reason in ('unavailable-block', 'unpinned-call',
                'unsupported-method', 'unknown-pool', 'unknown-selector', 'unsupported-getter')
                else 'fixture-decode'] += 1
            return {'jsonrpc': '2.0', 'id': row['id'],
                    'error': {'code': -32000, 'message': 'Synthetic fixture has no such observation'}}

    def call(self, address, data):
        spec = self.signatures.get(data[:4])
        if spec is None:
            raise ValueError('unknown-selector')
        signature, inputs, outputs = spec
        self.selectors[signature] += 1
        args = self.codec.decode(inputs, data[4:]) if inputs else ()
        pool = self.addresses.get(address.lower())
        if signature == 'aggregate3((address,bool,bytes)[])':
            values = ([(True, self.call(target, raw)) for target, _, raw in args[0]],)
        elif signature == 'extsload(bytes32[])':
            if address.lower() != POOL_MANAGER.lower():
                raise ValueError('unknown-pool')
            values = ([self.storage.get(slot, bytes(32)) for slot in args[0]],)
        elif signature in ('getPair(address,address)', 'getPool(address,address,uint24)'):
            tokens = sorted(token.lower() for token in args[:2])
            protocol = 'v2' if signature.startswith('getPair') else 'v3'
            found = next((item for item in self.pools if item['protocol'] == protocol
                and [item['token0']['address'].lower(), item['token1']['address'].lower()] == tokens
                and (protocol == 'v2' or int(item['feePips']) == args[2])), None)
            values = (found['address'] if found else ZERO,)
        elif signature == 'decimals()':
            values = (18,)
        elif signature == 'totalSupply()':
            if address.lower() != CORE.lower():
                raise ValueError('unknown-pool')
            values = (10**24,)
        else:
            if inputs and inputs[0] == 'bytes32':
                if address.lower() != STATE_VIEW.lower():
                    raise ValueError('unknown-pool')
                pool = self.ids.get(Web3.to_hex(args[0]).lower())
                if pool is None:
                    # Every modeled StateView getter delegates to StateLibrary
                    # extsload. Absent pool/tick mapping storage is zero, rather
                    # than a pool-existence revert from the view contract.
                    return self.codec.encode(outputs, [0] * len(outputs))
            if pool is None:
                raise ValueError('unknown-pool')
            if signature == 'getReserves()':
                values = (int(pool['reserve0']), int(pool['reserve1']), 0)
            elif signature == 'slot0()':
                values = (int(pool['sqrtRatioX96']), pool['tick'], 0, 1, 1, 0, True)
            elif signature == 'getSlot0(bytes32)':
                values = (int(pool['sqrtRatioX96']), pool['tick'], 0, int(pool['lpFee']))
            elif signature in ('liquidity()', 'getLiquidity(bytes32)'):
                values = (int(pool['liquidity']),)
            elif signature == 'tickSpacing()':
                values = (int(pool['tickSpacing']),)
            elif signature in ('tickBitmap(int16)', 'getTickBitmap(bytes32,int16)'):
                word = args[-1]
                values = (next((int(row['bitmap']) for row in pool['bitmapWords']
                                if row['wordPosition'] == word), 0),)
            elif signature in ('ticks(int24)', 'getTickLiquidity(bytes32,int24)'):
                tick = next((row for row in pool['ticks'] if row['index'] == args[-1]), None)
                values = (int(tick['liquidityGross']), int(tick['liquidityNet'])) if tick else (0, 0)
                if signature.startswith('ticks('):
                    values += (0, 0, 0, 0, 0, tick is not None)
            else:
                raise ValueError('unsupported-getter')
        return self.codec.encode(outputs, values)


class MatrixService:
    """Own a genuine Quoter/registry/SDK, with an equal injected topology catalog."""
    def __init__(self, case, transport, node, root):
        self.case, self.transport = case, transport
        self.settings = SimpleNamespace(**{**vars(settings()), 'RPC_URL': transport.url,
            'RPC_AUTHORIZATION': None, 'CYBERGOLD_UNISWAP_API_KEY': None,
            'CYBERGOLD_UNISWAP_API_SWAPPER': None})
        self.registry = PoolRegistry(self.settings)
        # Only catalog identities are injected. No getter/tick observations are
        # injected into either strategy's cold canonical acquisition cache.
        scalar = {'reserve0', 'reserve1', 'sqrtRatioX96', 'tick', 'liquidity',
                  'bitmapWords', 'ticks', 'context', 'lpFee', 'protocolFee'}
        identities = [{key: deepcopy(value) for key, value in pool.items() if key not in scalar}
                      for pool in case.pools]
        self.catalog_identities = {pool['id']: pool for pool in identities}
        self.registry.inventory = ({identities[-1]['id']: deepcopy(identities[-1])}
            if case.catalog_delay_ms else deepcopy(self.catalog_identities))
        self.registry.seed = deepcopy(identities[-1])
        self.catalog_expanded = not bool(case.catalog_delay_ms)
        self.catalog_expansions = self.discovery_calls = 0
        self.catalog_loading = None
        self.catalog_events = []
        self.started = time.perf_counter()
        self.registry.loaded = True
        self.registry.loaded_at = time.monotonic()
        self.engine = RouteQuoteEngine(self.settings, self.registry,
            SdkWorker([node, str(root / 'src/uniswap-sdk/worker.ts')]))
        self.preview_calls = 0
        self.families = Counter()
        async def basis(_):
            return [PAXG, OTHER], [500000, 500000]
        async def preview(mode, value, block):
            self.preview_calls += 1
            if not case.core_preview or mode != 'issue-exact-in':
                raise QuoteFailure('quote-no-route')
            # Invented producer response accepted through Quoter.preview; no
            # estimate is substituted for a live Core preview in this harness.
            matched = min(2000, *map(int, value['maximumAmountsIn']))
            return {'netCygldOut': str(matched*3), 'amountsInExact': [str(matched)]*2,
                'orderedCoreAssets': [PAXG, OTHER],
                'fees': {'protocolFeeCygld': '0', 'helperFeeCygld': '0'}}
        async def simulate(request, selected, **kwargs):
            # Synthetic SDK component benchmark, never a Helpers execution oracle.
            return await fixture_plan_simulator(self.quoter, request, selected,
                basis_reader=basis, **kwargs)
        self.quoter = Quoter(self.settings, self.engine, preview=preview,
                             basis_reader=basis, exploration_seed=42, plan_simulator=simulate)
        async def exploration_block():
            return deepcopy(BLOCK)  # Known synthetic SDK construction data, no header RPC.
        self.quoter.exploration_block = exploration_block
        self.quoter.seed_routes = lambda *_: None
        async def expand_catalog():
            # One registry-owned catalog publication may have independent
            # Market/Core subscribers. Getter observations remain uninjected.
            started = time.perf_counter()
            await asyncio.sleep(case.catalog_delay_ms / 1000)
            self.registry.inventory.update(deepcopy(self.catalog_identities))
            self.catalog_expanded = True
            self.catalog_expansions += 1
            self.catalog_events.append({'kind': 'controlled-catalog-publication',
                'clock': 'harness-session',
                'arrivalMs': round((time.perf_counter()-self.started)*1000, 3),
                'delayElapsedMs': round((time.perf_counter()-started)*1000, 3),
                'inventoryPools': len(self.registry.inventory)})
        async def discover(*_):
            self.discovery_calls += 1
            if not self.catalog_expanded:
                # The server already owns every immutable pool observation.
                # Only ordinary topology publication is delayed; state still
                # comes from production HTTP getter/bitmap/tick acquisition.
                if self.catalog_loading is None:
                    self.catalog_loading = asyncio.create_task(expand_catalog())
                await asyncio.shield(self.catalog_loading)
        self.quoter.discover = discover
        candidate = self.quoter.candidate
        async def observed_candidate(*args, **kwargs):
            value = await candidate(*args, **kwargs)
            self.families[value['routeFamily']] += 1
            return value
        self.quoter.candidate = observed_candidate

    def catalog_state(self):
        return {'inventoryPools': len(self.registry.inventory),
            'fullCatalogPools': len(self.catalog_identities),
            'expanded': self.catalog_expanded, 'expansions': self.catalog_expansions,
            'discoveryCalls': self.discovery_calls,
            'sha256': hashlib.sha256(json.dumps(self.registry.inventory,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()}

    async def close(self):
        if self.catalog_loading is not None:
            self.catalog_loading.cancel()
            await asyncio.gather(self.catalog_loading, return_exceptions=True)
        await self.engine.close()
        await self.registry.close()
