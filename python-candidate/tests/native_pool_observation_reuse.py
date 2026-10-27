"""Disposable PostgreSQL two-process-equivalent observation reuse control.

DATABASE_URL must name the caller-owned test database. No RPC is contacted;
the existing UniswapStore table/namespace and native connection pool are used.
"""
import asyncio
from copy import deepcopy
import json
import os
from types import SimpleNamespace

from cybergold_candidate.database import Database
from cybergold_candidate.uniswap_state import PoolRegistry, UniswapStore
from test_snapshot_copy import _reuse_snapshot

CORE = '0x' + '9' * 40


async def run():
    first_db, second_db = Database(os.environ['DATABASE_URL']), Database(os.environ['DATABASE_URL'])
    first = UniswapStore(first_db, 1, CORE)
    second = UniswapStore(second_db, 1, CORE)
    registry = PoolRegistry(SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE), store=first)
    try:
        await first.prepare()
        await second.prepare()
        async with first_db.connection() as a, second_db.connection() as b:
            a_pid = (await (await a.execute('SELECT pg_backend_pid() AS pid')).fetchone())['pid']
            b_pid = (await (await b.execute('SELECT pg_backend_pid() AS pid')).fetchone())['pid']
            assert a_pid != b_pid
            version = (await (await a.execute('SHOW server_version')).fetchone())['server_version']
        rows = [_reuse_snapshot(index, index * 2560) for index in range(8)]
        physical_id = rows[0]['address'].lower()
        for index, row in enumerate(rows):
            if index % 2 == 0:
                row['id'] = 'seed-alias:'+str(index)
        await asyncio.gather(*(store.save('observation', row['id'], row)
            for index, row in enumerate(rows) for store in ([first] if index % 2 == 0 else [second])))
        saved = await first.load('observation')
        assert set(saved) == {physical_id}
        observed = saved[physical_id]
        assert {row['wordPosition'] for row in observed['bitmapWords']} == set(range(8))
        assert {row['index'] for row in observed['ticks']} == {index * 2560 for index in range(8)}
        registry.observed[rows[0]['id']] = deepcopy(rows[0])
        await registry._load()
        assert set(registry.observed) == {physical_id}
        assert len(registry.observed[physical_id]['bitmapWords']) == 8
        replacement = _reuse_snapshot(20, 20 * 2560, block_hash='0x' + 'fe' * 32,
            block_number=int(rows[0]['context']['blockNumber']) - 1)
        await second.save('observation', replacement['id'], replacement)
        assert (await first.load('observation'))[replacement['id']] == replacement
        fork = UniswapStore(first_db, 31338, CORE)
        fork.scope = 'generation:observation-reuse-control:'
        await fork.save('observation', rows[0]['id'], rows[0])
        await fork.save('observation', rows[1]['id'], rows[1])
        assert (await fork.load('observation'))[physical_id] == rows[1]
        print(json.dumps({'postgresVersion': version, 'distinctDatabaseConnections': True,
            'concurrentSameHashWrites': len(rows), 'preservedBitmapWords': 8, 'preservedTicks': 8,
            'seedAndAddressAliasesShareStoredRecord': True,
            'sameHashReloadUnion': True, 'differentHashReplacementUnchanged': True,
            'sandboxSameHeaderReplacementUnchanged': True, 'rpc': 'none'}))
    finally:
        await registry.close()
        await asyncio.gather(first_db.close(), second_db.close())


if __name__ == '__main__':
    asyncio.run(run())
