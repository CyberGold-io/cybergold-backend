"""Actual retained collector versus configured Python collector in native PG."""
import asyncio
import json
import os
from pathlib import Path
import subprocess

from cybergold_candidate.environment import load_environment
from cybergold_candidate.reconciliation_receipt import RpcCounter
from cybergold_candidate.safe_collector import EVENTS, SafeIndexer

ROOT = Path(__file__).parents[2]
ADDRESS = '0x' + '6' * 40
NODE = '''
import {query,withTransaction} from './src/server/onchain-indexer/db.ts';
import {retainedSafeProjection} from './python-candidate/tests/retained_safe_projection.ts';
import {retainedSafeCollector} from './python-candidate/tests/retained_safe_collector.ts';
import {ingestAddressScopedRawLogs,readRawJournalCoverage,prepareRawJournalReplayCoverage,readRawJournalLogs} from './src/server/onchain-indexer/rawLogJournal.ts';
import {createIndexerRpcRequestCounter} from './src/server/onchain-indexer/rpcRequestInstrumentation.ts';
import {toEventHash} from 'viem';
const x=JSON.parse(process.argv[1]),calls=[],counter=createIndexerRpcRequestCounter();
const hash=n=>'0x'+n.toString(16).padStart(64,'0');
const projection=retainedSafeProjection(query,withTransaction);
const client={getBlockNumber:async()=>{calls.push('latest');return BigInt(x.anchor);},
 getBlock:async({blockNumber})=>{calls.push('block:'+blockNumber);return {number:blockNumber,hash:hash(blockNumber),timestamp:blockNumber+1000n};},
 request:async({params})=>{const p=params[0],from=BigInt(p.fromBlock),to=BigInt(p.toBlock);calls.push('logs:'+from+'-'+to+(p.topics?':'+p.topics[0]:''));
  const logs=[];for(let n=from;n<=to;n++)logs.push({address:x.address,blockNumber:'0x'+n.toString(16),blockHash:hash(n),transactionHash:hash(n+1000n),logIndex:'0x0',
   topics:[p.topics?.[0]??(n===102n?hash(999n):toEventHash(n%2n?'ExecutionSuccess(bytes32,uint256)':'ExecutionFailure(bytes32,uint256)')),hash(777n)],data:'0x'+(2n**200n).toString(16).padStart(64,'0')});
  return logs;}};
const collector=retainedSafeCollector({serverEnv:{ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS:x.scoped?'1':'0',ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED:x.replay?'1':'0'},
 addressScopedRawLogsEnabled:v=>v==='1',rawJournalProjectionReplayEnabled:v=>v==='1',createPublicClient:()=>client,indexerRpcTransport:()=>null,shouldSplitDirectProviderLogRequest:()=>false,
 ensureSafeCursorVersion:projection.version,lastScannedSafeBlock:projection.cursor,lastScannedSafeBlockHash:projection.hash,finalizedSafeProjectionProfile:projection.profile,
 committedSafeBoundary:projection.committed,deleteIndexedSafeExecutionLogs:projection.deleteFrom,persistSafeExecutionLogs:projection.persist,setLastScannedSafeBlock:projection.putCursor,
 ingestAddressScopedRawLogs,readRawJournalCoverage,prepareRawJournalReplayCoverage,readRawJournalLogs});
const result=await collector(x.address,{chainId:4400n,rpcUrl:'synthetic',lookbackBlocks:3n,reorgWindow:2n,chunkBlocks:2n,maxBlocksPerRun:20n},counter,
 {finalizedAnchor:x.legacy?undefined:{blockNumber:BigInt(x.anchor),blockHash:hash(BigInt(x.anchor))},finalizedProfile:x.profile,maximumBlocksPerRun:x.partial?2n:undefined});
const rows={};for(const table of ['onchain_event_logs','onchain_raw_logs','onchain_sync_state'])rows[table]=(await query(`SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'chain_id'-'updated_at'-'created_at' AS value FROM ${table} t WHERE chain_id=4400) data`)).rows[0].rows;
console.log(JSON.stringify({result,calls,rows,counts:counter.snapshot()}));await globalThis.__cybergoldDashboardPgPool?.end();
'''


async def qualify(database, dsn):
    cases = [dict(scoped=True, replay=False, anchor=103, profile='first'),
        dict(scoped=True, replay=True, anchor=103, profile='changed'),
        dict(scoped=True, replay=True, anchor=108, profile='changed', partial=True),
        dict(scoped=True, replay=True, anchor=108, profile='changed'),
        dict(scoped=False, replay=False, anchor=110, profile='changed', legacy=True)]
    async with database.connection() as connection:
        for table in ['onchain_event_logs', 'onchain_raw_logs', 'onchain_sync_state']:
            await connection.execute('DELETE FROM ' + table + ' WHERE chain_id IN (4400,4401)')
    for case in cases:
        expected = json.loads(await asyncio.to_thread(subprocess.check_output,
            ['node', '--env-file=tests/fixture.env', '--import', 'tsx', '--input-type=module', '-e', NODE, json.dumps({**case, 'address': ADDRESS})],
            cwd=ROOT, env={**os.environ, 'TZ': 'UTC', 'DATABASE_URL': dsn}, text=True))
        calls = []
        def block_hash(number):
            return '0x' + f'{number:064x}'
        class Client:
            async def block_number(self):
                calls.append('latest'); return case['anchor']
            async def block(self, number):
                calls.append('block:' + str(number)); return {'number': number, 'hash': block_hash(number), 'timestamp': number + 1000}
            async def logs(self, address, value, topic=None):
                begin, end = value['fromBlock'], value['toBlock']
                calls.append(f'logs:{begin}-{end}' + (':' + topic if topic else ''))
                return [{'address': address, 'blockNumber': hex(number), 'blockHash': block_hash(number), 'transactionHash': block_hash(number + 1000),
                    'logIndex': '0x0', 'topics': [topic or (block_hash(999) if number == 102 else EVENTS[0 if number % 2 else 1][1]), block_hash(777)],
                    'data': '0x' + f'{2**200:064x}'} for number in range(begin, end + 1)]
        settings = load_environment({'NEXT_PUBLIC_CHAIN_ID': '4401', 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': ADDRESS, 'NEXT_PUBLIC_RPC_URL': 'http://synthetic',
            'SAFE_EVENT_INDEXER_SAFE_ADDRESSES': ADDRESS, 'SAFE_EVENT_INDEXER_LOOKBACK_BLOCKS': '3', 'SAFE_EVENT_INDEXER_CHUNK_BLOCKS': '2',
            'SAFE_EVENT_INDEXER_REORG_WINDOW': '2', 'SAFE_EVENT_INDEXER_MAX_BLOCKS_PER_RUN': '20',
            'ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS': '1' if case['scoped'] else '0',
            'ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED': '1' if case['replay'] else '0'})
        counter = RpcCounter()
        result = await SafeIndexer(database, settings).reconcile(counter, client=Client(), raw_client=Client(),
            anchor=None if case.get('legacy') else {'blockNumber': case['anchor'], 'blockHash': block_hash(case['anchor'])},
            profile=case['profile'], maximum_blocks=2 if case.get('partial') else None)
        rows = {}
        async with database.connection() as connection:
            for table in ['onchain_event_logs', 'onchain_raw_logs', 'onchain_sync_state']:
                rows[table] = (await (await connection.execute("SELECT COALESCE(jsonb_agg(value ORDER BY value::text),'[]'::jsonb) AS rows FROM (SELECT to_jsonb(t)-'chain_id'-'updated_at'-'created_at' AS value FROM " + table + ' t WHERE chain_id=4401) data')).fetchone())['rows']
        actual = {'result': result, 'calls': calls, 'rows': rows, 'counts': counter.snapshot()}
        assert actual == expected, (case, next((key for key in actual if actual[key] != expected[key]), None), actual, expected)
    return {'nativeSafeCollectorRunsCompared': len(cases), 'nativeConfiguredSafeCollectorReplayAndContinuationMatchNode': True,
        'nativeSafeCollectorRetainsUnknownRawLogsAndProjectsKnownEvents': True}
