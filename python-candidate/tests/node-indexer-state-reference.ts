import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {parseAbiItem,encodeFunctionData} from 'viem';
import {CORE_DIAMOND_ABI} from '../../src/contracts/generated/coreDiamond';
const source=readFileSync('src/server/onchain-indexer/indexer.ts','utf8');
const parsed=ts.createSourceFile('retained-state.ts',source,ts.ScriptTarget.Latest,true);
const names=['readCoreAndTokenMetrics','readBasketSnapshot','readCygldRefGramsFp18','bigIntToTokenNumber','parseBigIntValue'];
const javascript=ts.transpileModule(parsed.statements.filter(s=>ts.isFunctionDeclaration(s)&&names.includes(s.name?.text??'')).map(s=>s.getText(parsed)).join('\n'),
 {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const core='0x'+'1'.repeat(40),assets=['0x'+'2'.repeat(40),'0x'+'3'.repeat(40)],hash='0x'+'a'.repeat(64);
const cases:any[]=[];
for(const mode of ['normal','fresh','stale','zero','empty','malformed','future','boundary','read-error','write-error','terminal','pinned-error','pinned-fresh','zero-time'])cases.push({domain:'reference',mode});
for(const mode of ['normal','metrics-error'])cases.push({domain:'metrics',mode});
for(const mode of ['normal','empty','mismatch','zero-balances','missing-assets','missing-targets','missing-gold','missing-units','token-error','terminal','pinned-error','decimals-zero','large'])cases.push({domain:'basket',mode});
for(const x of cases){
 const calls:any[]=[];let value=x.mode==='zero'?'0':x.mode==='empty'?'':x.mode==='malformed'?'invalid':(10n**18n).toString();
 const updated=x.mode==='stale'?1:x.mode==='zero-time'?0:x.mode==='future'?100000001:x.mode==='boundary'?100000000-86400000:99999999;
 const cached=x.mode==='normal'?null:{stateValue:value,updatedAtMs:updated};
 const pinned=x.mode.startsWith('pinned');
 const readContract=async(r:any)=>{
  calls.push({address:r.address,data:encodeFunctionData(r),target:pinned?{blockHash:hash,requireCanonical:true}:{blockNumber:'103'}});
  if(x.mode==='metrics-error'&&r.functionName==='issuanceFeePpm'||['read-error','pinned-error','terminal'].includes(x.mode)&&r.functionName==='cygldRefGramsFp18'||x.mode==='token-error'&&r.address!==core)throw new Error('fixture read failure');
  if(x.mode==='missing-assets'&&r.functionName==='basketAssets'||x.mode==='missing-targets'&&r.functionName==='basketTargetsPpm'||x.mode==='missing-gold'&&r.functionName==='basketGoldRefGramsFp18'||x.mode==='missing-units'&&r.functionName==='basketCygldPerUnitFp18')throw new Error('fixture optional failure');
  const total=x.mode==='large'?2n**220n:1000n*10n**18n;
  const values:any={totalSupply:total,decimals:x.mode==='decimals-zero'?0:18,issuanceFeePpm:5000n,redemptionFeePpm:8000n,paused:false,
   cygldRefGramsFp18:2n*10n**18n,basketAssets:x.mode==='empty'?[]:assets,basketTargetsPpm:x.mode==='mismatch'?[500000n]:[500000n,500000n],
   basketGoldRefGramsFp18:[10n**18n,2n*10n**18n],basketCygldPerUnitFp18:[10n**18n,2n*10n**18n],
   balanceOf:x.mode==='zero-balances'?0n:r.address===assets[0]?100n*10n**18n:50n*10n**18n,symbol:r.address===assets[0]?'ONE':'TWO'};
  return values[r.functionName];};
 const dependencies={parseAbiItem,CORE_DIAMOND_ABI,Date:{now:()=>100000000},DEFAULT_CYGLD_REF_CACHE_TTL_MS:86400000,INDEXER_STATE_KEY_CYGLD_REF_GRAMS_FP18:'cygld_ref_grams_fp18',
  parseNumberEnv:(_name:any,fallback:any)=>fallback,getSyncStateEntry:async()=>{calls.push('cache');return cached;},
  setSyncState:async(_config:any,key:any,next:any)=>{calls.push('put:'+key+':'+next);if(x.mode==='write-error')throw new Error('fixture write failure');}};
 const factory=new Function(...Object.keys(dependencies),javascript+';return {metrics:readCoreAndTokenMetrics,basket:readBasketSnapshot,reference:readCygldRefGramsFp18};');
 const reads=factory(...Object.values(dependencies));let result,error;
 const target=pinned?{blockHash:hash,requireCanonical:true}:{blockNumber:103n};
 try{result=await reads[x.domain]({coreAddress:core},{readContract},target,{forcePinnedRead:pinned,forcePinnedStateReads:pinned,isTerminalReadFailure:()=>x.mode==='terminal'});}catch(e){error=(e as Error).message;}
 x.expected={...(error?{error}:{result}),calls};x.cache=cached;x.pinned=pinned;
}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?value.toString():value));
