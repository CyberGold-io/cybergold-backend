import { encodeFunctionData, encodeFunctionResult, parseAbi } from 'viem';
const abi = parseAbi(['function name() view returns (string)', 'function nonces(address) view returns (uint256)']);
console.log(JSON.stringify({ core:`0x${'4'.repeat(40)}`, helpers:`0x${'5'.repeat(40)}`,
  name:{data:encodeFunctionData({abi,functionName:'name'}),result:encodeFunctionResult({abi,functionName:'name',result:'CyberGold Ω'}),value:'CyberGold Ω'},
  rows:[`0x${'1'.repeat(40)}`,`0x${'2'.repeat(40)}`].map((owner,index)=>({owner,
    data:encodeFunctionData({abi,functionName:'nonces',args:[owner as `0x${string}`]}),
    result:encodeFunctionResult({abi,functionName:'nonces',result:2n**255n+BigInt(index)}),value:(2n**255n+BigInt(index)).toString()}))}));
