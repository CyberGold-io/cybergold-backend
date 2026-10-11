"""Native retained holder/identity parity over two disposable namespaces."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
from cybergold_candidate.holder_projection import HolderProjection
from cybergold_candidate.projection_identity import ensure_identity
from cybergold_candidate.event_projection import EventProjection

ROOT=Path(__file__).parents[2]
CORE='0x'+'8'*40
A='0x'+'9'*40
B='0x'+'6'*40
OLD='0x'+'7'*40
ZERO='0x'+'0'*40
TABLES=['onchain_sync_state','onchain_token_balances','onchain_holder_balance_deltas',
    'onchain_recovery_share_balances','onchain_recovery_share_balances_v2',
    'onchain_read_model_snapshots','onchain_event_logs','onchain_raw_logs']
VIEW="SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'chain_id'-'updated_at'-'created_at' AS value FROM {table} t WHERE chain_id={chain}) data"
NODE='''
import {query,withTransaction} from './src/server/onchain-indexer/db.ts';
import {retainedProjection} from './python-candidate/tests/retained_projection.ts';
const x=JSON.parse(process.argv[1]);const config={chainId:4100n,coreAddress:x.core,governanceAddress:x.governance};
const holder=retainedProjection(query,withTransaction);let result;let error;
try{
 if(x.action==='persist')result=await holder.persist(config,x.logs.map(entry=>({...entry,blockNumber:BigInt(entry.blockNumber)})),{updateHolderCache:x.update});
 if(x.action==='deleteFrom')result=await holder.deleteFrom(config,BigInt(x.block),x.additional);
 if(x.action==='identity')result=await holder.identity(config);
 if(x.action==='rebuild')result=await holder.rebuild(config,x.retention===null?undefined:BigInt(x.retention));
 if(x.action==='rewind')result=await holder.rewind(config,BigInt(x.block));
 if(x.action==='prune')result=await holder.prune(config,BigInt(x.block));
 if(x.action==='snapshots')result=await holder.snapshots(config,BigInt(x.block));
 if(x.action==='delta')result=await holder.delta(config,x.address,BigInt(x.amount),x.meta?{recordDelta:{...x.meta,blockNumber:BigInt(x.meta.blockNumber)}}:undefined);
 if(x.action==='transfer')result=await holder.transfer(config,{...x.transfer,value:BigInt(x.transfer.value)},{...x.meta,blockNumber:BigInt(x.meta.blockNumber)});
 if(x.action==='clear')result=await holder.clear(config);
 if(x.action==='entry')result=await holder.entry(config,x.key);
}catch(failure){error=failure.message;}
const view={};for(const table of x.tables)view[table]=(await query(x.view.replace('{table}',table).replace('{chain}','4100'))).rows[0].rows;
console.log(JSON.stringify({result:result??null,error:error??null,view}));await globalThis.__cybergoldDashboardPgPool?.end();
'''

async def qualify(pool,dsn):
    config={'chainId':4101,'coreAddress':CORE,'governanceAddress':None};holder=HolderProjection(pool,config)
    # The retained Linux image uses UTC, including pg Date serialization.
    async def native(input):
        value={**input,'core':CORE,'governance':config['governanceAddress'],'tables':TABLES,'view':VIEW}
        return json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',NODE,json.dumps(value)],
            cwd=ROOT,env={**os.environ,'TZ':'UTC','DATABASE_URL':dsn},text=True))
    compared=0
    async def check(input):
        nonlocal compared
        compared+=1
        node=await native(input);result=error=None
        try:
            action=input['action']
            if action=='persist':result=await EventProjection(pool,config).persist(input['logs'],input['update'])
            elif action=='deleteFrom':result=await EventProjection(pool,config).delete_from(input['block'],input['additional'])
            elif action=='identity':result=await ensure_identity(pool,config)
            elif action=='rebuild':result=await holder.rebuild(input['retention'])
            elif action=='rewind':result=await holder.rewind(input['block'])
            elif action=='prune':result=await holder.prune_deltas(input['block'])
            elif action=='snapshots':result=await holder.prune_snapshots(input['block'])
            elif action=='delta':result=await holder.apply_delta(input['address'],int(input['amount']),input.get('meta'))
            elif action=='transfer':result=await holder.apply_transfer({**input['transfer'],'value':int(input['transfer']['value'])},input['meta'])
            elif action=='clear':result=await holder.clear()
            elif action=='entry':result=await holder.state_entry(input['key'])
        except Exception as failure:error=str(failure)
        assert (result,error)==(node['result'],node['error']),(input,result,error,node)
        async with pool.connection() as connection:
            for table in TABLES:
                actual=(await (await connection.execute(VIEW.format(table=table,chain=4101))).fetchone())['rows']
                assert actual==node['view'][table],(input,table,next(((a,b) for a,b in zip(actual,node['view'][table]) if a!=b),(len(actual),len(node['view'][table]))))
        return result
    async def both(sql,params=()):
        async with pool.connection() as connection:
            for chain in [4100,4101]:await connection.execute(sql,(chain,*params))
    async def state(key,value):
        await both('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value) VALUES (%s,%s,%s,%s)
            ON CONFLICT(chain_id,contract_address,state_key) DO UPDATE SET state_value=EXCLUDED.state_value''',(CORE,key,value))
    assert await check({'action':'identity'}) is True
    huge=2**256-1
    transfers=[(100,ZERO,A,str(huge)),(101,A,B,str(huge//3)),(102,B,ZERO,'2'),(103,B,B,'4')]
    for block,from_address,to,amount in transfers:
        payload=json.dumps({'args':{'from':from_address,'to':to,'value':amount}})
        await both("INSERT INTO onchain_event_logs(chain_id,contract_address,event_name,block_number,tx_hash,log_index,block_timestamp,payload) VALUES (%s,%s,'Transfer',%s,%s,0,'2026-10-01T00:00:00Z',%s::jsonb)",(CORE,block,'0x'+f'{block:064x}',payload))
    await both("INSERT INTO onchain_event_logs(chain_id,contract_address,event_name,block_number,tx_hash,log_index,block_timestamp,payload) VALUES (%s,%s,'Transfer',104,%s,0,'2026-10-01T00:00:00Z','{\"args\":{}}')",(CORE,'0x'+'a'*64))
    await check({'action':'rebuild','retention':101})
    assert await holder.count()==2 and await holder.balance(A)==huge-huge//3
    assert await check({'action':'identity'}) is False
    assert await holder.count()==2
    assert await check({'action':'rewind','block':102}) is True
    await check({'action':'rebuild','retention':None})
    await check({'action':'prune','block':102})
    await state('holder_cache_ready','0');assert await check({'action':'rewind','block':102}) is False
    await state('holder_cache_ready','1')
    await both('DELETE FROM onchain_holder_balance_deltas WHERE chain_id=%s')
    assert await check({'action':'rewind','block':102}) is False
    await check({'action':'delta','address':ZERO,'amount':'10'})
    await check({'action':'delta','address':B,'amount':'-'+str(huge)})
    await state('holder_count','invalid')
    await both("UPDATE onchain_token_balances SET balance_raw='invalid' WHERE chain_id=%s AND holder_address=%s",(A,))
    meta={'blockNumber':120,'txHash':'0x'+'b'*64,'logIndex':0}
    await check({'action':'delta','address':A,'amount':'10','meta':meta})
    await check({'action':'delta','address':A,'amount':'2','meta':meta})
    await check({'action':'transfer','transfer':{'from':A,'to':A,'value':'3'},'meta':meta})
    event={'contractAddress':CORE.upper(),'eventName':'Transfer','blockNumber':130,'blockHash':'0x'+'e'*64,
        'txHash':'0x'+'D'*64,'logIndex':0,'blockTimestampMs':1790812800123,
        'payload':{'args':{'from':ZERO,'to':B,'value':'17'}}}
    before=await holder.balance(B)
    await check({'action':'persist','logs':[event,event],'update':True})
    assert await holder.balance(B)==before+17
    for index,milliseconds in enumerate([0,253402300800123,8640000000000000,-62167219200123]):
        await check({'action':'persist','logs':[{**event,'eventName':'fixture-time','blockNumber':131+index,
            'txHash':'0x'+f'{9000+index:064x}','blockTimestampMs':milliseconds,'payload':{'wide':str(huge),'unicode':'☃'}}],'update':True})
    await check({'action':'persist','logs':[{**event,'txHash':'0x'+'e'*64,'blockNumber':139}],'update':False})
    assert await holder.balance(B)==before+17
    await check({'action':'deleteFrom','block':130,'additional':[B.upper()]})
    for block in [100,105,110]:
        await both("INSERT INTO onchain_read_model_snapshots(chain_id,contract_address,model_key,block_number,payload) VALUES (%s,%s,'holder-fixture',%s,'{}')",(CORE,block))
    await check({'action':'snapshots','block':105})
    await state('state_snapshot_version','1');await check({'action':'identity'})
    await state('raw_journal_version','2');await check({'action':'identity'})
    await state('raw_journal_version','1');await state('dashboard_projection_version','14');await check({'action':'identity'})
    await state('governance_address',OLD);await state('dashboard_projection_governance_address',OLD);await state('last_scanned_block','100')
    await both("INSERT INTO onchain_event_logs(chain_id,contract_address,event_name,block_number,tx_hash,log_index,block_timestamp,payload) VALUES (%s,%s,'old-governance',99,%s,0,'2026-10-01T00:00:00Z','{}')",(OLD,'0x'+'c'*64))
    config['governanceAddress']=B;await check({'action':'identity'})
    assert await holder.state('governance_address')==OLD and await holder.state('dashboard_projection_governance_address')==B
    assert await holder.state('last_scanned_block') is None
    await check({'action':'clear'})
    await state('state-read-fixture','1000000000000000000')
    await both("UPDATE onchain_sync_state SET updated_at='2026-10-01T00:00:00.123456Z' WHERE chain_id=%s AND state_key='state-read-fixture'")
    await check({'action':'entry','key':'state-read-fixture'})
    await check({'action':'entry','key':'missing-state-read-fixture'})
    return {'holderProjectionOperationsCompared':compared,'projectedLogDeduplicationPreservesBalances':True,
        'projectedLogExtendedTimestampsMatchNode':True,'projectedLogPayloadAndNamespaceMatchNode':True,'holderNativeNodePythonProjectionMatches':True,'holderUint256CountsAndUnderflowClamp':True,
        'holderDeltaRewindRebuildAndRetention':True,'holderIncompleteRewindReturnsFalse':True,
        'identityNativeNodePythonWritesMatch':True,'identityLegacyGovernanceAndVersionPreserved':True,
        'identityRawIncompatibilityRollsBack':True,'snapshotPruneRetainsLatestPerModel':True}
