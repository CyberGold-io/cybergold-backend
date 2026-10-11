import { createPublicClient, custom } from 'viem';
import { mainnet } from 'viem/chains';
const configs = [
 {base:'0',priority:'0'}, {base:'1',priority:'0'}, {base:'11',priority:'7'},
 {base:(2n**150n+3n).toString(),priority:(2n**100n+1n).toString()},
 {base:'100',priority:'0'}, {base:'100',fallback:true,gas:'123'},
 {base:'100',fallback:true,gas:'90'}, {base:null,priority:'1'},
 {base:'100',fallback:true,gasFailure:true},
];
const rows=[];
for (const config of configs) {
 const calls=[];
 const client=createPublicClient({chain:mainnet,transport:custom({async request({method,params}) {
  calls.push({method,params:params??[]});
  if(method==='eth_getBlockByNumber') return {number:'0x65',hash:`0x${'a'.repeat(64)}`,timestamp:'0x6a000001',
   ...(config.base===null?{}:{baseFeePerGas:`0x${BigInt(config.base).toString(16)}`})};
  if(method==='eth_maxPriorityFeePerGas'&&!config.fallback)return `0x${BigInt(config.priority!).toString(16)}`;
  if(method==='eth_gasPrice'&&!config.gasFailure)return `0x${BigInt(config.gas!).toString(16)}`;
  throw new Error('synthetic unsupported provider method');
 }},{retryCount:0})});
 try {
  const fees=await client.estimateFeesPerGas();rows.push({config,calls,fees});
 } catch {rows.push({config,calls,error:true});}
}
console.log(JSON.stringify(rows,(_,value)=>typeof value==='bigint'?value.toString():value));
