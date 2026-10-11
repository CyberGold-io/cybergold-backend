import {POST} from '../../src/api/safe/route';
const address='0x'+'a'.repeat(40),hash='0x'+'b'.repeat(64);
const cases:any[]=[];
const actions=['safe-info','pending-transactions','executed-transactions','propose-transaction','confirm-transaction','transaction-details'];
const suppliers=[{status:200,body:'{"ok":true}'},{status:201,body:'[]'},{status:200,body:'null'},
  {status:201,body:''},{status:201,body:' \r\n'},{status:204,body:''},{status:422,body:''},
  {status:200,body:'"text"'},{status:200,body:'invalid-json'},
  {status:429,body:'{"private":"supplier-error"}',retry:'30'},
  {status:500,body:'invalid-json',retry:'3601'},{status:503,body:'{}',retry:'0001'},
  {status:200,body:'{"number":1e309}'},{status:200,body:'{"text":"\\ud800"}'},
  {status:200,body:'{}',throw:true}];
for(const action of actions)for(const supplier of suppliers)
  cases.push({body:{action,safeAddress:address,safeTxHash:hash,payload:{value:'1',operation:0}},supplier});
for(const body of [null,[],true,0,'text',{}, {action:false},{action:[]},{action:'unknown'},
  {action:'safe-info'},{action:'safe-info',safeAddress:'0xaa'},
  {action:'confirm-transaction',safeTxHash:hash},
  {action:'confirm-transaction',safeTxHash:'0xaa',payload:{}},
  {action:'propose-transaction',safeAddress:address,payload:[]},
  {action:'propose-transaction',safeAddress:address,payload:{}},
  {action:'propose-transaction',safeAddress:address,payload:{text:'\ud800',number:1e309}},
  {action:'propose-transaction',safeAddress:address,payload:null}])cases.push({body,supplier:suppliers[0]});
cases.push({body:{action:'safe-info',safeAddress:address},supplier:suppliers[0],configured:false});
cases.push({raw:'{',supplier:suppliers[0]});
const realFetch=globalThis.fetch;
for(const entry of cases){
  process.env.SAFE_TX_SERVICE_URL=entry.configured===false?'':'http://fixture-supplier/';
  const calls:any[]=[];
  globalThis.fetch=(async(url:any,init:any)=>{
    calls.push({url:String(url),method:init.method,body:init.body?JSON.parse(init.body):null,
      contentType:init.headers['Content-Type']});
    if(entry.supplier.throw)throw new Error('fixture-private-transport-error');
    return new Response(entry.supplier.body || null,{status:entry.supplier.status,
      headers:entry.supplier.retry?{'Retry-After':entry.supplier.retry}:{}});
  }) as typeof fetch;
  const raw=entry.raw??JSON.stringify(entry.body);
  let response:Response;
  try{response=await POST(new Request('http://fixture/api/safe',{method:'POST',body:raw}));}
  catch{response=new Response(null,{status:500});}
  const text=await response.text();const result=text?JSON.parse(text):null;
  if(result?.correlationId)result.correlationId='correlated';
  Object.assign(entry,{raw,status:response.status,result,cache:response.headers.get('cache-control'),
    retry:response.headers.get('retry-after'),calls});
}
globalThis.fetch=realFetch;
console.log(JSON.stringify(cases));
