import { createPublicClient, custom, encodeFunctionData, encodeFunctionResult, maxUint256, parseAbi } from 'viem';
const tokenAbi=parseAbi(['function approve(address spender,uint256 amount) returns (bool)']);
const helpersAbi=parseAbi(['function permit2() view returns (address)']);
const helpers=`0x${'1'.repeat(40)}` as const,permit2=`0x${'2'.repeat(40)}` as const;
const output=[];
for (const gas of [0n,21000n,2n**100n+1n]) {
  const owner=`0x${String(output.length+3).repeat(40)}` as const,token=`0x${'6'.repeat(40)}` as const,calls:unknown[]=[];
  const client=createPublicClient({transport:custom({request:async({method,params})=>{
    calls.push({method,params});
    if(method==='eth_estimateGas')return `0x${gas.toString(16)}`;
    throw new Error(`Unexpected supplier method ${method}`);
  }})});
  const estimated=await client.estimateContractGas({account:owner,address:token,abi:tokenAbi,functionName:'approve',args:[permit2,maxUint256]});
  output.push({helpers,permit2,payload:{owner,token},gas:estimated.toString(),calls,
    helpersCall:{to:helpers,data:encodeFunctionData({abi:helpersAbi,functionName:'permit2'})},
    helpersResult:encodeFunctionResult({abi:helpersAbi,functionName:'permit2',result:permit2})});
}
console.log(JSON.stringify(output));
