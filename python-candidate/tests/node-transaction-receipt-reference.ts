import { createPublicClient, custom } from 'viem';

const hash=`0x${'a'.repeat(64)}` as const;
const receipt={transactionHash:hash,transactionIndex:'0x0',blockHash:`0x${'b'.repeat(64)}`,
  blockNumber:`0x${(2n**60n+1n).toString(16)}`,from:`0x${'1'.repeat(40)}`,to:`0x${'2'.repeat(40)}`,
  cumulativeGasUsed:'0x5208',gasUsed:'0x5208',effectiveGasPrice:'0x1',contractAddress:null,
  logsBloom:`0x${'0'.repeat(512)}`,type:'0x2',status:'0x1',
  logs:[{address:`0x${'2'.repeat(40)}`,data:`0x${'c'.repeat(64)}`,topics:[`0x${'d'.repeat(64)}`],
    blockNumber:'0x65',blockHash:`0x${'b'.repeat(64)}`,transactionHash:hash,transactionIndex:'0x0',logIndex:'0x0',removed:false}]};
const rows=[];
for(const raw of [receipt,{...receipt,status:'0x0'},null]) {
  const calls=[];
  const client=createPublicClient({transport:custom({async request({method,params}) {
    calls.push({method,params});return raw;
  }},{retryCount:0})});
  try {
    const value=await client.getTransactionReceipt({hash});
    rows.push({hash,raw,calls,receipt:{transactionHash:value.transactionHash,blockHash:value.blockHash,
      blockNumber:String(value.blockNumber),status:value.status,
      logs:value.logs.map(({address,data,topics})=>({address,data,topics}))}});
  } catch {
    rows.push({hash,raw,calls,receipt:null});
  }
}
console.log(JSON.stringify(rows));
