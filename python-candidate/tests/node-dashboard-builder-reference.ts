import {retainedDashboard} from './retained_dashboard';
const cases:any[]=[],end=1790812800123,hash='0x'+'a'.repeat(64),core='0x'+'1'.repeat(40);
for(const range of ['24H','7D','1M'])for(const mode of ['normal','empty','bounds','bad-amounts','hex','negative','wide','zero-decimals','fraction','prior-supply-negative'])cases.push({domain:'buckets',range,mode});
for(const mode of ['normal','hash','wrong-hash','empty','holder-wide','holder-limit','negative-holders','zero-decimals','missing-fees','read-error','no-holders','no-updates','no-basket'])cases.push({domain:'summary',mode});
function rows(start:number,mode:string){
 if(mode==='empty')return [];
 return [start-1,start,start+1,start+3600000,end-1,end,end+1].map((ms,index)=>({block_timestamp:new Date(ms),tx_hash:'tx-'+index,
  amount_raw:mode==='bad-amounts'?['invalid',null,'','1.2','+7','  12  ','-0x1'][index]:mode==='hex'?'0x10':mode==='negative'?'-3':mode==='wide'?(2n**220n).toString():mode==='fraction'?'1234567890123456789':String(index+1)}));
}
for(const x of cases){
 const calls:any[]=[];
 const metrics={totalSupplyRaw:x.mode==='wide'?2n**240n:x.mode==='prior-supply-negative'?0n:1000n*10n**18n,tokenDecimals:x.mode==='zero-decimals'?0n:18n,
  issuanceFeePpm:x.mode==='missing-fees'?null:5000n,redemptionFeePpm:8000n,paused:false};
 const helper=retainedDashboard({
  readCoreAndTokenMetrics:async()=>{calls.push('metrics');if(x.mode==='read-error')throw new Error('fixture read failure');return metrics;},
  readBasketSnapshot:async(_config:any,_client:any,_target:any,options:any)=>{calls.push({basket:options.forcePinnedStateReads??false});return x.mode==='no-basket'?null:{fixture:'basket'};},
  getHolderCountBigInt:async()=>{calls.push('count');return x.mode==='holder-wide'?2n**53n:x.mode==='holder-limit'?2n**53n-1n:x.mode==='negative-holders'?-1n:x.mode==='no-holders'?null:7n;},
  query:async(sql:string,params:any[])=>{
   if(sql.includes('amount_raw')){const name=sql.includes("event_name = 'Transfer'")?'Transfer':params[2];calls.push(name);return {rows:rows(end-30*86400000,x.mode)};}
   const names=params[2];calls.push(names);return {rowCount:x.mode==='no-updates'?0:1,rows:[{block_timestamp:new Date(end-1000),tx_hash:names[0]}]};}});
 let result,error;
 if(x.domain==='buckets'){
  const window=helper.empty(x.range,end);x.rows=rows(window.windowStartMs,x.mode).map(r=>({...r,block_timestamp_ms:r.block_timestamp.getTime()}));
  for(const field of ['mintRaw','redeemRaw','transferRaw'])helper.apply(window,rows(window.windowStartMs,x.mode),field,end);
  result=helper.materialize(window,metrics.totalSupplyRaw,metrics.tokenDecimals);x.supply=metrics.totalSupplyRaw;x.decimals=metrics.tokenDecimals;
 }else{
  const client={getBlock:async(value:any)=>{calls.push({block:value.blockHash??value.blockNumber.toString()});return {hash:x.mode==='wrong-hash'?'0x'+'b'.repeat(64):hash,timestamp:BigInt(Math.floor(end/1000))};}};
  try{result=await helper.summary({coreAddress:core,chainId:31338n},103n,{fixture:'recovery'},client,{blockNumber:103n},
   {expectedBlockHash:['hash','wrong-hash'].includes(x.mode)?hash:undefined,forcePinnedStateReads:x.mode==='hash'});}catch(e){error=(e as Error).message;}
 }
 x.expected={...(error?{error}:{result}),calls};
}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?value.toString():value));
