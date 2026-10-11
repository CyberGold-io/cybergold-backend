import {POST} from '../../src/api/safe/events/route';
const address='0x'+'a'.repeat(40),other='0x'+'b'.repeat(40),hash='0x'+'c'.repeat(64);
process.env.SAFE_EVENT_INDEXER_SAFE_ADDRESSES=address;
process.env.NEXT_PUBLIC_CHAIN_ID='31338';
Date.now=()=>1790762430123;
const rows=[{event_name:'ExecutionFailure',tx_hash:'0x'+'d'.repeat(64),block_number:'9007199254740993',
  block_timestamp:new Date('2026-09-30T10:00:00Z'),safe_tx_hash:hash},
  {event_name:'ExecutionSuccess',tx_hash:'0x'+'e'.repeat(64),block_number:'1',
  block_timestamp:new Date('2026-09-30T09:00:00Z'),safe_tx_hash:hash}];
const cases:any[]=[];
for(const body of [null,[],true,0,'text',{}, {safeAddress:address},
  {safeAddress:'invalid',safeTxHashes:[]},{safeAddress:other,safeTxHashes:[]},
  {safeAddress:address,safeTxHashes:[]},{safeAddress:address,safeTxHashes:[hash]},
  {safeAddress:other,safeTxHashes:[hash]},{safeAddress:address,safeTxHashes:[hash,hash.toUpperCase().replace('0X','0x')]},
  {safeAddress:address,safeTxHashes:[hash.repeat(2)]},{safeAddress:address,safeTxHashes:[[hash]]},
  {safeAddress:address,safeTxHashes:[null]},{safeAddress:address,safeTxHashes:Array(65).fill(hash)}])
  cases.push({body});
for(const mode of ['global-limit','safe-limit','busy','sql-error'])cases.push({body:{safeAddress:address,safeTxHashes:[hash]},mode});
for(const raw of ['{','\ufeff'+JSON.stringify({safeAddress:address,safeTxHashes:[]}), ' '.repeat(16385)])cases.push({raw});
cases.push({body:{safeAddress:address,safeTxHashes:[]},declared:'16385'});
for(const entry of cases){
  const calls:any[]=[];
  const query=async(sql:string,params:any[]=[])=>{
    if(sql.includes('onchain_api_rate_limits')){
      calls.push({operation:'rate',params});
      const limited=entry.mode==='global-limit'||entry.mode==='safe-limit'&&!params[0].endsWith(':global');
      return {rowCount:limited?0:1,rows:limited?[]:[{request_count:1}]};
    }
    if(sql.includes('generate_series'))return {rowCount:entry.mode==='busy'?0:1,rows:entry.mode==='busy'?[]:[{slot:0}]};
    if(sql.includes('FROM onchain_event_logs')){
      calls.push({operation:'read',params});
      if(entry.mode==='sql-error')throw new Error('fixture-sql-error');
      return {rows};
    }
    return {rows:[],rowCount:0};
  };
  globalThis.__cybergoldDashboardPgPool={query,connect:async()=>({query,release(){}})} as any;
  const raw=entry.raw??JSON.stringify(entry.body);
  let response:Response;
  try{response=await POST(new Request('http://fixture/api/safe/events',{method:'POST',body:raw,
    headers:entry.declared?{'content-length':entry.declared}:{}}));}catch{response=new Response(null,{status:500});}
  const text=await response.text();
  Object.assign(entry,{raw,status:response.status,result:text?JSON.parse(text):null,
    cache:response.headers.get('cache-control'),retry:response.headers.get('retry-after'),calls});
}
console.log(JSON.stringify(cases));
