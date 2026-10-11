import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {encodeFunctionData} from 'viem';
import {CORE_DIAMOND_ABI} from '../../src/contracts/generated/coreDiamond';
import {reconcileRecoveryPoolLifecycleSnapshot} from '../../src/utils/recovery';
import {readRecoveryFundSnapshot} from '../../src/server/onchain-indexer/recoveryFundSnapshot';
import {buildRecoveryPortfolioReadModel} from '../../src/server/onchain-indexer/recoveryPortfolioModel';
const source=readFileSync('src/server/onchain-indexer/indexer.ts','utf8'),parsed=ts.createSourceFile('retained-recovery.ts',source,ts.ScriptTarget.Latest,true);
const javascript=ts.transpileModule(parsed.statements.filter(s=>ts.isFunctionDeclaration(s)&&['readRecoverySnapshot','uniqueOrderedAssets'].includes(s.name?.text??'')).map(s=>s.getText(parsed)).join('\n'),
 {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const core='0x'+'1'.repeat(40),governance='0x'+'9'.repeat(40),assets=['0x'+'2'.repeat(40),'0x'+'3'.repeat(40)],reserve='0x'+'4'.repeat(40),hash='0x'+'a'.repeat(64);
const cases:any[]=[];
for(const domain of ['fund','snapshot'])for(const mode of ['normal','no-governance','read-error','terminal','trusted-core','treasury','preview-generation','preview-amount','aggregate','acquired','exhausted','bad-terms','deficit','paused','wide','empty'])cases.push({domain,mode});
for(const mode of ['no-pools','empty-pool','custody','lifecycle','cardinality','reserve-cardinality'])cases.push({domain:'snapshot',mode});
for(const x of cases){
 const calls:any[]=[];const noPools=x.mode==='no-pools'||x.mode==='empty';
 const poolAssets=noPools?[]:x.mode==='cardinality'?Array.from({length:257},(_v,i)=>'0x'+(i+1).toString(16).padStart(40,'0')):assets;
 const reserveAssets=x.mode==='reserve-cardinality'?Array.from({length:513},(_v,i)=>'0x'+(i+1000).toString(16).padStart(40,'0')):[reserve];
 const inputPools=poolAssets.map(asset=>({asset,impaired:true,coreAttachedShares:'100',externalShares:'200',redeemableRaw:'300'}));
 const scale=x.mode==='wide'?2n**200n:1n;const terms={generation:7n,coverageShares:100n*scale,purchasedShares:20n*scale,initialCygldCommitment:1000n*scale};
 if(x.mode==='exhausted')Object.assign(terms,{coverageShares:0n,purchasedShares:0n,initialCygldCommitment:0n});
 if(x.mode==='bad-terms')terms.purchasedShares=terms.coverageShares;
 const commitment=x.mode==='exhausted'||noPools?0n:800n*scale*BigInt(poolAssets.length);
 const client={readContract:async(r:any)=>{
  calls.push({address:r.address,data:encodeFunctionData(r),target:{blockHash:hash,requireCanonical:true}});
  if(['read-error','terminal'].includes(x.mode)&&r.functionName==='trustedRecoveryFundCore')throw new Error('fixture read failure');
  const empty=x.mode==='empty-pool';
  const pool={impaired:!empty,coreAttachedShares:empty?0n:100n,externalShares:empty?0n:200n,redeemableRaw:empty?0n:300n,
   cygldPerAssetRawFp18:10n**18n,cygldSupplyCap:1000n,referenceShares:100n,referenceValueCygld:100n,shareDecimals:18};
  const custody={lifecycle:1,poolImpaired:!empty,redeemablePoolRaw:pool.redeemableRaw,coreAttachedShares:pool.coreAttachedShares,
   externalShares:x.mode==='custody'?99n:pool.externalShares,exitEntitlementRaw:50n,liveBalanceAvailable:true,liveRawCustody:400n,activeAvailableRaw:50n,poolRawDeficit:0n,exitEntitlementDeficitRaw:0n};
  const values:any={coreAttachedRecoveryAssets:[...poolAssets].reverse(),basketAssets:noPools?[]:[reserve],
   reserveLifecycle:{lifecycle:x.mode==='lifecycle'?3:1,exitEntitlementRaw:50n},recoveryPool:pool,reserveCustodyStatus:custody,
   trustedRecoveryFundCore:x.mode==='trusted-core'?governance:core,paused:x.mode==='paused',
   recoveryFundTreasuryStatus:[x.mode==='deficit'?0n:10000n*scale,x.mode==='treasury'?20000n*scale:0n,x.mode==='aggregate'?commitment+1n:x.mode==='empty-pool'?0n:commitment],
   assetRecoveryFund:terms,acquiredRecoveryShares:x.mode==='acquired'?201n:50n,
   previewAssetRecoveryFundPurchase:[x.mode==='preview-generation'?8n:7n,x.mode==='preview-amount'?799n*scale:800n*scale]};
  return values[r.functionName];}};
 const config={chainId:31338n,coreAddress:core,governanceAddress:x.mode==='no-governance'?null:governance};
 const dependencies={CORE_DIAMOND_ABI,reconcileRecoveryPoolLifecycleSnapshot,readRecoveryFundSnapshot,recoveryQuery:()=>{},
  readIndexedRecoveryAssets:async()=>{calls.push('indexed-recovery');return poolAssets;},
  readIndexedReserveAssets:async()=>{calls.push('indexed-reserve');return reserveAssets;}};
 const readSnapshot=new Function(...Object.keys(dependencies),javascript+';return readRecoverySnapshot;')(...Object.values(dependencies));
 let result,error,model;
 try{result=x.domain==='snapshot'?await readSnapshot(config,103n,client,{blockHash:hash,requireCanonical:true},()=>x.mode==='terminal'):
  await readRecoveryFundSnapshot({coreAddress:core,governanceAddress:config.governanceAddress,client,stateReadTarget:{blockHash:hash,requireCanonical:true},pools:inputPools,isTerminalReadFailure:()=>x.mode==='terminal'});
  if(x.domain==='snapshot')model=buildRecoveryPortfolioReadModel(31338n,103n,core,result);
 }catch(e){error=(e as Error).message;}
 x.pools=inputPools;x.poolAssets=poolAssets;x.reserveAssets=reserveAssets;x.expected={...(error?{error}:{result,...(x.domain==='snapshot'?{model}:{})}),calls};
}
console.log(JSON.stringify(cases,(_key,value)=>typeof value==='bigint'?value.toString():value));
