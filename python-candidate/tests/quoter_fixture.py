"""Offline real-SDK fixtures shared by the optional search/funding controls."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.uniswap_routes import pool_identity
from cybergold_candidate.uniswap_v4 import v4_pool_id, POOL_MANAGER
from test_universal_quote import BLOCK, CORE, PAXG, OTHER, WETH, settings


def synthetic_pool(a, b, number, protocol, liquidity=10**6):
    a, b = sorted((a.lower(), b.lower()))
    address = '0x' + format(number, '040x')
    pool = {'id': address, 'address': address, 'protocol': protocol, 'feePips': 3000,
        'tickSpacing': 60, 'hooks': '0x' + '00' * 20,
        'token0': {'address': a, 'decimals': 18, 'chainId': 1},
        'token1': {'address': b, 'decimals': 18, 'chainId': 1},
        'context': {'chainId': 1, 'blockNumber': str(BLOCK['number']), 'blockHash': BLOCK['hash']}}
    if protocol == 'v2':
        return {**pool, 'reserve0': str(10**9), 'reserve1': str(10**9)}
    words = {i: 0 for i in range((-887272 // 60) >> 8, ((887272 // 60) >> 8) + 1)}
    ticks = []
    for tick, net in [(-60, liquidity), (60, -liquidity)]:
        compressed = tick // 60
        words[compressed >> 8] |= 1 << (compressed % 256)
        ticks.append({'index': tick, 'liquidityGross': str(liquidity), 'liquidityNet': str(net)})
    pool.update(sqrtRatioX96=str(2**96), tick=0, liquidity=str(liquidity), ticks=ticks,
        bitmapWords=[{'wordPosition': word, 'bitmap': str(bits)} for word, bits in words.items()])
    if protocol == 'v4':
        pool.pop('address')
        pool.update(id=v4_pool_id((a, b, 3000, 60, pool['hooks'])), poolManager=POOL_MANAGER,
            lpFee=3000, protocolFee=0)
    return pool


class Registry:
    chain, core = 1, CORE

    def __init__(self, pools, block=BLOCK):
        self.inventory = {pool['id']: deepcopy(pool) for pool in pools}
        self.observed = deepcopy(self.inventory)
        self.pending = SharedReads()
        self.seed = pools[-1]
        self.at = deepcopy(block)
        self.heads = self.verifications = 0

    def observation(self, pool):
        return next((row for row in self.observed.values() if pool_identity(row) == pool_identity(pool)), None)

    async def ensure_loaded(self):
        pass

    async def snapshot(self, pool, block):
        row = self.observation(pool)
        if row is None:
            raise AssertionError('Offline snapshot absent')
        return deepcopy(row)

    async def extend_ticks(self, *_):
        raise AssertionError('Offline bitmap/tick coverage absent')

    def get_rpc(self):
        return self

    async def block(self, *_):
        self.heads += 1
        return deepcopy(self.at)

    async def assert_canonical(self, *_):
        self.verifications += 1


async def basis(_):
    return [PAXG, OTHER], [500000, 500000]


def service(test, pools, **options):
    registry = Registry(pools)
    engine = RouteQuoteEngine(settings(), registry, sdk=SdkWorker())
    test.addAsyncCleanup(engine.close)
    test.addAsyncCleanup(registry.pending.close)
    return Quoter(settings(), engine, basis_reader=basis, **options)


@lru_cache
def historical_data():
    return json.loads((Path(__file__).parent / 'fixtures/quoter-optimization-state.json').read_text())


def expand(pool):
    result = deepcopy(pool)
    ranges = result.pop('zeroBitmapRanges', [])
    result.setdefault('bitmapWords', []).extend({'wordPosition': word, 'bitmap': '0'}
        for first, last in ranges for word in range(first, last + 1))
    return result


def historical_service(test, name='buy500', **options):
    from types import SimpleNamespace
    from cybergold_candidate.uniswap_v4 import POOL_ID
    data = historical_data()
    case = next(row for row in data['cases'] if row['case'] == name)
    pools = list(case['inventory'].values())
    registry = Registry(pools, data['anchor'])
    registry.inventory = deepcopy(case['inventory'])
    registry.observed = {key: expand(pool) for key, pool in case['observed'].items()}
    registry.seed = registry.inventory[POOL_ID]
    registry.core = case['request']['outputCurrency'] if case['request']['intent'] == 0 else case['request']['inputs'][0]['currency']
    config = SimpleNamespace(**{**vars(settings()), 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': registry.core})
    engine = RouteQuoteEngine(config, registry, sdk=SdkWorker())
    test.addAsyncCleanup(engine.close)
    test.addAsyncCleanup(registry.pending.close)
    async def basis_reader(_):
        return deepcopy(case['basis'])
    async def preview(mode, value, block):
        assert mode == 'issue-exact-in'
        return deepcopy(data['corePreviews'][','.join(value['maximumAmountsIn'])])
    q = Quoter(config, engine, basis_reader=basis_reader, preview=preview, **options)
    q.seed_routes = lambda *_: None
    async def discover(*_):
        pass
    q.discover = discover
    return q, deepcopy(case)


def historical_route(q, row):
    return [{'pool': deepcopy(q.engine.registry.inventory[hop['pool']]), 'zeroForOne': hop['zeroForOne']}
            if 'pool' in hop else deepcopy(hop) for hop in row['hops']]
