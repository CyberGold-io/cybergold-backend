// Compile the actual retained collector with synthetic clients/stores.
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {decodeAbiParameters,toEventHash,hexToBigInt,hexToNumber,toHex} from 'viem';
import {normalizeFinalizedRunAnchor,planFinalizedProjectionScan,selectFinalizedPlanningBoundary} from '../../src/server/onchain-indexer/finalizedReconciliation';
import {instrumentEthGetLogsRequest} from '../../src/server/onchain-indexer/rpcRequestInstrumentation';
const source=readFileSync('src/server/safe-events/indexer.ts','utf8');
const parsed=ts.createSourceFile('retained-safe.ts',source,ts.ScriptTarget.Latest,true);
const selected=parsed.statements.filter(s=>ts.isFunctionDeclaration(s)&&['reconcileSafeExecutionEvents','safeExecutionLogArgs'].includes(s.name?.text??'')||
 ts.isVariableStatement(s)&&s.declarationList.declarations.some(d=>d.name.getText(parsed)==='SAFE_EXECUTION_EVENTS')).map(s=>s.getText(parsed));
const javascript=ts.transpileModule(selected.join('\n').replace(/^export /gm,''),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
export function retainedSafeCollector(dependencies:any){
 const common={decodeAbiParameters,toEventHash,hexToBigInt,hexToNumber,toHex,normalizeFinalizedRunAnchor,
  planFinalizedProjectionScan,selectFinalizedPlanningBoundary,instrumentEthGetLogsRequest,RAW_JOURNAL_VERSION:'1',ADDRESS_SCOPED_TRANSPORT_RETRY_COUNT:0};
 const values={...common,...dependencies};
 return new Function(...Object.keys(values),javascript+';return reconcileSafeExecutionEvents;')(...Object.values(values));
}
