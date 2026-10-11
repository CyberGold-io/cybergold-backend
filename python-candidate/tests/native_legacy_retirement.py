"""BQ4 lifetime replay removal and atomic completion on disposable PostgreSQL.

Run from the repository root with the frozen Python environment and Node/npm
comparison dependencies. Uses a cached postgres:18-alpine image; no live host.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg import sql

from cybergold_candidate.database import Database
from cybergold_candidate import snapshot_refresh
from cybergold_candidate.recovery_persistence import STATE_KEYS
from cybergold_candidate.snapshot_persistence import persist_snapshot, RECOVERY_MODEL, DASHBOARD_MODEL

ROOT = Path(__file__).parents[2]
CORE, HOLDER, ZERO = ('0x' + char * 40 for char in ('6', '7', '0'))
HASH, OLD_HASH = '0x' + 'a' * 64, '0x' + 'b' * 64
CHAIN, PROFILE = 4801, 'fixture-profile'
TABLES = ('onchain_event_logs', 'onchain_sync_state', 'onchain_recovery_share_balances',
    'onchain_recovery_share_balances_v2', 'onchain_read_model_snapshots')


class Recovery:
    def __init__(self, *args): pass
    async def snapshot(self, *args): return None


class Dashboard:
    def __init__(self, *args): pass
    async def summary(self, *args, **kwargs): return {'enabled': True, 'fixture': 'new-dashboard'}


class Client:
    async def block(self, number=None, *, block_hash=None):
        return {'number': 100 if number is not None else 103,
            'hash': OLD_HASH if number is not None else HASH}


class LegacyRetirement(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = 'cybergold-bq4-' + uuid.uuid4().hex[:12]
        subprocess.run(['docker', 'run', '--pull', 'never', '--detach', '--name', cls.container,
            '--publish', '127.0.0.1::5432', '-e', 'POSTGRES_PASSWORD=public-bq4-fixture',
            'postgres:18-alpine'], check=True, stdout=subprocess.DEVNULL)
        cls.addClassCleanup(subprocess.run, ['docker', 'rm', '--force', '--volumes', cls.container],
            check=True, stdout=subprocess.DEVNULL)
        port = subprocess.check_output(['docker', 'port', cls.container, '5432/tcp'], text=True).strip().rsplit(':', 1)[1]
        cls.url = 'postgresql://postgres:public-bq4-fixture@127.0.0.1:' + port + '/postgres'
        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(cls.url): break
            except psycopg.OperationalError:
                if time.monotonic() > deadline: raise
                time.sleep(.1)

    async def asyncSetUp(self):
        name = 'bq4_' + uuid.uuid4().hex[:12]
        with psycopg.connect(self.url, autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        self.dsn = self.url.rsplit('/', 1)[0] + '/' + name
        self.database = Database(self.dsn)
        self.addAsyncCleanup(self.database.close)
        await self.database.ensure_schema()
        self.config = {'chainId': CHAIN, 'coreAddress': CORE, 'governanceAddress': None,
            'finalizedSnapshotMulticall': False, 'recoveryShareV2': True}
        self.snapshot = {'blockNumber': 103, 'blockHash': HASH, 'profile': PROFILE}
        async with self.database.connection() as connection:
            await connection.execute('''INSERT INTO onchain_recovery_share_balances
                (chain_id,contract_address,share_id,holder_address,balance_raw) VALUES(%s,%s,'1',%s,'9')''',
                (CHAIN, CORE, HOLDER))
            for model in (RECOVERY_MODEL, DASHBOARD_MODEL):
                await persist_snapshot(connection, CHAIN, CORE, model, 100, {'fixture': 'previous-complete-model'})

    async def logs(self, count, block=100, prefix='history', amount=0):
        payload = json.dumps({'args': {'operator': HOLDER, 'from': ZERO, 'to': HOLDER,
            'id': '1', 'value': str(amount)}})
        async with self.database.connection() as connection:
            await connection.execute('''INSERT INTO onchain_event_logs
                (chain_id,contract_address,event_name,block_number,tx_hash,log_index,block_timestamp,payload)
                SELECT %s,%s,'TransferSingle',%s,%s||i,0,'2026-10-01T00:00:00Z',%s::jsonb
                FROM generate_series(1,%s) i''', (CHAIN, CORE, block, prefix, payload, count))

    async def checkpoint(self):
        async with self.database.connection() as connection:
            for key, value in zip(STATE_KEYS, ('1', '100', OLD_HASH, PROFILE), strict=True):
                await connection.execute('''INSERT INTO onchain_sync_state
                    (chain_id,contract_address,state_key,state_value) VALUES(%s,%s,%s,%s)''', (CHAIN, CORE, key, value))
            await connection.execute('''INSERT INTO onchain_recovery_share_balances_v2
                (chain_id,contract_address,share_id,holder_address,balance_raw) VALUES(%s,%s,'1',%s,%s)''',
                (CHAIN, CORE, HOLDER, str(2**200)))

    async def view(self):
        result = {}
        async with self.database.connection() as connection:
            for table in TABLES[1:]:
                result[table] = (await (await connection.execute(sql.SQL('''SELECT COALESCE(
                    jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows
                    FROM (SELECT to_jsonb(t)-'updated_at'-'created_at' AS value FROM {} t) data''')
                    .format(sql.Identifier(table)))).fetchone())['rows']
            result['eventCount'] = (await (await connection.execute('SELECT count(*) AS count FROM onchain_event_logs')).fetchone())['count']
        return result

    async def refresh(self):
        with patch.object(snapshot_refresh, 'RecoveryStateReads', Recovery), patch.object(snapshot_refresh, 'DashboardReads', Dashboard):
            await snapshot_refresh.refresh_snapshot(self.config, self.snapshot, Client(), self.database)

    async def test_incremental_snapshot_survives_lifetime_history_above_100000(self):
        await self.logs(100001)
        await self.checkpoint()
        await self.logs(1, 103, 'incremental', 7)
        before = await self.view()
        # Reproduce the exact old failure through the unchanged historical oracle.
        node = '''
import {query,withTransaction} from './src/server/onchain-indexer/db.ts';
import {retainedRefresh} from './python-candidate/tests/retained_snapshot_refresh.ts';
const x=JSON.parse(process.argv[1]);
const refresh=retainedRefresh({recoveryQuery:query,recoveryTransaction:withTransaction,
 readRecoverySnapshot:async()=>null,buildOnchainDashboardSummary:async()=>({enabled:true}),setSyncState:async()=>{}});
const client={getBlock:async(value)=>({number:value.blockNumber??103n,hash:value.blockNumber?x.oldHash:x.hash})};
let error=null;try{await refresh({chainId:4801n,coreAddress:x.core,finalizedSnapshotMulticall:false,recoveryShareV2:true},
 {blockNumber:103n,blockHash:x.hash,profile:x.profile},client);}catch(failure){error=failure.message;}
console.log(JSON.stringify({error}));await globalThis.__cybergoldDashboardPgPool?.end();
'''
        output = await asyncio.to_thread(subprocess.check_output,
            ['node', '--env-file=tests/fixture.env', '--import', 'tsx', '--input-type=module', '-e', node,
                json.dumps({'core': CORE, 'oldHash': OLD_HASH, 'hash': HASH, 'profile': PROFILE})],
            cwd=ROOT, env={**os.environ, 'DATABASE_URL': self.dsn}, text=True)
        self.assertEqual(json.loads(output), {'error': 'Recovery-share replay exceeds 100000 indexed transfer logs'})
        self.assertEqual(await self.view(), before)
        await self.refresh()
        after = await self.view()
        self.assertEqual(after['eventCount'], 100002)
        self.assertEqual(after['onchain_recovery_share_balances'], before['onchain_recovery_share_balances'])
        self.assertEqual(after['onchain_recovery_share_balances_v2'][0]['balance_raw'], str(2**200 + 7))
        self.assertEqual({row['model_key'] for row in after['onchain_read_model_snapshots'] if row['block_number'] == 103},
            {RECOVERY_MODEL, DASHBOARD_MODEL})
        states = {row['state_key']: row['state_value'] for row in after['onchain_sync_state']}
        self.assertEqual(states['recovery_share_v2_block'], '103')
        self.assertEqual(states['finalized_snapshot_block'], '103')

    async def test_non_v2_mode_publishes_models_without_legacy_replay(self):
        await self.logs(100001)
        self.config['recoveryShareV2'] = False
        self.snapshot['blockHash'] = None
        before = await self.view()
        await self.refresh()
        after = await self.view()
        self.assertEqual(after['eventCount'], before['eventCount'])
        self.assertEqual(after['onchain_recovery_share_balances'], before['onchain_recovery_share_balances'])
        self.assertEqual(after['onchain_recovery_share_balances_v2'], [])
        self.assertEqual(len(after['onchain_read_model_snapshots']), 4)

    async def test_failed_dashboard_write_rolls_back_v2_checkpoint_and_models_then_retries(self):
        await self.checkpoint()
        await self.logs(1, 103, 'incremental', 7)
        before = await self.view()
        async with self.database.connection() as connection:
            await connection.execute('''CREATE FUNCTION bq4_fail_dashboard() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.model_key=TG_ARGV[0] AND NEW.block_number=103 THEN
                    RAISE EXCEPTION 'synthetic ordinary dashboard write failure'; END IF;
                RETURN NEW; END $$''')
            await connection.execute(sql.SQL('''CREATE TRIGGER bq4_failure BEFORE INSERT OR UPDATE
                ON onchain_read_model_snapshots FOR EACH ROW EXECUTE FUNCTION bq4_fail_dashboard({})''')
                .format(sql.Literal(DASHBOARD_MODEL)))
        with self.assertRaises(psycopg.Error): await self.refresh()
        self.assertEqual(await self.view(), before)
        async with self.database.connection() as connection:
            await connection.execute('DROP TRIGGER bq4_failure ON onchain_read_model_snapshots')
        await self.refresh()
        after = await self.view()
        self.assertEqual(after['onchain_recovery_share_balances_v2'][0]['balance_raw'], str(2**200 + 7))
        self.assertEqual(len(after['onchain_read_model_snapshots']), 4)

    async def test_v2_full_replay_limit_is_preserved(self):
        await self.logs(100001)
        before = await self.view()
        with self.assertRaisesRegex(ValueError, 'Recovery-share v2 replay exceeds 100000 indexed transfer logs'):
            await self.refresh()
        self.assertEqual(await self.view(), before)

    async def test_v2_incremental_window_limit_is_preserved(self):
        await self.checkpoint()
        await self.logs(100001, 103)
        before = await self.view()
        with self.assertRaisesRegex(ValueError, 'Recovery-share v2 replay exceeds 100000 indexed transfer logs'):
            await self.refresh()
        self.assertEqual(await self.view(), before)

    async def test_retained_snapshot_comparison_preserves_supported_models(self):
        from native_snapshot_refresh_db import qualify
        await qualify(self.database, self.dsn)


if __name__ == '__main__': unittest.main()
