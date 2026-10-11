// Exercise the retained real Fastify route with synthetic supplier responses.
import { createBackendServer } from '../../src/http-server';

const call = { jsonrpc: '2.0', id: 7, method: 'eth_call', params: [{ to: '0x01' }, 'latest'] };
const good = '{ "jsonrpc": "2.0", "id": 7, "result": "0x01" }\n';
const cases: any[] = [
  { name: 'raw-success', raw: ' '+JSON.stringify(call)+'\n', responses: [{ body: good }] },
  { name: 'upstream-error', responses: [{ body: JSON.stringify({jsonrpc:'2.0',id:7,error:{code:-32000,message:'reverted'}}) }] },
  { name: 'upstream-id-preserved', responses: [{ body: '{"jsonrpc":"2.0","id":8,"result":"0x02"}' }] },
  { name: 'batch-success', payload: [call, {...call,id:'second',method:'eth_chainId'}], responses:[{body:'[{"jsonrpc":"2.0","id":7,"result":"0x01"},{"jsonrpc":"2.0","id":"second","result":"0x7a6a"}]'}] },
  { name: 'success-status', responses:[{status:201,body:good}] },
  { name: 'empty-success', responses:[{status:204}] },
  { name: 'response-nonjson', responses:[{body:'supplier-private-response'}] },
  { name: 'response-missing-id', responses:[{body:'{"jsonrpc":"2.0","result":"0x01"}'}] },
  { name: 'response-both-result-error', responses:[{body:'{"jsonrpc":"2.0","id":7,"result":null,"error":{"code":-1,"message":"error"}}'}] },
  { name: 'response-empty-array', responses:[{body:'[]'}] },
  { name: 'response-null', responses:[{body:'null'}] },
  { name: 'response-utf8-bom', responses:[{body:'\ufeff'+good}] },
  { name: 'supplier-unavailable', responses:[{status:503,body:'supplier-private-response'}] },
  { name: 'supplier-redirect', responses:[{status:302,body:'redirect',headers:{location:'http://fixture.invalid/next'}}] },
  { name: 'supplier-connection', responses:[{mode:'connection'}] },
  { name: 'supplier-timeout', responses:[{mode:'timeout'}] },
  { name: 'batch-unavailable', payload:[call,{...call,id:null}], responses:[{status:503}] },
  { name: 'missing-upstream', url:'' },
  { name: 'non-sandbox-rate-limit', responses:[{status:429,headers:{'retry-after':'2'}}] },
  { name: 'non-sandbox-rate-limit-default', responses:[{status:429}] },
  { name: 'sandbox-rate-retry', url:'https://rpc.cybergold.io/api', responses:[{status:429,headers:{'retry-after':'1'}},{body:good}] },
  { name: 'sandbox-rate-retry-once', url:'https://rpc.cybergold.io:443/api', responses:[{status:429,headers:{'retry-after':'1'}},{status:429,headers:{'retry-after':'2'}}] },
  { name: 'sandbox-cooldown-past-deadline', url:'https://rpc.cybergold.io/', responses:[{status:429,headers:{'retry-after':'30'}}] },
  { name: 'request-invalid-json', raw:'{invalid' },
  { name: 'request-empty', raw:'' },
  { name: 'request-invalid-utf8', builder:'invalid-utf8' },
  { name: 'request-bom', builder:'bom', responses:[{body:good}] },
  { name: 'request-too-large', builder:'too-large' },
  { name: 'request-declared-too-large', declaredLength:'1048577' },
  { name: 'request-null', payload:null },
  { name: 'request-empty-batch', payload:[] },
  { name: 'request-denied', payload:{...call,method:'eth_sendRawTransaction'} },
  { name: 'request-first-error', payload:[{...call,id:true},{...call,method:'eth_sendRawTransaction'}] },
  { name: 'non-json-media-type', contentType:'text/plain', responses:[{body:good}] },
];
const app = await createBackendServer('api',{logger:false});
const originalFetch=globalThis.fetch;
const results=[];
try {
  for (const fixture of cases) {
    delete (globalThis as any).cyberGoldRpcReadPacer;
    if (fixture.url === '') delete process.env.RPC_URL;
    else process.env.RPC_URL=fixture.url??'https://fixture.invalid/rpc';
    process.env.RPC_AUTHORIZATION='fixture-authorization';
    let attempts=0;
    let forwardedBody:string|null=null;
    let authenticated=false;
    let redirectMode:string|undefined;
    globalThis.fetch=(async (_url,options:any)=>{
      const response=fixture.responses?.[attempts++]??{};
      forwardedBody=options.body;
      authenticated=options.headers.Authorization==='fixture-authorization';
      redirectMode=options.redirect;
      if (response.mode==='connection') throw new Error('fixture-private-transport-error');
      if (response.mode==='timeout') return await new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true}));
      return new Response(response.status===204?null:response.body??'',{status:response.status??200,headers:response.headers});
    }) as typeof fetch;
    const body=fixture.builder==='invalid-utf8'?Buffer.from([0xff]):fixture.builder==='too-large'?' '.repeat(1048577)
      :fixture.builder==='bom'?'\ufeff'+JSON.stringify(call):fixture.raw??JSON.stringify('payload' in fixture?fixture.payload:call);
    const response=await app.inject({method:'POST',url:'/api/rpc',payload:body,
      headers:{'content-type':fixture.contentType??'application/json',...(fixture.declaredLength?{'content-length':fixture.declaredLength}:{})}});
    results.push({fixture, result:{status:response.statusCode,body:response.json(),text:response.body,
      cacheControl:response.headers['cache-control'],contentType:response.headers['content-type'],
      retryAfter:response.headers['retry-after']??null,attempts,forwardedBody,authenticated,redirectMode:redirectMode??null}});
  }
  process.stdout.write(JSON.stringify(results)+'\n');
} finally { globalThis.fetch=originalFetch; await app.close(); }
