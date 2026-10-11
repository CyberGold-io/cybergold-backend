import {PrivateIndexerGatewayClient, privateIndexerGatewayFromEnvironment,
 assertPrivateIndexerGatewayRuntime, indexerGatewayHealthIsSuppressed,
 IndexerGatewayRangeReductionRequiredError} from '../../src/server/onchain-indexer/gatewayLease';
import {createIndexerRpcRequestCounter,IndexerGatewayRpcMethodRejectedError} from '../../src/server/onchain-indexer/rpcRequestInstrumentation';
const url='http://broker.test/rpc/indexer', token='a'.repeat(43), revision='c'.repeat(64), hash='0x'+'b'.repeat(64);
const expectation={reconciliationId:'fixture:1',expectedRuntimeRevision:revision,
 expectedFinalizedAnchor:{blockNumber:100n,blockHash:hash}};
const acquired={kind:'cybergold-rpc-indexer-lease',formatVersion:1,reconciliationId:'fixture:1',
 configRevision:revision,expiresInSeconds:60,finalizedAnchor:{number:100,hash},leaseToken:'d'.repeat(43)};
const released={kind:'cybergold-rpc-indexer-lease-release',formatVersion:1,reconciliationId:'fixture:1',released:true};
const clone=(value:any)=>JSON.parse(JSON.stringify(value));
const specifications:any[]=[];
function add(operation:string,reply:any,extra:any={}) {specifications.push({operation,reply,...extra});}
for(const operation of ['acquire','release']){
 const valid=operation==='acquire'?acquired:released;
 add(operation,{body:valid});
 for(const key of Object.keys(valid))for(const value of [null,true,false,0,-1,1.5,'','wrong',[],{}]){
  add(operation,{body:{...valid,[key]:value}});
 }
 for(const key of Object.keys(valid)){const body=clone(valid);delete body[key];add(operation,{body});}
 add(operation,{body:{...valid,extra:'ignored?'}});
 for(const status of [201,204,301,400,401,413,429,500])add(operation,{body:valid,status});
 for(const contentType of ['', 'text/plain', 'application/problem+json','APPLICATION/JSON; charset=utf-8'])add(operation,{body:valid,contentType});
 for(const length of ['0','4096','4097','0000001','-1','1.5','NaN',' 1 '])add(operation,{body:valid,length});
 for(const raw of ['null','[]','{','true','"text"','\ufeff'+JSON.stringify(valid),JSON.stringify(valid)+' '.repeat(4096)])add(operation,{raw});
 add(operation,{body:valid,otherUrl:true});add(operation,{body:valid,throws:true});
}
for(const number of [0,99,101,Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER+1,-1,1.5,true,'100'])
 add('acquire',{body:{...acquired,finalizedAnchor:{number,hash}}});
for(const hashValue of [hash.toUpperCase().replace('0X','0x'),'0x'+'f'.repeat(64),'x',null])
 add('acquire',{body:{...acquired,finalizedAnchor:{number:100,hash:hashValue}}});
for(const seconds of [1,60,Number.MAX_SAFE_INTEGER,9007199254740,0,-1,1.5,true,'60'])
 add('acquire',{body:{...acquired,expiresInSeconds:seconds}});
for(const count of [42,43,128,129])add('acquire',{body:{...acquired,leaseToken:'d'.repeat(count)}});
for(const now of [-1,0,1.5,Number.MAX_SAFE_INTEGER])add('acquire',{body:acquired},{issuedNow:now});
for(const expectedRevision of ['wrong',revision.toUpperCase(),'e'.repeat(64)])
 add('acquire',{body:acquired},{expectation:{...expectation,expectedRuntimeRevision:expectedRevision}});
for(const id of ['',':bad','x'.repeat(128),'x'.repeat(129)])
 add('acquire',{body:acquired},{expectation:{...expectation,reconciliationId:id}});
for(const number of ['-1','9007199254740992','101'])
 add('acquire',{body:acquired},{expectation:{...expectation,expectedFinalizedAnchor:{blockNumber:BigInt(number),blockHash:hash}}});
const range={kind:'cybergold-rpc-indexer-range-reduction-required',formatVersion:1};
for(const body of [{jsonrpc:'2.0',id:1,result:'0x1'}, {result:[]}, {}, [], true, null,
 {jsonrpc:'2.0',id:1,error:{code:-32005,message:'limit'}},
 {jsonrpc:'2.0',id:1,error:{code:-32602,message:'parameters'}},
 {jsonrpc:'2.0',id:1,error:null,result:'0x2'}])add('rpc',{body});
for(const error of [false,0,'',{},[],true,'ordinary failure'])add('rpc',{body:{error,result:'0x2'}});
for(const status of [201,204,301,400,401,413,429,500])add('rpc',{body:range,status});
for(const body of [range,{...range,extra:1},{...range,formatVersion:true},{...range,kind:'other'},null,[]])
 add('rpc',{body,status:413});
for(const contentType of ['', 'text/plain','APPLICATION/JSON; charset=utf-8'])
 add('rpc',{body:range,status:413,contentType});
for(const raw of ['{','\ufeff'+JSON.stringify(range),JSON.stringify(range)+' '.repeat(4096)])add('rpc',{raw,status:413});
for(const length of ['4096','4097','1.5'])add('rpc',{body:range,status:413,length});
add('rpc',{body:{result:'0x1'},otherUrl:true});add('rpc',{throws:true});
add('rpc',{body:{result:'0x1'}},{method:'eth_sendRawTransaction'});
for(const now of [60999,61000,61001])add('rpc',{body:{result:'0x1'}},{requestNow:now});
add('rpc',{body:{result:'0x1'}},{beforeExpires:true});
add('rpc',{body:{result:'0x1'}},{beforeThrows:true});
for(const beforeFailure of ['range','accounting'])add('rpc',{body:{result:'0x1'}},{beforeFailure});
add('after-release',{body:released});
const cases:any[]=[];
for(const specification of specifications){
 const calls:any[]=[];let now=specification.issuedNow??1000;let lease:any=null;
 const counter=createIndexerRpcRequestCounter();
 const fetchFunction=async (target:any,init:any)=>{
  const targetUrl=new URL(target).toString();const body=JSON.parse(init.body);
  const headers=new Headers(init.headers);
  calls.push({path:new URL(target).pathname,body:{...body,...(body.method?{id:0}:{})},
   authorization:headers.get('authorization')===`Bearer ${token}`,lease:headers.get('x-cybergold-rpc-lease'),
   reconciliation:headers.get('x-cybergold-rpc-reconciliation'),redirect:init.redirect});
  const useReply=specification.operation==='acquire'||targetUrl.endsWith('/release')||body.method;
  const reply=useReply?specification.reply:{body:acquired};
  if(reply.throws)throw new Error('synthetic transport failure');
  const raw=reply.raw??JSON.stringify(reply.body);const status=reply.status??200;
  const response=new Response([204,205,304].includes(status)?null:raw,{status,
   headers:{'Content-Type':reply.contentType??'application/json',...(reply.length!==undefined?{'Content-Length':reply.length}:{})}});
  Object.defineProperty(response,'url',{value:reply.otherUrl?'http://different.test/rpc/indexer':targetUrl});
  return response;
 };
 let result:any=null,error:any=null;
 try{
  const client=new PrivateIndexerGatewayClient(new URL(url),token,{fetch:fetchFunction as any,now:()=>now});
  const wanted=specification.expectation??expectation;
  lease=await client.acquire(wanted);
  if(specification.operation==='acquire')result={reconciliationId:lease.reconciliationId,finalizedAnchor:lease.finalizedAnchor,
   configRevision:lease.configRevision,expiresInSeconds:lease.expiresInSeconds,expiresAtMs:lease.expiresAtMs};
  else if(specification.operation==='release'){await lease.release();result=true;}
  else {
   if(specification.operation==='after-release')await lease.release();
   now=specification.requestNow??now;
   const before=specification.beforeExpires?async()=>{now=61000;}:specification.beforeThrows?async()=>{throw new Error('synthetic callback failure');}:
    specification.beforeFailure?async()=>{throw specification.beforeFailure==='range'?new IndexerGatewayRangeReductionRequiredError():new IndexerGatewayRpcMethodRejectedError();}:undefined;
   const transport=lease.createRpcTransport(counter,before)({chain:undefined} as any);
   result=await transport.request({method:specification.method??'eth_chainId',params:[]});
   if(result===undefined)result=null;
  }
 }catch(failure){
  error={restart:lease?.isRestartRequiredError(failure)??false,range:lease?.isRangeReductionRequiredError(failure)??false,
   accounting:lease?.isRpcAccountingFailure(failure)??false};
  if(specification.operation==='acquire'||specification.operation==='release')error.message=(failure as Error).message;
 }
 cases.push({specification,result,error,calls,counts:counter.snapshot()});
}
const environments:any[]=[];
const env=(value:any)=>{let result=null,error=null;try{const client=privateIndexerGatewayFromEnvironment(value);result=client!==null;}catch(failure){error=(failure as Error).message;}environments.push({value,result,error});};
for(const flag of [undefined,'','0','false','1','true','TRUE','no',' 1 ',true]){
 env({...flag!==undefined?{ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED:flag}:{}});
 env({ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED:flag,ONCHAIN_INDEXER_RPC_URL:url,ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN:token});
}
for(const candidateUrl of [url,'HTTP://BROKER.TEST:80/rpc/indexer','https://broker.test:443/rpc/indexer',
 'http://broker.test/x/../rpc/indexer','http://broker.test/rpc/%69ndexer','http://broker.test/rpc/indexer?',
 'http://broker.test/rpc/indexer#','http://broker.test/rpc/indexer?q=1','http://broker.test/rpc/indexer#x',
 'http://user:pass@broker.test/rpc/indexer','http://@broker.test/rpc/indexer','ftp://broker.test/rpc/indexer',
 'broken','/rpc/indexer','http://broker.test/rpc/indexer/','http://[::1]/rpc/indexer','http://broker.test:99999/rpc/indexer',
 'http://bücher.test/rpc/indexer',' http://broker.test/rpc/indexer \n'])
 env({ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED:'1',ONCHAIN_INDEXER_RPC_URL:candidateUrl,ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN:token});
for(const candidateUrl of ['mailto:test@example.test','http:broker.test/rpc/indexer','http:///broker.test/rpc/indexer',
 'http://127.1/rpc/indexer','http://0x7f000001/rpc/indexer','http://broker.test/%2e/rpc/indexer',
 'http://broker.test/x/%2e%2e/rpc/indexer','http://broker.test:0/rpc/indexer','http://broker.test\\rpc\\indexer'])
 env({ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED:'1',ONCHAIN_INDEXER_RPC_URL:candidateUrl,ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN:token});
for(const value of ['', 'a'.repeat(42),'a'.repeat(128),'a'.repeat(129),'a'.repeat(42)+'!'])
 env({ONCHAIN_INDEXER_RPC_GATEWAY_ENABLED:'1',ONCHAIN_INDEXER_RPC_URL:url,ONCHAIN_INDEXER_RPC_GATEWAY_TOKEN:value});
const health:any[]=[];
for(const activeReconciliationId of [null,'fixture:1'])for(const ambiguousUntilMs of [-1,0,1,1.5,Number.MAX_SAFE_INTEGER+1])
 for(const nowMs of [-1,0,1,1.5,Number.MAX_SAFE_INTEGER+1]){
  const input={activeReconciliationId,ambiguousUntilMs,nowMs};health.push({input,result:indexerGatewayHealthIsSuppressed(input)});
 }
const runtime:any[]=[];
for(const isEnabled of [false,true])for(const chainId of [1n,31338n])for(const archiveFreeFinalizedMode of [false,true])
 for(const addressScopedRawLogs of [false,true]){
  let error=null;try{assertPrivateIndexerGatewayRuntime({enabled:isEnabled,chainId,archiveFreeFinalizedMode,addressScopedRawLogs});}catch(failure){error=(failure as Error).message;}
  runtime.push({input:{enabled:isEnabled,chainId:chainId.toString(),archiveFreeFinalizedMode,addressScopedRawLogs},error});
 }
const inFlight:any[]=[];const order:number[]=[];let active=0,maximum=0;
const concurrencyCounter=createIndexerRpcRequestCounter();
const concurrentFetch=async (target:any,init:any)=>{
 const body=JSON.parse(init.body);const targetUrl=new URL(target).toString();
 let value:any=acquired;
 if(body.method){
  order.push(body.params[0]);active++;maximum=Math.max(maximum,active);
  await new Promise<void>(resolve=>inFlight.push(resolve));active--;value={result:'0x1'};
 }else if(targetUrl.endsWith('/release'))value=released;
 const response=new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
 Object.defineProperty(response,'url',{value:targetUrl});return response;
};
const concurrentLease=await new PrivateIndexerGatewayClient(new URL(url),token,{fetch:concurrentFetch as any,now:()=>1000}).acquire(expectation);
const concurrentTransport=concurrentLease.createRpcTransport(concurrencyCounter)({chain:undefined} as any);
const work=Array.from({length:9},(_value,index)=>concurrentTransport.request({method:'eth_chainId',params:[index]}));
while(inFlight.length<4)await new Promise(resolve=>setImmediate(resolve));
let busyRelease=false;try{await concurrentLease.release();}catch{busyRelease=true;}
while(order.length<9||inFlight.length){
 for(const resolve of inFlight.splice(0))resolve();await new Promise(resolve=>setImmediate(resolve));
}
await Promise.all(work);await concurrentLease.release();
const concurrency={maximum,order,busyRelease,counts:concurrencyCounter.snapshot()};
console.log(JSON.stringify({cases,environments,health,runtime,concurrency},(_key,value)=>typeof value==='bigint'?value.toString():value));
