"""Optional task-DB probe: additive V3 migration and V4 cache identities/restart.

Run seed, restart the task PostgreSQL container, then recover. DATABASE_URL must
refer to the disposable qualification DB. Contract RPC is synthetic; these
checks do not claim live discovery/backfill. No product CI/startup requirement.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from cybergold_candidate import database as database_module
from cybergold_candidate.database import Database, SCHEMA
from cybergold_candidate.authoritative_pool_cache import AuthoritativePoolCache
from cybergold_candidate.pool_producer import PoolProducer, identifier_from_pool
from cybergold_candidate.uniswap_state import PoolRegistry, ZERO
from cybergold_candidate.uniswap_routes import v4_pool_id
from test_pool_protocols import Rpc, SETTINGS, A, B, C, NOW


def migrate(operation, revision):
    engine = create_engine(make_url(os.environ['DATABASE_URL']).set(drivername='postgresql+psycopg'),poolclass=NullPool)
    try:
        with engine.begin() as connection:
            config = Config(str(Path(database_module.__file__).resolve().parents[2]/'schema/alembic.ini'))
            config.attributes['connection'] = connection
            getattr(command,operation)(config,revision)
    finally:
        engine.dispose()


def pool(registry,rpc,spacing,hooks):
    identity = v4_pool_id((A,B,100,spacing,hooks))
    rpc.v4_states[identity] = {'price':441947936735403526595706575860+spacing,
                             'tick':34378,'liquidity':879772594612909362900+spacing}
    return {'id':identity,'protocol':'v4','poolManager':rpc.pool_manager,
            'token0':registry.token(A,18),'token1':registry.token(B,18),
            'feePips':100,'tickSpacing':spacing,'hooks':hooks}


async def run(stage):
    database = Database(os.environ['DATABASE_URL'])
    rpc = Rpc()
    registry = PoolRegistry(SETTINGS,rpc)
    registry.inventory.clear()
    producer = PoolProducer(SETTINGS,registry=registry,now=lambda:NOW)
    cache = AuthoritativePoolCache(database,producer)
    pools = [pool(registry,rpc,1,ZERO),pool(registry,rpc,60,ZERO),pool(registry,rpc,1,C)]
    try:
        if stage == 'seed':
            # Install the immutable predecessor, seed an old row, then run the
            # real lazy additive migration; no fixture-authored copy SQL.
            for statement in SCHEMA['statements']:
                async with database.connection() as connection:
                    await connection.execute(statement)
            async with database.connection() as connection:
                await connection.execute('''INSERT INTO quote_pool_cache
                    (chain_id,dex,token0,token1,fee,pool_address,exists,success_count,
                    active_liquidity_raw,sqrt_price_x96_raw,tick,token0_balance_raw,token1_balance_raw,
                    liquidity_checked_at,last_checked_at,last_success_at)
                    VALUES (1,'uniswap_v3',%s,%s,500,%s,TRUE,17,%s,%s,-12,%s,%s,NOW(),NOW(),NOW())''',
                    (A,B,C,str(2**100),str(2**150),str(2**200),str(2**201)))
            migrate('stamp','0012_retained')
            migrate('upgrade','head')
            await database.ensure_schema()
            for entry in pools:
                registry.inventory[entry['id']] = entry
            entries = [{**identifier_from_pool(entry),'dex':'uniswap_v4','chainId':1,
                        'exists':False,'activeLiquidityRaw':'0','token0BalanceRaw':'99999999'} for entry in pools]
            await cache.record(entries)
        elif stage == 'recover':
            migrate('upgrade','head')
            await database.ensure_schema()
        else:
            raise ValueError('Stage must be seed or recover')
        async with database.connection() as connection:
            cursor = await connection.execute('''SELECT i.legacy_payload=to_jsonb(q) AS exact
                FROM quote_pool_cache q JOIN quote_pool_identity_cache i
                ON i.chain_id=q.chain_id AND i.dex=q.dex
                AND i.identity='legacy-v3:'||q.token0||':'||q.token1||':'||q.fee::text
                WHERE q.chain_id=1 AND q.token0=%s AND q.token1=%s AND q.fee=500''',(A,B))
            assert (await cursor.fetchone())['exact'] is True
            cursor = await connection.execute("SELECT count(*) AS count FROM quote_pool_identity_cache WHERE dex='uniswap_v4'")
            assert (await cursor.fetchone())['count'] == 3
            cursor = await connection.execute('SELECT identity,identifier FROM quote_pool_identity_cache WHERE dex=%s',('uniswap_v4',))
            identities = await cursor.fetchall()
            assert {row['identifier']['id'] for row in identities} == {entry['id'] for entry in pools}
            assert len({row['identity'] for row in identities}) == 3
            assert all(row['identity'].startswith('v4:'+rpc.pool_manager.lower()+':') for row in identities)
        # No registry inventory is required after restart; DB identity hints
        # re-acquire state using the same production supplier and canonical RPC.
        registry.inventory.clear()
        rows = await cache.list(1,'uniswap_v4',[{'tokenA':A,'tokenB':B}])
        assert len(rows) == 3
        assert {row['poolKey']['tickSpacing'] for row in rows} == {1,60}
        assert {row['poolKey']['hooks'].lower() for row in rows} == {ZERO,C}
        assert all(row['exists'] and 'token0BalanceRaw' not in row for row in rows)
        assert all(int(row['activeLiquidityRaw']) > 2**64 for row in rows)
        precise = await cache.list(1,'uniswap_v4',[identifier_from_pool(pools[1])])
        assert [row['id'] for row in precise] == [pools[1]['id']]
        all_protocols = await cache.list(1,'uniswap',[{'tokenA':A,'tokenB':B}])
        assert len(all_protocols) == 4 and {row['protocol'] for row in all_protocols} == {'v3','v4'}
        # A synthetic canonical-history/generation replacement cannot turn
        # stale identity hints into pool/catalog authority.
        await registry.observe_generation('replacement-fork')
        registry.inventory.clear()
        rpc.v4_states = {entry['id']:{'price':0,'tick':0,'liquidity':0} for entry in pools}
        rpc.reads.completed.clear()
        absent = await cache.list(1,'uniswap_v4',[{'tokenA':A,'tokenB':B}])
        assert len(absent) == 3 and all(not row['exists'] for row in absent)
        assert all(entry['id'] not in registry.inventory for entry in pools)
        assert (await producer.catalog())['entries'] == []
        print(json.dumps({'stage':stage,'rpc':'synthetic canonical contract supplier',
            'legacyRowExact':True,'v4Identities':3,'spacingHooksCollisions':False,
            'singletonBalancesAbsent':True,'staleHintsDoNotCreateCatalogAuthority':True}))
    finally:
        await registry.close()
        await database.close()


if __name__ == '__main__': asyncio.run(run(sys.argv[1]))
