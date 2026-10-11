"""Native completion commit/read interoperability on the disposable schema."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

from psycopg.errors import NotNullViolation

from cybergold_candidate.completed_state import CompletedState,CORE_COMMITTED,SAFE_COMMITTED,RECEIPT_KEY,REQUIRED_MODELS
from cybergold_candidate.snapshot_persistence import persist_snapshot

ROOT=Path(__file__).parents[2]


async def qualify(database,dsn):
    def node(script,*args):
        return subprocess.check_output(['node','--env-file=tests/fixture.env','--import','tsx',
            *script,*args],cwd=ROOT,env={**os.environ,'DATABASE_URL':dsn},text=True)
    with tempfile.TemporaryDirectory(prefix='cybergold-completion-fixture-') as directory:
        receipt_path=Path(directory)/'receipt.json'
        receipt_path.write_text(await asyncio.to_thread(node,['python-candidate/tests/node-receipt-reference.ts']))
        fixture=json.loads(await asyncio.to_thread(node,['python-candidate/tests/node-completed-state-reference.ts'],str(receipt_path)))
    config=fixture['config'];state=CompletedState(database,config)
    async with database.connection() as connection:
        async with connection.transaction():
            for address,values in fixture['states'].items():
                for key,value in values.items():
                    if key in (*CORE_COMMITTED,*SAFE_COMMITTED,RECEIPT_KEY):continue
                    await connection.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
                        VALUES (%s,%s,%s,%s) ON CONFLICT(chain_id,contract_address,state_key)
                        DO UPDATE SET state_value=EXCLUDED.state_value''',(config['chainId'],address,key,value))
            for model in REQUIRED_MODELS:await persist_snapshot(connection,config['chainId'],config['coreAddress'],model,100,{'fixture':True})
    runtime=lambda:{'activeGatewayReconciliationId':None,'gatewayLeaseAmbiguousUntilMs':0}
    assert await state.receipt(runtime(),1000) is None
    case=fixture['commits'][0];checkpoint=case['checkpoint']
    checkpoint['coreCursor']['blockNumber']=int(checkpoint['coreCursor']['blockNumber'])
    for cursor in checkpoint['safeCursors']:cursor['blockNumber']=int(cursor['blockNumber'])
    anchor={'blockNumber':100,'blockHash':checkpoint['coreCursor']['blockHash']}
    checkpoint=await state.read_working(anchor,checkpoint['profile'])
    lease=SimpleNamespace(reconciliation_id=case['lease']['reconciliationId'],config_revision=case['lease']['configRevision'],finalized_anchor=anchor)
    built=await state.build_receipt(lease,checkpoint,case['receipt']['rpcRequests'],1790762400098,1790762400123)
    case={**case,'receipt':built}
    await state.commit(lease,checkpoint,case['receipt'])
    assert await state.receipt(runtime(),1000)==case['receipt']
    script='''
import {query,withTransaction} from './src/server/onchain-indexer/db';
import {retainedCompletion} from './python-candidate/tests/retained_completion';
const input=JSON.parse(process.argv[1]);const runtime={activeGatewayReconciliationId:null,gatewayLeaseAmbiguousUntilMs:0};
const retained=retainedCompletion({config:input.config,runtime,now:1000,query,withTransaction});
let result;
if(input.write||input.build){
 const checkpoint=input.checkpoint;checkpoint.coreCursor.blockNumber=BigInt(checkpoint.coreCursor.blockNumber);
 for(const field of ['safeCursors','rawCursors'])for(const cursor of checkpoint[field])cursor.blockNumber=BigInt(cursor.blockNumber);
 if(input.build){
  input.lease.finalizedAnchor.blockNumber=BigInt(input.lease.finalizedAnchor.blockNumber);
  result=await retained.build({config:input.config,lease:input.lease,checkpoint,rpcRequests:input.receipt.rpcRequests,
   startedAtMs:1790762400098,completedAtMs:1790762400123});
 }else await retained.commit({config:input.config,lease:input.lease,checkpoint,receipt:input.receipt});
}
console.log(JSON.stringify(input.build?result:await retained.read()));await globalThis.__cybergoldDashboardPgPool?.end();
'''
    async def retained_read(extra=None):
        output=await asyncio.to_thread(node,['--input-type=module','-e',script],json.dumps({'config':config,**(extra or {})}))
        return json.loads(output)
    assert await retained_read()==case['receipt']
    assert await retained_read({'build':True,'checkpoint':checkpoint,'lease':{'reconciliationId':lease.reconciliation_id,
        'configRevision':lease.config_revision,'finalizedAnchor':anchor},'receipt':case['receipt']})==built
    # Failure after earlier upserts rolls back all completion state together.
    try:await state.commit(SimpleNamespace(reconciliation_id=None,config_revision='f'*64),checkpoint,case['receipt'])
    except NotNullViolation:pass
    else:raise AssertionError('Native failed completion did not roll back')
    assert await retained_read()==case['receipt'] and await state.receipt(runtime(),1000)==case['receipt']
    await state.commit(lease,checkpoint,None)
    assert await retained_read() is None and await state.read_state(RECEIPT_KEY) is None
    next_receipt={**case['receipt'],'reconciliationId':'fixture:node-write'}
    await retained_read({'write':True,'checkpoint':checkpoint,'lease':{'reconciliationId':'fixture:node-write',
        'configRevision':lease.config_revision},'receipt':next_receipt})
    assert await state.receipt(runtime(),1000)==next_receipt
    # A newer, partial model invalidates the completed health record in both.
    async with database.connection() as connection:
        await persist_snapshot(connection,config['chainId'],config['coreAddress'],REQUIRED_MODELS[0],101,{'fixture':'partial'})
    assert await retained_read() is None and await state.receipt(runtime(),1000) is None
    return {'completionNodePythonBidirectionalWrites':True,'failedCompletionAtomic':True,
        'partialCompletionDeletesPriorReceipt':True,'latestIncompleteSnapshotSuppressesReceipt':True,
        'nativeReceiptDurableCountsMatchNode':True}
