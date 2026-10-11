import {retainedSafeCollector} from './retained_safe_collector';
import {createIndexerRpcRequestCounter,instrumentEthGetLogsRequest} from '../../src/server/onchain-indexer/rpcRequestInstrumentation';
import {toEventHash} from 'viem';
const hash=(n:bigint)=>'0x'+n.toString(16).padStart(64,'0'),address='0x'+'5'.repeat(40);
const success=toEventHash('ExecutionSuccess(bytes32,uint256)'),failure=toEventHash('ExecutionFailure(bytes32,uint256)');
const cases:any[]=[];
for(const scoped of [true,false])for(const mode of ['normal','legacy','already','partial','reorg','ahead','overlap','missing-profile','wrong-cursor','wrong-header','wrong-anchor','rpc-error','malformed','unknown','block-hash','version-error','cardinality'])cases.push({scoped,mode});
for(const mode of ['normal','backfill','gap','covered','partial','malformed','unknown','prepare-error','legacy'])cases.push({scoped:true,replay:true,mode});
for(const mode of ['normal','wrong-committed','already','partial'])cases.push({scoped:true,lease:true,mode});
cases.push({scoped:false,replay:true,mode:'normal'});
for(const x of cases){
 const calls:any[]=[];let persisted:any[]=[];let cursor:any=null;const counter=createIndexerRpcRequestCounter();
 const anchored=x.mode!=='legacy';const anchor={blockNumber:103n,blockHash:hash(103n)};const profile=x.mode==='missing-profile'?undefined:'profile';
 const scanned=x.mode==='already'?103n:x.mode==='ahead'?105n:x.mode==='wrong-cursor'?102n:null;
 const working={blockNumber:scanned,blockHash:x.mode==='reorg'?hash(999n):scanned===null?null:hash(scanned),profile:x.mode==='overlap'?'old':'profile'};
 const committed={...working,blockNumber:x.mode==='already'?103n:102n,blockHash:hash(x.mode==='already'?103n:102n),reconciliationId:'accepted'};
 let coverage=x.mode==='backfill'?{startBlock:102n,cursorBlock:103n}:x.mode==='gap'?{startBlock:90n,cursorBlock:99n}:x.mode==='covered'?{startBlock:100n,cursorBlock:103n}:null;
 function logs(from:bigint,to:bigint,topic?:string){
  const values=[];for(let n=from;n<=to;n++)values.push({contractAddress:address,blockNumber:n,blockHash:x.mode==='block-hash'?hash(999n):hash(n),transactionHash:hash(n+1000n),logIndex:0,
   blockTimestampSeconds:n+1000n,topics:[x.mode==='unknown'?hash(999n):topic??success,hash(777n)],data:x.mode==='malformed'?'0x11':'0x'+(2n**200n).toString(16).padStart(64,'0')});
  return x.mode==='cardinality'?Array.from({length:10001},()=>values[0]):values;
 }
 const read=async(n:bigint)=>{calls.push('header:'+n);return {number:x.mode==='wrong-header'||x.mode==='wrong-cursor'?42n:n,
  hash:x.mode==='wrong-anchor'&&n===103n?hash(999n):hash(n),timestamp:n+1000n};};
 const client={getBlockNumber:async()=>{calls.push('latest');return 103n;},getBlock:async({blockNumber}:any)=>read(blockNumber),request:async({params}:any)=>{
  const range=params[0],from=BigInt(range.fromBlock),to=BigInt(range.toBlock);calls.push('legacy:'+from+'-'+to+':'+range.topics[0]);
  if(x.mode==='rpc-error')throw new Error('fixture RPC failure');
  return logs(from,to,range.topics[0]).map(l=>({...l,address,blockNumber:toHex(l.blockNumber),logIndex:'0x0'}));}};
 const ingest=async(input:any)=>{calls.push('ingest:'+input.fromBlock+'-'+input.toBlock);counter.recordEthGetLogsPlan('safe-address');counter.recordEthGetLogsAttempt('safe-address',false);
  if(x.mode==='rpc-error'){counter.recordEthGetLogsFailure();throw new Error('fixture RPC failure');}
  coverage={startBlock:100n,cursorBlock:input.toBlock};return logs(input.fromBlock,input.toBlock);};
 const collector=retainedSafeCollector({serverEnv:{ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS:x.scoped?'1':'0',ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED:x.replay?'1':'0'},
  addressScopedRawLogsEnabled:(v:string)=>v==='1',rawJournalProjectionReplayEnabled:(v:string)=>v==='1',createPublicClient:()=>client,indexerRpcTransport:()=>null,
  shouldSplitDirectProviderLogRequest:()=>false,ensureSafeCursorVersion:async()=>{calls.push('version');if(x.mode==='version-error')throw new Error('fixture version failure');},
  lastScannedSafeBlock:async()=>{calls.push('cursor');return working.blockNumber;},lastScannedSafeBlockHash:async()=>{calls.push('hash');return working.blockHash;},
  finalizedSafeProjectionProfile:async()=>{calls.push('profile');return working.profile;},committedSafeBoundary:async()=>{calls.push('committed');return committed;},
  readRawJournalCoverage:async()=>{calls.push('coverage');return coverage;},ingestAddressScopedRawLogs:ingest,
  prepareRawJournalReplayCoverage:async(input:any)=>{calls.push('prepare:'+input.enabled);if(x.mode==='prepare-error')throw new Error('fixture replay failure');return input.enabled?coverage:null;},
  readRawJournalLogs:async(input:any)=>{calls.push('replay:'+input.fromBlock+'-'+input.toBlock);return logs(input.fromBlock,input.toBlock);},
  deleteIndexedSafeExecutionLogs:async(_chain:any,_address:any,from:any)=>{calls.push('delete:'+from);},
  persistSafeExecutionLogs:async(_chain:any,_address:any,values:any[])=>{calls.push('persist:'+values.length);persisted=values;},
  setLastScannedSafeBlock:async(_chain:any,_address:any,block:any,blockHash:any,p:any)=>{calls.push('put:'+block);cursor={block,hash:blockHash??null,profile:p??null};}});
 let result,error;
 try{result=await collector(address,{chainId:31338n,rpcUrl:'synthetic',lookbackBlocks:3n,reorgWindow:2n,maxBlocksPerRun:20n,chunkBlocks:2n},counter,
  {finalizedAnchor:anchored?anchor:undefined,finalizedProfile:profile,maximumBlocksPerRun:x.mode==='partial'?2n:undefined,
   gatewayLease:x.lease?{createRpcTransport:()=>null,isRangeReductionRequiredError:()=>false}:undefined,committedReconciliationId:x.mode==='wrong-committed'?'other':'accepted'});
 }catch(e){error=(e as Error).message;}
 x.expected={...(error?{error}:{result}),calls,persisted,cursor,counts:counter.snapshot()};
}
function toHex(n:bigint){return '0x'+n.toString(16);}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?value.toString():value));
