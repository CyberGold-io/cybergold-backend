import {shouldSplitDirectProviderLogRequest} from '../../src/server/onchain-indexer/adaptiveLogPagination';
const cases:any[]=[];
for(const name of ['HttpRequestError','RpcRequestError','Error'])for(const status of [null,413,429,503])
 for(const code of [null,-32005,-32016,-32000,'-32005']){
  const value={name,status,code};cases.push({value,result:shouldSplitDirectProviderLogRequest(value)});
 }
console.log(JSON.stringify(cases));
