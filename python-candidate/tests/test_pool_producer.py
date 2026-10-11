import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.authoritative_pool_cache import AuthoritativePoolCache
from cybergold_candidate.pool_producer import PoolProducer, PoolIdentifier

A, B, POOL = ('0x' + digit * 40 for digit in ('1', '2', '3'))
HASH = '0x' + 'a' * 64


class Rpc:
    factory = '0x' + '4' * 40
    def __init__(self):
        self.calls = []
        self.mode = 'normal'
        self.closed = False
    async def block(self, _hash):
        return {'hash': HASH, 'number': 100}
    async def read(self, group, address, name, block, args=()):
        self.calls.append((group, address, name, block, args))
        if self.mode == 'outage':
            raise ValueError('https://secret:password@private.invalid')
        return {'getPool': '0x' + '0' * 40 if self.mode == 'empty' else POOL,
                'slot0': (2**150, -12, 1, 2, 3, 4, True), 'liquidity': 2**100,
                'balanceOf': 2**200}[name]
    async def assert_canonical(self, block):
        assert block['hash'] == HASH
        if self.mode == 'reorg':
            raise ValueError('Canonical block changed')
    async def close(self):
        self.closed = True


class Database:
    def __init__(self):
        self.writes = []
        self.rows = []
    async def ensure_schema(self):
        pass
    @asynccontextmanager
    async def connection(self):
        yield self
    async def execute(self, statement, parameters):
        if statement.startswith('INSERT'):
            self.writes.append(parameters)
        return self
    async def fetchall(self):
        return self.rows


async def run():
    rpc = Rpc()
    producer = PoolProducer(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338'), rpc,
                            now=lambda: '2026-10-01T07:00:00.000Z')
    database = Database()
    cache = AuthoritativePoolCache(database, producer)
    identifier = {'tokenA': B, 'tokenB': A, 'fee': 3000}
    normal = await producer.get(identifier)
    assert normal['context']['blockHash'] == HASH
    assert (normal['token0'], normal['token1']) == (A, B)
    assert normal['activeLiquidityRaw'] == str(2**100) and normal['token0BalanceRaw'] == str(2**200)
    assert all(call[3]['hash'] == HASH for call in rpc.calls) and len(rpc.calls) == 5
    rpc.mode = 'empty';rpc.calls.clear()
    empty = await producer.get(identifier)
    assert empty['exists'] is False and 'poolAddress' not in empty and len(rpc.calls) == 1
    rpc.mode = 'reorg'
    try:
        await producer.get(identifier)
    except ValueError:
        pass
    else:
        raise AssertionError('Reorged observation published')
    rpc.mode = 'normal'
    forged = {**identifier, 'chainId': 1, 'dex': 'uniswap_v3', 'poolAddress': '0x'+'9'*40,
              'exists': False, 'quoteSucceeded': True, 'activeLiquidityRaw': '0', 'sqrtPriceX96Raw': '1',
              'tick': 1, 'token0BalanceRaw': '0', 'token1BalanceRaw': '0'}
    await cache.record([forged, {**forged, 'tokenA': A, 'tokenB': B}])
    assert len(database.writes) == 1
    params = database.writes[0]
    assert params[0] == 31338 and params[5].lower() == POOL and params[6] is True
    assert params[7] == str(2**100) and params[10] == str(2**200)
    database.rows = [{'dex': 'uniswap_v3','token0': A,'token1': B,'fee': 3000,
        'poolAddress': '0x'+'9'*40,'exists': True,'successCount': 99,'activeLiquidityRaw': '0',
        'sqrtPriceX96Raw': '1','tick': 1,'token0BalanceRaw': '0','token1BalanceRaw': '0',
        'liquidityCheckedAt': None,'lastCheckedAt': None}]
    listed = await cache.list(31338, 'uniswap_v3', [{'tokenA': A,'tokenB': B}])
    assert listed[0]['poolAddress'].lower() == POOL and listed[0]['activeLiquidityRaw'] == str(2**100)
    assert listed[0]['successCount'] == 0
    assert await cache.list(1, 'uniswap_v3', [{'tokenA': A,'tokenB': B}]) == []
    rpc.mode = 'empty'
    await cache.record([forged])
    assert database.writes[-1][5] is None and database.writes[-1][6] is False
    assert database.writes[-1][7:12] == (None, None, None, None, None)
    rpc.mode = 'outage'
    before = len(database.writes)
    for operation in (cache.record([forged]), cache.list(31338, 'uniswap_v3', [{'tokenA': A,'tokenB': B}])):
        try:
            await operation
        except ValueError:
            pass
        else:
            raise AssertionError('Outage published browser-owned data')
    assert len(database.writes) == before
    app = create_app(pool_producer=producer, pool_cache=cache)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as api:
            bad = await api.post('/api/pools/snapshot', json={**identifier,'fee':2**24})
            assert bad.status_code == 400
            failed = await api.post('/api/pools/snapshot', json=forged)
            assert failed.status_code == 503 and failed.headers['cache-control'] == 'no-store'
            assert 'password' not in failed.text and 'correlationId' in failed.json()
            rpc.mode = 'normal'
            good = await api.post('/api/pools/snapshot', json=forged)
            assert good.status_code == 200 and good.json() == normal
            recorded = await api.post('/api/quote-pool-cache', json={'action':'record-observations','entries':[forged]})
            assert recorded.status_code == 200 and database.writes[-1][5].lower() == POOL
    assert rpc.closed
    PoolIdentifier.model_validate(identifier)
    print('PASS: configured canonical/wide pool reads, empty/reorg/outage, fabricated current/retained state, deduplication, chain isolation, complete replacement and HTTP redaction/shutdown')


if __name__ == '__main__':
    asyncio.run(run())
