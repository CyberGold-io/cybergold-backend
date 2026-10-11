import {mock} from 'node:test';
let mode='normal';let status='reconciled';let calls:any[]=[];
const outcome=()=>({status,dashboardHistoryProgress:null});
await mock.module(new URL('../../src/server/onchain-indexer/indexer.ts',import.meta.url).href,{namedExports:{
  getLastOnchainIndexerReconciliationReceipt:async()=>{
    if(mode==='error')throw new Error('fixture worker failure');return mode==='absent'?null:{fixture:'receipt'};},
  runOnchainIndexerWorkerOnce:async(input:any)=>{
    calls.push({force:input.force,diagnostic:Boolean(input.onDiagnosticStage)});input.onDiagnosticStage?.('fixture-stage');
    if(mode==='error')throw new Error('fixture worker failure');
    if(mode==='secret')throw new Error('Bearer fixture-private-value');return outcome();},
  getSandboxForkGenerationStatus:async()=>{if(mode==='error')throw new Error('failure');return null;},
  transitionSandboxForkGeneration:async(input:any)=>{
    calls.push(input);if(mode==='error')throw new Error('failure');
    return status==='applied'?{status,plan:{kind:'reuse-prefix',invalidateFrom:101n,retainedThrough:100n}}:{status};},
  getOnchainDashboardSummary:async()=>({enabled:false}),
}});
const reconcile=await import('../../src/api/internal/onchain-indexer/reconcile/route');
const fork=await import('../../src/api/internal/onchain-indexer/fork-generation/route');
const token='a'.repeat(32);process.env.ONCHAIN_INDEXER_WORKER_TOKEN=token;
const base={kind:'cybergold-b2b-reconcile-request',formatVersion:1,mode:'require-worker-run'};
const anchor={generation:'11111111-1111-4111-8111-111111111111',forkBlock:'100',forkBlockHash:'0x'+'a'.repeat(64)};
const forkBody={kind:'cybergold-sandbox-fork-generation',formatVersion:1,action:'prepare',current:anchor};
const cases:any[]=[];
for(const route of ['reconcile','fork'])for(const method of ['GET','POST'])
 for(const auth of [null,'Bearer wrong','Bearer '+token])cases.push({route,method,auth,raw:JSON.stringify(route==='reconcile'?base:forkBody)});
for(const value of ['reconciled','incomplete','deferred-cadence','busy'])
 for(const raw of ['',JSON.stringify(base)])for(const query of ['', '?force=1','?diagnostic=1'])
 cases.push({route:'reconcile',method:'POST',raw,status:value,query});
for(const raw of ['{','\ufeff'+JSON.stringify(base),' '.repeat(4097),JSON.stringify({...base,extra:true})])
 cases.push({route:'reconcile',method:'POST',raw,query:'?diagnostic=1'});
for(const mode of ['error','secret'])cases.push({route:'reconcile',method:'POST',raw:JSON.stringify(base),mode,query:'?diagnostic=1'});
for(const mode of ['error','absent'])cases.push({route:'reconcile',method:'GET',mode});
for(const raw of ['{','\ufeff'+JSON.stringify(forkBody),' '.repeat(1025),JSON.stringify({...forkBody,extra:true})])
 cases.push({route:'fork',method:'POST',raw});
for(const status of ['busy','prepared','applied'])cases.push({route:'fork',method:'POST',raw:JSON.stringify(forkBody),status});
cases.push({route:'fork',method:'POST',raw:JSON.stringify(forkBody),mode:'error'},
 {route:'fork',method:'GET',mode:'error'},
 {route:'fork',method:'POST',raw:JSON.stringify(forkBody),type:'text/plain'});
for(const entry of cases){
 mode=entry.mode??'normal';status=entry.status??'reconciled';calls=[];
 const module=entry.route==='reconcile'?reconcile:fork;
 const response=await module[entry.method as 'GET'|'POST'](new Request('http://fixture/'+(entry.query??''),{
   method:entry.method,...(entry.method==='POST'?{body:entry.raw}:{}),
   headers:{'authorization':entry.auth??(Object.hasOwn(entry,'auth')?'':'Bearer '+token),'content-type':entry.type??'application/json'}}));
 Object.assign(entry,{result:await response.json(),code:response.status,cache:response.headers.get('cache-control'),retry:response.headers.get('retry-after'),calls});
}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?{$bigint:value.toString()}:value));
