import { readFileSync } from 'node:fs';
import { encodeFunctionData, encodeFunctionResult } from 'viem';
const abis=JSON.parse(readFileSync('python-candidate/src/cybergold_candidate/protocol-facts-abi.json','utf8'));
const core=`0x${'4'.repeat(40)}`,helpers=`0x${'5'.repeat(40)}`,assets=[`0x${'6'.repeat(40)}`,`0x${'7'.repeat(40)}`];
const values:Record<string,unknown>={basketAssets:assets,basketTargetsPpm:[400000n,600000n],basketGoldRefGramsFp18:[2n**200n,31000000000000000000n],basketCygldPerUnitFp18:[2n**190n,17n],cygldRefGramsFp18:2n**180n,issuanceFeePpm:0n,paused:false,helperFeePpm:15n,totalSupply:200n*10n**18n,maxTotalSupply:250n*10n**18n,effectiveCygldSupplyCap:240n*10n**18n,decimals:18,name:'Gold €',symbol:'XAU'};
const rows=[];
for(const [group,abi] of Object.entries(abis) as [string,any[]][]){
 for(const fn of abi){rows.push({group,name:fn.name,address:group==='core'?core:group==='helpers'?helpers:assets[0],data:encodeFunctionData({abi,functionName:fn.name}),result:encodeFunctionResult({abi,functionName:fn.name,result:values[fn.name]}),value:values[fn.name]});}
}
console.log(JSON.stringify({core,helpers,assets,rows},(_key,v)=>typeof v==='bigint'?v.toString():v));
