import {createPublicClient,http} from 'viem';
import {HttpRequestError} from 'viem';
import {shouldRetry} from '../../node_modules/viem/_esm/utils/buildRequest.js';
const policies:any[]=[];
for(const code of [-1,-32005,-32603,429,-32016,-32000,-32601,4001,0])policies.push({code,retry:shouldRetry({code})});
for(const status of [0,200,400,401,403,404,408,413,429,500,501,502,503,504])policies.push({status,retry:shouldRetry(new HttpRequestError({body:{},url:'http://synthetic',status}))});
policies.push({abort:true,retry:shouldRetry(new DOMException('cancelled','AbortError'))});
const cases:any[]=[];
for(const raw of [false,true])for(const mode of ['ok','http500','http401','rpc-limit','rpc-invalid','http-rpc-invalid','http-rpc-limit','invalid-json','retry-after','retry-after-date','always-fail','empty-array','string','null','empty-error','error-string']){
 let attempts=0;const delays:number[]=[];let payload:any;let authorization:any;
 const realSetTimeout=globalThis.setTimeout,realClearTimeout=globalThis.clearTimeout;
 globalThis.setTimeout=((callback:any,delay:number)=>{if(delay!==10000){delays.push(delay);queueMicrotask(callback);}return {fake:true};}) as any;
 globalThis.clearTimeout=((handle:any)=>{if(!handle?.fake)realClearTimeout(handle);}) as any;
 const client=createPublicClient({transport:http('http://synthetic',{retryCount:raw?0:undefined,
  fetchOptions:{headers:{Authorization:'Bearer synthetic'}},fetchFn:async(_url,init:any)=>{
   attempts++;payload=JSON.parse(init.body);delete payload.id;authorization=init.headers.Authorization;
   if(attempts>1&&mode!=='always-fail'||mode==='ok')return new Response(JSON.stringify({jsonrpc:'2.0',result:'0x7a6a'}),{headers:{'Content-Type':'application/json'}});
   if(['empty-array','string','null','empty-error','error-string'].includes(mode))return new Response(JSON.stringify(
    mode==='empty-array'?[]:mode==='string'?'fixture':mode==='null'?null:mode==='empty-error'?{error:{}}:{error:'fixture'}),{headers:{'Content-Type':'application/json'}});
   if(mode==='invalid-json')return new Response('bad-json');
   const code=['rpc-limit','http-rpc-limit'].includes(mode)?-32005:-32602;
   const body=['rpc-limit','rpc-invalid','http-rpc-invalid','http-rpc-limit'].includes(mode)?JSON.stringify({error:{code,message:'fixture'}}):'fixture';
   return new Response(body,{status:mode==='http401'?401:mode.startsWith('rpc-')?200:500,
    headers:{'Retry-After':mode==='retry-after'?'2':mode==='retry-after-date'?'Thu, 01 Oct 2026 02:00:00 GMT':''}});
  }})});
 let result,error;
 try{result=await client.request({method:'eth_chainId'});}catch(failure){error=true;}
 finally{globalThis.setTimeout=realSetTimeout;globalThis.clearTimeout=realClearTimeout;}
 cases.push({raw,mode,expected:{result:result??null,error:!!error,attempts,delays,payload,authorization}});
}
console.log(JSON.stringify({policies,cases}));
