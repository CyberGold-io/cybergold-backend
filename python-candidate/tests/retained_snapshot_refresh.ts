import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {normalizeFinalizedRunAnchor} from '../../src/server/onchain-indexer/finalizedReconciliation';
import {createBoundedFinalizedMulticallClient,isFinalizedMulticallBudgetExceeded} from '../../src/server/onchain-indexer/finalizedSnapshotMulticall';
import {buildRecoveryPortfolioReadModel} from '../../src/server/onchain-indexer/recoveryPortfolioModel';
import {readRecoveryShareV2Checkpoint,reconcileRecoveryShareBalancesV2,rebuildRecoveryShareBalances} from '../../src/server/onchain-indexer/recoverySharePersistence';
import {persistRecoveryPortfolioReadModel,pruneRecoveryApiRateLimits} from '../../src/server/onchain-indexer/recoveryPortfolioRepository';
import {persistDashboardSnapshot} from '../../src/server/onchain-indexer/dashboardSnapshotRepository';
const source=readFileSync('src/server/onchain-indexer/indexer.ts','utf8'),parsed=ts.createSourceFile('retained-snapshot-refresh.ts',source,ts.ScriptTarget.Latest,true);
const selected=parsed.statements.filter(s=>ts.isFunctionDeclaration(s)&&s.name?.text==='refreshRecoveryPortfolioReadModel'||
 ts.isVariableStatement(s)&&s.declarationList.declarations.some(d=>/^INDEXER_STATE_KEY_FINALIZED_SNAPSHOT_/.test(d.name.getText(parsed))));
const javascript=ts.transpileModule(selected.map(s=>s.getText(parsed)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
export function retainedRefresh(dependencies:any){
 const deps={normalizeFinalizedRunAnchor,createBoundedFinalizedMulticallClient,isFinalizedMulticallBudgetExceeded,
  buildRecoveryPortfolioReadModel,readRecoveryShareV2Checkpoint,reconcileRecoveryShareBalancesV2,rebuildRecoveryShareBalances,
  persistRecoveryPortfolioReadModel,pruneRecoveryApiRateLimits,persistDashboardSnapshot,...dependencies};
 return new Function(...Object.keys(deps),javascript+';return refreshRecoveryPortfolioReadModel;')(...Object.values(deps));
}
