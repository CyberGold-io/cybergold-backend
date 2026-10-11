// Actual retained Safe SQL functions; no RPC or scheduler is started.
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {toEventHash} from 'viem';
const source=readFileSync('src/server/safe-events/indexer.ts','utf8');
const parsed=ts.createSourceFile('retained-safe.ts',source,ts.ScriptTarget.Latest,true);
const functions=['deleteIndexedSafeExecutionLogs','persistSafeExecutionLogs','lastScannedSafeBlock',
 'setLastScannedSafeBlock','lastScannedSafeBlockHash','finalizedSafeProjectionProfile','committedSafeBoundary','ensureSafeCursorVersion'];
const selected=parsed.statements.filter(statement=>ts.isFunctionDeclaration(statement)&&functions.includes(statement.name?.text??'')||
 ts.isVariableStatement(statement)&&statement.declarationList.declarations.some(declaration=>/^SAFE_/.test(declaration.name.getText(parsed)))).map(statement=>statement.getText(parsed));
const javascript=ts.transpileModule(selected.join('\n').replace(/^export /gm,''),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const identity=JSON.parse(readFileSync('src/server/onchain-indexer/snapshot-identity.json','utf8'));
const factory=new Function('query','withTransaction','snapshotIdentity','toEventHash',javascript+`;return {
 deleteFrom:deleteIndexedSafeExecutionLogs,persist:persistSafeExecutionLogs,cursor:lastScannedSafeBlock,
 putCursor:setLastScannedSafeBlock,hash:lastScannedSafeBlockHash,profile:finalizedSafeProjectionProfile,
 committed:committedSafeBoundary,version:ensureSafeCursorVersion};`);
export function retainedSafeProjection(query:any,transaction:any){return factory(query,transaction,identity,toEventHash);}
