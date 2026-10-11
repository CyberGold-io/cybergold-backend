import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {toHex,toEventSelector} from 'viem';
import {normalizeFinalizedRunAnchor,resolveFinalizedRunAnchor,resolveArchiveFreeDeploymentStart,planFinalizedProjectionScan,
 selectFinalizedPlanningBoundary,finalizedRunProfile,reconciliationAnchorBlockTag} from '../../src/server/onchain-indexer/finalizedReconciliation';
import {createKnownRawLogDecoder} from '../../src/server/onchain-indexer/rawLogModel';
import {prepareRawJournalReplayCoverage,readRawJournalLogs,ingestAddressScopedRawLogs} from '../../src/server/onchain-indexer/rawLogJournal';
import {instrumentEthGetLogsRequest} from '../../src/server/onchain-indexer/rpcRequestInstrumentation';
import {shouldSplitDirectProviderLogRequest} from '../../src/server/onchain-indexer/adaptiveLogPagination';
import {createDashboardHistoryProgress} from '../../src/server/onchain-indexer/internalReconcileContract';
import {retainedDashboard} from './retained_dashboard';
import {retainedProjection} from './retained_projection';
const source=readFileSync('src/server/onchain-indexer/indexer.ts','utf8'),parsed=ts.createSourceFile('retained-core-collector.ts',source,ts.ScriptTarget.Latest,true);
const names=['reconcileInternal','resolveStartBlock','detectDeploymentBlock','hasCodeAtBlock'];
const selected=parsed.statements.filter(s=>ts.isFunctionDeclaration(s)&&names.includes(s.name?.text??'')||
 ts.isVariableStatement(s)&&s.declarationList.declarations.some(d=>/^INDEXER_STATE_KEY_|^(GATEWAY_HISTORICAL_MAX_BLOCKS_PER_RUN|RAW_JOURNAL_VERSION|DASHBOARD_PROJECTION_VERSION)$/.test(d.name.getText(parsed))));
const javascript=ts.transpileModule(selected.map(s=>s.getText(parsed)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
export function retainedCore(query:any,transaction:any,dependencies:any){
 const store=retainedProjection(query,transaction),definitions=retainedDashboard({}).definitions;
 const snapshotIdentity=JSON.parse(readFileSync('src/server/onchain-indexer/snapshot-identity.json','utf8'));
 const deps={snapshotIdentity,normalizeFinalizedRunAnchor,resolveFinalizedRunAnchor,resolveArchiveFreeDeploymentStart,
  planFinalizedProjectionScan,selectFinalizedPlanningBoundary,finalizedRunProfile,reconciliationAnchorBlockTag,toHex,toEventSelector,
  prepareRawJournalReplayCoverage,readRawJournalLogs,ingestAddressScopedRawLogs,instrumentEthGetLogsRequest,
  shouldSplitDirectProviderLogRequest,createDashboardHistoryProgress,EVENT_DEFINITIONS:definitions.core,RECOVERY_FUND_EVENT_DEFINITIONS:definitions.governance,
  decodeCoreRawLog:createKnownRawLogDecoder(definitions.core),decodeGovernanceRawLog:createKnownRawLogDecoder(definitions.governance),
  maxBigInt:(a:bigint,b:bigint)=>a>b?a:b,ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT:0,
  ensureIndexerVersion:store.identity,getLastScannedBlock:store.last,getSyncStateBigInt:store.bigState,
  getSyncStateString:store.state,setSyncState:store.put,getCommittedFinalizedBoundary:store.committed,
  setFinalizedProjectionCursor:store.cursor,setLastScannedBlock:store.lastPut,getHolderCacheReady:store.ready,
  clearHolderCache:store.clear,setHolderCountBigInt:store.countPut,setHolderCacheReady:store.readyPut,
  rollbackHolderCacheFromBlock:store.rewind,deleteLogsFromBlock:store.deleteFrom,deleteReadModelSnapshotsFromBlock:store.snapshots,
  persistLogs:store.persist,rebuildHolderCacheFromIndexedLogs:store.rebuild,pruneOldHolderDeltas:store.prune,
  indexerRpcTransport:()=>({}),...dependencies};
 return new Function(...Object.keys(deps),javascript+';return reconcileInternal;')(...Object.values(deps));
}
