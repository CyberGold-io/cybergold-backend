import {retainedForkControl} from './retained_fork_control';
const core='0x'+'a'.repeat(40),hash='0x'+'1'.repeat(64);
const previous={generation:'old',forkBlock:'1000',forkBlockHash:hash},current={generation:'next',forkBlock:'1200',forkBlockHash:'0x'+'2'.repeat(64)};
const cases:any[]=[];
for(const action of ['prepare','apply','status'])for(const mode of ['normal','no-config','mainnet','busy','schema-error','rpc-chain','current-number','current-hash','previous-number','rpc-error','db-error'])cases.push({action,mode});
for(const mode of ['normal','previous-number'])cases.push({action:'apply',mode,older:true});
for(const entry of cases){
 const x=entry;const calls:any[]=[];const runtime={lastReconciledAtMs:12,lastReconciliationReceipt:{retained:true}};
 const config=x.mode==='no-config'?null:{chainId:x.mode==='mainnet'?1n:31338n,coreAddress:core,startBlock:100n};
 const anchor=(value:any)=>({...value,forkBlock:BigInt(value.forkBlock)});
 const input={action:x.action,previous:anchor(previous),current:anchor({...current,...(x.older?{forkBlock:'800'}:{})})};
 const rows=[['sandbox_fork_generation',previous.generation],['sandbox_fork_block',previous.forkBlock],
 ['sandbox_fork_block_hash',hash],['sandbox_fork_projection_status','ready']].map(([state_key,state_value])=>({state_key,state_value}));
 const query=async(sql:string,params:any[])=>{calls.push('query');if(x.mode==='db-error')throw new Error('fixture database failure');
  if(sql.includes('SELECT')&&params.length===3)return {rows};
  if(sql.includes('SELECT'))return {rows:[{state_key:'last_scanned_block',state_value:'900'}]};return {rows:[]};};
 const client={getChainId:async()=>{calls.push('chain');return x.mode==='rpc-chain'?1:31338;},
  getBlock:async({blockNumber}:any)=>{calls.push('block:'+blockNumber);
   if(x.mode==='rpc-error')throw new Error('fixture RPC failure');
   const isCurrent=blockNumber===input.current.forkBlock;
   return {number:BigInt(isCurrent&&x.mode==='current-number'||!isCurrent&&x.mode==='previous-number'?42:blockNumber),
    hash:isCurrent?(x.mode==='current-hash'?hash:input.current.forkBlockHash):hash};}};
 const controller=retainedForkControl({config,runtime,query,client,schema:async()=>{calls.push('schema');if(x.mode==='schema-error')throw new Error('fixture schema failure');},
  lock:async(key:any,fn:any)=>{calls.push('lock:'+key);return x.mode==='busy'?{acquired:false}:{acquired:true,result:await fn()};},
  transaction:async(fn:any)=>{calls.push('transaction');return fn(query);}});
 let result,error;
 try{result=x.action==='status'?await controller.status():await controller.transition(input);}catch(failure){error=(failure as Error).message;}
 Object.assign(entry,{config:config?{...config,chainId:config.chainId.toString(),startBlock:config.startBlock.toString()}:null,input,
  expected:{...(error?{error}:{result}),calls,runtime}});
}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?value.toString():value));
