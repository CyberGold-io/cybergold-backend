"""Optional disposable-PostgreSQL seed/restart/reorg activity qualification.

DATABASE_URL is the task DB. RPC headers/logs are synthetic, and only the
existing UniswapStore namespace is written. This is not a runtime/release gate.
"""
import asyncio
from copy import deepcopy
import json
import os
import sys
from types import SimpleNamespace

from cybergold_candidate.database import Database
from cybergold_candidate.pool_activity import get_pool_activity, pool_identity
from cybergold_candidate.uniswap_state import PoolRegistry, UniswapStore
from test_pool_activity import Rpc, pool, swap, block, C, D

CORE = '0x'+hex(0x292).removeprefix('0x').rjust(40, '0')
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE)


async def run(stage):
    database = Database(os.environ['DATABASE_URL'])
    store = UniswapStore(database, 1, CORE)
    rpc = Rpc()
    registry = PoolRegistry(SETTINGS, rpc, store)
    registry.inventory.clear()
    first, second, third = pool('v2'), pool('v3'), pool('v4')
    second.update(id=D, address=D)
    entries = [first, second, third]
    try:
        if stage == 'seed':
            registry.inventory = {entry['id']: deepcopy(entry) for entry in entries}
            for entry in entries:
                await store.save('inventory', entry['id'], entry)
                state = {**entry, 'context': {'chainId': 1, 'blockNumber': '100', 'blockHash': block(100)['hash']},
                         'ticks': [], 'bitmapWords': []}
                if entry['protocol'] == 'v2':
                    state.update(reserve0='100', reserve1='200')
                else:
                    state.update(sqrtRatioX96=str(1 << 96), liquidity='1000', tick=0)
                await store.save('observation', entry['id'], state)
            rpc.rows = [swap(entry, -(2**100) if entry['protocol'] == 'v4' else 2**100, 50 if entry['protocol'] == 'v4' else -50)
                        for entry in entries]
            await registry.monitor(block(102))
            rpc.rows = [swap(third, -9000, 4000, number=103)]
            await registry.monitor(block(104))
            await asyncio.gather(*tuple(registry.background))
        elif stage == 'recover':
            before = await get_pool_activity(store, 1)
            assert len(before['events']) == 4
            assert {event['pool']['protocol'] for event in before['events']} == {'v2', 'v3', 'v4'}
            assert all(int(item['amount0InRaw']) > 2**53 for summary in before['pools']
                       for item in [summary['rollups'][0]['rollup']])
            rpc.branch_start = 103
            rpc.rows = [swap(third, -200, 100, number=103, branch=1)]
            await registry.monitor(block(105, 1))
            await asyncio.gather(*tuple(registry.background))
            after = await get_pool_activity(store, 1, {'protocol': 'v4', 'poolId': third['id'], 'poolManager': C})
            assert [event['arguments']['amount0'] for event in after['events']] == ['-200', str(-(2**100))]
            assert all(event['blockHash'] != block(103)['hash'] for event in after['events'])
            assert after['pools'][0]['indexedThroughBlockHash'] == block(105, 1)['hash']
            # Catalog rollback removes the affected exact protocol's bundle.
            await registry.commit_catalog('v3', {'blockNumber': '0', 'checkpoints': []}, removed=[D])
            assert pool_identity(second) not in await store.load('activity')
            assert pool_identity(first) in await store.load('activity')
            # Existing generation namespace isolates a new Sandbox history.
            store.scope = 'generation:activity-probe-new:'
            assert (await get_pool_activity(store, 1))['events'] == []
        else:
            raise ValueError('Expected seed or recover')
        print(json.dumps({'stage': stage, 'rpc': 'synthetic canonical headers/logs',
            'store': 'real PostgreSQL JSONB namespace', 'protocols': ['v2', 'v3', 'v4'],
            'wideIntegersLossless': True, 'restartRecovery': stage == 'recover',
            'orphanedEventsAndRollupsRemoved': stage == 'recover'}))
    finally:
        await registry.close()
        await database.close()


if __name__ == '__main__':
    asyncio.run(run(sys.argv[1]))
