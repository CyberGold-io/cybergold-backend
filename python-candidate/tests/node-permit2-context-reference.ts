import { encodeFunctionData, encodeFunctionResult, parseAbi } from 'viem';
const helpers=`0x${'5'.repeat(40)}` as const;
const permit2='0x000000000022D473030F116dDEE9F6B43aC78BA3' as const;
const owners=[`0x${'1'.repeat(40)}`,`0x${'2'.repeat(40)}`] as const;
const tokens=[`0x${'6'.repeat(40)}`,`0x${'7'.repeat(40)}`] as const;
const abi=parseAbi(['function permit2() view returns (address)','function nonceBitmap(address,uint256) view returns (uint256)','function allowance(address,address) view returns (uint256)']);
console.log(JSON.stringify({helpers,permit2,owners,tokens,
  router:{data:encodeFunctionData({abi,functionName:'permit2'}),result:encodeFunctionResult({abi,functionName:'permit2',result:permit2})},
  nonceRows:owners.flatMap((owner,index)=>[0n,1n].map(word=>({owner,word:word.toString(),data:encodeFunctionData({abi,functionName:'nonceBitmap',args:[owner,word]}),
    result:encodeFunctionResult({abi,functionName:'nonceBitmap',result:index===0?(word===0n?2n**256n-1n:1n):5n})}))),
  allowanceRows:owners.flatMap((owner,index)=>tokens.map((token,offset)=>({owner,token,data:encodeFunctionData({abi,functionName:'allowance',args:[owner,permit2]}),
    result:encodeFunctionResult({abi,functionName:'allowance',result:2n**255n+BigInt(index+offset)}),value:(2n**255n+BigInt(index+offset)).toString()})))}));
