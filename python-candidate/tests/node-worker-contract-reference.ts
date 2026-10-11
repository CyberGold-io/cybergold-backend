import {authorizeIndexerWorker} from '../../src/server/onchain-indexer/workerAuth';
import {parseInternalReconcileRequest,buildInternalReconcileResponse,createDashboardHistoryProgress}
  from '../../src/server/onchain-indexer/internalReconcileContract';
import {planForkGenerationTransition} from '../../src/server/onchain-indexer/forkGenerationTransition';
import {parseInternalForkGenerationRequest} from '../../src/server/onchain-indexer/internalForkGenerationContract';
const cases:any[]=[];const add=(op:string,input:any)=>cases.push({op,input});
for(const token of [undefined,'','a'.repeat(31),'a'.repeat(32),'é'.repeat(16),'a '.repeat(16),'\ud800'.repeat(11),'😀'.repeat(8)])
 for(const header of [null,'Bearer '+(token??''),'bearer '+(token??''),'Bearer wrong','Bearer '+(token??'')+' '])add('auth',{token:token??null,header});
const body={kind:'cybergold-b2b-reconcile-request',formatVersion:1,mode:'require-worker-run'};
for(const value of [null,[],{},true,body,{...body,mode:'allow-exact-receipt-noop'},
 {...body,mode:'invalid'},{...body,formatVersion:true},{...body,extra:true}])add('parse',{raw:JSON.stringify(value)});
for(const raw of ['', '{','\ufeff'+JSON.stringify(body),'{"kind":"first","kind":"last","formatVersion":1,"mode":"require-worker-run"}',
 ' '.repeat(4097)])add('parse',{raw});
for(const [contentType,declared] of [['text/plain',null],['APPLICATION/JSON; charset=utf-8',null],
 ['application/json','-1'],['application/json','4097']])add('parse',{raw:JSON.stringify(body),contentType,declared});
for(const status of ['reconciled','incomplete','deferred-cadence','busy'])for(const legacy of [false,true])
 add('response',{result:{status,dashboardHistoryProgress:null},legacy});
for(const indexedThroughBlock of [-1n,0n,50n,100n,101n])for(const timestamp of [-1n,0n,1790762400n,253402300800n,8640000000000n,8640000000001n])
 add('progress',{startBlock:0n,indexedThroughBlock,networkFinalizedBlock:100n,
   indexedThroughTimestampSeconds:timestamp,networkFinalizedTimestampSeconds:timestamp});
const hash='0x'+'a'.repeat(64),other='0x'+'b'.repeat(64);
for(const generation of ['same','different',' '])for(const forkBlock of [-1n,90n,100n,110n])
 for(const currentHashAtPreviousForkBlock of [null,hash,other])for(const deploymentStartBlock of [-1n,90n,101n])
 add('fork-plan',{previous:{generation:'same',forkBlock:100n,forkBlockHash:hash},
   current:{generation,forkBlock,forkBlockHash:hash},deploymentStartBlock,currentHashAtPreviousForkBlock});
const anchor={generation:'11111111-1111-4111-8111-111111111111',forkBlock:'100',forkBlockHash:hash};
for(const value of [null,[],{},true,{kind:'cybergold-sandbox-fork-generation',formatVersion:1,action:'prepare',current:anchor},
 {kind:'cybergold-sandbox-fork-generation',formatVersion:1,action:'apply',current:anchor,previous:anchor},
 {kind:'cybergold-sandbox-fork-generation',formatVersion:true,action:'prepare',current:anchor},
 ...[{generation:'bad'},{forkBlock:'01'},{forkBlockHash:'0xaa'},{extra:true}].map(patch=>
 ({kind:'cybergold-sandbox-fork-generation',formatVersion:1,action:'prepare',current:{...anchor,...patch}}))])add('fork-parse',value);
for(const entry of cases){
 let result:any=null,error:string|null=null;
 try{const value=entry.input;
 switch(entry.op){
 case 'auth':result=authorizeIndexerWorker(value.header,value.token??undefined);break;
 case 'parse':result=await parseInternalReconcileRequest({request:new Request('http://fixture',{method:'POST',body:value.raw,
   headers:{'content-type':value.contentType??'application/json',...(value.declared?{'content-length':value.declared}:{})}})});break;
 case 'response':result=buildInternalReconcileResponse(value.result,value.legacy);break;
 case 'progress':result=createDashboardHistoryProgress(value);break;
 case 'fork-plan':result=planForkGenerationTransition(value);break;
 case 'fork-parse':result=parseInternalForkGenerationRequest(value);break;
 }}catch(failure){error=(failure as Error).message;}
 Object.assign(entry,{result,error});
}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?{$bigint:value.toString()}:value));
