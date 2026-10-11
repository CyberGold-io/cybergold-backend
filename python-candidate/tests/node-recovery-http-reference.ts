import {handleRecoverySharesRequest,RecoverySharesApiError} from '../../src/utils/recoverySharesApi';
import {HttpRequestError} from 'viem';
const holder='0x'+'a'.repeat(40),hash='0x'+'b'.repeat(64);
Date.now=()=>1790762400000;
const cases:any[]=[];
for(const query of ['', '?holder=', '?holder=invalid','?holder='+holder,
  '?holder='+holder+'&holder=invalid','?holder=invalid&holder='+holder,
  '?holder='+holder+'&offset=1','?holder='+holder+'&offset=00','?holder='+holder+'&offset=-1',
  '?holder='+holder+'&offset=1&blockHash='+hash,'?holder='+holder+'&offset=1&offset=-1&blockHash='+hash,
  '?holder='+holder+'&offset='+(2n**256n).toString()+'&blockHash='+hash,
  '?holder='+holder+'&offset='+(2n**256n-1n).toString()+'&blockHash='+hash,
  '?holder='+holder+'&blockHash=0x00','?holder='+holder.slice(2),
  '?holder='+holder.toUpperCase(), '?holder='+holder+'&offset='])cases.push({query});
for(const failure of ['ordinary','api-busy','api-unavailable','http503',
  ...['30','0','9007199254740992','invalid','Wed, 30 Sep 2026 10:00:30 GMT',
    'Sep 30 2026 10:00:30 GMT','2026-09-30T10:00:30Z','9/30/2026 10:00:30 GMT',
    '2026-09-30T09:59:59.999Z','2026-09-30T10:00:00.001Z'].map(retry=>'http429:'+retry)])
  cases.push({query:'?holder='+holder,failure});
for(const entry of cases){
  const calls:any[]=[];
  const response=await handleRecoverySharesRequest(new Request('http://fixture/api/recovery/shares'+entry.query),async(address,page)=>{
    calls.push({holder:address,offset:page?.offset?.toString(),blockHash:page?.blockHash??null});
    if(entry.failure==='ordinary')throw new Error('fixture-private-error');
    if(entry.failure==='api-busy')throw new RecoverySharesApiError('Recovery snapshot changed; restart discovery',503,1);
    if(entry.failure==='api-unavailable')throw new RecoverySharesApiError('Recovery RPC capacity exhausted',429,30);
    if(entry.failure?.startsWith('http'))throw new HttpRequestError({url:'http://fixture',status:entry.failure==='http503'?503:429,
      headers:new Headers(entry.failure.startsWith('http429:')?{'Retry-After':entry.failure.slice(8)}:{})});
    return {fixture:'portfolio'};
  });
  Object.assign(entry,{status:response.status,result:await response.json(),cache:response.headers.get('cache-control'),
    retry:response.headers.get('retry-after'),calls});
}
console.log(JSON.stringify(cases));
