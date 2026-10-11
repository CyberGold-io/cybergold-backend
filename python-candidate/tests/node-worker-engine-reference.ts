import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {archiveFreeFinalizedModeEnabled,defaultReconcileIntervalMs} from '../../src/server/onchain-indexer/finalizedReconciliation';
import {addressScopedRawLogsEnabled} from '../../src/server/onchain-indexer/rawLogModel';
import {rawJournalProjectionReplayEnabled} from '../../src/server/onchain-indexer/rawLogJournal';
import {recoveryShareV2Enabled} from '../../src/server/onchain-indexer/recoverySharePersistence';
import {finalizedSnapshotMulticallEnabled} from '../../src/server/onchain-indexer/finalizedSnapshotMulticall';
import {createIndexerRpcRequestCounter} from '../../src/server/onchain-indexer/rpcRequestInstrumentation';
import {classifyInternalReconcileOutcome} from '../../src/server/onchain-indexer/internalReconcileContract';
const source=readFileSync('src/server/onchain-indexer/indexer.ts','utf8'),parsed=ts.createSourceFile('retained-worker-engine.ts',source,ts.ScriptTarget.Latest,true);
const names=['getIndexerConfig','parseBigIntEnv','parseBoundedBigIntEnv','parseNumberEnv','parseRuntimeConfigId','reconcileLogs','runOnchainIndexerWorkerOnce'];
const javascript=ts.transpileModule(parsed.statements.filter(s=>ts.isFunctionDeclaration(s)&&names.includes(s.name?.text??'')).map(s=>s.getText(parsed)).join('\n').replace(/^export /gm,''),
 {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const core='0x'+'1'.repeat(40),base={DATABASE_URL:'postgresql://fixture.invalid/db',NEXT_PUBLIC_RPC_URL:'http://fixture.invalid',NEXT_PUBLIC_CORE_DIAMOND_ADDRESS:core,NEXT_PUBLIC_CHAIN_ID:'1'};
const configurations:any[]=[{}];
for(const [key,values] of Object.entries({ONCHAIN_INDEXER_START_BLOCK:['0','100'],ONCHAIN_INDEXER_CHUNK_SIZE:['1','10001'],
 ONCHAIN_INDEXER_MAX_BLOCKS_PER_RUN:['1','50001'],ONCHAIN_INDEXER_REORG_WINDOW:['1','257'],ONCHAIN_INDEXER_RECONCILE_INTERVAL_MS:['1','75000'],
 ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE:['1'],ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS:['1'],ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED:['1'],
 ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED:['1'],ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED:['1'],CYBERGOLD_RUNTIME_CONFIG_ID:['sha256:'+'a'.repeat(64),'invalid'],
 DATABASE_URL:[null],NEXT_PUBLIC_CORE_DIAMOND_ADDRESS:[null],NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS:['0x'+'2'.repeat(40)],
 ONCHAIN_INDEXER_RPC_URL:['http://indexer.invalid'],RPC_URL:['http://rpc.invalid']}))for(const value of values)configurations.push({[key]:value});
configurations.push({ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE:'1',ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS:'1',ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED:'1',ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED:'1',ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED:'1'});
function factory(deps:any){const d={archiveFreeFinalizedModeEnabled,defaultReconcileIntervalMs,addressScopedRawLogsEnabled,rawJournalProjectionReplayEnabled,
 recoveryShareV2Enabled,finalizedSnapshotMulticallEnabled,createIndexerRpcRequestCounter,classifyInternalReconcileOutcome,...deps};
 return new Function(...Object.keys(d),javascript+';return {config:getIndexerConfig,run:runOnchainIndexerWorkerOnce};')(...Object.values(d));}
const configCases=configurations.map(values=>{const env={...base,...values};for(const key in env)if(env[key]===null)delete env[key];
 return {values,expected:factory({serverEnv:env,publicEnv:env,targetChainId:1}).config()};});
const runs:any[]=[];
for(const mode of ['normal','partial','busy','disabled','cadence','force-after-cadence','failed','expectation','forced-empty','shared-promise']){
 const calls:any[]=[],state={reconcilePromise:null,lastReconciledAtMs:mode.includes('cadence')?99999:0,lastRpcRequestCounts:null};
 const config={chainId:1n,coreAddress:core,privateGatewayClient:null,reconcileIntervalMs:60000};
 const fn=factory({Date:{now:()=>100000},serverEnv:{...base,DATABASE_URL:mode==='disabled'?undefined:base.DATABASE_URL,ONCHAIN_INDEXER_RECONCILE_INTERVAL_MS:'60000'},publicEnv:base,targetChainId:1,ensureSchema:async()=>calls.push('schema'),
  withSharedAdvisoryLock:async(key,work)=>{calls.push(['lock',key]);return mode==='busy'?{acquired:false}:{acquired:true,result:await work()};},
  getRuntimeState:()=>state,reconcileInternal:async(_config,counter,_anchor,_lease,stage)=>{
   calls.push('collect');counter.recordEthGetLogsPlan('core-address');
   if(mode==='failed')throw new Error('fixture collection failure');
   if(mode==='forced-empty')return undefined;
   return {completed:mode!=='partial',dashboardHistoryProgress:mode==='partial'?{fixture:'progress'}:null};}});
 // The real counter has a scoped request instrument; the fixture above only
 // records a planned range to compare the worker's preserved final accounting.
 if(mode==='shared-promise')state.reconcilePromise=Promise.resolve({completed:true,dashboardHistoryProgress:null});
 let result,error;try{result=await fn.run({force:mode==='force-after-cadence'||!mode.includes('cadence'),
  gatewayExpectation:mode==='expectation'?{}:undefined,onDiagnosticStage:s=>calls.push(['stage',s])});}catch(e){error=(e as Error).message;}
 runs.push({mode,expected:{result:result??null,error:error??null,calls,lastReconciledAtMs:state.lastReconciledAtMs,
  lastRpcRequestCounts:state.lastRpcRequestCounts,promiseCleared:state.reconcilePromise===null}});
}
console.log(JSON.stringify({configCases,runs},(_key,value)=>typeof value==='bigint'?value.toString():value));
