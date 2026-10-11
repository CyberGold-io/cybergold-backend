import {createReconciliationReceipt,parseReconciliationReceipt} from '../../src/server/onchain-indexer/reconciliationReceipt';
import {createIndexerRpcRequestCounter,INDEXER_GATEWAY_RPC_METHODS} from '../../src/server/onchain-indexer/rpcRequestInstrumentation';
const hash='0x'+'a'.repeat(64),core='0x'+'a'.repeat(40),safe='0x'+'b'.repeat(40);
const counter=createIndexerRpcRequestCounter();
counter.recordEthGetLogsPlan('core-address');counter.recordEthGetLogsAttempt('core-address',false);counter.recordGatewayRpcAttempt('eth_getLogs');
counter.recordEthGetLogsAttempt('core-address',true);counter.recordGatewayRpcAttempt('eth_getLogs');counter.recordEthGetLogsFailure();counter.recordGatewayRpcFailure();
for(const method of INDEXER_GATEWAY_RPC_METHODS.filter(value=>value!=='eth_getLogs'))counter.recordGatewayRpcAttempt(method);
const input:any={reconciliationId:'fixture:1',gatewayConfigRevision:'c'.repeat(64),runtimeConfigId:'sha256:'+'d'.repeat(64),
 finalizedAnchor:{blockNumber:100n,blockHash:hash},identities:{databaseSchemaVersion:'12',rawJournalVersion:'1',dashboardProjectionVersion:'14',stateSnapshotVersion:'1',safeCursorVersion:'1'},
 rawJournal:{trackedAddressCount:2,logCount:'340282366920938463463374607431768211456',cursors:[{address:safe,blockNumber:100n,blockHash:hash},{address:core,blockNumber:100n,blockHash:hash}]},
 dashboardProjection:{eventLogCount:'11',blockNumber:100n,blockHash:hash,profile:'fixture-profile'},stateSnapshot:{modelCount:'2',blockNumber:100n,blockHash:hash,profile:'fixture-profile'},
 safeCursors:{configuredSafeCount:1,eventLogCount:'1',cursors:[{address:safe,blockNumber:100n,blockHash:hash}]},rpcRequests:counter.snapshot(),completedAtMs:1790762400123,durationMs:25};
const stored=createReconciliationReceipt(input);const cases:any[]=[];
const add=(raw:string)=>{let result=null,error=null;try{result=parseReconciliationReceipt(raw);}catch(failure){error=(failure as Error).message;}cases.push({raw,result,error});};
add(JSON.stringify(stored));for(const raw of ['{','null','[]','true','1','{}'])add(raw);
const paths:string[][]=[];
function pathsOf(value:any,path:string[]=[]){
 if(value&&typeof value==='object'){paths.push(path);for(const key of Object.keys(value))pathsOf(value[key],[...path,key]);}
 else paths.push(path);
}pathsOf(stored);
for(const path of paths)for(const replacement of [null,true,false,0,-1,1.5,'','invalid',{},[]]){
 const value=JSON.parse(JSON.stringify(stored));let parent=value;
 for(const key of path.slice(0,-1))parent=parent[key];
 if(path.length)parent[path.at(-1)!]=replacement;
 add(JSON.stringify(path.length?value:replacement));
}
for(const path of paths){
 const value=JSON.parse(JSON.stringify(stored));let selected=value;for(const key of path)selected=selected[key];
 if(selected&&typeof selected==='object'&&!Array.isArray(selected)){selected.extra='unrelated';add(JSON.stringify(value));}
}
for(const stamp of ['2026-09-30T10:00:00Z','Wed, 30 Sep 2026 10:00:00 GMT','2026-09-30T10:00:00.123Z','+010000-01-01T00:00:00.000Z']){
 add(JSON.stringify({...stored,completedAt:stamp}));
}
for(const field of ['rawJournal','safeCursors']){
 const value=JSON.parse(JSON.stringify(stored));value[field].cursors.push(value[field].cursors[0]);value[field].cursorCount++;
 if(field==='rawJournal')value[field].trackedAddressCount++;else value[field].configuredSafeCount++;add(JSON.stringify(value));
}
const creations:any[]=[];
for(const completedAtMs of [0,1,1001,1790762400123,8640000000000000,8640000000000001,-1,1.5]){
 let result=null,error=null;try{result=createReconciliationReceipt({...input,completedAtMs});}catch(failure){error=(failure as Error).message;}
 creations.push({completedAtMs,result,error});
}
const detached=counter.snapshot();let rejected=null;
try{counter.recordGatewayRpcAttempt('eth_sendRawTransaction');}catch(failure){rejected=(failure as Error).message;}
counter.recordGatewayRpcAttempt('eth_call');
console.log(JSON.stringify({cases,input:JSON.parse(JSON.stringify(input,(_key,value)=>typeof value==='bigint'?value.toString():value)),creations,
 counts:{before:detached,after:counter.snapshot(),rejected}}));
