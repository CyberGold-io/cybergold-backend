"""Native Node/Python completion comparison across legacy projection retirement."""
import asyncio
import json
import os
from pathlib import Path
import subprocess

from cybergold_candidate import snapshot_refresh

ROOT = Path(__file__).parents[2]
CORE, HOLDER, ZERO = '0x' + '6' * 40, '0x' + '7' * 40, '0x' + '0' * 40
HASH, OLD_HASH = '0x' + 'a' * 64, '0x' + 'b' * 64
TABLES = ['onchain_sync_state', 'onchain_event_logs', 'onchain_recovery_share_balances',
    'onchain_recovery_share_balances_v2', 'onchain_read_model_snapshots']
NODE = '''
import {query,withTransaction} from './src/server/onchain-indexer/db.ts';
import {retainedRefresh} from './python-candidate/tests/retained_snapshot_refresh.ts';
const x=JSON.parse(process.argv[1]);let headers=0;const calls=[];
const refresh=retainedRefresh({recoveryQuery:query,recoveryTransaction:withTransaction,
 readRecoverySnapshot:async()=>{calls.push('recovery');return null;},
 buildOnchainDashboardSummary:async()=>{calls.push('dashboard');return {enabled:true,fixture:'dashboard'};},
 setSyncState:async(config,key,value,runQuery)=>{await runQuery(`INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
  VALUES($1,$2,$3,$4) ON CONFLICT(chain_id,contract_address,state_key) DO UPDATE SET state_value=EXCLUDED.state_value`,[config.chainId.toString(),config.coreAddress,key,value]);}});
const client={getBlock:async(value)=>{calls.push({block:value.blockHash??value.blockNumber.toString()});headers++;
 const previous=value.blockNumber!==undefined;
 return {number:previous?(x.mode==='checkpoint-wrong-number'?101n:102n):x.mode==='anchor-wrong-number'?104n:103n,
  hash:previous?x.oldHash:x.mode==='anchor-changed-after'&&headers===2?'0x'+'c'.repeat(64):x.hash};}};
let error;try{await refresh({chainId:4800n,coreAddress:x.core,finalizedSnapshotMulticall:x.mode==='multicall',recoveryShareV2:x.mode!=='legacy'},
 {blockNumber:103n,blockHash:x.mode==='legacy'?null:x.hash,profile:x.mode==='missing-profile'?null:'fixture-profile'},client);}catch(failure){error=failure.message;}
console.log(JSON.stringify({error:error??null,calls}));await globalThis.__cybergoldDashboardPgPool?.end();
'''


async def qualify(pool, dsn):
    config = {'chainId': 4800, 'coreAddress': CORE, 'governanceAddress': None}
    async def seed(mode):
        async with pool.connection() as connection:
            for table in TABLES:
                await connection.execute('DELETE FROM ' + table + ' WHERE chain_id=4800')
            await connection.execute('''INSERT INTO onchain_event_logs
                (chain_id,contract_address,event_name,block_number,tx_hash,log_index,block_timestamp,payload)
                VALUES(4800,%s,'TransferSingle',100,'snapshot-refresh-transfer',0,'2026-10-01T00:00:00Z',%s::jsonb)''',
                (CORE, json.dumps({'args': {'operator': HOLDER, 'from': ZERO, 'to': HOLDER, 'id': '1', 'value': str(2**200)}})))
            await connection.execute('''INSERT INTO onchain_recovery_share_balances
                (chain_id,contract_address,share_id,holder_address,balance_raw) VALUES(4800,%s,'1',%s,'9')''', (CORE, HOLDER))
            if mode in ('incremental', 'checkpoint-wrong-number'):
                for key, value in [('recovery_share_v2_version', '1'), ('recovery_share_v2_block', '102'),
                    ('recovery_share_v2_block_hash', OLD_HASH), ('recovery_share_v2_profile', 'fixture-profile')]:
                    await connection.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
                        VALUES(4800,%s,%s,%s)''', (CORE, key, value))
                await connection.execute('''INSERT INTO onchain_recovery_share_balances_v2
                    (chain_id,contract_address,share_id,holder_address,balance_raw) VALUES(4800,%s,'1',%s,%s)''', (CORE, HOLDER, str(2**200)))
    async def view():
        result = {}
        async with pool.connection() as connection:
            for table in TABLES:
                result[table] = (await (await connection.execute("SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'updated_at'-'created_at' AS value FROM " + table + ' t WHERE chain_id=4800) data')).fetchone())['rows']
        return result
    original_recovery, original_dashboard = snapshot_refresh.RecoveryStateReads, snapshot_refresh.DashboardReads
    try:
        for mode in ['normal', 'legacy', 'multicall', 'incremental', 'checkpoint-wrong-number', 'missing-profile', 'anchor-wrong-number', 'anchor-changed-after']:
            await seed(mode)
            expected = json.loads(await asyncio.to_thread(subprocess.check_output,
                ['node', '--env-file=tests/fixture.env', '--import', 'tsx', '--input-type=module', '-e', NODE,
                    json.dumps({'mode': mode, 'core': CORE, 'hash': HASH, 'oldHash': OLD_HASH})],
                cwd=ROOT, env={**os.environ, 'TZ': 'UTC', 'DATABASE_URL': dsn}, text=True))
            node_rows = await view()
            await seed(mode)
            before = await view()
            calls, headers = [], 0
            class Recovery:
                def __init__(self, *args): pass
                async def snapshot(self, *args):
                    calls.append('recovery'); return None
            class Dashboard:
                def __init__(self, *args): pass
                async def summary(self, *args, **kwargs):
                    calls.append('dashboard'); return {'enabled': True, 'fixture': 'dashboard'}
            class Client:
                async def block(self, number=None, *, block_hash=None):
                    nonlocal headers
                    calls.append({'block': block_hash or str(number)}); headers += 1
                    previous = number is not None
                    return {'number': 101 if mode == 'checkpoint-wrong-number' and previous else 102 if previous else 104 if mode == 'anchor-wrong-number' else 103,
                        'hash': OLD_HASH if previous else '0x' + 'c' * 64 if mode == 'anchor-changed-after' and headers == 2 else HASH}
            snapshot_refresh.RecoveryStateReads, snapshot_refresh.DashboardReads = Recovery, Dashboard
            error = None
            try:
                await snapshot_refresh.refresh_snapshot({**config, 'finalizedSnapshotMulticall': mode == 'multicall', 'recoveryShareV2': mode != 'legacy'},
                    {'blockNumber': 103, 'blockHash': None if mode == 'legacy' else HASH, 'profile': None if mode == 'missing-profile' else 'fixture-profile'}, Client(), pool)
            except Exception as failure:
                error = str(failure)
            assert {'error': error, 'calls': calls} == expected, (mode, error, calls, expected)
            actual = await view()
            legacy = 'onchain_recovery_share_balances'
            # The historical Node oracle still writes the retired projection.
            # Compare every supported model and assert Python leaves legacy rows
            # untouched, rather than changing that oracle to hide the difference.
            assert actual[legacy] == before[legacy], (mode, actual[legacy], before[legacy])
            assert {key: value for key, value in actual.items() if key != legacy} == {
                key: value for key, value in node_rows.items() if key != legacy}, (mode, actual, node_rows)
            if error is not None:
                assert await view() == before, mode
        return {'nativeSnapshotRefreshComparisons': 8, 'nativeSnapshotV2ModelsAtomic': True,
            'nativeSnapshotLegacyProjectionUntouched': True, 'nativeSnapshotAnchorAndPreviousCheckpointMatchNode': True}
    finally:
        snapshot_refresh.RecoveryStateReads, snapshot_refresh.DashboardReads = original_recovery, original_dashboard
