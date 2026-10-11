"""Actual Node/Python indexed assets and dashboard SQL on disposable PostgreSQL."""
import asyncio
import json
import os
from pathlib import Path
import subprocess

from cybergold_candidate.holder_projection import HolderProjection
from cybergold_candidate.indexer_recovery_reads import RecoveryStateReads
from cybergold_candidate.dashboard_builder import DashboardReads

ROOT = Path(__file__).parents[2]
CORE, OTHER = '0x' + '1' * 40, '0x' + '9' * 40
END = 1790812800123
NODE = '''
import {query} from './src/server/onchain-indexer/db.ts';
import {readIndexedRecoveryAssets,readIndexedReserveAssets} from './src/server/onchain-indexer/recoverySharePersistence.ts';
import {retainedDashboard} from './python-candidate/tests/retained_dashboard.ts';
const x=JSON.parse(process.argv[1]);const config={chainId:4600n,coreAddress:x.core};
const helper=retainedDashboard({query});let result,error;
try{
 if(x.domain==='assets')result=await (x.event==='RecoveryActivated'?readIndexedRecoveryAssets:readIndexedReserveAssets)(config,BigInt(x.block),query);
 if(x.domain==='amount')result=(await helper.amount(config,x.event,x.core,x.argument,new Date(x.start),new Date(x.end))).map(row=>({block_timestamp_ms:row.block_timestamp.getTime(),tx_hash:row.tx_hash,amount_raw:row.amount_raw}));
 if(x.domain==='transfer')result=(await helper.transfers(config,new Date(x.start),new Date(x.end))).map(row=>({block_timestamp_ms:row.block_timestamp.getTime(),tx_hash:row.tx_hash,amount_raw:row.amount_raw}));
 if(x.domain==='latest')result=await helper.latest(config,helper.groups()[x.category]);
}catch(failure){error=failure.message;}
console.log(JSON.stringify({result:result??null,error:error??null}));await globalThis.__cybergoldDashboardPgPool?.end();
'''


async def qualify(pool, dsn):
    store = HolderProjection(pool, {'chainId': 4600, 'coreAddress': CORE})
    recovery = RecoveryStateReads({'chainId': 4600, 'coreAddress': CORE}, None, store)
    dashboard = DashboardReads({'chainId': 4600, 'coreAddress': CORE}, None, store)
    async def insert(event, block, timestamp, payload, *, core=CORE, chain=4600):
        await store.execute('''INSERT INTO onchain_event_logs
            (chain_id,contract_address,event_name,block_number,tx_hash,log_index,block_timestamp,payload)
            VALUES (%s,%s,%s,%s,%s,%s,'epoch'::timestamptz + %s * INTERVAL '1 millisecond',%s::jsonb)''',
            (chain, core, event, block, '0x' + f'{block + chain:064x}', block, timestamp, json.dumps(payload)))
    async def check(input):
        expected = json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node', '--env-file=tests/fixture.env', '--import', 'tsx', '--input-type=module', '-e', NODE, json.dumps({**input, 'core': CORE})],
            cwd=ROOT, env={**os.environ, 'TZ': 'UTC', 'DATABASE_URL': dsn}, text=True))
        result = error = None
        try:
            if input['domain'] == 'assets':
                result = await recovery.indexed_assets(input['event'], input['block'])
            elif input['domain'] in ('amount', 'transfer'):
                result = await dashboard.amount_logs(input.get('event', 'Transfer'), CORE, input.get('argument', 'value'), input['start'], input['end'])
            else:
                result = await dashboard.latest(input['category'])
        except Exception as failure:
            error = str(failure)
        assert {'result': result, 'error': error} == expected, (input, result, error, expected)
    for event in ('RecoveryActivated', 'ReserveLifecycleChanged'):
        for index, payload in enumerate([{'args': {'asset': '0x' + '3' * 40}}, {'args': {'asset': '0x' + '2' * 40}},
            {'args': {'asset': '0x' + '3' * 40}}, {'args': {'asset': 'invalid'}}, None, {'args': []}]):
            await insert(event, (100 if event == 'RecoveryActivated' else 200) + index, END, payload)
        await insert(event, 400 if event == 'RecoveryActivated' else 401, END, {'args': {'asset': OTHER}}, core=OTHER)
        await insert(event, 500 if event == 'RecoveryActivated' else 501, END, {'args': {'asset': OTHER}}, chain=1)
        for block in (99, 202, 999):
            await check({'domain': 'assets', 'event': event, 'block': block})
    for event, argument, base in [('Issued', 'grossCygldOut', 600), ('Redeemed', 'netCygldIn', 700), ('Transfer', 'value', 800)]:
        for index, offset in enumerate([-1001, -1000, -999, -1, 0, 1]):
            await insert(event, base + index, END + offset, {'args': {argument: str(2**220 + index)}})
        await check({'domain': 'transfer' if event == 'Transfer' else 'amount', 'event': event,
            'argument': argument, 'start': END-1000, 'end': END})
    await check({'domain': 'latest', 'category': 'logic'})
    await insert('DiamondCut', 900, END, {})
    await insert('IssuanceFeePpmUpdated', 901, END-999, {})
    await insert('BasketConfigured', 902, END-100, {})
    await check({'domain': 'latest', 'category': 'logic'})
    await check({'domain': 'latest', 'category': 'parameter'})
    # The retained reader's existing 100000-row limit reports its own ordinary
    # error. This adds no CI/release or operational authorization predicate.
    await store.execute('''INSERT INTO onchain_event_logs
        (chain_id,contract_address,event_name,block_number,tx_hash,log_index,block_timestamp,payload)
        SELECT 4600,%s,'Issued',10000+i,'0x'||LPAD(to_hex(10000+i),64,'0'),i,
            'epoch'::timestamptz + %s * INTERVAL '1 millisecond','{"args":{"grossCygldOut":"1"}}'::jsonb
        FROM generate_series(1,100001) i''', (CORE, END))
    await check({'domain': 'amount', 'event': 'Issued', 'argument': 'grossCygldOut', 'start': END, 'end': END})
    await store.execute("UPDATE onchain_event_logs SET event_name='Transfer' WHERE chain_id=4600 AND block_number>10000", ())
    await check({'domain': 'transfer', 'start': END, 'end': END})
    return {'indexedRecoveryReserveAssetNativeComparisons': 6, 'dashboardNativeSqlComparisons': 8,
        'indexedAssetsBoundedBySnapshotAndNamespace': True, 'dashboardSqlTimeBoundsOrderingAndWideValuesMatch': True,
        'dashboardExistingLogLimitMatchesNode': True}
