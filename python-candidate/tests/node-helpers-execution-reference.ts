import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { createPublicClient, custom, encodeFunctionResult, type Abi } from 'viem';
import { HELPERS_DIAMOND_ABI } from '../../src/contracts/generated/helpersDiamond';
const abi=JSON.parse(readFileSync('python-candidate/src/cybergold_candidate/helpers-execution-abi.json','utf8')) as Abi;
const helpers=`0x${'1'.repeat(40)}` as const,owner=`0x${'2'.repeat(40)}` as const;
type Parameter={type:string;name?:string;components?:Parameter[]};
function value(parameter:Parameter,wide:boolean):unknown {
  const array=parameter.type.match(/^(.*)\[([0-9]*)\]$/);
  if(array)return Array.from({length:array[2]?Number(array[2]):2},()=>value({...parameter,type:array[1]},wide));
  if(parameter.type==='tuple')return Object.fromEntries(parameter.components!.map(part=>[part.name,value(part,wide)]));
  if(parameter.type==='address')return `0x${'3'.repeat(40)}`;
  if(parameter.type.startsWith('uint')||parameter.type.startsWith('int'))return parameter.type.endsWith('8')?1:wide?2n**100n+1n:7n;
  if(parameter.type==='bool')return true;
  if(parameter.type.startsWith('bytes'))return `0x${'ab'.repeat(parameter.type==='bytes'?65:Number(parameter.type.slice(5)))}`;
  throw new Error(parameter.type);
}
const rows=[];
for(const method of abi) {
 if(method.type!=='function')continue;
 assert.deepEqual(method, HELPERS_DIAMOND_ABI.find(entry=>entry.type==='function'&&entry.name===method.name));
 for(const wide of [false,true]) {
  const args=method.inputs.map(part=>value(part as Parameter,wide));
  if(method.name.endsWith('WithMixedPermits')) {
   const inputParameter={...method.inputs[1],type:'tuple'} as Parameter;
   const inputs=[0,1,2].map(authorization=>{
    const input=value(inputParameter,wide) as Record<string,unknown>;
    return {...input,token:`0x${String(authorization+3).repeat(40)}`,authorization,maximumInputAmount:input.maximumInputAmount,
      permit:{...(input.permit as Record<string,unknown>),value:authorization===1?input.maximumInputAmount:0n}};
   });
   const permit2=args[2] as Record<string,unknown>;
   args[1]=inputs;
   args[2]={...permit2,permit:{...(permit2.permit as Record<string,unknown>),
     permitted:[{token:inputs[2].token,amount:inputs[2].maximumInputAmount}]}};
  }
  const output=method.outputs.map(part=>value(part as Parameter,wide));
  const encoded=encodeFunctionResult({abi,functionName:method.name,result:output.length===1?output[0]:output} as never);
  const gas=wide?2n**100n+1n:21000n+BigInt(rows.length);
  const calls:unknown[]=[];
  const client=createPublicClient({transport:custom({request:async({method,params})=>{
    calls.push({method,params});
    if(method==='eth_call')return encoded;
    if(method==='eth_estimateGas')return `0x${gas.toString(16)}`;
    throw new Error(method);
  }},{retryCount:0})});
  const nativeValue=method.name==='issueFromNativeExactOut'?(wide?2n**100n+1n:0n):undefined;
  const simulation=await client.simulateContract({account:owner,address:helpers,abi,functionName:method.name,args,value:nativeValue} as never);
  const estimated=await client.estimateContractGas(simulation.request);
  rows.push({helpers,payload:{owner,operation:method.name,args,...(nativeValue===undefined?{}:{value:nativeValue.toString()})},
    calls,encoded,gas:estimated.toString()});
 }
}
console.log(JSON.stringify(rows,(_,item)=>typeof item==='bigint'?item.toString():item));
