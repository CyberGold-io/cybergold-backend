import {readFileSync} from 'node:fs';
import {retainedCompletion} from './retained_completion';
const receipt=JSON.parse(readFileSync(process.argv[2],'utf8')).cases[0].result;
const core='0x'+'a'.repeat(40),safe='0x'+'b'.repeat(40),hash='0x'+'a'.repeat(64),profile='fixture-profile';
const config={chainId:'1',coreAddress:core,governanceAddress:null,safeAddresses:[safe],privateGatewayClient:true,
 runtimeConfigId:receipt.runtimeConfigId,recoveryShareV2:false};
const coreState:any={committed_finalized_block:'100',committed_finalized_block_hash:hash,
 committed_finalized_profile:profile,committed_reconciliation_id:'fixture:1',committed_gateway_config_revision:'c'.repeat(64),
 completed_reconciliation_receipt_v2:JSON.stringify(receipt),last_scanned_block:'100',finalized_projection_block_hash:hash,
 finalized_projection_profile:profile,raw_log_journal_version:'1',raw_log_last_scanned_block:'100',
 raw_log_last_scanned_block_hash:hash,finalized_snapshot_block:'100',finalized_snapshot_block_hash:hash,finalized_snapshot_profile:profile};
const safeState:any={safe_committed_finalized_block:'100',safe_committed_finalized_block_hash:hash,
 safe_committed_finalized_profile:profile,safe_committed_reconciliation_id:'fixture:1',raw_log_journal_version:'1',
 raw_log_last_scanned_block:'100',raw_log_last_scanned_block_hash:hash,safe_execution_cursor_version:'1',
 safe_execution_last_scanned_block:'100',safe_execution_last_scanned_block_hash:hash,safe_finalized_projection_profile:profile};
const clone=(value:any)=>JSON.parse(JSON.stringify(value));
const cases:any[]=[];
function add(extra:any={}){cases.push({config:clone(config),states:{[core]:clone(coreState),[safe]:clone(safeState)},
 runtime:{activeGatewayReconciliationId:null,gatewayLeaseAmbiguousUntilMs:0},now:1000,modelCount:2,...extra});}
add();
for(const address of [core,safe])for(const key of Object.keys(address===core?coreState:safeState)){
 for(const value of [null,'invalid','101']){
  const states={[core]:clone(coreState),[safe]:clone(safeState)};
  if(value===null)delete states[address][key];else states[address][key]=value;
  add({states});
 }
 if(key.includes('hash')){
  const states={[core]:clone(coreState),[safe]:clone(safeState)};states[address][key]=hash.toUpperCase().replace('0X','0x');add({states});
 }
}
for(const value of ['00100','0x64',' 100 ','-1','0'])add({states:{[core]:{...coreState,committed_finalized_block:value},[safe]:safeState}});
for(const now of [999,1000,1001])add({runtime:{activeGatewayReconciliationId:'fixture:running',gatewayLeaseAmbiguousUntilMs:1000},now});
add({runtime:{activeGatewayReconciliationId:'fixture:running',gatewayLeaseAmbiguousUntilMs:1.5}});
for(const modelCount of [0,1,3])add({modelCount});
for(const privateGatewayClient of [null,false])add({config:{...config,privateGatewayClient}});
add({config:{...config,runtimeConfigId:null}});add({queryErrorKey:'completed_reconciliation_receipt_v2'});add({queryErrorKey:'committed_finalized_profile'});
add({config:{...config,safeAddresses:[]}});add({config:{...config,safeAddresses:[safe,'0x'+'d'.repeat(40)]}});
const recovery={recovery_share_v2_version:'1',recovery_share_v2_block:'100',recovery_share_v2_block_hash:hash,recovery_share_v2_profile:profile};
for(const change of [{},{recovery_share_v2_version:'2'},{recovery_share_v2_block:'99'},{recovery_share_v2_profile:'wrong'}])
 add({config:{...config,recoveryShareV2:true},states:{[core]:{...coreState,...recovery,...change},[safe]:safeState}});
for(const item of cases){
 const dependencies={...item,runtime:clone(item.runtime),query:async(sql:string,params:any[])=>{
  if(sql.includes('model_count'))return {rowCount:1,rows:[{model_count:String(item.modelCount)}]};
  if(typeof params[2]==='string'){
   if(params[2]===item.queryErrorKey)throw new Error('synthetic query failure');
   const value=item.states[params[1]]?.[params[2]];return value===undefined?{rowCount:0,rows:[]}:{rowCount:1,rows:[{state_value:value}]};
  }
  const addresses=Array.isArray(params[1])?params[1]:[params[1]];
  return {rowCount:0,rows:addresses.flatMap((address:string)=>Object.entries(item.states[address]??{})
   .filter(([key])=>params[2].includes(key)).map(([state_key,state_value])=>({contract_address:address,state_key,state_value})))};
 },withTransaction:async()=>{throw new Error('Read requested a write');}};
 let result=null,error=null;try{result=await retainedCompletion(dependencies).read();}catch(failure){error=(failure as Error).message;}
 item.result=result;item.error=error;item.runtimeAfter=clone(dependencies.runtime);
}
const commits:any[]=[];
for(const stored of [receipt,null]){
 const calls:any[]=[];const checkpoint={coreCursor:{address:core,blockNumber:100n,blockHash:hash},
  safeCursors:[{address:safe,blockNumber:100n,blockHash:hash}],rawCursors:[],profile};
 const lease={reconciliationId:'fixture:1',configRevision:'c'.repeat(64)};
 const query=async(sql:string,params:any[])=>{calls.push({operation:sql.includes('DELETE')?'delete':'put',params});return {rows:[],rowCount:1};};
 await retainedCompletion({config,runtime:{},now:1000,query,withTransaction:async(action:any)=>action(query)}).commit({config,lease,checkpoint,receipt:stored});
 commits.push({checkpoint,lease,receipt:stored,calls});
}
const builds:any[]=[];
const checkpoint={coreCursor:{address:core,blockNumber:100n,blockHash:hash},safeCursors:[{address:safe,blockNumber:100n,blockHash:hash}],
 rawCursors:[{address:core,blockNumber:100n,blockHash:hash},{address:safe,blockNumber:100n,blockHash:hash}],profile};
const lease={reconciliationId:'fixture:1',configRevision:'c'.repeat(64),finalizedAnchor:{blockNumber:100n,blockHash:hash}};
const build=(extra:any={})=>builds.push({checkpoint,lease,states:coreState,
 counts:{raw:'340282366920938463463374607431768211456',events:'11',safe:'1',models:'2'},...extra});
build();
for(const field of ['raw','events','safe','models'])for(const value of [null,'01','-1','1'])
 build({counts:{raw:'0',events:'0',safe:'0',models:'2',[field]:value}});
for(const key of ['finalized_snapshot_block','finalized_snapshot_block_hash','finalized_snapshot_profile']){
 const missing={...coreState};delete missing[key];build({states:missing});build({states:{...coreState,[key]:'invalid'}});
}
for(const field of ['coreCursor','safeCursors','rawCursors']){
 const altered={...checkpoint,[field]:field==='coreCursor'?{...checkpoint.coreCursor,blockNumber:99n}:
  checkpoint[field].map((value:any,index:number)=>index===0?{...value,blockNumber:99n}:value)};build({checkpoint:altered});
}
for(const item of builds){
 const query=async(sql:string,params:any[])=>{
  if(sql.includes('row_count')){
   const key=sql.includes('onchain_raw_logs')?'raw':sql.includes('onchain_read_model_snapshots')?'models':params.length===3?'safe':'events';
   return {rowCount:1,rows:[{row_count:item.counts[key]}]};
  }
  const value=item.states[params[2]];return value===undefined?{rowCount:0,rows:[]}:{rowCount:1,rows:[{state_value:value}]};
 };
 let result=null,error=null;
 try{result=await retainedCompletion({config,runtime:{},now:1000,query}).build({config,lease:item.lease,
  checkpoint:item.checkpoint,rpcRequests:receipt.rpcRequests,startedAtMs:1790762400098,completedAtMs:1790762400123});}
 catch(failure){error=(failure as Error).message;}
 item.result=result;item.error=error;
}
console.log(JSON.stringify({cases,commits,builds,receipt,config,states:{[core]:coreState,[safe]:safeState}},(_key,value)=>typeof value==='bigint'?value.toString():value));
