"""Retained Safe scan/replay coordination; clients and stores belong to the worker."""
import asyncio

from web3 import Web3

from .indexer_policy import finalized_anchor, planning_boundary, projection_scan
from .safe_abi import safe_execution_args
from .completed_state import IDENTITY
from .indexer_rpc import direct_rpc, leased_rpc
from .raw_ingestion import RawJournal
from .runtime import safe_history_profile
from .safe_projection import SafeProjection
from .worker_rpc import approved_range_reduction
from .gateway_lease import GatewayRangeReductionError

EVENTS = [(name, Web3.keccak(text=name + '(bytes32,uint256)').hex())
    for name in ('ExecutionSuccess', 'ExecutionFailure')]
EVENTS = [(name, '0x' + topic.removeprefix('0x')) for name, topic in EVENTS]


async def reconcile_safe(projection, journal, config, counter, client, raw_client,
    *, address_scoped, raw_replay, anchor=None, profile=None, lease_bound=False,
    committed_id=None, maximum_blocks=None, should_split=None):
    await projection.ensure_version()
    if raw_replay and (not address_scoped or anchor is None):
        raise ValueError('Safe raw journal replay requires finalized address-scoped reconciliation')
    latest = anchor['blockNumber'] if anchor is not None else await client.block_number()
    scanned = await projection.cursor()
    first = max(latest - config['lookbackBlocks'], 0)
    if anchor is not None:
        working = {'blockNumber': scanned, 'blockHash': await projection.cursor_hash(),
            'profile': await projection.profile()}
        committed = await projection.committed() if lease_bound else {
            'blockNumber': None, 'blockHash': None, 'profile': None, 'reconciliationId': None}
        if committed.get('reconciliationId') != committed_id:
            committed = {'blockNumber': None, 'blockHash': None, 'profile': None}
        boundary = planning_boundary(lease_bound, working, committed)
        canonical = None
        if boundary['blockNumber'] is not None and boundary['blockNumber'] <= latest:
            if boundary['blockNumber'] == latest:
                canonical = anchor['blockHash']
            else:
                header = finalized_anchor(await client.block(boundary['blockNumber']))
                if header['blockNumber'] != boundary['blockNumber']:
                    raise ValueError('Safe cursor header returned the wrong block number')
                canonical = header['blockHash']
        plan = projection_scan(first, anchor, boundary, canonical, config['reorgWindow'],
            not profile or boundary['profile'] != profile)
        start = plan['fromBlock']
        if start is None:
            return True
    else:
        start = first if scanned is None else max(scanned - config['reorgWindow'], 0)
    end = min(start + (maximum_blocks if maximum_blocks is not None else config['maxBlocksPerRun']) - 1, latest)
    headers, logs = {}, []

    async def read_header(number):
        if number in headers:
            return headers[number]
        block = await client.block(number)
        header = finalized_anchor(block)
        if header['blockNumber'] != number:
            raise ValueError('Safe block header returned the wrong block number')
        headers[number] = {'hash': header['blockHash'], 'timestamp': block['timestamp']}
        return headers[number]

    async def ingest(begin, stop):
        async def request(value):
            return await raw_client.logs(projection.address, value)
        return await journal.ingest(first, begin, stop, counter, 'safe-address',
            request, read_header, should_split, headers)

    async def ingest_coverage(begin, stop):
        while begin <= stop:
            chunk_end = min(begin + config['chunkBlocks'] - 1, stop)
            await ingest(begin, chunk_end)
            begin = chunk_end + 1

    if raw_replay and anchor is not None:
        coverage = await journal.coverage()
        if coverage is not None and coverage['startBlock'] > first:
            await ingest_coverage(first, coverage['startBlock'] - 1)
        if coverage is not None and coverage['startBlock'] <= first and coverage['cursorBlock'] + 1 < first:
            await ingest_coverage(coverage['cursorBlock'] + 1, first - 1)
    coverage = await journal.prepare_replay(raw_replay, first, anchor['blockNumber'], read_header) if anchor is not None else None

    def append(log):
        logs.append(log)
        if len(logs) > 10_000:
            raise ValueError('Safe event indexer log cardinality exceeds 10,000 entries per run')

    if address_scoped:
        cursor = start
        while cursor <= end:
            stop = min(cursor + config['chunkBlocks'] - 1, end)
            raw_logs = await journal.replay(cursor, stop, coverage) if coverage is not None and stop <= coverage['cursorBlock'] else await ingest(cursor, stop)
            for log in raw_logs:
                topic = log['topics'][0].lower() if log['topics'] else None
                name = next((name for name, selector in EVENTS if selector.lower() == topic), None)
                if name is None:
                    continue
                args = safe_execution_args(log)
                if args is None:
                    raise ValueError('Failed to decode known ' + name + ' Safe raw log')
                append({'eventName': name, **args, 'blockNumber': log['blockNumber'],
                    'blockHash': log['blockHash'], 'transactionHash': log['transactionHash'],
                    'logIndex': log['logIndex'], 'timestamp': log['blockTimestampSeconds'],
                    'topics': log['topics'], 'data': log['data']})
            cursor = stop + 1
    else:
        for name, topic in EVENTS:
            cursor = start
            while cursor <= end:
                stop = min(cursor + config['chunkBlocks'] - 1, end)
                counter.plan('safe-event')
                counter.log_attempt('safe-event')
                try:
                    raw_logs = await client.logs(projection.address, {'fromBlock': cursor, 'toBlock': stop}, topic)
                except (Exception, asyncio.CancelledError):
                    counter.log_failure()
                    raise
                for log in raw_logs:
                    if not log.get('blockNumber') or not log.get('transactionHash'):
                        continue
                    args = safe_execution_args(log)
                    if args is None:
                        continue
                    number = int(log['blockNumber'], 16)
                    header = await read_header(number)
                    if anchor is not None and (not log.get('blockHash') or log['blockHash'].lower() != header['hash'].lower()):
                        raise ValueError('Safe finalized log block hash changed during the run')
                    append({'eventName': name, **args, 'blockNumber': number, 'blockHash': log.get('blockHash'),
                        'transactionHash': log['transactionHash'], 'logIndex': int(log['logIndex'], 16) if log.get('logIndex') else 0,
                        'timestamp': header['timestamp'], 'topics': log['topics'], 'data': log['data']})
                cursor = stop + 1
    last = await read_header(end) if anchor is not None else None
    if anchor is not None and end == anchor['blockNumber'] and last['hash'].lower() != anchor['blockHash'].lower():
        raise ValueError('Safe projection reached a different finalized anchor hash')
    await projection.delete_from(start)
    await projection.persist(logs)
    await projection.put_cursor(end, last['hash'] if last is not None else None, profile)
    return anchor is None or end == anchor['blockNumber']


async def reconcile_configured(addresses, reconcile):
    reached = True
    for address in addresses:
        result = await reconcile(address)
        reached = reached and result
    return reached


class SafeIndexer:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings
        self.addresses, lookback = safe_history_profile(settings)
        def bounded(name, fallback, maximum):
            return min(int(getattr(settings, name) or 0) or fallback, maximum)
        self.config = {'lookbackBlocks': lookback,
            'chunkBlocks': bounded('SAFE_EVENT_INDEXER_CHUNK_BLOCKS', 10000, 10000),
            'reorgWindow': bounded('SAFE_EVENT_INDEXER_REORG_WINDOW', 12, 256),
            'maxBlocksPerRun': bounded('SAFE_EVENT_INDEXER_MAX_BLOCKS_PER_RUN', 20000, 50000)}
        self.chain = int(settings.NEXT_PUBLIC_CHAIN_ID)

    async def reconcile(self, counter, *, client=None, raw_client=None, lease=None, before_request=None,
        anchor=None, profile=None, committed_id=None, maximum_blocks=None):
        if not self.addresses:
            return True
        scoped = self.settings.ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS == '1'
        own_client = client is None
        client = client or (leased_rpc(lease, counter, before_request) if lease is not None else direct_rpc(self.settings))
        own_raw = raw_client is None and scoped and lease is None
        raw_client = raw_client or (direct_rpc(self.settings, raw_logs=True) if own_raw else client)
        if lease is None and before_request is not None:
            client.before_request = raw_client.before_request = before_request
        async def reconcile(address):
            projection = SafeProjection(self.database, self.chain, address)
            journal = RawJournal(self.database, self.chain, address, IDENTITY['rawJournalVersion'])
            return await reconcile_safe(projection, journal, self.config, counter, client, raw_client,
                address_scoped=scoped, raw_replay=self.settings.ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED == '1',
                anchor=anchor, profile=profile, lease_bound=lease is not None, committed_id=committed_id,
                maximum_blocks=maximum_blocks, should_split=approved_range_reduction if lease is None else lambda error: isinstance(error, GatewayRangeReductionError))
        try:
            return await reconcile_configured(self.addresses, reconcile)
        finally:
            if own_raw:
                await raw_client.close()
            if own_client:
                await client.close()
