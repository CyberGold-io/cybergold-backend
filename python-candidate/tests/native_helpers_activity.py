"""Independent Helpers backfill/reorg/fork recovery on disposable PostgreSQL."""
import asyncio
import argparse
import json
from pathlib import Path
import subprocess
import time
from unittest.mock import patch

import httpx

from cybergold_candidate.database import Database
from cybergold_candidate.fork_recovery import prepare_generation, apply_generation
from cybergold_candidate.helpers_activity import ABI, decode_helpers_activity, get_helpers_activity
from cybergold_candidate.helpers_collector import HelpersCollector
from cybergold_candidate.app import create_app
from cybergold_candidate.environment import load_environment
from cybergold_candidate.worker_engine import WorkerEngine
from cybergold_candidate.indexing_budget import IndexingRpcPacer
from cybergold_candidate.indexer_rpc import IndexerProvider, IndexerRpc

ROOT = Path(__file__).parents[2]
ADDRESS, CORE = '0x' + '2' * 40, '0x' + '3' * 40


async def qualify(dsn, fixture):
    assert ABI == fixture['events'], 'Helpers activity ABI differs from the canonical generated ABI'
    for row in fixture['rows']:
        value = decode_helpers_activity(row)
        assert {key: value[key] for key in ('eventName', 'arguments')} == row['expected'], (row['expected'], value)
    malformed = {**fixture['rows'][0], 'data': '0x01'}
    assert decode_helpers_activity(malformed)['eventName'] is None
    unknown = {**fixture['rows'][0], 'topics': ['0x' + 'f' * 64]}
    assert decode_helpers_activity(unknown)['eventName'] is None
    database = Database(dsn)
    await database.ensure_schema()
    try:
        async with database.connection() as connection:
            await connection.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
                VALUES (31338,%s,'last_scanned_block','105'),(1,%s,'last_scanned_block','999')''', (CORE, ADDRESS))
        config = {'chainId': 31338, 'startBlock': 100, 'chunkSize': 1, 'maxBlocksPerRun': 2, 'reorgWindow': 2}
        collector = HelpersCollector(database, config, ADDRESS)
        class Rpc:
            salt, latest, fail, cancel = 0, 105, False, False
            calls = []
            @staticmethod
            def hash(number, salt=0):
                return '0x' + f'{number + (salt if number >= 103 else 0):064x}'
            async def block(self, number=None, *, block_hash=None):
                number = self.latest if isinstance(number, str) else number
                return {'number': number, 'hash': self.hash(number, self.salt), 'timestamp': 1000 + number}
            async def logs(self, address, interval):
                self.calls.append((address, interval))
                if self.fail: raise ConnectionError('Synthetic Helpers RPC unavailable')
                if self.cancel: raise asyncio.CancelledError()
                return [{'address': address, 'blockNumber': hex(101), 'blockHash': self.hash(101),
                    'transactionHash': row['tx_hash'], 'logIndex': hex(row['log_index']),
                    'topics': row['topics'], 'data': row['data']} for row in fixture['rows']
                    if interval['fromBlock'] <= 101 <= interval['toBlock']]
            async def close(self):
                pass
        rpc = Rpc()
        outcomes = [await collector.reconcile(rpc, rpc) for _ in range(3)]
        assert [item['indexedThroughBlock'] for item in outcomes] == ['101', '103', '105']
        assert [item['completed'] for item in outcomes] == [False, False, True]
        assert rpc.calls[0][1]['fromBlock'] == 100, 'Helpers adopted the unrelated Core cursor'
        view = await get_helpers_activity(database, 31338, ADDRESS)
        assert len(view['events']) == 16 and view['journalStartBlock'] == '100' and view['indexedThroughBlock'] == '105'
        assert view['source'] == 'retained-helpers-journal'
        calls = len(rpc.calls)
        assert (await collector.reconcile(rpc, rpc))['counts']['attempts'] == 0 and len(rpc.calls) == calls
        assert not (await get_helpers_activity(database, 1, ADDRESS))['events']
        assert not (await get_helpers_activity(database, 31338, CORE))['events']
        assert await get_helpers_activity(None, 31338, ADDRESS) == {'enabled': False, 'events': []}
        async def read():
            return await get_helpers_activity(database, 31338, ADDRESS)
        app = create_app(helpers_activity=read)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as api:
                response = await api.get('/api/activity/helpers')
                assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
                assert response.json() == view
                assert (await api.head('/api/activity/helpers')).content == b''
        # The operator view stays bounded even when the retained journal grows.
        async with database.connection() as connection:
            await connection.execute('''INSERT INTO onchain_raw_logs
                (chain_id,contract_address,block_number,block_hash,tx_hash,log_index,
                 block_timestamp_seconds,topics,data)
                SELECT chain_id,contract_address,block_number,block_hash,
                       '0x'||lpad(to_hex(n),64,'0'),n,block_timestamp_seconds,topics,data
                FROM onchain_raw_logs CROSS JOIN generate_series(100,200) n
                WHERE chain_id=31338 AND contract_address=%s AND log_index=0''', (ADDRESS,))
        bounded = await get_helpers_activity(database, 31338, ADDRESS)
        assert bounded['hasMore'] and len(bounded['events']) == 100
        async with database.connection() as connection:
            await connection.execute('DELETE FROM onchain_raw_logs WHERE chain_id=31338 AND contract_address=%s AND log_index>=100', (ADDRESS,))

        # A changed canonical suffix must advance even with a two-block budget.
        rpc.salt = 10000
        reorg = await collector.reconcile(rpc, rpc)
        assert reorg['indexedThroughBlock'] == '104' and not reorg['completed']
        before = await collector.journal.coverage()
        rpc.fail = True
        try: await collector.reconcile(rpc, rpc)
        except ValueError as error:
            assert str(error) == 'Address-scoped log request failed without an approved range-reduction signal'
        else: raise AssertionError('Failed provider response advanced Helpers coverage')
        assert await collector.journal.coverage() == before
        rpc.fail, rpc.cancel = False, True
        try: await collector.reconcile(rpc, rpc)
        except asyncio.CancelledError: pass
        else: raise AssertionError('Cancellation was swallowed')
        assert await collector.journal.coverage() == before
        rpc.cancel = False
        assert (await collector.reconcile(rpc, rpc))['completed']

        previous = {'generation': 'helpers-old', 'forkBlock': 102, 'forkBlockHash': rpc.hash(102)}
        current = {'generation': 'helpers-next', 'forkBlock': 106, 'forkBlockHash': rpc.hash(106, rpc.salt)}
        async with database.connection() as connection:
            async with connection.transaction():
                await prepare_generation(connection, CORE, previous)
                await apply_generation(connection, CORE, previous, current, 100, rpc.hash(102))
        assert (await collector.journal.coverage())['cursorBlock'] == 102
        assert len((await get_helpers_activity(database, 31338, ADDRESS))['events']) == 16
        rpc.latest = 106
        assert (await collector.reconcile(rpc, rpc))['indexedThroughBlock'] == '104'
        assert (await collector.reconcile(rpc, rpc))['completed']
        # A divergent fork invalidates the Helpers raw journal through the
        # existing chain-wide generation transition, without extra metadata.
        next_anchor = {'generation': 'helpers-diverged', 'forkBlock': 108, 'forkBlockHash': rpc.hash(108, rpc.salt)}
        async with database.connection() as connection:
            async with connection.transaction():
                # Existing Core recovery owns readiness; no Helpers gate added.
                from cybergold_candidate.fork_recovery import mark_ready
                await mark_ready(connection, CORE, 106)
                await prepare_generation(connection, CORE, current)
                await apply_generation(connection, CORE, current, next_anchor, 100, '0x' + 'f' * 64)
        assert await collector.journal.coverage() is None
        assert not (await get_helpers_activity(database, 31338, ADDRESS))['events']
        rpc.latest = 108
        assert (await collector.reconcile(rpc, rpc))['indexedThroughBlock'] == '101'
        async with database.connection() as connection:
            mainnet = await (await connection.execute('''SELECT state_value FROM onchain_sync_state
                WHERE chain_id=1 AND contract_address=%s AND state_key='last_scanned_block' ''', (ADDRESS,))).fetchone()
            assert mainnet['state_value'] == '999'
            assert (await (await connection.execute('SELECT count(*) AS n FROM onchain_event_logs')).fetchone())['n'] == 0

        class CompletedCore:
            def __init__(self, *_args):
                pass
            async def reconcile(self, *_args, **_kwargs):
                return {'completed': True, 'dashboardHistoryProgress': None,
                    'finalizedAnchor': {'blockNumber': rpc.latest, 'blockHash': rpc.hash(rpc.latest, rpc.salt)}}
        settings = load_environment({'DATABASE_URL': dsn, 'NEXT_PUBLIC_CHAIN_ID': '1',
            'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': CORE, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS': ADDRESS,
            'RPC_URL': 'http://fixture.invalid', 'NEXT_PUBLIC_RPC_URL': 'http://fixture.invalid',
            'ONCHAIN_INDEXER_START_BLOCK': '100',
            'ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE': '1', 'ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS': '1',
            'ONCHAIN_INDEXER_MAX_BLOCKS_PER_RUN': '2'})
        engine = WorkerEngine(database, settings, rpc_factory=lambda *_args: rpc)
        # Small native recovery cases keep their fixture budget; production
        # Core and Helpers share the larger production catch-up setting.
        engine.collection_config['maxBlocksPerRun'] = 2
        await engine.collect_helpers(None)
        assert engine.helpers_progress['indexedThroughBlock'] == '101'
        with patch('cybergold_candidate.worker_engine.CoreCollector', CompletedCore):
            assert (await engine.run_once())['status'] == 'reconciled'
            assert engine.helpers_progress['indexedThroughBlock'] == '103'
            core_counts = engine.runtime['lastRpcRequestCounts']
            assert core_counts['ethGetLogs']['attempts'] == 0
            rpc.fail = True
            assert (await engine.run_once())['status'] == 'reconciled'
            assert engine.helpers_progress == {'error': True}
            assert engine.runtime['lastRpcRequestCounts'] == core_counts
            rpc.fail = False

        # Actual Core, Helpers and Safe journals on both chains use one paced
        # attempt stream and the larger block budget. Empty synthetic ranges
        # isolate collection from the separately qualified state snapshot ABI.
        elapsed, requests = 0, []
        async def paced_sleep(seconds):
            nonlocal elapsed
            elapsed += seconds
            await asyncio.sleep(0)
        def dispatch(request):
            body = json.loads(request.content)
            requests.append((body['method'], elapsed, body['params']))
            if body['method'] == 'eth_getLogs':
                result = []
            else:
                number = int(body['params'][0], 16)
                result = {'number': hex(number), 'hash': Rpc.hash(number), 'timestamp': hex(1000 + number)}
            return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})
        def transport(raw=False):
            provider = IndexerProvider('http://fixture.invalid', http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(dispatch)))
            return IndexerRpc(provider=provider, retry_count=0 if raw else 3, sleep=paced_sleep)
        async def snapshot(*_args):
            pass
        budget_core, budget_helpers, budget_safe = ('0x' + digit * 40 for digit in ('4', '7', '8'))
        anchor = {'blockNumber': 60099, 'blockHash': Rpc.hash(60099)}
        for chain in (1, 31338):
            large = WorkerEngine(database, settings.model_copy(update={
                'NEXT_PUBLIC_CHAIN_ID': str(chain),
                'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': budget_core,
                'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS': budget_helpers,
                'SAFE_EVENT_INDEXER_SAFE_ADDRESSES': budget_safe,
                'ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED': '1',
                'ONCHAIN_INDEXER_MAX_BLOCKS_PER_RUN': '500',
                'ONCHAIN_INDEXER_CHUNK_SIZE': '2000'}), rpc_factory=transport)
            large.indexing_pacer = IndexingRpcPacer(monotonic=lambda: elapsed, sleep=paced_sleep)
            before = len(requests)
            with patch('cybergold_candidate.safe_collector.direct_rpc', lambda *_args, raw_logs=False: transport(raw_logs)), \
                 patch('cybergold_candidate.core_collector.refresh_snapshot', snapshot):
                assert (await large.run_once(supplied_anchor=anchor))['status'] == 'incomplete'
                assert large.helpers_progress['indexedThroughBlock'] == '50099' and not large.helpers_progress['completed']
                async with database.connection() as connection:
                    value = await (await connection.execute("""SELECT state_value FROM onchain_sync_state
                        WHERE chain_id=%s AND contract_address=%s AND state_key='last_scanned_block' """, (chain, budget_core))).fetchone()
                    assert value['state_value'] == '50099'
                assert large.config['maxBlocksPerRun'] == 500
                assert large.collection_config['maxBlocksPerRun'] == 50000
                assert (await large.run_once(supplied_anchor=anchor))['status'] == 'reconciled'
                assert large.helpers_progress['indexedThroughBlock'] == '60099' and large.helpers_progress['completed']
            attempts = requests[before:]
            assert large.indexing_pacer.attempts == len(attempts)
            assert large.helpers_progress['rpcRequestsPerHour'] == 10000
            assert {item[2][0]['address'] for item in attempts if item[0] == 'eth_getLogs'} == {
                budget_core, budget_helpers, budget_safe}
            for previous, current in zip(attempts, attempts[1:]):
                assert current[1] - previous[1] >= .36 - 1e-8
            async with database.connection() as connection:
                value = await (await connection.execute("""SELECT state_value FROM onchain_sync_state
                    WHERE chain_id=%s AND contract_address=%s AND state_key='last_scanned_block' """, (chain, budget_core))).fetchone()
                assert value['state_value'] == '60099'
        return {'result': 'pass', 'canonicalHelpersEventDecodersComparedWithViem': 16,
            'initialIndependentBackfill': True, 'boundedContinueAndCanonicalNoOp': True,
            'boundedReorgProgress': True, 'failedAndCancelledCallsPreserveCoverage': True,
            'forkPrefixReuseAndDivergentReset': True, 'chainAndAddressIsolation': True,
            'coreProjectionAndReceiptUnchanged': True, 'installedDatabaseUsed': False,
            'nativeWorkerIntegrationAndFailureIsolation': True, 'nativeReadOnlyHttpNoStore': True,
            'coreAndHelpers50000BlockPassOnBothChains': True, 'pacedActualHttpAttemptsIncludingHeaders': True,
            'coreHelpersSafeShareOneEnvironmentAllowance': True, 'twoPassCatchupAndSettingsPreserved': True, 'installedActivation': False}
    finally:
        await database.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dsn')
    parser.add_argument('--fixture', type=Path)
    args = parser.parse_args()
    if args.dsn:
        print(json.dumps(asyncio.run(qualify(args.dsn, json.loads(args.fixture.read_text())))))
        raise SystemExit(0)
    container = 'cybergold-helpers-activity-fixture'
    try:
        fixture = json.loads(subprocess.check_output(['node', '--import', 'tsx',
            'python-candidate/tests/node-helpers-activity-reference.ts'], cwd=ROOT, text=True))
        subprocess.run(['docker', 'run', '--detach', '--name', container, '--env',
            'POSTGRES_HOST_AUTH_METHOD=trust', '--publish', '127.0.0.1::5432', 'postgres:16'],
            check=True, capture_output=True)
        for attempt in range(50):
            if subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'postgres'], capture_output=True).returncode == 0: break
            if attempt == 49: raise RuntimeError('Disposable PostgreSQL did not start')
            time.sleep(.2)
        port = subprocess.check_output(['docker', 'port', container, '5432/tcp'], text=True).strip().rsplit(':', 1)[1]
        print(json.dumps(asyncio.run(qualify('postgresql://postgres@127.0.0.1:' + port + '/postgres', fixture))))
    finally:
        subprocess.run(['docker', 'rm', '-f', '-v', container], capture_output=True)
