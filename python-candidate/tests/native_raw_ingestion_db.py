"""Actual retained ingestion coordination, counters and DB interoperability."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
from cybergold_candidate.raw_ingestion import RawJournal
from cybergold_candidate.reconciliation_receipt import RpcCounter

ROOT=Path(__file__).parents[2]
ADDRESS='0x'+'4'*40
NODE='''
import {query} from './src/server/onchain-indexer/db.ts';
import {ingestAddressScopedRawLogs,prepareRawJournalReplayCoverage,readRawJournalCoverage} from './src/server/onchain-indexer/rawLogJournal.ts';
import {createIndexerRpcRequestCounter} from './src/server/onchain-indexer/rpcRequestInstrumentation.ts';
const x=JSON.parse(process.argv[1]);const calls=[];const counter=createIndexerRpcRequestCounter();let result,error;
const hash=block=>'0x'+block.toString(16).padStart(64,'0');
const readBlockHeader=async block=>{calls.push('header:'+block);return {hash:hash(block),timestamp:x.mode==='bad-time'?8640000000001n:1000n+block};};
const requestLogs=async range=>{
 calls.push('logs:'+range.fromBlock+'-'+range.toBlock);
 if(x.mode==='unapproved'||x.mode==='one-block-failure'||['split','duplicate-adaptive'].includes(x.mode)&&range.fromBlock!==range.toBlock)throw new Error('fixture range failure');
 if(x.mode==='empty')return [];
 const logs=[];for(let block=range.fromBlock;block<=range.toBlock;block++)logs.push({address:x.mode==='bad-address'?'0x'+'5'.repeat(40):x.address,
  blockNumber:'0x'+block.toString(16),blockHash:x.mode==='bad-hash'?'0x'+'f'.repeat(64):hash(block),
  transactionHash:x.mode==='duplicate-adaptive'?hash(999n):hash(block+1000n),logIndex:'0x0',topics:[],data:'0x'});
 if(x.mode==='conflicting-duplicate')logs.push({...logs[0],data:'0x11'});
 return logs.reverse();
};
try{
 result=await ingestAddressScopedRawLogs({chainId:4300n,address:x.address,authoritativeStartBlock:100n,
  fromBlock:100n,toBlock:x.mode==='one-block-failure'?100n:103n,journalVersion:'1',requestCounter:counter,requestSource:'safe-address',
  requestLogs,readBlockHeader,shouldSplitRequestFailure:()=>x.mode!=='unapproved'});
}catch(failure){error=failure.message;}
let replay,replayError;
try{replay=await prepareRawJournalReplayCoverage({enabled:true,chainId:4300n,address:x.address,expectedVersion:'1',
 requiredStartBlock:100n,maximumBlock:103n,readBlockHeader});}catch(failure){replayError=failure.message;}
const rows=(await query("SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'chain_id'-'updated_at'-'created_at' AS value FROM onchain_raw_logs t WHERE chain_id=4300) data")).rows[0].rows;
console.log(JSON.stringify({result:result??null,error:error??null,replay:replay??null,replayError:replayError??null,
 coverage:await readRawJournalCoverage({chainId:4300n,address:x.address,expectedVersion:'1'}),calls,counts:counter.snapshot(),rows},(_key,value)=>typeof value==='bigint'?value.toString():value));
await globalThis.__cybergoldDashboardPgPool?.end();
'''

async def qualify(pool,dsn):
    journal=RawJournal(pool,4301,ADDRESS,'1');comparisons=0
    for mode in ['normal','empty','split','unapproved','one-block-failure','bad-time','bad-address','bad-hash','conflicting-duplicate','duplicate-adaptive']:
        async with pool.connection() as connection:
            for table in ['onchain_raw_logs','onchain_sync_state']:await connection.execute('DELETE FROM '+table+' WHERE chain_id IN (4300,4301)')
        expected=json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',NODE,json.dumps({'mode':mode,'address':ADDRESS})],
            cwd=ROOT,env={**os.environ,'TZ':'UTC','DATABASE_URL':dsn},text=True))
        calls=[];counter=RpcCounter();result=error=None;comparisons+=1
        def block_hash(number):return '0x'+f'{number:064x}'
        async def header(number):
            calls.append('header:'+str(number));return {'hash':block_hash(number),'timestamp':8640000000001 if mode=='bad-time' else 1000+number}
        async def request(range):
            calls.append('logs:'+str(range['fromBlock'])+'-'+str(range['toBlock']))
            if mode in ['unapproved','one-block-failure'] or mode in ['split','duplicate-adaptive'] and range['fromBlock']!=range['toBlock']:
                raise RuntimeError('fixture range failure')
            if mode=='empty':return []
            logs=[{'address':'0x'+'5'*40 if mode=='bad-address' else ADDRESS,'blockNumber':hex(block),
                'blockHash':'0x'+'f'*64 if mode=='bad-hash' else block_hash(block),
                'transactionHash':block_hash(999 if mode=='duplicate-adaptive' else block+1000),'logIndex':'0x0','topics':[],'data':'0x'}
                for block in range_values(range)]
            if mode=='conflicting-duplicate':logs.append({**logs[0],'data':'0x11'})
            return list(reversed(logs))
        def range_values(value):return range(value['fromBlock'],value['toBlock']+1)
        try:result=await journal.ingest(100,100,100 if mode=='one-block-failure' else 103,counter,'safe-address',request,header,lambda _:mode!='unapproved')
        except Exception as failure:error=str(failure)
        replay=replay_error=None
        try:replay=await journal.prepare_replay(True,100,103,header)
        except Exception as failure:replay_error=str(failure)
        def wire(value):
            if isinstance(value,dict):return {key:str(item) if key in ['blockNumber','blockTimestampSeconds','startBlock','cursorBlock'] and type(item) is int else wire(item) for key,item in value.items()}
            if isinstance(value,list):return [wire(item) for item in value]
            return value
        actual={'result':wire(result),'error':error,'replay':wire(replay),'replayError':replay_error,'coverage':wire(await journal.coverage()),'calls':calls,'counts':counter.snapshot()}
        async with pool.connection() as connection:
            actual['rows']=(await (await connection.execute("SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'chain_id'-'updated_at'-'created_at' AS value FROM onchain_raw_logs t WHERE chain_id=4301) data")).fetchone())['rows']
        assert actual==expected,(mode,next((key for key in actual if actual[key]!=expected[key]),None),actual,expected)
    return {'rawIngestionOperationsCompared':comparisons,'rawNativeRangeCoverageCountersAndReplayMatchNode':True,
        'rawNativeApprovedSubdivisionAndFailureMatchNode':True}
