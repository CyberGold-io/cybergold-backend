import {applySandboxForkGeneration,markSandboxForkGenerationReady,prepareSandboxForkGeneration,readSandboxForkGeneration} from '../../src/server/onchain-indexer/forkGenerationRecovery.ts';

const core='0x'+'a'.repeat(40),safe='0x'+'b'.repeat(40),hash='0x'+'1'.repeat(64);
const previous={generation:'old',forkBlock:'1000',forkBlockHash:hash};
const current={generation:'next',forkBlock:'1200',forkBlockHash:'0x'+'2'.repeat(64)};
const anchorKeys=['sandbox_fork_generation','sandbox_fork_block','sandbox_fork_block_hash','sandbox_fork_projection_status'];
const row=(chain:string,address:string,key:string,value:string)=>({chain,address,key,value});
const prepared=anchorKeys.map((key,i)=>row('31338',core,key,[previous.generation,previous.forkBlock,hash,'ready'][i]));
const cursors=[row('31338',core,'last_scanned_block','900'),row('31338',core,'finalized_projection_block_hash',hash),
 row('31338',core,'raw_log_last_scanned_block','1100'),row('31338',core,'raw_log_last_scanned_block_hash',hash),
 row('31338',core,'raw_log_start_block','100'),row('31338',core,'raw_log_journal_version','1'),
 row('31338',safe,'safe_execution_last_scanned_block','890'),row('31338',safe,'safe_execution_last_scanned_block_hash',hash),
 row('31338',core,'finalized_snapshot_block','1100'),row('31338',core,'completed_reconciliation_receipt_v2','retained'),
 row('31338',core,'recovery_share_v2_block','900'),row('31338',core,'recovery_share_v2_block_hash',hash),
 row('31338',core,'recovery_share_v2_profile','profile'),row('31338',core,'recovery_share_v2_version','1'),
 row('31338',core,'unrelated','preserved'),row('1',core,'last_scanned_block','9999')];
const base={rows:[...prepared,...cursors],core,previous,current,deploymentStart:'100',commonHash:hash};
function database(rows:any[]){
 const state=new Map(rows.map(value=>[[value.chain,value.address,value.key].join('/'),value.value]));const operations:any[]=[];
 const execute=async(sql:string,params:any[]=[])=>{
  const table=sql.match(/(?:FROM|INTO|UPDATE)\s+(\w+)/i)?.[1];const command=sql.trim().split(/\s/)[0];
  if(command==='SELECT'){
   const [chain,addressOrKeys,keys]=params;
   return {rows:[...state].flatMap(([identity,value])=>{const [chainId,address,key]=identity.split('/');
    if(chainId!==chain||!(keys?address===addressOrKeys&&keys.includes(key):addressOrKeys.includes(key)))return [];
    return [{...(sql.includes('contract_address,')?{contract_address:address}:{}),state_key:key,state_value:value}];})};
  }
  operations.push({command,table,params});
  if(command==='INSERT'||command==='UPDATE'){const [chain,address,key,value]=params;state.set([chain,address,key].join('/'),value);}
  if(command==='DELETE'&&table==='onchain_sync_state'){
   const [chain,keys]=params;for(const identity of state.keys()){const [rowChain,,key]=identity.split('/');if(rowChain===chain&&keys.includes(key))state.delete(identity);}
  }
  return {rows:[]};
 };
 return {execute,state,operations};
}
const cases:any[]=[];
function add(name:string,action:string,mutate:(input:any)=>void=()=>{}){const input=structuredClone(base);mutate(input);cases.push({name,action,input});}
add('reuse-prefix','apply');add('projection-ahead','apply',x=>x.rows.find((r:any)=>r.key==='last_scanned_block').value='1100');
add('safe-ahead','apply',x=>x.rows.find((r:any)=>r.key==='safe_execution_last_scanned_block').value='1100');
add('missing-core-projection','apply',x=>x.rows=x.rows.filter((r:any)=>r.key!=='last_scanned_block'||r.chain==='1'));
add('full-replay','apply',x=>x.commonHash='0x'+'f'.repeat(64));add('no-common-hash','apply',x=>x.commonHash=null);
add('older-fork','apply',x=>x.current.forkBlock='800');add('deployment-after-old','apply',x=>x.deploymentStart='1100');
add('not-prepared','apply',x=>x.rows=x.rows.filter((r:any)=>!anchorKeys.includes(r.key)));
add('same-generation','apply',x=>x.current.generation=x.previous.generation);
add('ready-current','apply',x=>x.rows=x.rows.map((r:any)=>r.key===anchorKeys[0]?{...r,value:x.current.generation}:r.key===anchorKeys[1]?{...r,value:x.current.forkBlock}:r.key===anchorKeys[2]?{...r,value:x.current.forkBlockHash}:r));
add('refreshing-current','apply',x=>{for(const r of x.rows){if(r.key===anchorKeys[0])r.value=x.current.generation;if(r.key===anchorKeys[1])r.value=x.current.forkBlock;if(r.key===anchorKeys[2])r.value=x.current.forkBlockHash;if(r.key===anchorKeys[3])r.value='refreshing';}});
add('refreshing-previous','apply',x=>x.rows.find((r:any)=>r.key===anchorKeys[3]).value='refreshing');
add('wrong-previous','apply',x=>x.previous.generation='other');add('uppercase-core','apply',x=>x.core=x.core.toUpperCase());
add('prepare-empty','prepare',x=>x.rows=[]);add('prepare-matching','prepare',x=>x.current=x.previous);
add('prepare-different','prepare');add('prepare-refreshing','prepare',x=>{x.current=x.previous;x.rows.find((r:any)=>r.key===anchorKeys[3]).value='refreshing';});
for(const key of anchorKeys.slice(0,3)){
 for(const action of ['read','prepare','apply'])add(action+'-missing-'+key,action,x=>x.rows=x.rows.filter((r:any)=>r.key!==key));
}
for(const value of ['bad','-1','0x100',' 1000 ','','1.5','9007199254740993000']){
 add('read-block-'+value,'read',x=>x.rows.find((r:any)=>r.key===anchorKeys[1]).value=value);
 for(const key of ['last_scanned_block','raw_log_last_scanned_block','safe_execution_last_scanned_block'])
  add('cursor-'+key+'-'+value,'apply',x=>x.rows.find((r:any)=>r.key===key&&r.chain==='31338').value=value);
}
for(const status of ['','unknown','refreshing','ready']){
 add('read-status-'+status,'read',x=>x.rows.find((r:any)=>r.key===anchorKeys[3]).value=status);
 for(const block of ['999','1000','1200'])add('mark-'+status+'-'+block,'mark',x=>{x.rows.find((r:any)=>r.key===anchorKeys[3]).value=status;x.reached=block;});
}
add('mark-absent','mark',x=>{x.rows=[];x.reached='1200';});
add('entire-transition','sequence',x=>x.rows=x.rows.filter((r:any)=>!anchorKeys.includes(r.key)));
const anchor=(value:any)=>({...value,forkBlock:BigInt(value.forkBlock)});
const wire=(value:any)=>JSON.parse(JSON.stringify(value??null,(_key,item)=>typeof item==='bigint'?item.toString():item));
for(const entry of cases){
 const x=entry.input;const db=database(x.rows);const input={execute:db.execute,coreAddress:x.core,current:anchor(x.current)};
 let result;
 try{
  if(entry.action==='read')result=await readSandboxForkGeneration(db.execute,x.core);
  if(entry.action==='prepare')result=await prepareSandboxForkGeneration(input);
  if(entry.action==='apply')result=await applySandboxForkGeneration({...input,previous:anchor(x.previous),deploymentStartBlock:BigInt(x.deploymentStart),currentHashAtPreviousForkBlock:x.commonHash});
  if(entry.action==='mark')result=await markSandboxForkGenerationReady({...input,reachedBlock:BigInt(x.reached)});
  if(entry.action==='sequence'){
   await prepareSandboxForkGeneration({...input,current:anchor(x.previous)});
   const apply={...input,previous:anchor(x.previous),deploymentStartBlock:BigInt(x.deploymentStart),currentHashAtPreviousForkBlock:x.commonHash};
   const first=await applySandboxForkGeneration(apply),second=await applySandboxForkGeneration(apply);
   await markSandboxForkGenerationReady({...input,reachedBlock:1200n});const third=await applySandboxForkGeneration(apply);
   result=[first,second,third,await readSandboxForkGeneration(db.execute,x.core)];
  }
  entry.expected={result:wire(result)};
 }catch(error){entry.expected={error:(error as Error).message};}
 entry.expected.state=[...db.state].sort(([a],[b])=>a.localeCompare(b));entry.expected.operations=db.operations;
}
console.log(JSON.stringify({core,cases}));
