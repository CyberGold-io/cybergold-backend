import { createPublicClient, custom, encodeFunctionResult, parseAbi } from 'viem';
const abi=parseAbi(['function execTransaction(address to,uint256 value,bytes data,uint8 operation,uint256 safeTxGas,uint256 baseGas,uint256 gasPrice,address gasToken,address refundReceiver,bytes signatures) payable returns (bool success)']);
const rows=[];
for(let index=0;index<3;index++) {
  const payload={address:`0x${String(index+1).repeat(40)}` as const,executor:`0x${'4'.repeat(40)}` as const,
    executorNonce:String(index+7),to:`0x${'5'.repeat(40)}` as const,value:(2n**200n+BigInt(index)).toString(),
    data:(index?'0xabcdef00':'0x') as `0x${string}`,operation:index?1:0,safeTxGas:'120000',baseGas:'2',gasPrice:'3',
    gasToken:`0x${'0'.repeat(40)}` as const,refundReceiver:`0x${'6'.repeat(40)}` as const,
    signatures:`0x${'ab'.repeat(65*(index+1))}` as `0x${string}`};
  const calls:unknown[]=[];const expected=index!==1;
  const encoded=encodeFunctionResult({abi,functionName:'execTransaction',result:expected});
  const client=createPublicClient({transport:custom({request:async({method,params})=>{calls.push({method,params});return encoded;}},{retryCount:0})});
  const simulation=await client.simulateContract({account:payload.executor,address:payload.address,abi,functionName:'execTransaction',
    args:[payload.to,BigInt(payload.value),payload.data,payload.operation,BigInt(payload.safeTxGas),BigInt(payload.baseGas),
      BigInt(payload.gasPrice),payload.gasToken,payload.refundReceiver,payload.signatures],nonce:Number(payload.executorNonce)});
  rows.push({payload,calls,result:simulation.result,encoded});
}
console.log(JSON.stringify(rows));
