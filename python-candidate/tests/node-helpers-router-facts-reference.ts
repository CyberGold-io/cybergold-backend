import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { encodeFunctionData, encodeFunctionResult, toFunctionSelector } from 'viem';
import { HELPERS_DIAMOND_ABI } from '../../src/contracts/generated/helpersDiamond';
const {helpers:abi}=JSON.parse(readFileSync('python-candidate/src/cybergold_candidate/helpers-router-facts-abi.json','utf8'));
const core=`0x${'4'.repeat(40)}`, helpers=`0x${'5'.repeat(40)}`;
const values:Record<string,unknown>={helperFeePpm:0n,permit2:`0x${'6'.repeat(40)}`,
  wrappedNative:`0x${'7'.repeat(40)}`,owner:`0x${'8'.repeat(40)}`,
  approvedAdapters:[`0x${'9'.repeat(40)}`,`0x${'0'.repeat(40)}`],paused:false};
const rows=abi.map((fn:any)=>{
  assert.deepEqual(fn,HELPERS_DIAMOND_ABI.find(entry=>entry.type==='function'&&entry.name===fn.name));
  return {name:fn.name,data:encodeFunctionData({abi,functionName:fn.name}),
    result:encodeFunctionResult({abi,functionName:fn.name,result:values[fn.name]})};
});
const historical=JSON.parse(readFileSync('python-candidate/src/cybergold_candidate/helpers-historical-probe-abi.json','utf8'));
const selectorMethods = ['executeExactInput', 'issueFromTokenExactOutWithPermit',
  'issueFromBasketExactInWithMixedPermits', 'issueFromBasketExactOutWithMixedPermits'];
const selectors = Object.fromEntries(selectorMethods.map(name => {
  const entry = [...HELPERS_DIAMOND_ABI,...historical].find(entry => entry.type === 'function' && entry.name === name);
  assert.ok(entry && entry.type === 'function');
  return [name, toFunctionSelector(entry)];
}));
console.log(JSON.stringify({core,helpers,rows,selectors}));
