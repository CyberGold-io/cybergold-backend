// Canonical private dashboard functions, isolated without RPC or scheduling.
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {parseAbiItem} from 'viem';
const source=readFileSync('src/server/onchain-indexer/indexer.ts','utf8');
const parsed=ts.createSourceFile('retained-dashboard.ts',source,ts.ScriptTarget.Latest,true);
const names=['parseBigIntValue','bigIntToTokenNumber','loadAmountLogs','loadTransferAmountLogs','getLatestEventRecord',
 'getLogicAndParameterEventNames','buildEmptyBuckets','applyAmountRowsToBuckets','materializeRangeBuckets','buildOnchainDashboardSummary'];
const selected=parsed.statements.filter(s=>ts.isFunctionDeclaration(s)&&names.includes(s.name?.text??'')||
 ts.isVariableStatement(s)&&s.declarationList.declarations.some(d=>['DASHBOARD_MAX_LOG_ROWS','DASHBOARD_RANGE_CONFIG',
 'TOKEN_DECIMALS_FALLBACK','EVENT_DEFINITIONS','RECOVERY_FUND_EVENT_DEFINITIONS'].includes(d.name.getText(parsed))));
const javascript=ts.transpileModule(selected.map(s=>s.getText(parsed)).join('\n'),
 {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
export function retainedDashboard(dependencies:any){
 const deps={parseAbiItem,...dependencies};
 return new Function(...Object.keys(deps),javascript+`;return {empty:buildEmptyBuckets,apply:applyAmountRowsToBuckets,
  materialize:materializeRangeBuckets,summary:buildOnchainDashboardSummary,amount:loadAmountLogs,
  transfers:loadTransferAmountLogs,latest:getLatestEventRecord,definitions:{core:EVENT_DEFINITIONS,governance:RECOVERY_FUND_EVENT_DEFINITIONS},groups:getLogicAndParameterEventNames};`)(...Object.values(deps));
}
