import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { quotePool, runRequest, sqrtRatioAtTick } from '../src/uniswap-sdk/engine.ts';
import { MissingPoolState } from '../src/uniswap-sdk/types.ts';
import type { PoolSnapshot, SdkRequest, StateLoader } from '../src/uniswap-sdk/types.ts';
const require = createRequire(import.meta.url);
const { Token, CurrencyAmount } = require('@uniswap/sdk-core');
const { Pool } = require('@uniswap/v3-sdk');
const t0 = { address:'0x0000000000000000000000000000000000000001', decimals:18, chainId:1 };
const t1 = { address:'0x0000000000000000000000000000000000000002', decimals:18, chainId:1 };
const pair: PoolSnapshot = { id:'pair', protocol:'v2', token0:t0, token1:t1, reserve0:'1000000', reserve1:'2000000', feePips:3000 };
const concentrated: PoolSnapshot = { id:'pool', protocol:'v3', token0:t0, token1:t1, feePips:3000,
  tickSpacing:60, sqrtRatioX96:sqrtRatioAtTick(0), tick:0, liquidity:'1000000000000000000',
  ticks:[{index:-600,liquidityGross:'1000000000000000000',liquidityNet:'1000000000000000000'},
         {index:600,liquidityGross:'1000000000000000000',liquidityNet:'-1000000000000000000'}],
  bitmapWords:[{wordPosition:-1,bitmap:(1n<<246n).toString()},{wordPosition:0,bitmap:(1n<<10n).toString()}] };

test('V2 SDK exact input and output use raw-unit rounding', async()=>{
  const input=await quotePool(pair,'exactIn','1000',true);
  assert.equal(input.amountOut,'1992');
  const output=await quotePool(pair,'exactOut','1992',true);
  assert.equal(output.amountIn,'1000');
  assert.equal(input.postState.reserve0,'1001000');
  assert.equal(pair.reserve0,'1000000');
});

test('Router 2.2 V2 exact-output advances actual forward rounding surplus and reused reserves', async()=>{
  const p={...pair,reserve0:'100000',reserve1:'200000'};
  const single=await quotePool(p,'exactOut','1000',true);
  assert.equal(single.amountIn,'505');assert.equal(single.amountOut,'1001');
  assert.equal(single.postState.reserve0,'100505');assert.equal(single.postState.reserve1,'198999');
  const next=await quotePool(single.postState,'exactOut','1000',true);
  assert.equal(next.amountIn,'510');assert.equal(next.postState.reserve1,'197998');

  const t2={...t1,address:'0x0000000000000000000000000000000000000003'};
  const second={...p,id:'second',token0:t1,token1:t2};
  const result=await runRequest({id:2,operation:'simulateRoute',mode:'exactOut',amount:'1000',pools:[p,second],
    route:{branches:[{amountIn:'0',hops:[{poolId:p.id,zeroForOne:true},{poolId:second.id,zeroForOne:true}]}]}});
  assert.equal(result.amountIn,'254');assert.equal(result.amountOut,'1001');assert.equal(result.remainingAmount,'0');
  assert.ok(Array.isArray(result.postState));
  assert.deepEqual(result.postState.map(state=>[state.reserve0,state.reserve1]),
    [['100254','199495'],['100505','198999']]);
  assert.equal(p.reserve1,'200000');assert.equal(second.reserve1,'200000');
});

test('covered V3 snapshots agree with upstream Pool SDK in both directions and modes',async()=>{
  for(const direction of [true,false]) for(const mode of ['exactIn','exactOut'] as const){
    const p=new Pool(new Token(1,t0.address,18),new Token(1,t1.address,18),3000,
      concentrated.sqrtRatioX96,concentrated.liquidity,0,concentrated.ticks);
    const currency=new Token(1,(mode==='exactIn' ? direction?t0:t1 : direction?t1:t0).address,18);
    const [amount,next]=await (mode==='exactIn'?p.getOutputAmount(CurrencyAmount.fromRawAmount(currency,'1000000000000')):
      p.getInputAmount(CurrencyAmount.fromRawAmount(currency,'1000000000000')));
    const actual=await quotePool(concentrated,mode,'1000000000000',direction);
    assert.equal(mode==='exactIn'?actual.amountOut:actual.amountIn,amount.quotient.toString());
    assert.equal(actual.postState.sqrtRatioX96,next.sqrtRatioX96.toString());
    assert.equal(actual.fullyFilled,true);
  }
});

test('V4 uses directional composed protocol+LP fee while retaining PoolKey identity',async()=>{
  const v4={...concentrated,protocol:'v4' as const, lpFee:3000, protocolFee:500|(1000<<12), hooks:'0x0000000000000000000000000000000000000000'};
  for(const direction of [true,false]){
    const p=direction?500:1000;
    const expected=await quotePool({...concentrated,feePips:p+3000-Math.floor(p*3000/1000000)},'exactIn','1000000000000',direction);
    const actual=await quotePool(v4,'exactIn','1000000000000',direction);
    assert.equal(actual.amountOut,expected.amountOut);
    assert.equal(actual.postState.lpFee,3000);
    assert.equal(actual.postState.protocolFee,v4.protocolFee);
  }
});

test('unknown bitmap and unknown initialized tick are precise state requests',async()=>{
  await assert.rejects(quotePool({...concentrated,bitmapWords:[]},'exactIn','1000',true),
    (e:unknown)=>e instanceof MissingPoolState&&e.wordPositions[0]===0);
  await assert.rejects(quotePool({...concentrated,ticks:[]},'exactIn','100000000000000000',true),
    (e:unknown)=>e instanceof MissingPoolState&&e.ticks[0]===-600);
});

test('SDK exposes unconsumed input and unfilled output at price limits',async()=>{
  const limit=sqrtRatioAtTick(-1);
  for(const mode of ['exactIn','exactOut'] as const){
    const result=await quotePool(concentrated,mode,'100000000000000000',true,limit);
    assert.equal(result.fullyFilled,false);
    assert.ok(BigInt(result.remainingAmount)>0n);
    assert.ok(BigInt(result.amountIn)>0n&&BigInt(result.amountOut)>0n);
  }
});

test('ordered branches advance shared pool state on candidate clones',async()=>{
  const first=await quotePool(pair,'exactIn','10000',true);
  const second=await quotePool(first.postState,'exactIn','10000',true);
  const original=structuredClone(pair);
  const route=await runRequest({id:1,operation:'simulateRoute',mode:'exactIn',amount:'20000',pools:[pair],
    route:{branches:[{amountIn:'10000',hops:[{poolId:'pair',zeroForOne:true}]},{amountIn:'10000',hops:[{poolId:'pair',zeroForOne:true}]}]}});
  assert.equal(route.amountOut,(BigInt(first.amountOut)+BigInt(second.amountOut)).toString());
  assert.deepEqual(pair,original);
  assert.ok('settled' in route);
  assert.equal(route.settled,true);
});

test('JSONL worker continues after malformed input and reports missing coverage',async()=>{
  const child=spawn(process.execPath,['src/uniswap-sdk/worker.ts'],{stdio:['pipe','pipe','pipe']});
  let out='',err='';child.stdout.on('data',d=>out+=d);child.stderr.on('data',d=>err+=d);
  child.stdin.end('bad-json\n'+JSON.stringify({id:'missing',operation:'quote',mode:'exactIn',amount:'1000',zeroForOne:true,pools:[{...concentrated,bitmapWords:[]}]})+'\n'+
    JSON.stringify({id:'ok',operation:'quote',mode:'exactIn',amount:'1000',zeroForOne:true,pools:[pair]})+'\n');
  const [exit]=await once(child,'exit');assert.equal(exit,0,err);
  const rows=out.trim().split('\n').map(line=>JSON.parse(line));
  assert.equal(rows[0].error.code,'INVALID_REQUEST');
  assert.equal(rows[1].missingState[0].wordPositions[0],0);
  assert.equal(rows[2].result.amountOut,'1992');
});

test('JSONL worker identifies SDK minimum-input rounding without classifying unrelated errors',async()=>{
  const child=spawn(process.execPath,['src/uniswap-sdk/worker.ts'],{stdio:['pipe','pipe','pipe']});
  let out='',err='';child.stdout.on('data',d=>out+=d);child.stderr.on('data',d=>err+=d);
  const tiny={...pair,reserve0:'100000000',reserve1:'1000000'};
  child.stdin.end([
    {id:'small',operation:'quote',mode:'exactIn',amount:'100',zeroForOne:true,pools:[tiny]},
    {id:'ordinary',operation:'unknown',pools:[]},
    {id:'ok',operation:'quote',mode:'exactIn',amount:'101',zeroForOne:true,pools:[tiny]},
  ].map(row=>JSON.stringify(row)).join('\n')+'\n');
  const [exit]=await once(child,'exit');assert.equal(exit,0,err);
  const rows=out.trim().split('\n').map(line=>JSON.parse(line));
  assert.equal(rows[0].error.code,'SDK_INPUT_TOO_SMALL');
  assert.equal(rows[1].error.code,'SDK_ERROR');
  assert.equal(rows[2].result.amountOut,'1');
});

test('Universal Router SDK 2.2 command reference has the extra hop price tuple field',async()=>{
  const { RoutePlanner, CommandType, UniversalRouterVersion }=require('@uniswap/universal-router-sdk');
  const { AbiCoder }=require('@ethersproject/abi');
  const planner=new RoutePlanner();
  const fields=[t0.address,'1000','1',[t0.address,t1.address],true,[]];
  planner.addCommand(CommandType.V2_SWAP_EXACT_IN,fields,false,UniversalRouterVersion.V2_2_0);
  assert.equal(planner.commands,'0x08');
  assert.equal(planner.inputs[0],AbiCoder.prototype.encode.call(new AbiCoder(),
    ['address','uint256','uint256','address[]','bool','uint256[]'],fields));
});

test('JSONL cancellation terminates a queued request without poisoning the next quote',async()=>{
  const child=spawn(process.execPath,['src/uniswap-sdk/worker.ts'],{stdio:['pipe','pipe','pipe']});
  let out='',err='';child.stdout.on('data',d=>out+=d);child.stderr.on('data',d=>err+=d);
  const request=(id:string)=>({id,operation:'quote',mode:'exactIn',amount:'1000',zeroForOne:true,pools:[pair]});
  child.stdin.end([request('first'),request('cancelled'),{id:'cancelled',operation:'cancel'},request('last')].map(row=>JSON.stringify(row)).join('\n')+'\n');
  const [exit]=await once(child,'exit');assert.equal(exit,0,err);
  const rows=out.trim().split('\n').map(line=>JSON.parse(line));
  assert.equal(rows[0].result.amountOut,'1992');
  assert.equal(rows[1].error.code,'CANCELLED');
  assert.equal(rows[2].result.amountOut,'1992');
});

const sparseRange: PoolSnapshot = { ...concentrated, id:'sparse-range', feePips:100, tickSpacing:1,
  liquidity:'0', ticks:[{index:-6144,liquidityGross:'1000000000000',liquidityNet:'-1000000000000'}],
  bitmapWords:Array.from({length:26},(_,index)=>({wordPosition:index===0?0:-index,bitmap:index===24?'1':'0'})) };

test('continued SDK state preserves the whole result and mutable state across repeated opposite pool use',async()=>{
  for(const mode of ['exactIn','exactOut'] as const){
    const original=structuredClone(sparseRange);
    const request: SdkRequest = {id:mode,operation:'simulateRoute',mode,amount:'1000',pools:[sparseRange],
      route:{branches:[{amountIn:'1000',hops:mode==='exactIn'
        ?[{poolId:sparseRange.id,zeroForOne:true},{poolId:sparseRange.id,zeroForOne:false}]
        :[{poolId:sparseRange.id,zeroForOne:true}]}]}};
    const expected=await runRequest(request);
    const requestedWords:number[]=[],requestedTicks:number[]=[];
    const load: StateLoader = async missing=>{
      assert.equal(missing.poolId,sparseRange.id);
      requestedWords.push(...missing.wordPositions);requestedTicks.push(...missing.ticks);
      return [{id:missing.poolId,
        bitmapWords:missing.wordPositions.map(position=>{
          const row=sparseRange.bitmapWords!.find(word=>word.wordPosition===position);assert.ok(row);return row;
        }),ticks:missing.ticks.map(index=>{
          const row=sparseRange.ticks!.find(tick=>tick.index===index);assert.ok(row);return row;
        })}];
    };
    const continued=await runRequest({...request,pools:[{...sparseRange,ticks:[],bitmapWords:[]}]},undefined,load);
    assert.deepEqual(continued,expected);
    assert.deepEqual(requestedWords,Array.from({length:26},(_,index)=>index===0?0:-index));
    assert.deepEqual(requestedTicks,[-6144]);
    assert.deepEqual(sparseRange,original);
    assert.ok(Array.isArray(expected.postState));
    assert.notEqual(expected.postState[0].sqrtRatioX96,sparseRange.sqrtRatioX96);
    assert.ok('residuals' in continued);
    assert.equal(continued.remainingAmount,'0');assert.deepEqual(continued.residuals,[]);
  }
});

function jsonlWorker(t:{after:(cleanup:()=>void)=>void}){
  const child=spawn(process.execPath,['src/uniswap-sdk/worker.ts'],{stdio:['pipe','pipe','pipe']});
  let stderr='';child.stderr.on('data',data=>stderr+=data);
  const exited=once(child,'exit');
  const lines=createInterface({input:child.stdout,crlfDelay:Infinity})[Symbol.asyncIterator]();
  t.after(()=>{if(child.exitCode===null)child.kill();});
  return {
    send:(...requests:unknown[])=>child.stdin.write(requests.map(row=>JSON.stringify(row)).join('\n')+'\n'),
    next:async()=>{const row=await lines.next();assert.equal(row.done,false,stderr);return JSON.parse(row.value!);},
    outputAvailable:()=>once(child.stdout,'data'),
    finish:async()=>{
      child.stdin.end();const extra=[];
      for(let row=await lines.next();!row.done;row=await lines.next())extra.push(JSON.parse(row.value));
      const [code]=await exited;assert.equal(code,0,stderr);return extra;
    },
  };
}
const pairRequest=(id:string):SdkRequest=>({id,operation:'quote',mode:'exactIn',amount:'1000',zeroForOne:true,pools:[pair]});
const compactPool=({ticks:_ticks,bitmapWords:_words,...pool}:PoolSnapshot)=>pool;

test('cancel ACK follows an already queued required-state frame without a late terminal frame', {timeout:10000},async t=>{
  const worker=jsonlWorker(t);
  worker.send({id:'paused',operation:'quote',mode:'exactIn',amount:'1000',zeroForOne:true,
    pools:[{...concentrated,bitmapWords:[]}],continueState:true},
    {id:'paused',operation:'cancel',acknowledge:true});
  const state=await worker.next();assert.equal(state.id,'paused');assert.equal(state.stateRequest[0].wordPositions[0],0);
  assert.deepEqual(await worker.next(),{id:'paused',cancelled:true});
  worker.send(pairRequest('after-state-cancel'));
  const next=await worker.next();assert.equal(next.id,'after-state-cancel');assert.equal(next.result.amountOut,'1992');
  assert.deepEqual(await worker.finish(),[]);
});

test('cancel ACK also follows a completed result that was queued before cancellation', {timeout:10000},async t=>{
  const worker=jsonlWorker(t),available=worker.outputAvailable();
  worker.send({...pairRequest('completed'),continueState:true});await available;
  worker.send({id:'completed',operation:'cancel',acknowledge:true});
  const completed=await worker.next();assert.equal(completed.id,'completed');assert.equal(completed.result.amountOut,'1992');
  assert.deepEqual(await worker.next(),{id:'completed',cancelled:true});
  worker.send(pairRequest('after-result-cancel'));
  assert.equal((await worker.next()).id,'after-result-cancel');
  assert.deepEqual(await worker.finish(),[]);
});

test('active continued cancellation preserves a foreign paused calculation and suppresses late owned replies', {timeout:10000},async t=>{
  const worker=jsonlWorker(t);
  worker.send({id:'foreign-paused',operation:'quote',mode:'exactIn',amount:'1000',zeroForOne:true,
    pools:[{...concentrated,bitmapWords:[]}],continueState:true});
  const state=await worker.next();assert.equal(state.id,'foreign-paused');assert.ok(state.stateRequest);
  // Fully observed zero-liquidity words keep the actual SDK calculation active;
  // cancellation needs no provider, additional observation or native action.
  const empty={...sparseRange,id:'empty-range',ticks:[],bitmapWords:Array.from({length:3467},(_,index)=>({wordPosition:-index,bitmap:'0'}))};
  worker.send({id:'active',operation:'quote',mode:'exactOut',amount:'1000',zeroForOne:true,pools:[empty],continueState:true},
    {id:'active',operation:'cancel',acknowledge:true});
  assert.deepEqual(await worker.next(),{id:'active',cancelled:true});
  worker.send({id:'foreign-paused',operation:'resume',coverage:[{id:concentrated.id,
    ticks:concentrated.ticks,bitmapWords:concentrated.bitmapWords}]});
  const actual=await worker.next(),expected=await quotePool(concentrated,'exactIn','1000',true);
  assert.equal(actual.id,'foreign-paused');
  assert.deepEqual(actual.result,{...expected,postState:compactPool(expected.postState)});
  worker.send(pairRequest('after-active-cancel'));assert.equal((await worker.next()).id,'after-active-cancel');
  assert.deepEqual(await worker.finish(),[]);
});
