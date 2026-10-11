import { encodeFunctionData, encodeFunctionResult } from 'viem';
import { CORE_DIAMOND_ABI } from '../../src/contracts/generated/coreDiamond.ts';
const core=`0x${'1'.repeat(40)}` as const;
console.log(JSON.stringify([0n,1n,2n**200n+1n].map((shares,index)=>{
  const holder=`0x${String(index+2).repeat(40)}` as const,asset=`0x${'5'.repeat(40)}` as const,minRawOut=BigInt(index),rawOut=shares*3n;
  return {core,payload:{holder,asset,shares:shares.toString(),minRawOut:minRawOut.toString()},rawOut:rawOut.toString(),
    call:{from:holder,to:core,data:encodeFunctionData({abi:CORE_DIAMOND_ABI,functionName:'redeemRecoveryShares',args:[asset,shares,holder,minRawOut]})},
    result:encodeFunctionResult({abi:CORE_DIAMOND_ABI,functionName:'redeemRecoveryShares',result:rawOut})};
})));
