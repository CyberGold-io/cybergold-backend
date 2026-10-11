import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { encodeFunctionData, encodeFunctionResult } from 'viem';
import { CORE_DIAMOND_ABI } from '../../src/contracts/generated/coreDiamond';
const {core:abi}=JSON.parse(readFileSync('python-candidate/src/cybergold_candidate/governance-core-facts-abi.json','utf8'));
const core=`0x${'4'.repeat(40)}`;
const values:Record<string,unknown>={treasury:`0x${'6'.repeat(40)}`,basketConfigHash:`0x${'7'.repeat(64)}`,
  issuanceFeePpm:0n,redemptionFeePpm:15n,MAX_FEE_PPM:1000000n,maxTotalSupply:2n**255n,totalSupply:2n**200n,
  safeWallet:`0x${'8'.repeat(40)}`};
const rows=abi.map((fn:any)=>{
  assert.deepEqual(fn,CORE_DIAMOND_ABI.find(entry=>entry.type==='function'&&entry.name===fn.name));
  return {name:fn.name,data:encodeFunctionData({abi,functionName:fn.name}),
    result:encodeFunctionResult({abi,functionName:fn.name,result:values[fn.name]})};
});
console.log(JSON.stringify({core,rows}));
