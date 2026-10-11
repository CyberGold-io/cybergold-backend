import {planIndexerIdentityTransition} from '../../src/server/onchain-indexer/indexerIdentity';
import {normalizeFinalizedRunAnchor,resolveArchiveFreeDeploymentStart,planFinalizedProjectionScan,
  selectFinalizedPlanningBoundary,finalizedRunProfile,finalizedSnapshotMatches,reconciliationAnchorBlockTag}
  from '../../src/server/onchain-indexer/finalizedReconciliation';
import {normalizeAddressScopedRpcLogs} from '../../src/server/onchain-indexer/rawLogModel';
import {parseRawJournalCoverageRows,assertRawJournalReplayCoverage,planRawJournalCoverageMerge,
  normalizeStoredRawJournalRows} from '../../src/server/onchain-indexer/rawJournalCoverage';
import {getAddress} from 'viem';
import {readFileSync} from 'node:fs';

const identity=JSON.parse(readFileSync('src/server/onchain-indexer/snapshot-identity.json','utf8'));
const address=getAddress('0x'+'ab'.repeat(20));
const hash='0x'+'a'.repeat(64),otherHash='0x'+'b'.repeat(64);
const cases:any[]=[];
const add=(op:string,input:any)=>cases.push({op,input});
const expected={rawJournalVersion:identity.rawJournalVersion,dashboardProjectionVersion:identity.dashboardProjectionVersion,
  stateSnapshotVersion:identity.stateSnapshotVersion,governanceAddress:address};
for(const raw of [null,'1','2']) for(const projection of [null,'14','15']) for(const state of [null,'1','2'])
  for(const governance of [null,address,'none']) add('identity',{stored:{rawJournalVersion:raw,dashboardProjectionVersion:projection,
    stateSnapshotVersion:state,legacyIndexerVersion:'15',dashboardProjectionGovernanceAddress:governance,
    legacyGovernanceAddress:address},expected});
for(const number of [null,-1n,0n,100n,9223372036854775807n,9223372036854775808n])
  for(const blockHash of [null,hash,hash.toUpperCase().replace('0X','0x'),'0xaa']) add('anchor',{number,hash:blockHash});
for(const chainId of [1n,31338n]) for(const configuredStartBlock of [-1n,0n,90n,101n])
  add('deployment',{chainId,configuredStartBlock,anchorBlock:100n});
for(const block of [null,89n,90n,99n,100n,101n]) for(const canonical of [null,hash,otherHash])
  for(const force of [false,true]) for(const window of [0n,12n]) add('scan',{
    deploymentStartBlock:90n,anchor:{blockNumber:100n,blockHash:hash},cursor:{blockNumber:block,blockHash:hash},
    canonicalCursorHash:canonical,reorgWindow:window,forceConfigurationOverlap:force});
for(const leaseBound of [false,true]) add('boundary',{leaseBound,working:{blockNumber:101n,blockHash:otherHash,profile:'working'},
  committed:{blockNumber:100n,blockHash:hash,profile:'committed'}});
for(const chain of [1n,31337n,31338n]) add('tag',chain);
for(const governanceAddress of [null,address]) add('profile',{addressScopedRawLogs:true,coreDeploymentStartBlock:90n,
  safeLookbackBlocks:50000n,governanceAddress,safeAddresses:[address,'0x'+'1'.repeat(40)],rawJournalVersion:'1',
  dashboardProjectionVersion:'15',safeCursorVersion:'1',coreEventSelectors:[hash],governanceEventSelectors:[otherHash],safeEventSelectors:[hash]});
for(const block of [null,99n,100n]) for(const storedHash of [null,hash,otherHash]) for(const exists of [false,true])
  add('snapshot',{anchor:{blockNumber:100n,blockHash:hash},expectedProfile:'profile',snapshotBlockNumber:block,
    snapshotBlockHash:storedHash,snapshotProfile:'profile',requiredSnapshotsExist:exists});

const baseLog={address,blockNumber:'0x64',blockHash:hash,transactionHash:otherHash,logIndex:'0x0',data:'0x',topics:[hash]};
const rpc=(value:any,header:any={hash,timestamp:1000n})=>add('rpc',{value,expectedAddress:address,fromBlock:90n,toBlock:110n,header});
rpc([baseLog]);rpc([baseLog,baseLog]);rpc([{...baseLog,blockNumber:'0x65',logIndex:'0x1'},baseLog]);
rpc([baseLog,{...baseLog,data:'0x01'}]);rpc(null);rpc([null]);rpc([[]]);
for(const patch of [{address:'0x'+'1'.repeat(40)},{address:address.toLowerCase()},
  {address:address.toUpperCase().replace('0X','0x')},{address:address.replace('a','A')},{removed:true},{removed:'true'},
  {blockHash:null},{transactionHash:'0xaa'},{blockNumber:'0x064'},{logIndex:'0x00'},
  {blockNumber:'0x80'},{blockNumber:'0x8000000000000000'},{logIndex:'0x80000000'},
  {data:'0x0'},{data:'0xAABB'},{topics:null},{topics:[hash,'0xaa']},{topics:[hash,hash,hash,hash,hash]}]) rpc([{...baseLog,...patch}]);
for(const header of [{hash:otherHash,timestamp:1000n},{hash:'0xaa',timestamp:1000n},
  {hash,timestamp:-1n},{hash,timestamp:8640000000001n},{hash,timestamp:1000}]) rpc([baseLog],header);
const rows=[{state_key:'raw_log_journal_version',state_value:'1'},{state_key:'raw_log_start_block',state_value:'90'},
  {state_key:'raw_log_last_scanned_block',state_value:'100'},{state_key:'raw_log_last_scanned_block_hash',state_value:hash}];
const coverage={address,journalVersion:'1',startBlock:90n,cursorBlock:100n,cursorBlockHash:hash};
add('coverage',{address,expectedVersion:'1',rows:[]});add('coverage',{address,expectedVersion:'1',rows});
add('coverage',{address,expectedVersion:'2',rows});add('coverage',{address,expectedVersion:'1',rows:rows.slice(1)});
add('coverage',{address,expectedVersion:'1',rows:[rows[0],rows[0],rows[2],rows[3]]});
for(const index of [1,2,3]) for(const value of ['01','-1','9223372036854775808','0xaa'])
  add('coverage',{address,expectedVersion:'1',rows:rows.map((row,i)=>i===index?{...row,state_value:value}:row)});
for(const requiredStartBlock of [-1n,89n,90n,91n]) for(const maximumBlock of [89n,99n,100n])
  for(const canonicalCursorHash of [hash,otherHash]) add('replay',{coverage,requiredStartBlock,maximumBlock,canonicalCursorHash});
for(const current of [null,coverage,{...coverage,startBlock:95n},{...coverage,journalVersion:'2'}])
  for(const [fromBlock,toBlock] of [[90n,100n],[101n,110n],[102n,110n],[90n,94n],[89n,89n]])
    add('merge',{current,address,journalVersion:'1',authoritativeStartBlock:90n,fromBlock,toBlock,toBlockHash:otherHash});
const stored={contract_address:address.toLowerCase(),block_number:'100',block_hash:hash,tx_hash:otherHash,log_index:0,
  topics:[hash],data:'0x',block_timestamp_seconds:'1000'};
const storedCase=(value:any)=>add('stored',{rows:value,address,fromBlock:90n,toBlock:100n,coverage});
storedCase([stored]);storedCase([stored,stored]);storedCase([{...stored,block_number:'99'},stored]);
for(const patch of [{contract_address:address},{block_number:'01'},{block_number:'101'},{block_hash:otherHash},
  {tx_hash:'0xaa'},{log_index:'01'},{log_index:'2147483648'},{topics:[hash,hash,hash,hash,hash]},
  {data:'0x0'},{block_timestamp_seconds:'8640000000001'}]) storedCase([{...stored,...patch}]);

for(const entry of cases) {
  let result:any=null,error:string|null=null,headerCalls=0;
  try {
    const value=entry.input;
    switch(entry.op) {
      case 'identity':result=planIndexerIdentityTransition(value.stored,value.expected);break;
      case 'anchor':result=normalizeFinalizedRunAnchor(value);break;
      case 'deployment':result=resolveArchiveFreeDeploymentStart(value);break;
      case 'scan':result=planFinalizedProjectionScan(value);break;
      case 'boundary':result=selectFinalizedPlanningBoundary(value);break;
      case 'tag':result=reconciliationAnchorBlockTag(value);break;
      case 'profile':result=finalizedRunProfile(value);break;
      case 'snapshot':result=finalizedSnapshotMatches(value);break;
      case 'rpc':result=await normalizeAddressScopedRpcLogs({...value,readBlockHeader:async()=>{headerCalls++;return value.header;}});break;
      case 'coverage':result=parseRawJournalCoverageRows(value);break;
      case 'replay':result=assertRawJournalReplayCoverage(value);break;
      case 'merge':result=planRawJournalCoverageMerge(value);break;
      case 'stored':result=normalizeStoredRawJournalRows(value);break;
    }
  } catch(failure) {error=(failure as Error).message;}
  Object.assign(entry,{result,error,headerCalls});
}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?{$bigint:value.toString()}:value));
