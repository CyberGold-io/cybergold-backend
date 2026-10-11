"""Actual Node/Python retained reader comparison against a new local database."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time

import httpx
from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from cybergold_candidate.app import create_app
from cybergold_candidate.safe_activity import get_safe_activity, select_safe_activity
from cybergold_candidate.core_activity import get_core_activity, select_core_activity
from cybergold_candidate.retained_reads import dashboard_snapshot, cached_pools
from cybergold_candidate.aliases import AliasAuthError, verify_and_consume, list_aliases, upsert_alias, delete_alias
from native_alias_http import qualify as qualify_alias_http
from cybergold_candidate.database import Database
from cybergold_candidate.environment import load_environment
from cybergold_candidate.runtime import create_configured_app
from cybergold_candidate.raw_journal import replace_range, read_coverage, read_logs
from cybergold_candidate.snapshot_persistence import persist_snapshot, DASHBOARD_MODEL
from cybergold_candidate.pool_cache import PoolCache
from cybergold_candidate.safe_status import SafeStatus, SafeEventLimitError
from native_recovery_db import qualify_recovery
from native_completed_db import qualify as qualify_completed
from native_fork_db import qualify as qualify_fork
from native_holder_db import qualify as qualify_holder
from native_safe_projection_db import qualify as qualify_safe_projection
from native_raw_ingestion_db import qualify as qualify_raw_ingestion
from native_safe_collector_db import qualify as qualify_safe_collector
from native_product_reads_db import qualify as qualify_product_reads
from native_snapshot_refresh_db import qualify as qualify_snapshot_refresh
from native_core_collector_db import qualify as qualify_core_collector

ROOT = Path(__file__).parents[2]
SAFE = '0x0000000000000000000000000000000000000001'
OTHER = '0x0000000000000000000000000000000000000002'
CORE = '0x0000000000000000000000000000000000000003'


async def compare(dsn, reference):
    alias_params = reference['aliasParams']
    reference = reference['views']
    # Same canonical DDL, shared bootstrap, retained rows and native pool lifecycle.
    class ObservedDatabase(Database):
        initializations = 0
        async def initialize_schema(self):
            self.initializations += 1
            await super().initialize_schema()
    database = ObservedDatabase(dsn)
    assert database.pool is None
    await asyncio.gather(*(database.ensure_schema() for _ in range(8)))
    assert database.initializations == 1 and database.pool.max_size == 8
    native_pool = database.pool
    assert await database.get_pool() is native_pool
    async with database.connection() as connection:
        assert (await (await connection.execute('SELECT count(*) AS count FROM onchain_raw_logs')).fetchone())['count'] == 5
        try:
            async with connection.transaction():
                await connection.execute('SELECT 1/0')
        except errors.DivisionByZero:
            pass
        assert (await (await connection.execute('SELECT 1 AS recovered')).fetchone())['recovered'] == 1
    node_lock_code = '''import {withSharedAdvisoryLock} from './src/server/onchain-indexer/db.ts';
        console.log(JSON.stringify(await withSharedAdvisoryLock('python-shared-writer-fixture',async()=>true)));
        await globalThis.__cybergoldDashboardPgPool?.end();'''
    async def node_lock():
        output = await asyncio.to_thread(subprocess.check_output,['node','--env-file=tests/fixture.env','--import','tsx',
            '--input-type=module','-e',node_lock_code],cwd=ROOT,env={**os.environ,'DATABASE_URL':dsn},text=True)
        return json.loads(output)
    async with database.advisory_lock('python-shared-writer-fixture') as acquired:
        assert acquired is True
        assert await node_lock() == {'acquired':False}
    assert await node_lock() == {'acquired':True,'result':True}
    journal_address='0x'+'7'*40
    journal_hash='0x'+'a'*64
    journal_log={'contractAddress':journal_address,'blockNumber':100,'blockHash':journal_hash,
        'transactionHash':'0x'+'b'*64,'logIndex':0,'topics':[],'data':'0x','blockTimestampSeconds':1000}
    replacement={'chainId':31338,'address':journal_address,'authoritativeStartBlock':100,
        'fromBlock':100,'toBlock':101,'toBlockHash':journal_hash,'journalVersion':'1','logs':[journal_log]}
    await replace_range(database,**replacement)
    async def journal_view():
        async with database.connection() as connection:
            coverage=await read_coverage(connection,31338,journal_address,'1')
            logs=await read_logs(connection,31338,journal_address,100,101,coverage)
            return coverage,logs
    initial=await journal_view()
    # A native DB error occurs after deletion; transaction rollback preserves
    # both retained log data and coverage without any schema/data restore.
    try:
        await replace_range(database,**{**replacement,'logs':[{**journal_log,'blockTimestampSeconds':'not-an-integer'}]})
    except errors.InvalidTextRepresentation:
        pass
    else:
        raise AssertionError('Invalid retained PostgreSQL row unexpectedly succeeded')
    assert await journal_view()==initial
    reorg_hash='0x'+'c'*64
    await replace_range(database,**{**replacement,'toBlockHash':reorg_hash,
        'logs':[{**journal_log,'blockHash':reorg_hash,'blockNumber':101}]})
    reorg=await journal_view()
    assert reorg[0]['cursorBlockHash']==reorg_hash and reorg[1][0]['blockNumber']==101
    node_journal_code='''import {readRawJournalCoverage,readRawJournalLogs} from './src/server/onchain-indexer/rawLogJournal.ts';
        const input={chainId:31338n,address:'0x'+'7'.repeat(40),expectedVersion:'1'};
        const coverage=await readRawJournalCoverage(input);
        const logs=await readRawJournalLogs({...input,fromBlock:100n,toBlock:101n,coverage});
        console.log(JSON.stringify({coverage,logs},(_key,value)=>typeof value==='bigint'?value.toString():value));
        await globalThis.__cybergoldDashboardPgPool?.end();'''
    node_journal=json.loads(await asyncio.to_thread(subprocess.check_output,
        ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',node_journal_code],
        cwd=ROOT,env={**os.environ,'DATABASE_URL':dsn},text=True))
    def wire_journal(value):
        return {key:str(item) if key in ('startBlock','cursorBlock','blockNumber','blockTimestampSeconds') else item
                for key,item in value.items()}
    assert node_journal=={'coverage':wire_journal(reorg[0]),'logs':[wire_journal(log) for log in reorg[1]]}
    await replace_range(database,**{**replacement,'toBlockHash':reorg_hash,'logs':[]})
    assert (await journal_view())[1]==[]
    for block in range(100,106):
        async with database.connection() as connection:
            async with connection.transaction():
                await persist_snapshot(connection,31338,journal_address,DASHBOARD_MODEL,block,
                    {'enabled':True,'lastScannedBlock':str(block),'supply':str(2**256-1)})
    async def snapshot_rows():
        async with database.connection() as connection:
            cursor=await connection.execute('''SELECT block_number::text,payload FROM onchain_read_model_snapshots
                WHERE chain_id=31338 AND contract_address=%s AND model_key=%s ORDER BY block_number DESC''',
                (journal_address,DASHBOARD_MODEL))
            return await cursor.fetchall()
    assert [row['block_number'] for row in await snapshot_rows()]==['105','104','103','102']
    async with database.connection() as connection:
        async with connection.transaction():
            await persist_snapshot(connection,31338,journal_address,DASHBOARD_MODEL,103,
                {'enabled':True,'lastScannedBlock':'103','supply':str(2**256-1)})
    assert [row['block_number'] for row in await snapshot_rows()]==['103','102']
    node_snapshot_code='''import {readCachedDashboardSnapshot} from './src/server/onchain-indexer/dashboardSnapshotRepository.ts';
        console.log(JSON.stringify(await readCachedDashboardSnapshot({chainId:31338n,coreAddress:'0x'+'7'.repeat(40)})));
        await globalThis.__cybergoldDashboardPgPool?.end();'''
    node_snapshot=json.loads(await asyncio.to_thread(subprocess.check_output,
        ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',node_snapshot_code],
        cwd=ROOT,env={**os.environ,'DATABASE_URL':dsn},text=True))
    assert node_snapshot==(await snapshot_rows())[0]['payload']
    pool_service=PoolCache(database)
    observations=[{'chainId':7,'dex':'uniswap_v3','tokenA':OTHER,'tokenB':SAFE,'fee':500,'exists':False},
        {'chainId':7,'dex':'uniswap_v3','tokenA':SAFE,'tokenB':OTHER,'fee':500,'exists':True,
         'quoteSucceeded':True,'poolAddress':CORE,'activeLiquidityRaw':str(2**64),
         'sqrtPriceX96Raw':str(2**96),'tick':-1,'token0BalanceRaw':'0','token1BalanceRaw':'2'}]
    await pool_service.record(observations)
    await pool_service.record([{**observations[0],'quoteSucceeded':True}])
    py_pools=await pool_service.list(7,'uniswap_v3',[{'tokenA':OTHER,'tokenB':SAFE}])
    node_pool_code='''import {listCachedPools,recordPoolObservations} from './src/server/quote-pool-cache/repository.ts';
        const original=JSON.parse(process.env.FIXTURE_OBSERVATIONS);
        await recordPoolObservations({entries:original.map(entry=>({...entry,chainId:8}))});
        await recordPoolObservations({entries:[{...original[0],chainId:8,quoteSucceeded:true}]});
        const input={dex:'uniswap_v3',pairs:[{tokenA:original[0].tokenA,tokenB:original[0].tokenB}]};
        console.log(JSON.stringify({python:await listCachedPools({...input,chainId:7}),node:await listCachedPools({...input,chainId:8})}));
        await globalThis.__cybergoldDashboardPgPool?.end();'''
    node_pools=json.loads(await asyncio.to_thread(subprocess.check_output,
        ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',node_pool_code],
        cwd=ROOT,env={**os.environ,'DATABASE_URL':dsn,'FIXTURE_OBSERVATIONS':json.dumps(observations)},text=True))
    assert node_pools['python']==py_pools
    def without_times(rows):return [{key:value for key,value in row.items() if not key.endswith('At')} for row in rows]
    assert without_times(py_pools)==without_times(node_pools['node'])
    assert py_pools[0]['successCount']==2 and py_pools[0]['activeLiquidityRaw']==str(2**64)
    await database.close()
    assert native_pool.closed
    async with AsyncConnectionPool(dsn, min_size=0, max_size=8, kwargs={'row_factory': dict_row}) as pool:
        actual = {}
        for name, chain, addresses in [('initial', 31338, [SAFE, OTHER]), ('separateChain', 1, [SAFE, OTHER]),
                                       ('oneSafe', 31338, [OTHER]), ('noAddresses', 31338, [])]:
            async with pool.connection() as connection:
                async with connection.transaction():
                    await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    actual[name] = await select_safe_activity(connection, chain, addresses, 50_000)
        for name, chain, address in [('coreInitial', 31338, CORE), ('coreOtherChain', 1, CORE),
                                    ('coreOtherAddress', 31338, '0x0000000000000000000000000000000000000004')]:
            async with pool.connection() as connection:
                async with connection.transaction():
                    await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    actual[name] = await select_core_activity(connection, chain, address)
        actual['dashboard'] = await dashboard_snapshot(pool, 31338, CORE)
        actual['otherDashboard'] = await dashboard_snapshot(pool, 1, CORE)
        pairs = [{'tokenA':OTHER,'tokenB':SAFE},{'tokenA':SAFE,'tokenB':OTHER}]
        actual['pools'] = await cached_pools(pool, 31338, 'uniswap_v3', pairs)
        actual['otherPools'] = await cached_pools(pool, 1, 'uniswap_v3', pairs)
        actual['emptyPools'] = await cached_pools(pool, 31338, 'uniswap_v3', [])
        actual['aliases'] = await list_aliases(pool, alias_params['editorAddress'],[OTHER,SAFE,OTHER])
        actual['emptyAliases'] = await list_aliases(pool,alias_params['editorAddress'],[])
        assert actual == reference, 'Node/Python retained SQL view mismatch'
        assert len(actual['pools']) == 2, 'Duplicate/reversed pair or expired pool leaked into view'
        assert await dashboard_snapshot(None, 31338, CORE) == {'enabled':False,'protocolLogicUpdate':None,
            'protocolParameterUpdate':None,'lastScannedBlock':None}
        try:
            await dashboard_snapshot(pool, 31338, OTHER)
        except RuntimeError as error:
            assert str(error) == 'On-chain dashboard has no completed cached snapshot'
        else:
            raise AssertionError('Missing completed snapshot was hidden')
        # Two accepted requests race on the retained database nonce constraint.
        async def consume():
            try:
                await verify_and_consume(pool,alias_params,1790762400000,1790762400000)
                return 'consumed'
            except AliasAuthError as error:
                return str(error)
        outcomes = await asyncio.gather(consume(),consume())
        assert sorted(outcomes) == ['Alias authorization nonce has already been used.','consumed']
        saved = await upsert_alias(pool,alias_params['editorAddress'],SAFE,'Python durable write')
        assert saved['alias'] == 'Python durable write'
        assert await list_aliases(pool,OTHER,[SAFE]) == [{'editorAddress':OTHER,'ownerAddress':SAFE,
            'alias':'Other editor','updatedAt':'2026-09-30T10:00:00.000Z'}]
        # Retained Node code sees the Python durable write and consumed nonce.
        code = '''import {listOwnerAliases} from './src/server/governance-owner-aliases/repository.ts';
          import {query} from './src/server/onchain-indexer/db.ts';
          const entries=await listOwnerAliases({editorAddress:process.env.FIXTURE_EDITOR,ownerAddresses:[process.env.FIXTURE_OWNER]});
          const nonces=await query('SELECT count(*)::integer AS count FROM governance_owner_alias_auth_nonces WHERE editor_address=$1 AND nonce=$2',[process.env.FIXTURE_EDITOR.toLowerCase(),'durable-candidate-nonce']);
          console.log(JSON.stringify({entries,nonces:nonces.rows[0].count}));
          await globalThis.__cybergoldDashboardPgPool?.end();'''
        output = await asyncio.to_thread(subprocess.check_output,['node','--env-file=tests/fixture.env','--import','tsx',
            '--input-type=module','-e',code],cwd=ROOT,env={**os.environ,'DATABASE_URL':dsn,
            'FIXTURE_EDITOR':alias_params['editorAddress'],'FIXTURE_OWNER':SAFE},text=True)
        old_node = json.loads(output)
        assert old_node == {'entries':[saved],'nonces':1}
        assert await delete_alias(pool,alias_params['editorAddress'],SAFE) is True
        assert await delete_alias(pool,alias_params['editorAddress'],SAFE) is False
        assert (await consume()) == 'Alias authorization nonce has already been used.'
        assert await get_safe_activity(None, 31338, [SAFE], 50_000) == {'enabled': False, 'events': []}
        assert await get_safe_activity(pool, 31338, [], 50_000) == {'enabled': False, 'events': []}
        async with pool.connection() as connection:
            try:
                async with connection.transaction():
                    await connection.execute('SET TRANSACTION READ ONLY')
                    await connection.execute('DELETE FROM onchain_raw_logs')
            except errors.ReadOnlySqlTransaction:
                pass
            else:
                raise AssertionError('Disposable PostgreSQL failed to enforce read-only transaction')
            await connection.execute('''INSERT INTO onchain_raw_logs(chain_id,contract_address,block_number,
                block_hash,tx_hash,log_index,block_timestamp_seconds,topics,data)
                SELECT 31338,%s,200+i,%s,'fixture'||i,0,1000,'[]'::jsonb,'0x'
                FROM generate_series(1,110) i''', (SAFE, '0x' + 'a' * 64))
        bounded = await get_safe_activity(pool, 31338, [SAFE, OTHER], 50_000)
        assert len(bounded['events']) == 100 and bounded['hasMore'] is True
        assert bounded['events'][0]['blockNumber'] == '310'
        async with pool.connection() as connection:
            await connection.execute('DELETE FROM onchain_raw_logs WHERE chain_id=31338 AND contract_address=%s AND block_number>=300', (SAFE,))
        rolled_back = await get_safe_activity(pool, 31338, [SAFE, OTHER], 50_000)
        assert rolled_back['events'][0]['blockNumber'] == '299'
        assert rolled_back['coverage'][0]['projectionIndexedThroughBlock'] == '60000'
        async with pool.connection() as connection:
            cursor = await connection.execute('SELECT count(*) AS count FROM onchain_event_logs')
            assert (await cursor.fetchone())['count'] == 0

        async def read():
            return await get_safe_activity(pool, 31338, [SAFE, OTHER], 50_000)

        async def core_read():
            return await get_core_activity(pool, 31338, CORE)

        async def dashboard_read():
            return await dashboard_snapshot(pool, 31338, CORE)

        async with httpx.AsyncClient() as supplier:
            app = create_app(client=supplier, safe_activity=read, core_activity=core_read, dashboard=dashboard_read)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as api:
                    response = await api.get('/api/activity/safe')
                    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
                    assert response.json() == rolled_back
                    core_response = await api.get('/api/activity/core')
                    assert core_response.status_code == 200 and core_response.headers['Cache-Control'] == 'no-store'
                    assert core_response.json() == reference['coreInitial']
                    dashboard = await api.get('/api/dashboard/onchain-summary')
                    assert dashboard.json() == reference['dashboard']
                    assert dashboard.headers['Cache-Control'] == 'public, max-age=10, stale-while-revalidate=20'
            settings=load_environment({'NEXT_PUBLIC_CHAIN_ID':'31338','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS':CORE,
                'NEXT_PUBLIC_RPC_URL':'http://fixture.invalid','DATABASE_URL':dsn,
                'SAFE_EVENT_INDEXER_SAFE_ADDRESSES':SAFE+','+OTHER})
            configured_database=Database(dsn)
            configured=create_configured_app(settings,configured_database,supplier)
            async with configured.router.lifespan_context(configured):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(configured),base_url='http://fixture') as api:
                    assert (await api.get('/api/activity/safe')).json()==rolled_back
                    assert (await api.get('/api/activity/core')).json()==reference['coreInitial']
                    configured_dashboard = (await api.get('/api/dashboard/onchain-summary')).json()
                    assert configured_dashboard == {**reference['dashboard'], 'sandboxForkGeneration': None}
                    alias_http_result=await qualify_alias_http(api,configured_database,dsn,ROOT)
            assert configured_database.pool is None
        status_hash='0x'+'d'*64
        async with pool.connection() as connection:
            for chain,address,block,index,name in [(31338,SAFE,100,0,'ExecutionSuccess'),
                    (31338,SAFE,101,1,'ExecutionFailure'),(1,SAFE,102,2,'ExecutionSuccess'),
                    (31338,OTHER,103,3,'ExecutionSuccess')]:
                await connection.execute('''INSERT INTO onchain_event_logs(chain_id,contract_address,
                    event_name,block_number,tx_hash,log_index,block_timestamp,payload)
                    VALUES(%s,%s,%s,%s,%s,%s,'2026-09-30T10:00:00Z',%s::jsonb)''',
                    (chain,address,name,block,'0x'+'e'*64,index,json.dumps({'args':{'txHash':status_hash}})))
        fixed_now=1790762430123
        status_service=SafeStatus(pool,31338,[SAFE],lambda:fixed_now)
        python_status=await status_service.get(SAFE,[status_hash])
        node_status_code='''import {getSafeExecutionStatuses} from './src/server/safe-events/indexer.ts';
            Date.now=()=>1790762430123;
            console.log(JSON.stringify(await getSafeExecutionStatuses(process.env.FIXTURE_SAFE,[process.env.FIXTURE_HASH])));
            await globalThis.__cybergoldDashboardPgPool?.end();'''
        node_status=json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node','--env-file=tests/fixture.env','--import','tsx','--input-type=module','-e',node_status_code],
            cwd=ROOT,env={**os.environ,'DATABASE_URL':dsn,'NEXT_PUBLIC_CHAIN_ID':'31338',
                'SAFE_EVENT_INDEXER_SAFE_ADDRESSES':SAFE,'FIXTURE_SAFE':SAFE,'FIXTURE_HASH':status_hash},text=True))
        assert python_status==node_status and python_status[0]['status']=='failed'
        assert python_status[0]['blockNumber']=='101'
        scope=f'safe-events:31338:{SAFE}'
        async with pool.connection() as connection:
            counters=await (await connection.execute('SELECT scope,request_count FROM onchain_api_rate_limits')).fetchall()
            assert sorted(row['request_count'] for row in counters)==[2,2]
            await connection.execute('UPDATE onchain_api_rate_limits SET request_count=60 WHERE scope=%s',(scope,))
        try:
            await status_service.get(SAFE,[status_hash])
        except SafeEventLimitError as failure:
            assert failure.retry==30 and str(failure)=='Safe event request rate limit exceeded.'
        else:raise AssertionError('Retained per-Safe shared rate limit was not applied')
        async with pool.connection() as connection:
            await connection.execute('UPDATE onchain_api_rate_limits SET request_count=1')
            await connection.commit()
            for slot in range(8):
                await connection.execute('SELECT pg_advisory_lock(hashtext(%s),%s)',(scope+':concurrency',slot))
            try:
                try:
                    await status_service.get(SAFE,[status_hash])
                except SafeEventLimitError as failure:
                    assert failure.retry==1 and str(failure)=='Safe event indexer is busy.'
                else:raise AssertionError('Retained eight-slot concurrency boundary was not applied')
            finally:
                for slot in range(8):
                    await connection.execute('SELECT pg_advisory_unlock(hashtext(%s),%s)',(scope+':concurrency',slot))
        assert await status_service.get(SAFE,[status_hash])==python_status
        recovery_result=await qualify_recovery(pool,dsn,ROOT)
        completed_result=await qualify_completed(pool,dsn)
        fork_result=await qualify_fork(pool,dsn)
        holder_result=await qualify_holder(pool,dsn)
        safe_projection_result=await qualify_safe_projection(pool,dsn)
        raw_ingestion_result=await qualify_raw_ingestion(pool,dsn)
        safe_collector_result=await qualify_safe_collector(pool,dsn)
        product_reads_result=await qualify_product_reads(pool,dsn)
        snapshot_refresh_result=await qualify_snapshot_refresh(pool,dsn)
        core_collector_result=await qualify_core_collector(pool,dsn)
        return {'result': 'pass', 'nodePythonViewsCompared': 14, 'configuredSafeAndChainSeparation': True,
                'readOnlyTransaction': True, 'uint256Lossless': True, 'bounded100Rows': True,
                'reorgDeletionVisible': True, 'projectionUnchanged': True, 'fastApiNoStore': True,
                'dashboardLatestModelAndOpaquePayload':True,'poolChainPairAgeOrdering':True,
                'aliasEditorNamespace':True,'aliasConcurrentNonceConsumption':True,
                'retainedNodeSeesPythonAliasAndNonce':True,'aliasDeleteRetainsConsumedNonce':True,
                'lazyPoolMaximumEight':True,'sharedSchemaBootstrapPreservesRows':True,
                'nodePythonSingleWriterLock':True,'failedJournalReplacementAtomic':True,
                'retainedNodeSeesPythonReorgJournal':True,'emptyRangeReplacesLogs':True,
                'snapshotRetentionAndRewind':True,'retainedNodeSeesPythonSnapshot':True,
                'configuredApiReadsAndPoolShutdown':True,'poolObservationWriteMatchesNode':True,
                'retainedNodeSeesPythonPoolObservation':True,'safeExecutionStatusMatchesNode':True,
                'safeRateCountersSharedWithNode':True,'safeConcurrencyAndRecovery':True,
                'installedDatabaseUsed': False,**recovery_result,**alias_http_result,**completed_result,**fork_result,**holder_result,**safe_projection_result,**raw_ingestion_result,**safe_collector_result,**product_reads_result,**snapshot_refresh_result,**core_collector_result}


container = 'cybergold-python-safe-db-fixture'
try:
    subprocess.run(['docker', 'run', '--detach', '--name', container, '--env', 'POSTGRES_HOST_AUTH_METHOD=trust',
                    '--publish', '127.0.0.1::5432', 'postgres:16'], check=True, capture_output=True)
    for attempt in range(50):
        if subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'postgres'], capture_output=True).returncode == 0:
            break
        if attempt == 49:
            raise RuntimeError('Disposable PostgreSQL did not start')
        time.sleep(.2)
    port = subprocess.check_output(['docker', 'port', container, '5432/tcp'], text=True).strip().rsplit(':', 1)[1]
    dsn = 'postgresql://postgres@127.0.0.1:' + port + '/postgres'
    environment = {**os.environ, 'DATABASE_URL': dsn}
    output = subprocess.check_output(['node', '--env-file=tests/fixture.env', '--import', 'tsx',
                                     'python-candidate/tests/node-safe-db-reference.ts'], cwd=ROOT, env=environment, text=True)
    print(json.dumps(asyncio.run(compare(dsn, json.loads(output)))))
finally:
    subprocess.run(['docker', 'rm', '-f', '-v', container], capture_output=True)
