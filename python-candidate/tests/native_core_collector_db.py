"""Actual retained Core collector versus Python, synthetic RPC and native SQL."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import subprocess

from cybergold_candidate.core_collector import CoreCollector
from cybergold_candidate.completed_state import IDENTITY
from cybergold_candidate.reconciliation_receipt import RpcCounter
from cybergold_candidate.indexer_event_codec import selector
from cybergold_candidate.dashboard_builder import DEFINITIONS

ROOT = Path(__file__).parents[2]
CORE, GOV = '0x' + '4' * 40, '0x' + '5' * 40
TABLES = ['onchain_sync_state','onchain_token_balances','onchain_holder_balance_deltas','onchain_recovery_share_balances',
    'onchain_recovery_share_balances_v2','onchain_read_model_snapshots','onchain_event_logs','onchain_raw_logs']
NODE = '''
import {query,withTransaction} from './src/server/onchain-indexer/db.ts';
import {encodeAbiParameters,encodeEventTopics,parseEventLogs} from 'viem';
import {createIndexerRpcRequestCounter} from './src/server/onchain-indexer/rpcRequestInstrumentation.ts';
import {retainedDashboard} from './python-candidate/tests/retained_dashboard.ts';
import {retainedCore} from './python-candidate/tests/retained_core_collector.ts';
const x=JSON.parse(process.argv[1]),calls=[],stages=[];const definitions=retainedDashboard({}).definitions;
const blockHash=(number)=>'0x'+number.toString(16).padStart(64,'0');
const coreAbi=definitions.core.find(d=>d.name==='Transfer').abi,govAbi=definitions.governance[0].abi;
function log(address,abi,args,number,id){const parameters=abi.inputs.filter(p=>!p.indexed);
 return {address,blockNumber:'0x'+number.toString(16),blockHash:blockHash(number),transactionHash:blockHash(1000+id),
  transactionIndex:'0x0',logIndex:'0x0',removed:false,topics:encodeEventTopics({abi:[abi],eventName:abi.name,args}),
  data:encodeAbiParameters(parameters,parameters.map(p=>args[p.name]))};}
const raw=[log(x.core,coreAbi,{from:'0x'+'0'.repeat(40),to:'0x'+'6'.repeat(40),value:2n**200n},100,1)];
if(x.mode==='governance')raw.push(log(x.governance,govAbi,{trustedCore:x.core},101,2));
if(x.mode==='unknown')raw.push({...raw[0],topics:['0x'+'f'.repeat(64)],transactionHash:blockHash(1003),blockNumber:'0x65',blockHash:blockHash(101)});
if(x.mode==='known-malformed')raw[0].data='0x01';
if(x.mode==='log-hash-mismatch')raw[0].blockHash=blockHash(99);
function selected(address,from,to,topic){return raw.filter(r=>r.address===address&&BigInt(r.blockNumber)>=from&&BigInt(r.blockNumber)<=to&&(!topic||r.topics[0]===topic));}
const client={
 getBlock:async(value)=>{const number=value.blockNumber??103n;calls.push(['block',value.blockTag??value.blockHash??number.toString()]);
  return {number:x.mode==='wrong-header-number'&&value.blockNumber!==undefined?number+1n:number,hash:blockHash(number),timestamp:1000n+number};},
 getBlockNumber:async()=>{calls.push(['head']);return 103n;},
 getCode:async(value)=>{calls.push(['code',value.blockNumber.toString()]);return value.blockNumber>=100n?'0x01':'0x';},
 getLogs:async(value)=>{const topic=(await import('viem')).toEventSelector(value.event);calls.push(['logs',value.address,value.fromBlock.toString(),value.toBlock.toString(),topic]);return parseEventLogs({abi:[value.event],logs:selected(value.address,value.fromBlock,value.toBlock,topic),strict:false});},
 request:async(value)=>{const p=value.params[0];calls.push(['logs',p.address,BigInt(p.fromBlock).toString(),BigInt(p.toBlock).toString(),null]);return selected(p.address,BigInt(p.fromBlock),BigInt(p.toBlock),null);}};
const finalized=!['legacy','detect-start','supplied-legacy'].includes(x.mode),scoped=!['legacy','legacy-events-finalized','detect-start'].includes(x.mode);
const config={chainId:4900n,coreAddress:x.core,governanceAddress:x.mode==='governance'?x.governance:null,
 startBlock:x.mode==='detect-start'?0n:100n,archiveFreeFinalizedMode:finalized,addressScopedRawLogs:scoped,
 rawJournalProjectionReplay:finalized&&scoped&&!['reorg-overlap','profile-overlap','missing-deltas'].includes(x.mode),
 chunkSize:2n,maxBlocksPerRun:x.mode==='partial'?2n:10n,reorgWindow:2n,recoveryShareV2:false,finalizedSnapshotMulticall:false};
const refresh=async(_config,snapshot)=>calls.push(['snapshot',snapshot]);
const reconcile=retainedCore(query,withTransaction,{ensureSchema:async()=>{},createPublicClient:()=>client,
 getRuntimeState:()=>({}),configuredSafeHistoryProfileForIndexer:()=>null,finalizedSnapshotIsComplete:async()=>x.mode==='snapshot-noop',
 refreshRecoveryPortfolioReadModel:refresh,reconcileConfiguredSafeExecutionEvents:async(_counter,options)=>{calls.push(['safe',options?{finalizedAnchor:options.finalizedAnchor,finalizedProfile:options.finalizedProfile,committedReconciliationId:options.committedReconciliationId,maximumBlocksPerRun:options.maximumBlocksPerRun}:null]);return x.mode!=='safe-partial';}});
const counter=createIndexerRpcRequestCounter();const outcomes=[];let error;
try{for(let phase=0;phase<(['continue','reorg-overlap','profile-overlap','missing-deltas'].includes(x.mode)?2:1);phase++){
 if(phase){if(['reorg-overlap','profile-overlap','missing-deltas'].includes(x.mode))await query("UPDATE onchain_sync_state SET state_value='changed' WHERE chain_id=4900 AND state_key='finalized_projection_profile'");
  if(x.mode==='missing-deltas')await query('DELETE FROM onchain_holder_balance_deltas WHERE chain_id=4900');}
 outcomes.push(await reconcile(config,counter,x.mode==='supplied-legacy'?{blockNumber:103n,blockHash:blockHash(103)}:undefined,undefined,s=>stages.push(s)));}}
catch(failure){error=failure.message;}
console.log(JSON.stringify({error:error??null,outcomes,calls,stages,counts:counter.snapshot(),raw},(_key,value)=>typeof value==='bigint'?value.toString():value));
await globalThis.__cybergoldDashboardPgPool?.end();
'''


async def qualify(pool, dsn):
    class Database:
        async def ensure_schema(self): pass
        @asynccontextmanager
        async def connection(self):
            async with pool.connection() as connection:
                yield connection
    database = Database()
    async def seed(mode):
        async with pool.connection() as connection:
            for table in TABLES:
                await connection.execute('DELETE FROM ' + table + ' WHERE chain_id=4900')
            for key, value in [('raw_journal_version', IDENTITY['rawJournalVersion']),
                ('dashboard_projection_version', '14' if mode == 'identity-reset' else IDENTITY['dashboardProjectionVersion']),
                ('state_snapshot_version', IDENTITY['stateSnapshotVersion']), ('indexer_version', IDENTITY['dashboardIndexerVersion']),
                ('governance_address', GOV if mode == 'governance' else 'none'),
                ('dashboard_projection_governance_address', GOV if mode == 'governance' else 'none')]:
                await connection.execute('INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value) VALUES(4900,%s,%s,%s)', (CORE,key,value))
    async def view():
        result = {}
        async with pool.connection() as connection:
            for table in TABLES:
                result[table] = (await (await connection.execute("SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'updated_at'-'created_at' AS value FROM " + table + ' t WHERE chain_id=4900) data')).fetchone())['rows']
        return result
    def wire(value, key=None):
        if type(value) is int:
            return str(value) if key == 'blockNumber' else value
        if isinstance(value,dict):
            return {key:wire(item,key) for key,item in value.items()}
        if isinstance(value,list):
            return [wire(item) for item in value]
        return value
    modes=['normal','continue','identity-reset','governance','unknown','known-malformed','log-hash-mismatch','wrong-header-number',
        'partial','safe-partial','snapshot-noop','legacy','legacy-events-finalized','detect-start','supplied-legacy','reorg-overlap','profile-overlap','missing-deltas']
    for mode in modes:
        await seed(mode)
        expected = json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',NODE,json.dumps({'mode':mode,'core':CORE,'governance':GOV})],
            cwd=ROOT,env={**os.environ,'TZ':'UTC','DATABASE_URL':dsn},text=True))
        node_rows = await view()
        await seed(mode)
        calls, stages = [], []
        finalized = mode not in ('legacy','detect-start','supplied-legacy')
        scoped = mode not in ('legacy','legacy-events-finalized','detect-start')
        config={'chainId':4900,'coreAddress':CORE,'governanceAddress':GOV if mode=='governance' else None,
            'startBlock':0 if mode=='detect-start' else 100,'archiveFreeFinalizedMode':finalized,'addressScopedRawLogs':scoped,
            'rawJournalProjectionReplay':finalized and scoped and mode not in ('reorg-overlap','profile-overlap','missing-deltas'),
            'chunkSize':2,'maxBlocksPerRun':2 if mode=='partial' else 10,'reorgWindow':2,'recoveryShareV2':False,'finalizedSnapshotMulticall':False}
        def block_hash(number):return '0x'+f'{number:064x}'
        class Client:
            async def block(self, number=None, *, block_hash=None):
                tag = number if isinstance(number,str) else block_hash or str(number)
                calls.append(['block',tag]);number=number if type(number) is int else 103
                return {'number':number+1 if mode=='wrong-header-number' and type(number) is int and tag not in ('latest','finalized') else number,
                    'hash':block_hash_fn(number),'timestamp':1000+number}
            async def block_number(self):
                calls.append(['head']);return 103
            async def request(self, method, params):
                assert method=='eth_getCode'
                number=int(params[1],16);calls.append(['code',str(number)]);return '0x01' if number>=100 else '0x'
            async def logs(self,address,value,topic=None):
                calls.append(['logs',address,str(value['fromBlock']),str(value['toBlock']),topic])
                return [log for log in expected['raw'] if log['address']==address and value['fromBlock']<=int(log['blockNumber'],16)<=value['toBlock']
                    and (topic is None or log['topics'][0]==topic)]
        block_hash_fn=block_hash
        collector=CoreCollector(database,config,{'safeAddresses':[],'lookbackBlocks':0,'eventSelectors':[]})
        async def complete(*args):return mode=='snapshot-noop'
        collector.completed.snapshot_complete=complete
        async def safes(counter,**options):
            calls.append(['safe',{'finalizedAnchor':wire(options['anchor']),'finalizedProfile':options['profile'],
                'committedReconciliationId':options['committed_id'],'maximumBlocksPerRun':str(options['maximum_blocks'])} if options else None])
            return mode!='safe-partial'
        async def refresh(snapshot,*args):calls.append(['snapshot',wire(snapshot)])
        outcomes,error,counter=[],None,RpcCounter()
        try:
            for phase in range(2 if mode in ('continue','reorg-overlap','profile-overlap','missing-deltas') else 1):
                if phase:
                    async with pool.connection() as connection:
                        if mode in ('reorg-overlap','profile-overlap','missing-deltas'):
                            await connection.execute("UPDATE onchain_sync_state SET state_value='changed' WHERE chain_id=4900 AND state_key='finalized_projection_profile'")
                        if mode=='missing-deltas':await connection.execute('DELETE FROM onchain_holder_balance_deltas WHERE chain_id=4900')
                outcomes.append(await collector.reconcile(counter,Client(),Client(),safes,
                    supplied_anchor={'blockNumber':103,'blockHash':block_hash(103)} if mode=='supplied-legacy' else None,
                    stage=stages.append,refresh=refresh))
        except Exception as failure:error=str(failure)
        actual={'error':error,'outcomes':wire(outcomes),'calls':calls,'stages':stages,'counts':counter.counts}
        comparison={key:expected[key] for key in actual}
        assert actual==comparison,(mode,next((key for key in actual if actual[key]!=comparison[key]),None),actual,comparison)
        assert await view()==node_rows,(mode,await view(),node_rows)
    return {'nativeCoreCollectorComparisons':len(modes),'nativeCoreGovernanceRawAndLegacyMatchNode':True,
        'nativeCoreUnknownJournalRetentionAndKnownDecodeFailureMatchNode':True,
        'nativeCoreReplayReorgHolderAndPartialCompletionMatchNode':True,'nativeCoreSourceEndpointsSynthetic':True}
