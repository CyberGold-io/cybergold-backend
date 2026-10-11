import {POST} from '../../src/api/faucet/route';
import {normalizeRequesterIp} from '../../src/server/faucet/forkFaucet';
const address='0x'+'a'.repeat(40),requestId='11111111-1111-4111-8111-111111111111';
const body={address,requestId};
const success={status:'ok',address,ethWei:'1000000000000000000',tokens:[{symbol:'PAXG',amount:'1'}],dryRun:false};
const cases:any[]=[];
for(const value of [null,[],true,{}, {address},{...body,extra:true},{...body,requestId:'bad'},{...body,address:'bad'},body])cases.push({body:value});
for(const pair of [[undefined,undefined],['127.0.0.1',undefined],['127.0.0.1','127.0.0.2'],
  ['::ffff:192.0.2.1','::ffff:c000:201, 127.0.0.1'],['::1','::1'],['01.1.1.1','01.1.1.1']])
  cases.push({body,ip:pair});
for(const entry of [{enabled:false},{type:'text/plain'},{declared:'-1'},{declared:'513'},
  {raw:' '.repeat(513)},{raw:'{'},{url:'https://fixture/fund'},{url:'http://127.0.0.2:9999/fund'},
  {token:'bad'},{throw:true}])cases.push({body,...entry});
const errors:Record<number,string[]>={400:['INVALID_JSON','INVALID_REQUEST','INVALID_ADDRESS','INVALID_REQUEST_ID','INVALID_REQUESTER_IP'],
  401:['UNAUTHORIZED'],404:['NOT_FOUND'],405:['METHOD_NOT_ALLOWED'],408:['REQUEST_TIMEOUT'],
  409:['REQUEST_ID_CONFLICT','REQUEST_IN_PROGRESS','REQUEST_UNCERTAIN'],411:['LENGTH_REQUIRED'],
  413:['REQUEST_TOO_LARGE'],415:['UNSUPPORTED_MEDIA_TYPE'],
  429:['ADDRESS_QUOTA_EXHAUSTED','IP_QUOTA_EXHAUSTED','GLOBAL_QUOTA_EXHAUSTED'],
  500:['INTERNAL_ERROR'],502:['FUNDING_FAILED'],503:['CHAIN_UNAVAILABLE']};
for(const [status,codes] of Object.entries(errors))for(const code of codes)
  cases.push({body,supplier:{status:Number(status),value:{error:{code,message:'fixture-private-detail'}},retry:'30'}});
for(const patch of [{dryRun:true},{ethWei:'01'},{ethWei:'-1'},{ethWei:(2n**256n).toString()},
  {address:'0x'+'b'.repeat(40)},{extra:true},{tokens:Array(17).fill({symbol:'PAXG',amount:'1'})},
  {tokens:[{symbol:'PAXG',amount:'1'},{symbol:'paxg',amount:'2'}]},
  {tokens:[{symbol:'bad-symbol',amount:'1'}]},{tokens:[{symbol:'PAXG',amount:'1',extra:true}]}])
  cases.push({body,supplier:{value:{...success,...patch}}});
for(const supplier of [{raw:'{'},{value:null},{type:'text/plain'},
  {declared:'65537'},{declared:'invalid'},{raw:' '.repeat(65537)},
  {status:429,value:{error:{code:'INVALID_ADDRESS',message:'private'}}},
  ...['0','3601','0001','date','30','99999'].map(retry=>({status:429,
    value:{error:{code:'IP_QUOTA_EXHAUSTED',message:'private'}},retry}))])cases.push({body,supplier});
const realFetch=globalThis.fetch;
for(const entry of cases){
  process.env.FORK_FAUCET_ENABLED=entry.enabled===false?'0':'1';
  process.env.FORK_FAUCET_SERVICE_URL=entry.url??'http://127.0.0.1:9999/fund';
  process.env.FORK_FAUCET_SERVICE_TOKEN=entry.token??'1'.repeat(64);
  const calls:any[]=[];
  globalThis.fetch=(async(url:any,init:any)=>{
    calls.push({url:String(url),method:init.method,body:JSON.parse(init.body),
      privateAuthorization:init.headers.Authorization==='Bearer '+'1'.repeat(64),redirect:init.redirect});
    if(entry.throw)throw new Error('fixture-private-transport');
    const supplier=entry.supplier??{};
    const headers:Record<string,string>={'content-type':supplier.type??'application/json'};
    if(supplier.retry!==undefined)headers['retry-after']=supplier.retry;
    if(supplier.declared!==undefined)headers['content-length']=supplier.declared;
    return new Response(supplier.raw??JSON.stringify('value' in supplier?supplier.value:success),{status:supplier.status??200,headers});
  }) as typeof fetch;
  const ip=entry.ip??['127.0.0.1','127.0.0.1'];
  const headers:Record<string,string>={'content-type':entry.type??'application/json','origin':'http://localhost:3030'};
  if(ip[0]!=null)headers['x-real-ip']=ip[0];if(ip[1]!=null)headers['x-forwarded-for']=ip[1];
  if(entry.declared!==undefined)headers['content-length']=entry.declared;
  const raw=entry.raw??JSON.stringify(entry.body);
  const response=await POST(new Request('http://fixture/api/faucet',{method:'POST',body:raw,headers}));
  const result=await response.json();
  if(response.status!==200){
    if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(result.correlationId))
      throw new Error('Faucet failure must carry a UUID correlation reference');
    delete result.correlationId;
  }
  Object.assign(entry,{raw,status:response.status,result,cache:response.headers.get('cache-control'),
    retry:response.headers.get('retry-after'),replace:response.headers.get('x-cybergold-faucet-request-id'),calls});
}
globalThis.fetch=realFetch;
console.log(JSON.stringify({cases,success,ips:['127.0.0.1','::1','2001:0DB8:0:0:1:0:0:1','::ffff:192.0.2.1',
  'fe80::1%eth0','01.2.3.4','127.1','garbage'].map(value=>({value,normalized:normalizeRequesterIp(value)??null}))}));
