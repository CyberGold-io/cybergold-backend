import {executeAdaptiveBlockRanges} from '../../src/server/onchain-indexer/adaptiveLogPagination';

const cases:any[]=[];
for(const maximumWidth of [0,1,2,4,8]) for(const approved of [false,true])
  for(const caps of [{},{maxAttempts:2},{maxRanges:2},{maxCardinality:2},{maxAttempts:0}]) {
    const input={baseRange:{fromBlock:100n,toBlock:107n},maximumWidth,approved,...caps};
    const calls:any[]=[];let result:any=null,error:string|null=null;
    try {
      result=await executeAdaptiveBlockRanges({...input,
        requestRange:async(attempt)=>{
          calls.push(attempt);
          if(attempt.range.toBlock-attempt.range.fromBlock+1n>BigInt(maximumWidth)) throw new Error('range-limit');
          return [attempt.range.fromBlock.toString()];
        },shouldSplitRequestFailure:()=>approved,validateRange:async(value)=>value as string[]});
    } catch(failure){error=(failure as Error).message;}
    cases.push({input,calls,result,error});
  }
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?{$bigint:value.toString()}:value));
