// Isolate the actual retained private functions without starting its scheduler
// or supplying deployed configuration. No production source is rewritten.
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {indexerGatewayHealthIsSuppressed} from '../../src/server/onchain-indexer/gatewayLease';
import {createReconciliationReceipt,parseReconciliationReceipt} from '../../src/server/onchain-indexer/reconciliationReceipt';
import {finalizedSnapshotMatches} from '../../src/server/onchain-indexer/finalizedReconciliation';
import {readRecoveryShareV2Checkpoint,RECOVERY_SHARE_V2_VERSION} from '../../src/server/onchain-indexer/recoverySharePersistence';

const functions=['getLastOnchainIndexerReconciliationReceipt','getSyncStateBigInt','getSyncStateString',
 'readAddressStateValues','checkpointCursor','readGatewaySuccessfulRunCheckpoint','setSyncState',
 'deleteSyncState','setAddressSyncState','commitGatewaySuccessfulRun','requiredFinalizedSnapshotsExist','finalizedSnapshotIsComplete',
 'buildCompletedGatewayReceipt','countRows'];
const source=readFileSync('src/server/onchain-indexer/indexer.ts','utf8');
const parsed=ts.createSourceFile('retained-indexer.ts',source,ts.ScriptTarget.Latest,true);
const selected:string[]=[];
for(const statement of parsed.statements){
 if(ts.isFunctionDeclaration(statement)&&functions.includes(statement.name?.text??''))selected.push(statement.getText(parsed));
 if(ts.isVariableStatement(statement)&&statement.declarationList.declarations.some(declaration=>
  /^INDEXER_STATE_KEY_|^RAW_LOG_CURSOR_|^SAFE_WORKING_|^(HASH_PATTERN|RAW_JOURNAL_VERSION|DASHBOARD_PROJECTION_VERSION|STATE_SNAPSHOT_VERSION|REQUIRED_FINALIZED_SNAPSHOT_MODEL_KEYS)$/.test(declaration.name.getText(parsed))))
  selected.push(statement.getText(parsed));
}
const safeSource=readFileSync('src/server/safe-events/indexer.ts','utf8');
const safeParsed=ts.createSourceFile('retained-safe.ts',safeSource,ts.ScriptTarget.Latest,true);
for(const statement of safeParsed.statements)if(ts.isVariableStatement(statement)&&statement.declarationList.declarations.some(declaration=>
 declaration.name.getText(safeParsed).startsWith('SAFE_COMMITTED_')))selected.push(statement.getText(safeParsed));
const javascript=ts.transpileModule(selected.join('\n').replace(/^export /gm,''),{
 compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const names=['query','withTransaction','getIndexerConfig','getRuntimeState','configuredSafeHistoryProfileForIndexer',
 'snapshotIdentity','indexerGatewayHealthIsSuppressed','parseReconciliationReceipt','finalizedSnapshotMatches',
 'readRecoveryShareV2Checkpoint','recoveryQuery','RECOVERY_SHARE_V2_VERSION','Date','createReconciliationReceipt'];
const factory=new Function(...names,javascript+`;return {read:getLastOnchainIndexerReconciliationReceipt,
 working:readGatewaySuccessfulRunCheckpoint,commit:commitGatewaySuccessfulRun,
 snapshots:finalizedSnapshotIsComplete,build:buildCompletedGatewayReceipt};`);
const identity=JSON.parse(readFileSync('src/server/onchain-indexer/snapshot-identity.json','utf8'));

export function retainedCompletion(dependencies:any){
 return factory(dependencies.query,dependencies.withTransaction,()=>dependencies.config,()=>dependencies.runtime,
  ()=>({safeAddresses:dependencies.config.safeAddresses}),identity,indexerGatewayHealthIsSuppressed,
  parseReconciliationReceipt,finalizedSnapshotMatches,readRecoveryShareV2Checkpoint,dependencies.query,
  RECOVERY_SHARE_V2_VERSION,{now:()=>dependencies.now},createReconciliationReceipt);
}
