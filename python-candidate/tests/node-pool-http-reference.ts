import {POST} from '../../src/api/quote-pool-cache/route';
import {readFileSync} from 'node:fs';

const identity=JSON.parse(readFileSync('src/server/onchain-indexer/snapshot-identity.json','utf8'));
globalThis.__cybergoldDashboardSchemaPromise=Promise.resolve();
globalThis.__cybergoldDashboardSchemaVersion=identity.databaseSchemaVersion;
const tokenA='0x'+'A'.repeat(40),tokenB='0x'+'b'.repeat(40);
const base={chainId:31338,dex:'uniswap_v3',tokenA,tokenB,fee:500,exists:true};
const liquidity={activeLiquidityRaw:'9007199254740993',sqrtPriceX96Raw:'79228162514264337593543950336',
  tick:-1,token0BalanceRaw:'0',token1BalanceRaw:'2'};
const cases:any[]=[];
const add=(body:any,fail=false,raw?:string)=>cases.push({body,fail,raw});
for(const body of [null,true,1,'text',[],{}, {action:'unknown'},
  {action:'list-pools',chainId:31338,dex:'uniswap_v3',pairs:[]},
  {action:'list-pools',chainId:1.5,dex:'uniswap_v3',pairs:[{tokenA,tokenB}]},
  {action:'list-pools',chainId:31338,dex:'uniswap_v3',pairs:[{tokenA,tokenB},{tokenA:tokenB,tokenB:tokenA}]},
  {action:'list-pools',chainId:true,dex:'uniswap_v3',pairs:[]},
  {action:'list-pools',chainId:31338,dex:'other',pairs:[]},
  {action:'list-pools',chainId:31338,dex:'uniswap_v3',pairs:[null]},
  {action:'record-observations',entries:[]},{action:'record-observations',entries:[base]},
  {action:'record-observations',entries:[{...base,...liquidity}]},
  {action:'record-observations',entries:[base,{...base,tokenA:tokenB,tokenB:tokenA,exists:false,quoteSucceeded:true,...liquidity},
    {...base,poolAddress:tokenA,quoteSucceeded:false}]},
  {action:'record-observations',entries:[base,{...base,fee:3000}]},
  {action:'record-observations',entries:[null]}]) add(body);
for(const patch of [{chainId:'31338'},{chainId:true},{chainId:-1},{chainId:1.5},{dex:'other'},
  {tokenA:'0xaa'},{fee:1.5},{fee:true},{fee:-1},{poolAddress:null},{poolAddress:'0xaa'},
  {quoteSucceeded:'yes'},{quoteSucceeded:true},{quoteSucceeded:null},{activeLiquidityRaw:'1'},
  {...liquidity,tick:1.5},{...liquidity,tick:null},{...liquidity,activeLiquidityRaw:null},
  {...liquidity,activeLiquidityRaw:'01'},{...liquidity,token1BalanceRaw:'-1'},
  {...liquidity,token1BalanceRaw:'115792089237316195423570985008687907853269984665640564039457584007913129639935'}]) {
  add({action:'record-observations',entries:[{...base,...patch}]});
}
add(null,false,'{');add({action:'record-observations',entries:[base]},true);
for(const entry of cases) {
  const calls:any[]=[];
  globalThis.__cybergoldDashboardPgPool={query:async(sql:string,params:any[])=>{
    calls.push({operation:sql.includes('INSERT INTO quote_pool_cache')?'record':'list',params});
    if(entry.fail)throw new Error('fixture-private-sql-text');
    return {rowCount:0,rows:[]};
  }} as any;
  const raw=entry.raw??JSON.stringify(entry.body);
  const response=await POST(new Request('http://fixture/api/quote-pool-cache',{method:'POST',body:raw}));
  const body=await response.json();if(body.correlationId)body.correlationId='correlated';
  Object.assign(entry,{raw,result:body,status:response.status,cache:response.headers.get('cache-control'),calls});
}
console.log(JSON.stringify(cases));
