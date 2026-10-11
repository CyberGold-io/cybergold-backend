import { createPublicClient, custom, encodeFunctionResult, parseAbi } from 'viem';
const abi=parseAbi(['function nonce() view returns (uint256)', 'function getTransactionHash(address to,uint256 value,bytes data,uint8 operation,uint256 safeTxGas,uint256 baseGas,uint256 gasPrice,address gasToken,address refundReceiver,uint256 nonce) view returns (bytes32)']);
const rows=[];
for(let index=0;index<3;index++) {
  const address=`0x${String(index+1).repeat(40)}` as const;
  const payload={address,to:`0x${'4'.repeat(40)}`,value:(2n**200n+BigInt(index)).toString(),data:index?'0xabcdef00':'0x',operation:index?1:0,safeTxGas:'120000',baseGas:'2',gasPrice:'3',gasToken:`0x${'0'.repeat(40)}`,refundReceiver:`0x${'5'.repeat(40)}`,nonce:(2n**255n+BigInt(index)).toString()};
  const calls=[];
  let result=encodeFunctionResult({abi,functionName:'nonce',result:BigInt(payload.nonce)});
  const client=createPublicClient({transport:custom({async request({method,params}) {calls.push({method,params});return result;}},{retryCount:0})});
  const nonce=await client.readContract({address,abi,functionName:'nonce'});
  result=encodeFunctionResult({abi,functionName:'getTransactionHash',result:`0x${String(index+6).repeat(64)}`});
  const safeTxHash=await client.readContract({address,abi,functionName:'getTransactionHash',args:[payload.to as `0x${string}`,BigInt(payload.value),payload.data as `0x${string}`,payload.operation,BigInt(payload.safeTxGas),BigInt(payload.baseGas),BigInt(payload.gasPrice),payload.gasToken as `0x${string}`,payload.refundReceiver as `0x${string}`,BigInt(payload.nonce)]});
  rows.push({payload,calls,nonce:String(nonce),safeTxHash});
}
console.log(JSON.stringify(rows));
