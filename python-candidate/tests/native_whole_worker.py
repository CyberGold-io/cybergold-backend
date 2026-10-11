"""Whole Linux worker replay versus historical Node, disposable data."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time

import httpx

from cybergold_candidate.database import Database
from cybergold_candidate.environment import CATALOG
from cybergold_candidate.fork_recovery import prepare_generation

ROOT = Path(__file__).parents[2]
CORE, SAFE = '0x' + '4' * 40, '0x' + '6' * 40
CHAIN = int(os.environ.get('FIXTURE_CHAIN_ID', '31338'))
IMAGE = os.environ.get('FIXTURE_IMAGE', 'cybergold-python-candidate:market-parity')
DATABASE_CONTAINER = 'cybergold-python-whole-worker-db'
WORKER_CONTAINER = 'cybergold-python-whole-worker'
RPC_CONTAINER = 'cybergold-python-whole-worker-rpc'
API_CONTAINER = 'cybergold-python-whole-worker-api'
NETWORK = 'cybergold-python-whole-worker-fixture'
TABLES = ['onchain_sync_state','onchain_token_balances','onchain_holder_balance_deltas','onchain_recovery_share_balances',
    'onchain_recovery_share_balances_v2','onchain_read_model_snapshots','onchain_event_logs','onchain_raw_logs']
CURRENT = {'generation': '11111111-1111-4111-8111-111111111111', 'forkBlock': 100, 'forkBlockHash': '0x' + f'{100:064x}'}
NODE = '''
import {runOnchainIndexerWorkerOnce,getOnchainDashboardSummary,getLastOnchainIndexerRpcRequestCounts,getSandboxForkGenerationStatus} from './src/server/onchain-indexer/indexer.ts';
const result=await runOnchainIndexerWorkerOnce({force:true});
let fork=null,forkError=null;try{fork=await getSandboxForkGenerationStatus();}catch(error){forkError=error.message;}
console.log(JSON.stringify({result,snapshot:await getOnchainDashboardSummary(),fork,forkError,counts:getLastOnchainIndexerRpcRequestCounts()},(_key,value)=>typeof value==='bigint'?value.toString():value));
await globalThis.__cybergoldDashboardPgPool?.end();
'''


def port(container, number):
    return subprocess.check_output(['docker','port',container,str(number)+'/tcp'],text=True).strip().rsplit(':',1)[1]


async def qualify(dsn, worker_url, api_url, rpc_url, env):
    database = Database(dsn)
    await database.ensure_schema()
    async def reset():
        async with database.connection() as connection:
            for table in TABLES:await connection.execute('DELETE FROM '+table+' WHERE chain_id=%s',(str(CHAIN),))
            if CHAIN == 31338:
                async with connection.transaction():await prepare_generation(connection,CORE,CURRENT)
    async def view():
        result={}
        async with database.connection() as connection:
            for table in TABLES:
                result[table]=(await (await connection.execute("SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'updated_at'-'created_at' AS value FROM "+table+' t WHERE chain_id=%s) data',(str(CHAIN),))).fetchone())['rows']
        return result
    async def node():
        return json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node','--import','tsx','--input-type=module','-e',NODE],cwd=ROOT,
            env={**env,'DATABASE_URL':dsn,'ONCHAIN_INDEXER_RPC_URL':rpc_url,'NEXT_PUBLIC_RPC_URL':rpc_url},text=True))
    try:
        await reset()
        retained=await node();retained_rows=await view()
        await reset()
        async with httpx.AsyncClient(timeout=90) as client:
            auth={'Authorization':'Bearer '+'t'*40}
            body={'formatVersion':1,'kind':'cybergold-b2b-reconcile-request','mode':'require-worker-run'}
            anonymous=await client.post(worker_url+'/api/internal/onchain-indexer/reconcile',json=body)
            assert anonymous.status_code==401
            response=await client.post(worker_url+'/api/internal/onchain-indexer/reconcile?diagnostic=1',headers=auth,json=body)
            assert response.status_code==200,(response.status_code,response.text)
            assert response.json()=={'kind':'cybergold-b2b-reconcile-response','formatVersion':2,**retained['result']},response.text
            actual_rows=await view()
            legacy = 'onchain_recovery_share_balances'
            assert actual_rows[legacy] == [], 'Python repopulated the retired legacy projection'
            assert {table: rows for table, rows in actual_rows.items() if table != legacy} == {
                table: rows for table, rows in retained_rows.items() if table != legacy}
            fork=await client.get(worker_url+'/api/internal/onchain-indexer/fork-generation',headers=auth)
            if CHAIN == 31338:
                assert fork.json()['current']==retained['fork'] and retained['fork']['status']=='ready'
            else:
                assert retained['forkError']=='Sandbox fork recovery requires the chain-31338 indexer'
                assert fork.status_code==503 and fork.json()=={'error':'Sandbox fork generation status failed'}
            before=(await client.get(rpc_url+'/fixture')).json()['requests']
            metrics=await client.get(worker_url+'/metrics')
            assert metrics.status_code==200 and 'cybergold_backend_indexer_runs_total' in metrics.text
            assert (await client.get(rpc_url+'/fixture')).json()['requests']==before,'Metrics scrape invoked RPC'
            # Current retained config disables App-side gateway receipts. Do not
            # invent a successful completed receipt for this direct RPC mode.
            health=await client.get(worker_url+'/api/internal/onchain-indexer/reconcile',headers=auth)
            assert health.status_code==503 and health.json()=={'error':'Completed on-chain indexer reconciliation is unavailable'}
            dashboard=await client.get(api_url+'/api/dashboard/onchain-summary')
            expected_snapshot = {**retained['snapshot'], **({'sandboxForkGeneration': CURRENT['generation']} if CHAIN == 31338 else {})}
            assert dashboard.status_code==200 and dashboard.json()==expected_snapshot,{'status':dashboard.status_code,'actual':dashboard.text,'retained':expected_snapshot}
            core=await client.get(api_url+'/api/activity/core')
            safe=await client.get(api_url+'/api/activity/safe')
            assert core.status_code==safe.status_code==200 and core.json()['enabled'] and safe.json()['enabled']
            assert core.json()['events'][0]['eventName']=='Transfer'
            assert safe.json()['events'][0]['eventName']=='ExecutionSuccess'
            rpc=await client.post(api_url+'/api/rpc',json={'jsonrpc':'2.0','id':7,'method':'eth_chainId','params':[]})
            assert rpc.status_code==200 and rpc.json()=={'jsonrpc':'2.0','id':7,'result':hex(CHAIN)}
        # Historical Node remains an oracle, but no longer a supported image
        # rollback: its legacy reader requires rows Python no longer maintains.
        # Exercise shutdown during a real reconciliation, not a stub engine.
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(rpc_url+'/fixture',json={'delayNextBlockSeconds':2})
            request=asyncio.create_task(client.post(worker_url+'/api/internal/onchain-indexer/reconcile',headers=auth,json=body))
            for attempt in range(100):
                if (await client.get(rpc_url+'/fixture')).json()['delayActive']:break
                await asyncio.sleep(.02)
            else:raise RuntimeError('Synthetic RPC did not observe the in-flight worker run')
            await asyncio.to_thread(subprocess.run,['docker','stop','--time','20',WORKER_CONTAINER],check=True,capture_output=True)
            response=await request
            assert response.status_code==200 and response.json()['status']=='reconciled',response.text
        assert subprocess.check_output(['docker','inspect',WORKER_CONTAINER,'--format','{{.State.ExitCode}}'],text=True).strip()=='0'
        assert await view()==actual_rows,'Shutdown changed completed state'
        subprocess.run(['docker','stop','--time','20',API_CONTAINER],check=True,capture_output=True)
        assert subprocess.check_output(['docker','inspect',API_CONTAINER,'--format','{{.State.ExitCode}}'],text=True).strip()=='0'
        return {'result':'pass','nativeWholeWorkerReplayMatchesActualNode':True,'nativeWholeWorkerLegacyV2ModelsAndSafeHistoryMatch':True,
            'nativeWholeWorkerForkDispositionMatchesNode':True,'chainId':CHAIN,'nativeWholeWorkerAuthenticatedControlAndNoRpcAtScrape':True,
            'nativeWholeWorkerDirectModeDoesNotInventReceipt':True,'nativeWholeWorkerLegacyProjectionRetired':True,
            'nativeInstalledRoleCommandsStartPythonApiAndWorker':True,'nativeConfiguredApiReadsWorkerWrites':True,
            'nativeWorkerSigtermDrainsInFlightReconciliation':True,'nativeApiSigtermClosesPool':True,
            'testedImageId':subprocess.check_output(['docker','image','inspect',IMAGE,'--format','{{.Id}}'],text=True).strip(),
            'installedEndpointsOrDatabaseUsed':False,'coreRawRows':len(actual_rows['onchain_raw_logs']),
            'snapshotModels':len(actual_rows['onchain_read_model_snapshots'])}
    finally:await database.close()


if __name__=='__main__':
    env={key:value for key,value in os.environ.items() if key not in {setting['name'] for setting in CATALOG}}
    values={'NEXT_PUBLIC_CHAIN_ID':str(CHAIN),'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS':CORE,'SAFE_EVENT_INDEXER_SAFE_ADDRESSES':SAFE,
        'ONCHAIN_INDEXER_START_BLOCK':'100','ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE':'1','ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS':'1',
        'ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED':'1','ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED':'1','ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED':'1',
        'ONCHAIN_INDEXER_WORKER_TOKEN':'t'*40}
    try:
        subprocess.run(['docker','network','create',NETWORK],check=True,capture_output=True)
        subprocess.run(['docker','run','--detach','--name',DATABASE_CONTAINER,'--network',NETWORK,'--env','POSTGRES_HOST_AUTH_METHOD=trust',
            '--publish','127.0.0.1::5432','postgres:16'],check=True,capture_output=True)
        for attempt in range(50):
            if subprocess.run(['docker','exec',DATABASE_CONTAINER,'pg_isready','-U','postgres'],capture_output=True).returncode==0:break
            time.sleep(.2)
        command=['docker','run','--detach','--name',RPC_CONTAINER,'--network',NETWORK,
            '--publish','127.0.0.1::8555',
            '--env','NEXT_PUBLIC_CHAIN_ID='+str(CHAIN),
            '--mount','type=bind,source='+str(ROOT/'python-candidate/tests')+',target=/fixture,readonly','--entrypoint','python']
        subprocess.run([*command,IMAGE,'/fixture/native_whole_worker_server.py','--rpc-only'],check=True,capture_output=True)
        for role,container,number in [('worker',WORKER_CONTAINER,3001),('api',API_CONTAINER,3000)]:
            command=['docker','run','--detach','--name',container,'--network',NETWORK,'--publish','127.0.0.1::'+str(number)]
            for key,value in {**values,'DATABASE_URL':'postgresql://postgres@'+DATABASE_CONTAINER+'/postgres','HOST':'0.0.0.0','PORT':str(number),
                'RPC_URL':'http://'+RPC_CONTAINER+':8555','NEXT_PUBLIC_RPC_URL':'http://'+RPC_CONTAINER+':8555',
                'ONCHAIN_INDEXER_RPC_URL':'http://'+RPC_CONTAINER+':8555'}.items():command.extend(['--env',key+'='+value])
            subprocess.run([*command,IMAGE,*(['python','-m','cybergold_candidate.worker_main'] if role=='worker' else [])],check=True,capture_output=True)
            for attempt in range(100):
                try:
                    if httpx.get('http://127.0.0.1:'+port(container,number)+'/metrics',timeout=1).status_code==200:break
                except httpx.RequestError:pass
                if attempt==99:raise RuntimeError('Native whole '+role+' did not start')
                time.sleep(.2)
        worker_url='http://127.0.0.1:'+port(WORKER_CONTAINER,3001)
        api_url='http://127.0.0.1:'+port(API_CONTAINER,3000);rpc_url='http://127.0.0.1:'+port(RPC_CONTAINER,8555)
        print(json.dumps(asyncio.run(qualify('postgresql://postgres@127.0.0.1:'+port(DATABASE_CONTAINER,5432)+'/postgres',worker_url,api_url,rpc_url,{**env,**values}))))
    except Exception:
        subprocess.run(['docker','logs','--tail','30',WORKER_CONTAINER],check=False)
        raise
    finally:
        subprocess.run(['docker','rm','--force','--volumes',WORKER_CONTAINER,API_CONTAINER,RPC_CONTAINER,DATABASE_CONTAINER],capture_output=True)
        subprocess.run(['docker','network','rm',NETWORK],capture_output=True)
