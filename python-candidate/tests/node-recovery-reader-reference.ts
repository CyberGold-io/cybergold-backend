import {createRecoveryPortfolioReader} from '../../src/server/recovery/portfolioReader';
const asset=(i:number)=>'0x'+i.toString(16).padStart(40,'0');
const core=asset(1000),holder=asset(1001),hash='0x'+'a'.repeat(64);
const cases:any[]=[];
for(const total of [0,1,2,64,65,128])for(const offset of [0,64,128])
  cases.push({total,offset});
for(const fault of ['count','duplicate-assets','next','pool-count','pool-order','balance-count',
  'negative-balance','excess-balance','custody','preview','fund','canonical'])cases.push({total:2,offset:0,fault});
for(const sequence of ['hit','expired','different-holder','same-height-reset','concurrent','retry-page','continuation-without-hash'])
  cases.push({total:2,offset:0,sequence});
for(const entry of cases){
  const calls:Record<string,number>={};let clock=0,currentHash=hash,failOnce=true;
  const call=(name:string)=>calls[name]=(calls[name]??0)+1;
  const reader:any={core,chainId:31338n,
    block:async(requested?:string)=>{call('block');return {number:9007199254740993n,hash:requested??currentHash};},
    assertCanonical:async()=>{call('canonical');if(entry.fault==='canonical')throw new Error('fixture-canonical-change');},
    count:async()=>{call('count');if(entry.fault==='count'||entry.sequence==='retry-page'&&failOnce){failOnce=false;throw new Error('fixture-count-error');}return BigInt(entry.total);},
    assets:async(_block:any,offset:bigint)=>{call('assets');const length=Math.min(Math.max(entry.total-Number(offset),0),64);
      const values=Array.from({length},(_,i)=>asset(Number(offset)+i+1));
      if(entry.fault==='duplicate-assets'&&values.length>1)values[1]=values[0];
      return [values,BigInt(entry.fault==='next'?999:Math.min(Number(offset)+length,entry.total))];},
    paused:async()=>{call('paused');return false;},
    pools:async(_block:any,assets:string[])=>{call('pools');const values=assets.map(value=>({asset:value,
      externalShares:'9007199254740993',custody:{liveBalanceAvailable:entry.fault!=='custody'}}));
      if(entry.fault==='pool-count')values.pop();if(entry.fault==='pool-order')values.reverse();return values;},
    balances:async(_block:any,_holder:any,assets:string[])=>{call('balances');const values=assets.map((_,i)=>
      entry.fault==='negative-balance'?-1n:entry.fault==='excess-balance'?9007199254740994n:i%2===0?9007199254740993n:0n);
      if(entry.fault==='balance-count')values.pop();return values;},
    preview:async()=>{call('preview');if(entry.fault==='preview')throw new Error('fixture-preview');return 2n**256n-1n;},
    fund:async()=>{call('fund');if(entry.fault==='fund')throw new Error('fixture-fund');return {status:{configured:false,
      available:false,reason:'not-configured',problem:null,governance:null,governancePaused:null},offers:[]};}};
  const load=createRecoveryPortfolioReader(reader,()=>clock);
  const request={offset:BigInt(entry.offset),blockHash:entry.offset?hash:undefined};
  const read=async(who=holder,page=request)=>{try{return {result:await load(who as any,page as any)};}catch(error){return {error:(error as Error).message};}};
  const results=entry.sequence==='concurrent'?await Promise.all([read(),read()]):[await read()];
  if(entry.sequence&&entry.sequence!=='concurrent'){
    if(entry.sequence==='expired')clock=10000;
    if(entry.sequence==='same-height-reset')currentHash='0x'+'b'.repeat(64);
    results.push(await read(entry.sequence==='different-holder'?asset(1002):holder,
      entry.sequence==='continuation-without-hash'?{offset:1n,blockHash:undefined}:request));
  }
  Object.assign(entry,{results,calls});
}
console.log(JSON.stringify(cases));
