import { encodeFunctionData, encodeFunctionResult, keccak256, parseAbi, stringToHex } from 'viem';
const abi=parseAbi(['function getRoleMemberCount(bytes32 role) view returns (uint256)','function getRoleMember(bytes32 role,uint256 index) view returns (address)']);
const surfaces={core:['DEFAULT_ADMIN_ROLE','UPGRADER_ROLE'],staking:['DEFAULT_ADMIN_ROLE','UPGRADER_ROLE','ALLOCATOR_ROLE','WITHDRAWER_ROLE'],'governance-diamond':['DEFAULT_ADMIN_ROLE','UPGRADER_ROLE','PROPOSER_ROLE','EXECUTOR_ROLE','CANCELLER_ROLE']};
console.log(JSON.stringify(Object.entries(surfaces).map(([surface,names],surfaceIndex)=>({surface,address:`0x${String(surfaceIndex+1).repeat(40)}`,
  roles:names.map((name,index)=>{
    const hash=name==='DEFAULT_ADMIN_ROLE'?`0x${'0'.repeat(64)}` as const:keccak256(stringToHex(name));
    const count=name==='CANCELLER_ROLE'?51n:BigInt(index===1?0:2);
    return {id:name,count:count.toString(),countCall:{data:encodeFunctionData({abi,functionName:'getRoleMemberCount',args:[hash]}),result:encodeFunctionResult({abi,functionName:'getRoleMemberCount',result:count})},
      members:Array.from({length:Number(count>50n?50n:count)},(_,memberIndex)=>{
        const address=`0x${String(memberIndex%2+4).repeat(40)}` as const;
        return {address,data:encodeFunctionData({abi,functionName:'getRoleMember',args:[hash,BigInt(memberIndex)]}),result:encodeFunctionResult({abi,functionName:'getRoleMember',result:address})};
      })};
  })}))));
