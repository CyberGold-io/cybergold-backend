import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { encodeAbiParameters, encodeFunctionData, parseAbiParameters, type Abi } from 'viem';
import { HELPERS_DIAMOND_FUNCTIONS, HELPERS_DIAMOND_ABI } from '../src/contracts/generated/helpersDiamond';
const fixture = JSON.parse(readFileSync('tests/fixtures/universal-exact-input.json','utf8'));
const step='(uint8 kind,address currencyOut,uint24 fee,int24 tickSpacing)';
const template=`(address inputCurrency,address outputCurrency,uint256 minimumOutput,(uint32 sharePpm,${step}[] steps)[] routes)`;
const continuation=`(${template} route,uint256 feeCygld)`;
const token='(uint8 kind,address token,uint256 id,uint256 minimumAmount)';
const integer = (value: unknown): unknown => Array.isArray(value) ? value.map(integer) : value && typeof value === 'object'
  ? Object.fromEntries(Object.entries(value).map(([key,item])=>[key,integer(item)]))
  : typeof value==='string' && /^[0-9]+$/.test(value) ? BigInt(value) : value;
function encodedBody(intent:number, body:any) {
  if(intent<2) {
    const branches=body.branches.map((branch:any)=>{
      const types=branch.kind===1 ? `(${template} route,uint256 feeCygld)` : intent===0
        ? `(address[] basketAssets,(uint256 amountIn,${template} route)[] acquisitions,${continuation}[] continuations)`
        : `(${token}[] expectedOutputs,${template}[] conversions)`;
      const data=encodeAbiParameters(parseAbiParameters(types),[integer(branch.data)] as never);
      return {...branch,data};
    });
    return encodeAbiParameters(parseAbiParameters('((uint8 kind,uint256 amountIn,bytes data)[] branches)'),[integer({branches})] as never);
  }
  const types=intent===2 ? `(${continuation}[] continuations)` : `(${token}[] expectedOutputs)`;
  return encodeAbiParameters(parseAbiParameters(types),[integer(body)] as never);
}
test('Python and Viem encode all canonical intent bodies, plans and funding without loss',()=>{
  const method=HELPERS_DIAMOND_ABI.find(row=>row.type==='function'&&row.name==='executeExactInput')!;
  for(const row of fixture.cases) {
    assert.equal(encodedBody(row.plan.intent,row.description),row.plan.body,row.name);
    assert.equal(encodeAbiParameters([method.inputs[0]],[integer(row.plan)] as never),row.encodedPlan,row.name);
    assert.equal(encodeFunctionData({abi:[method] as Abi,functionName:'executeExactInput',args:integer([row.plan,row.funding]) as never}),row.calldata,row.name);
  }
});
test('successor payload retains true exact-output and no-hook native V4 identities',()=>{
  for(const row of fixture.adapterCases) {
    const route=row.route;
    assert.equal(encodeAbiParameters(parseAbiParameters(`(bool,uint256,uint256,(uint256,${step}[])[])`),[[
      route.mode==='exactIn',BigInt(route.limit),BigInt(route.deadline),route.branches.map((branch:any)=>[
        route.mode==='exactIn'?BigInt(branch.amountIn):0n,branch.hops.map((hop:any)=>[
          2,hop.pool.token1.address,3000,60])])]]),row.encoded);
  }
});

test('candidate interface exposes 43 base selectors plus true exact-output and universal execution',()=>{
  assert.equal(HELPERS_DIAMOND_FUNCTIONS.length,45);
  const functions=HELPERS_DIAMOND_ABI.filter(row=>row.type==='function');
  assert.equal(functions.length,45);
  assert.ok(functions.some(row=>row.name==='executeExactInput'));
  assert.ok(functions.some(row=>row.name==='swapExactOutput'));
  assert.ok(functions.every(row=>!['swapExactInput','issueFromBasketExactInWithMixedPermits','issueFromBasketExactInWithPermit2',
    'redeemToBasketExactIn','redeemToBasketExactInWithPermit','redeemToBasketExactInWithPermit2',
    'redeemToTokenExactIn','redeemToTokenExactInWithPermit','redeemToTokenExactInWithPermit2',
    'redeemToNativeExactIn','redeemToNativeExactInWithPermit','redeemToNativeExactInWithPermit2'].includes(row.name)));
});
