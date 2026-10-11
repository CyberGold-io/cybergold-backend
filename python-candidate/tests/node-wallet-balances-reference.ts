import { encodeFunctionData, encodeFunctionResult, erc20Abi, parseAbi } from 'viem';
const holders = [`0x${'1'.repeat(40)}`, `0x${'2'.repeat(40)}`] as const;
const core = `0x${'4'.repeat(40)}` as const;
const multicall = '0xca11bde05977b3631167028862be2a173976ca11';
const addresses = [core, '0x68749665FF8D2d112Fa859AA293F07A622782F38',
  '0x45804880De22913dAFE09f4980848ECE6EcbAf78', '0xdAC17F958D2ee523a2206206994597C13D831ec7',
  '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'] as const;
const aggregateAbi = parseAbi(['function aggregate3((address target,bool allowFailure,bytes callData)[] calls) payable returns ((bool success,bytes returnData)[] results)',
  'function getEthBalance(address addr) view returns (uint256 balance)']);
console.log(JSON.stringify({core, multicall, rows: holders.map((holder, index) => {
  const calls = [...addresses.map(target => ({target, allowFailure:true,
    callData:encodeFunctionData({abi:erc20Abi,functionName:'balanceOf',args:[holder]})})),
    {target:multicall, allowFailure:true, callData:encodeFunctionData({abi:aggregateAbi,functionName:'getEthBalance',args:[holder]})}];
  const members = [...addresses.map(() => ({success:true,
    returnData:encodeFunctionResult({abi:erc20Abi,functionName:'balanceOf',result:2n**255n+BigInt(index)})})),
    {success:true,returnData:encodeFunctionResult({abi:aggregateAbi,functionName:'getEthBalance',result:2n**200n+BigInt(index)})}];
  return {holder, calls, members,
    data:encodeFunctionData({abi:aggregateAbi,functionName:'aggregate3',args:[calls]}),
    result:encodeFunctionResult({abi:aggregateAbi,functionName:'aggregate3',result:members}),
    partialNativeResult:encodeFunctionResult({abi:aggregateAbi,functionName:'aggregate3',result:[...members.slice(0,6),{success:false,returnData:'0x'}]}),
    value:(2n**255n+BigInt(index)).toString(), native:`0x${(2n**200n+BigInt(index)).toString(16)}`};
})}));
