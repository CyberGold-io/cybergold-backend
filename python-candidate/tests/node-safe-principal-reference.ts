import assert from 'node:assert/strict';
import { encodeFunctionData, encodeFunctionResult } from 'viem';
// Retained App SAFE_ABI signatures, independently checked against the public
// selectors used by its existing getOwners/getThreshold consumers.
const abi = [
  {type:'function',name:'getOwners',inputs:[],outputs:[{name:'',type:'address[]'}],stateMutability:'view'},
  {type:'function',name:'getThreshold',inputs:[],outputs:[{name:'',type:'uint256'}],stateMutability:'view'},
] as const;
const first=`0x${'1'.repeat(40)}` as const, second=`0x${'2'.repeat(40)}` as const, eoa=`0x${'3'.repeat(40)}` as const;
const ownersData=encodeFunctionData({abi,functionName:'getOwners'});
const thresholdData=encodeFunctionData({abi,functionName:'getThreshold'});
assert.equal(ownersData,'0xa0e67e2b'); assert.equal(thresholdData,'0xe75235b8');
const rows=[first,second].map((address,index)=>({address,code:index===0?'0x6001':'0x6002',
  owners:index===0?[second]:[first,second],threshold:index===0?'1':(2n**200n).toString(),
  calls:[{data:ownersData,result:encodeFunctionResult({abi,functionName:'getOwners',result:index===0?[second]:[first,second]})},
    {data:thresholdData,result:encodeFunctionResult({abi,functionName:'getThreshold',result:index===0?1n:2n**200n})}]}));
console.log(JSON.stringify({core:first,eoa,rows}));
