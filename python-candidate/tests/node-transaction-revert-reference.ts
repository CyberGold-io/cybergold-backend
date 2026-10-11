import { createPublicClient, custom } from 'viem';
const rows=[];
for (const type of ['0x0','0x1','0x2','0x3','0x4']) {
 const transaction={hash:'0x'+'a'.repeat(64),from:'0x'+'1'.repeat(40),to:'0x'+'2'.repeat(40),input:'0x1234',
  value:'0x'+(2n**200n).toString(16),gas:'0x5208',nonce:'0x7',type,gasPrice:'0x3',maxFeePerGas:'0x5',maxPriorityFeePerGas:'0x1',
  blockNumber:null,blockHash:null,transactionIndex:null,...(type==='0x1'?{accessList:[]}:{})};
 const calls=[];
 const client=createPublicClient({transport:custom({async request({method,params}) {
  calls.push({method,params});if(method==='eth_getTransactionByHash')return transaction;
  if(method==='eth_call')return '0x1234';throw new Error(method);
 }},{retryCount:0})});
 const {from:account,...txn}=await client.getTransaction({hash:transaction.hash as `0x${string}`});
 await client.call({...txn,account,data:txn.input,gasPrice:txn.type!=='eip1559'?txn.gasPrice:undefined,
  maxFeePerGas:txn.type==='eip1559'?txn.maxFeePerGas:undefined,maxPriorityFeePerGas:txn.type==='eip1559'?txn.maxPriorityFeePerGas:undefined});
 rows.push({transaction,call:calls[1]});
}
console.log(JSON.stringify(rows));
