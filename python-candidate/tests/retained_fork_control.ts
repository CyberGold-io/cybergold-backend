// Actual retained control functions, with injected RPC and DB boundaries.
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {applySandboxForkGeneration,prepareSandboxForkGeneration,readSandboxForkGeneration} from '../../src/server/onchain-indexer/forkGenerationRecovery.ts';
const source=readFileSync('src/server/onchain-indexer/indexer.ts','utf8');
const parsed=ts.createSourceFile('retained-indexer.ts',source,ts.ScriptTarget.Latest,true);
const selected=parsed.statements.filter(statement=>ts.isFunctionDeclaration(statement)&&
 ['transitionSandboxForkGeneration','getSandboxForkGenerationStatus'].includes(statement.name?.text??'')).map(statement=>statement.getText(parsed));
const javascript=ts.transpileModule(selected.join('\n').replace(/^export /gm,''),{
 compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const factory=new Function('getIndexerConfig','ensureSchema','withSharedAdvisoryLock','createPublicClient',
 'indexerRpcTransport','withTransaction','prepareSandboxForkGeneration','applySandboxForkGeneration',
 'getRuntimeState','readSandboxForkGeneration','query',javascript+';return {transition:transitionSandboxForkGeneration,status:getSandboxForkGenerationStatus};');
export function retainedForkControl(x:any){return factory(()=>x.config,x.schema,x.lock,()=>x.client,()=>null,x.transaction,
 prepareSandboxForkGeneration,applySandboxForkGeneration,()=>x.runtime,readSandboxForkGeneration,x.query);}
