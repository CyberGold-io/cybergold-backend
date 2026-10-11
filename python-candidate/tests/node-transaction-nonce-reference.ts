import { createPublicClient, custom } from 'viem';

const rows=[];
for (const nonce of [0n,7n,BigInt(Number.MAX_SAFE_INTEGER),2n**53n,2n**100n+1n]) {
  const owner=`0x${'1'.repeat(40)}` as const;
  const calls=[];
  const client=createPublicClient({transport:custom({async request({method,params}) {
    calls.push({method,params});
    return `0x${nonce.toString(16)}`;
  }},{retryCount:0})});
  try {
    const value=await client.getTransactionCount({address:owner,blockTag:'pending'});
    rows.push({owner,nonce:nonce.toString(),calls,value:String(value)});
  } catch {
    rows.push({owner,nonce:nonce.toString(),calls,error:true});
  }
}
console.log(JSON.stringify(rows));
