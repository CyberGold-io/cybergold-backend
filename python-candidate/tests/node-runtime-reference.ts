import {configuredSafeHistoryProfileForIndexer} from '../../src/server/safe-events/indexer';
import {getOnchainDashboardSummary} from '../../src/server/onchain-indexer/indexer';

const base = {...process.env};
// Actual retained dashboard/configuration code; no network/DB dependency.
globalThis.__cybergoldDashboardPgPool = {query: async () => ({rowCount:1, rows:[{payload:{enabled:true}}]})} as any;
const flags = ['ARCHIVE_FREE_FINALIZED_MODE','ADDRESS_SCOPED_RAW_LOGS','RAW_JOURNAL_REPLAY_ENABLED',
  'RECOVERY_SHARE_V2_ENABLED','FINALIZED_MULTICALL_ENABLED'];
const cases:Record<string,string|undefined>[]=[];
for (let mask=0;mask<32;mask++) cases.push(Object.fromEntries(flags.map((flag,index)=>[
  'ONCHAIN_INDEXER_'+flag,String((mask>>index)&1)])));
cases.push({DATABASE_URL:undefined}, {CYBERGOLD_RUNTIME_CONFIG_ID:'invalid'},
  {CYBERGOLD_RUNTIME_CONFIG_ID:'sha256:'+'a'.repeat(64)},
  {SAFE_EVENT_INDEXER_LOOKBACK_BLOCKS:'0'}, {SAFE_EVENT_INDEXER_LOOKBACK_BLOCKS:'1'},
  {SAFE_EVENT_INDEXER_LOOKBACK_BLOCKS:'100001'},
  {SAFE_EVENT_INDEXER_SAFE_ADDRESS:'0x'+'1'.repeat(40)},
  {SAFE_EVENT_INDEXER_SAFE_ADDRESSES:'0x'+'2'.repeat(40)+',0x'+'1'.repeat(40)+',0x'+'2'.repeat(40)},
  {SAFE_EVENT_INDEXER_SAFE_ADDRESSES:Array.from({length:17},(_,i)=>'0x'+(i+1).toString(16).padStart(40,'0')).join(',')});
const results=[];
for (const values of cases) {
  process.env={...base,DATABASE_URL:'postgresql://fixture.invalid/db',...values};
  for (const [key,value] of Object.entries(process.env)) if (value===undefined) delete process.env[key];
  let safe:any=null,error:string|null=null;
  try {
    const profile=configuredSafeHistoryProfileForIndexer();
    safe={addresses:profile.safeAddresses,lookback:Number(profile.lookbackBlocks)};
  } catch(failure) {error=(failure as Error).message;}
  results.push({values:Object.fromEntries(Object.entries(values).map(([key,value])=>[key,value??null])),
    safe,error,dashboardEnabled:(await getOnchainDashboardSummary()).enabled});
}
console.log(JSON.stringify(results));
