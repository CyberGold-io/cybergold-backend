// Retained holder/identity functions, isolated without the scheduler or RPC.
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {zeroAddress} from 'viem';
import {parseAddressLike,parseBigIntLike} from '../../src/server/onchain-indexer/recoverySharePersistence.ts';
import {planIndexerIdentityTransition} from '../../src/server/onchain-indexer/indexerIdentity.ts';
const source=readFileSync('src/server/onchain-indexer/indexer.ts','utf8');
const parsed=ts.createSourceFile('retained-indexer.ts',source,ts.ScriptTarget.Latest,true);
const names=['getSyncStateString','getSyncStateBigInt','getLastScannedBlock','getCommittedFinalizedBoundary','setFinalizedProjectionCursor','setLastScannedBlock','getSyncStateEntry','setSyncState','deleteSyncState','isZeroAddress','extractTransferArgs',
 'toJsonSafe','persistLogs','deleteLogsFromBlock','clearHolderCache','clearReadModelSnapshots','getHolderCacheReady','setHolderCacheReady','getHolderCountBigInt',
 'setHolderCountBigInt','getHolderBalanceRaw','setHolderBalanceRaw','recordHolderDelta','applyHolderBalanceDelta',
 'applyTransferToHolderCache','rollbackHolderCacheFromBlock','rebuildHolderCacheFromIndexedLogs','pruneOldHolderDeltas',
 'deleteReadModelSnapshotsFromBlock','deleteProjectedLogsForAddress','ensureIndexerVersion'];
const selected=parsed.statements.filter(statement=>
 ts.isFunctionDeclaration(statement)&&names.includes(statement.name?.text??'')||ts.isVariableStatement(statement)&&
 statement.declarationList.declarations.some(declaration=>/^INDEXER_STATE_KEY_|^(HASH_PATTERN|RAW_JOURNAL_VERSION|DASHBOARD_PROJECTION_VERSION|STATE_SNAPSHOT_VERSION|LEGACY_INDEXER_VERSION)$/.test(declaration.name.getText(parsed)))).map(statement=>statement.getText(parsed));
const javascript=ts.transpileModule(selected.join('\n').replace(/^export /gm,''),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const identity=JSON.parse(readFileSync('src/server/onchain-indexer/snapshot-identity.json','utf8'));
const factory=new Function('query','withTransaction','snapshotIdentity','zeroAddress','parseAddressLike','parseBigIntLike',
 'planIndexerIdentityTransition',javascript+`;return {identity:ensureIndexerVersion,clear:clearHolderCache,
 persist:persistLogs,deleteFrom:deleteLogsFromBlock,rebuild:rebuildHolderCacheFromIndexedLogs,rewind:rollbackHolderCacheFromBlock,delta:applyHolderBalanceDelta,
 transfer:applyTransferToHolderCache,prune:pruneOldHolderDeltas,snapshots:deleteReadModelSnapshotsFromBlock,entry:getSyncStateEntry,
 state:getSyncStateString,bigState:getSyncStateBigInt,last:getLastScannedBlock,committed:getCommittedFinalizedBoundary,
 cursor:setFinalizedProjectionCursor,put:setSyncState,lastPut:setLastScannedBlock,ready:getHolderCacheReady,
 readyPut:setHolderCacheReady,countPut:setHolderCountBigInt};`);
export function retainedProjection(query:any,transaction:any){return factory(query,transaction,identity,zeroAddress,parseAddressLike,parseBigIntLike,planIndexerIdentityTransition);}
