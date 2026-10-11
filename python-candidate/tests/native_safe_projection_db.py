"""Native Safe SQL/cursor interoperability with retained Node functions."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
from cybergold_candidate.safe_projection import SafeProjection,COMMITTED_KEYS

ROOT=Path(__file__).parents[2]
SAFE='0x'+'5'*40
NODE='''
import {query,withTransaction} from './src/server/onchain-indexer/db.ts';
import {retainedSafeProjection} from './python-candidate/tests/retained_safe_projection.ts';
const x=JSON.parse(process.argv[1]);const store=retainedSafeProjection(query,withTransaction);const chain=4200n;
let result,error;
try{
 if(x.action==='version')result=await store.version(chain,x.safe);
 if(x.action==='cursor')result=await store.putCursor(chain,x.safe,BigInt(x.block),x.hash??undefined,x.profile??undefined);
 if(x.action==='delete')result=await store.deleteFrom(chain,x.safe,BigInt(x.block));
 if(x.action==='persist')result=await store.persist(chain,x.safe,x.logs.map(log=>({...log,blockNumber:BigInt(log.blockNumber),timestamp:BigInt(log.timestamp),payment:BigInt(log.payment)})));
}catch(failure){error=failure.message;}
const rows={};
for(const table of ['onchain_event_logs','onchain_sync_state'])rows[table]=(await query(`SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'chain_id'-'updated_at'-'created_at' AS value FROM ${table} t WHERE chain_id=4200) data`)).rows[0].rows;
console.log(JSON.stringify({error:error??null,rows,views:{cursor:await store.cursor(chain,x.safe),hash:await store.hash(chain,x.safe),profile:await store.profile(chain,x.safe),committed:await store.committed(chain,x.safe)}},(_key,value)=>typeof value==='bigint'?value.toString():value));
await globalThis.__cybergoldDashboardPgPool?.end();
'''

async def qualify(pool,dsn):
    store=SafeProjection(pool,4201,SAFE)
    count=0
    async def check(input):
        nonlocal count
        count+=1
        node=json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',NODE,json.dumps({**input,'safe':SAFE})],
            cwd=ROOT,env={**os.environ,'TZ':'UTC','DATABASE_URL':dsn},text=True))
        error=None
        try:
            action=input['action']
            if action=='version':await store.ensure_version()
            if action=='cursor':await store.put_cursor(input['block'],input.get('hash'),input.get('profile'))
            if action=='delete':await store.delete_from(input['block'])
            if action=='persist':await store.persist(input['logs'])
        except Exception as failure:error=str(failure)
        assert error==node['error'],(input,error,node['error'])
        async with pool.connection() as connection:
            for table in ['onchain_event_logs','onchain_sync_state']:
                rows=(await (await connection.execute(f"SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'chain_id'-'updated_at'-'created_at' AS value FROM {table} t WHERE chain_id=4201) data")).fetchone())['rows']
                assert rows==node['rows'][table],(input,table)
        cursor=await store.cursor();committed=await store.committed()
        if committed['blockNumber'] is not None:committed['blockNumber']=str(committed['blockNumber'])
        assert {'cursor':str(cursor) if cursor is not None else None,'hash':await store.cursor_hash(),
            'profile':await store.profile(),'committed':committed}==node['views'],input
    async def put(key,value):
        async with pool.connection() as connection:
            for chain in [4200,4201]:await connection.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
                VALUES (%s,%s,%s,%s) ON CONFLICT(chain_id,contract_address,state_key) DO UPDATE SET state_value=EXCLUDED.state_value''',(chain,SAFE,key,value))
    await check({'action':'version'})
    await check({'action':'cursor','block':100,'hash':'0x'+'A'*64,'profile':'profile'})
    await check({'action':'cursor','block':101,'hash':None,'profile':''})
    log={'eventName':'ExecutionSuccess','safeTxHash':'0x'+'F'*64,'blockNumber':100,'blockHash':'0x'+'c'*64,
        'transactionHash':'0x'+'D'*64,'logIndex':0,'timestamp':1790812800,'payment':str(2**256-1),'topics':[],'data':'0x'}
    # Wire timestamps/payment as strings for lossless Node/Python fixture input.
    await check({'action':'persist','logs':[log]})
    await check({'action':'persist','logs':[{**log,'eventName':'ExecutionFailure','blockNumber':102,'timestamp':1790812801}]})
    await check({'action':'delete','block':101})
    for key,value in zip(COMMITTED_KEYS,['101','0x'+'b'*64,'committed-profile','run-1'],strict=True):await put(key,value)
    await check({'action':'version'})
    await put(COMMITTED_KEYS[0],'invalid');await put('safe_execution_last_scanned_block','invalid');await check({'action':'version'})
    await put('safe_execution_cursor_version','2');await check({'action':'version'})
    return {'safeProjectionOperationsCompared':count,'safeProjectedWritesAndReplacementMatchNode':True,
        'safeCursorOptionalHashProfileAndCommittedReadsMatchNode':True,'safeCursorVersionPreserved':True}
