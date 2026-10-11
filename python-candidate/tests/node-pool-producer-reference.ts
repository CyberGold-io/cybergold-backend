import { readFileSync } from 'node:fs';
import { encodeFunctionData, encodeFunctionResult } from 'viem';
const abi=JSON.parse(readFileSync('python-candidate/src/cybergold_candidate/pool-producer-abi.json','utf8'));
const tokenA=`0x${'1'.repeat(40)}`,tokenB=`0x${'2'.repeat(40)}`,pool=`0x${'3'.repeat(40)}`,factory=`0x${'4'.repeat(40)}`;
const rows=[
 {group:'factory',name:'getPool',address:factory,args:[tokenA,tokenB,3000],value:pool},
 {group:'pool',name:'slot0',address:pool,args:[],value:[2n**150n,-12,1,2,3,4,true]},
 {group:'pool',name:'liquidity',address:pool,args:[],value:2n**100n},
 {group:'token',name:'balanceOf',address:tokenA,args:[pool],value:2n**200n},
 {group:'token',name:'balanceOf',address:tokenB,args:[pool],value:2n**201n},
].map(row=>({...row,data:encodeFunctionData({abi:abi[row.group],functionName:row.name,args:row.args}),result:encodeFunctionResult({abi:abi[row.group],functionName:row.name,result:row.value})}));
const empty=encodeFunctionResult({abi:abi.factory,functionName:'getPool',result:`0x${'0'.repeat(40)}`});
console.log(JSON.stringify({tokenA,tokenB,pool,factory,rows,empty},(_key,v)=>typeof v==='bigint'?v.toString():v));
