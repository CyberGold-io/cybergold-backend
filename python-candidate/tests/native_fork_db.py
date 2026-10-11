"""Fork invalidation parity on the existing disposable PostgreSQL schema."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
from cybergold_candidate.fork_recovery import apply_generation,prepare_generation,mark_ready

ROOT=Path(__file__).parents[2]
CORE='0x'+'c'*40
SAFE='0x'+'d'*40
HASH='0x'+'1'*64
TABLES=['onchain_sync_state','onchain_event_logs','onchain_raw_logs','onchain_token_balances',
    'onchain_holder_balance_deltas','onchain_recovery_share_balances','onchain_recovery_share_balances_v2',
    'onchain_read_model_snapshots','quote_pool_cache','governance_owner_aliases','governance_owner_alias_auth_nonces','onchain_api_rate_limits']
# Read content only; timestamps do not affect fork invalidation or isolation.
VIEW="SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'updated_at'-'created_at' AS value FROM {table} t) data"
NODE='''
import {query,withTransaction} from './src/server/onchain-indexer/db.ts';
import {applySandboxForkGeneration,markSandboxForkGenerationReady,readSandboxForkGeneration} from './src/server/onchain-indexer/forkGenerationRecovery.ts';
const input=JSON.parse(process.argv[1]);const anchor=value=>({...value,forkBlock:BigInt(value.forkBlock)});
const rolled=new Error('fixture rollback');let result;let view;let error;
try{await withTransaction(async execute=>{
 result=await applySandboxForkGeneration({execute,coreAddress:input.core,previous:anchor(input.previous),current:anchor(input.current),
  deploymentStartBlock:100n,currentHashAtPreviousForkBlock:input.commonHash});
 await markSandboxForkGenerationReady({execute,coreAddress:input.core,reachedBlock:1200n});
 const stored=await readSandboxForkGeneration(execute,input.core);view={};
 for(const table of input.tables)view[table]=(await execute(input.view.replace('{table}',table))).rows[0].rows;
 result={result,stored};throw rolled;
});}catch(failure){if(failure!==rolled)error=failure.message;}
console.log(JSON.stringify(error?{error}:{result,view},(_key,value)=>typeof value==='bigint'?value.toString():value));
await globalThis.__cybergoldDashboardPgPool?.end();
'''

class RollbackFixture(Exception):pass

async def qualify(pool,dsn):
    previous={'generation':'native-old','forkBlock':1000,'forkBlockHash':HASH}
    current={'generation':'native-next','forkBlock':1200,'forkBlockHash':'0x'+'2'*64}
    async with pool.connection() as connection:
        async with connection.transaction():
            await prepare_generation(connection,CORE,previous)
            for address,key,value in [(CORE,'last_scanned_block','900'),(SAFE,'safe_execution_last_scanned_block','890'),
                (CORE,'raw_log_last_scanned_block','1100'),(CORE,'raw_log_start_block','100'),(CORE,'raw_log_journal_version','1'),
                (CORE,'finalized_projection_block_hash',HASH),(SAFE,'safe_execution_last_scanned_block_hash',HASH),
                (CORE,'raw_log_last_scanned_block_hash',HASH)]:
                await connection.execute('INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value) VALUES (31338,%s,%s,%s)',(address,key,value))
            for chain in [31338,1]:
                for block in [900,1100]:
                    tx='0x'+f'{block:064x}'
                    await connection.execute("INSERT INTO onchain_event_logs(chain_id,contract_address,event_name,block_number,block_hash,tx_hash,log_index,block_timestamp,payload) VALUES (%s,%s,'fixture',%s,%s,%s,0,NOW(),'{}')",(chain,CORE,block,HASH,tx))
                    await connection.execute("INSERT INTO onchain_raw_logs(chain_id,contract_address,block_number,block_hash,tx_hash,log_index,topics,data,block_timestamp_seconds) VALUES (%s,%s,%s,%s,%s,0,'[]','0x',1000)",(chain,CORE,block,HASH,tx))
                    await connection.execute("INSERT INTO onchain_holder_balance_deltas(chain_id,contract_address,block_number,tx_hash,log_index,holder_address,delta_raw) VALUES (%s,%s,%s,%s,0,%s,'10')",(chain,CORE,block,tx,SAFE))
                await connection.execute("INSERT INTO onchain_token_balances(chain_id,contract_address,holder_address,balance_raw) VALUES (%s,%s,%s,'10')",(chain,CORE,SAFE))
                for table in ['onchain_recovery_share_balances','onchain_recovery_share_balances_v2']:
                    await connection.execute(f"INSERT INTO {table}(chain_id,contract_address,share_id,holder_address,balance_raw) VALUES (%s,%s,'1',%s,'10')",(chain,CORE,SAFE))
                await connection.execute("INSERT INTO onchain_read_model_snapshots(chain_id,contract_address,model_key,block_number,payload) VALUES (%s,%s,'fork-fixture',1100,'{}')",(chain,CORE))
                await connection.execute("INSERT INTO quote_pool_cache(chain_id,dex,token0,token1,fee,exists) VALUES (%s,'fork-fixture',%s,%s,500,true)",(chain,CORE,SAFE))
    async def view(connection):
        result={}
        for table in TABLES:result[table]=(await (await connection.execute(VIEW.format(table=table))).fetchone())['rows']
        return result
    async def retained(common):
        data={'core':CORE,'previous':previous,'current':current,'commonHash':common,'tables':TABLES,'view':VIEW}
        return json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',NODE,json.dumps(data)],
            cwd=ROOT,env={**os.environ,'DATABASE_URL':dsn},text=True))
    cases=[('reuse-prefix','900','1100',HASH),('replay-prefix','1100','1100',HASH),
        ('full-replay','900','1100','0x'+'f'*64),('failure-after-deletes','900','invalid',HASH)]
    for name,projection,raw,common in cases:
        async with pool.connection() as connection:
            await connection.execute("UPDATE onchain_sync_state SET state_value=%s WHERE chain_id=31338 AND state_key='last_scanned_block'",(projection,))
            await connection.execute("UPDATE onchain_sync_state SET state_value=%s WHERE chain_id=31338 AND contract_address=%s AND state_key='raw_log_last_scanned_block'",(raw,CORE))
        node_result=await retained(common)
        async with pool.connection() as connection:
            before=await view(connection)
            try:
                async with connection.transaction():
                    result=await apply_generation(connection,CORE,previous,current,100,common)
                    await mark_ready(connection,CORE,1200)
                    from cybergold_candidate.fork_recovery import read_generation
                    stored=await read_generation(connection,CORE)
                    actual={'result':{'result':result,'stored':stored},'view':await view(connection)}
                    # Only planner/anchor BigInts are decimal strings on the Node wire.
                    actual['result']['stored']['anchor']['forkBlock']=str(stored['anchor']['forkBlock'])
                    for key in ('invalidateFrom','retainedThrough'):
                        number=actual['result']['result']['plan'][key]
                        if number is not None:actual['result']['result']['plan'][key]=str(number)
                    assert actual==node_result,(name,actual,node_result)
                    for table in TABLES:
                        assert [row for row in actual['view'][table] if row.get('chain_id')==1]==[row for row in before[table] if row.get('chain_id')==1],(name,table)
                    for table in ['governance_owner_aliases','governance_owner_alias_auth_nonces','onchain_api_rate_limits']:assert actual['view'][table]==before[table]
                    raise RollbackFixture()
            except RollbackFixture:pass
            except ValueError as error:
                assert name=='failure-after-deletes' and node_result=={'error':str(error)}
            assert await view(connection)==before,(name,'transaction rollback')
    return {'forkNativeNodePythonInvalidationMatches':True,'forkReuseReplayAndDivergence':True,
        'forkMainnetAliasesNoncesAndQuotasPreserved':True,'forkFailedInvalidationAtomic':True}
