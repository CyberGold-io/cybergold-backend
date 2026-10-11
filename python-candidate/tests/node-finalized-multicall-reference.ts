import {parseAbi,encodeFunctionData,encodeFunctionResult,createPublicClient,http} from 'viem';
import {createBoundedFinalizedMulticallClient,planBoundedMulticallBatches} from '../../src/server/onchain-indexer/finalizedSnapshotMulticall';
const hash='0x'+'a'.repeat(64),address='0x'+'1'.repeat(40);
const abi=parseAbi(['function fixture(uint256 value) view returns (uint256)']);
const limits={maxCalls:100,maxTotalCalldataBytes:10000,maxCallsPerBatch:2,maxBatchCalldataBytes:1000,maxProviderRequests:10};
const plans:any[]=[];
for(const sizes of [[],[4],[4,36,68],[1000],[1001],[0],[-1],[1.5],Array(101).fill(1),Array(20).fill(600),Array(70).fill(36)]){
 let result,error;try{result=planBoundedMulticallBatches(sizes,limits);}catch(e){error=(e as Error).message;}plans.push({sizes,expected:error?{error}:{result}});
}
const cases:any[]=[];
for(const mode of ['normal','contract-failure','provider-failure','wrong-count','wrong-anchor','not-canonical','block-number','block-tag','call-cap','byte-cap','provider-cap','bad-provider-cap']){
 const calls:any[]=[];const selected={...limits,...(mode==='call-cap'?{maxCalls:3}:{}),...(mode==='byte-cap'?{maxTotalCalldataBytes:100}:{}),
  ...(mode==='provider-cap'?{maxProviderRequests:2}:{}),...(mode==='bad-provider-cap'?{maxProviderRequests:0}:{})};
 const client=createBoundedFinalizedMulticallClient({blockHash:hash,limits:selected,client:{
  multicall:async(input:any)=>{calls.push(input);if(mode==='provider-failure')throw new Error('fixture provider failure');
   return input.contracts.slice(0,mode==='wrong-count'?0:undefined).map((r:any)=>mode==='contract-failure'&&r.args[0]===2n?
    {status:'failure',error:new Error('fixture contract failure')}:{status:'success',result:r.args[0]+2n});},readContract:async()=>{throw new Error('unexpected direct read');}}});
 const waves:any[]=[];
 for(const wave of [[1n,2n,3n,4n],[5n]]){
  const requests=wave.map(value=>({address,abi,functionName:'fixture',args:[value],blockHash:mode==='wrong-anchor'?'0x'+'b'.repeat(64):hash,
   requireCanonical:mode!=='not-canonical',...(mode==='block-number'?{blockNumber:1n}:{}),...(mode==='block-tag'?{blockTag:'finalized'}:{})}));
  const settled=await Promise.allSettled(requests.map(request=>client.readContract(request)));
  waves.push(settled.map(value=>value.status==='fulfilled'?{result:value.value}:{error:value.reason.message}));
 }
 cases.push({mode,limits:selected,expected:{waves,calls}});
}
const codec:any[]=[];
for(const [declaration,args,result] of [
 ['function amount(uint256 x) view returns(uint256)',[2n**240n],2n**220n],
 ['function asset(address x) view returns(address)',[address],address],
 ['function tag(bytes32 x) view returns(bytes32)',['0x'+'f'.repeat(64)],'0x'+'e'.repeat(64)],
 ['function items(uint256[] x) view returns(uint256[])',[[1n,2n**200n]],[3n,4n]],
 ['function viewPool() view returns((uint256 shares,address asset,bytes32 id) pool)',[],{shares:2n**190n,asset:address,id:'0x'+'d'.repeat(64)}],
 ['function labels() view returns(string,bool,uint8)',[],['CG',true,18]],
] as any[]){
 const a=parseAbi([declaration]),name=a[0].name;
 codec.push({request:{address,abi:a,functionName:name,args},result,encoded:encodeFunctionData({abi:a,functionName:name,args}),
  returnData:encodeFunctionResult({abi:a,functionName:name,result})});
}
const aggregateAbi=parseAbi(['function aggregate3((address target,bool allowFailure,bytes callData)[] calls) payable returns((bool success,bytes returnData)[] results)']);
const aggregateResult=encodeFunctionResult({abi:aggregateAbi,functionName:'aggregate3',result:[
 {success:true,returnData:encodeFunctionResult({abi,functionName:'fixture',result:99n})},{success:false,returnData:'0x'}]});
const wireCalls:any[]=[];
const transport=createPublicClient({transport:http('http://synthetic',{retryCount:0,fetchFn:async(_url,init:any)=>{
 const body=JSON.parse(init.body);wireCalls.push(body.params);return new Response(JSON.stringify({result:aggregateResult}),{headers:{'Content-Type':'application/json'}});}})});
const wireInput={contracts:[1n,2n].map(value=>({address,abi,functionName:'fixture',args:[value]})),allowFailure:true,blockHash:hash,requireCanonical:true,
 multicallAddress:'0xca11bde05977b3631167028862be2a173976ca11',batchSize:65536};
const wireResults=await transport.multicall(wireInput as any);
console.log(JSON.stringify({plans,cases,codec,aggregate:{input:wireInput,response:aggregateResult,calls:wireCalls,
 results:wireResults.map(value=>value.status==='success'?{status:'success',result:value.result}:{status:'failure'})}},(_key,value)=>typeof value==='bigint'?value.toString():value));
