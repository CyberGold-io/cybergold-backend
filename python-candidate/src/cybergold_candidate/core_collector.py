"""Retained Core/Governance scan, raw replay, reorg and holder coordination."""
import asyncio
import re

from .completed_state import CompletedState, CORE_COMMITTED, IDENTITY
from .dashboard_builder import DEFINITIONS
from .event_projection import EventProjection
from .gateway_lease import range_reduction_required
from .holder_projection import HolderProjection
from .indexer_event_codec import decode_known, decode_legacy, selector
from .indexer_policy import HASH, anchor_tag, deployment_start, finalized_anchor, finalized_profile, planning_boundary, projection_scan
from .projection_identity import ensure_identity
from .raw_ingestion import RawJournal
from .recovery_persistence import parse_integer
from .snapshot_refresh import refresh_snapshot
from .worker_contract import history_progress
from .worker_rpc import approved_range_reduction


async def resolve_start(config, client, store, head):
    if config['archiveFreeFinalizedMode']:
        return deployment_start(config['chainId'], config['startBlock'], head)
    if config['startBlock'] > 0:
        return min(config['startBlock'], head)
    cached = parse_integer(await store.state('deployment_block'))
    if cached is not None:
        return min(cached, head)
    async def has_code(number):
        code = await client.request('eth_getCode', [config['coreAddress'], hex(number)])
        return bool(code) and code != '0x'
    try:
        if await has_code(head):
            low, high, first = 0, head, head
            while low <= high:
                middle = (low + high) // 2
                if await has_code(middle):
                    first = middle
                    if middle == 0:
                        break
                    high = middle - 1
                else:
                    low = middle + 1
            await store.put_state('deployment_block', str(first))
            return first
    except Exception:
        pass  # Retained RPC/code-detection failure falls back to full scan.
    return 0


class CoreCollector:
    def __init__(self, database, config, safe_profile):
        self.database, self.config, self.safe_profile = database, config, safe_profile
        self.store = HolderProjection(database, config)
        self.projection = EventProjection(database, config)
        self.completed = CompletedState(database, {**config, 'safeAddresses': safe_profile['safeAddresses']})

    async def committed(self):
        block, block_hash, profile, identifier, revision = await asyncio.gather(*(self.store.state(key) for key in CORE_COMMITTED))
        number = parse_integer(block)
        complete = number is not None and block_hash and HASH.fullmatch(block_hash) and profile and identifier and revision and re.fullmatch('[0-9a-f]{64}', revision)
        return {'blockNumber': number if complete else None, 'blockHash': block_hash.lower() if complete else None,
            'profile': profile if complete else None, 'reconciliationId': identifier if complete else None}

    async def put_cursor(self, block, block_hash, profile):
        async with self.database.connection() as connection:
            async with connection.transaction():
                for key, value in [('last_scanned_block', str(block)), ('finalized_projection_block_hash', block_hash.lower()),
                    ('finalized_projection_profile', profile)]:
                    await self.store.put_state(key, value, connection)

    async def reconcile(self, counter, client, raw_client, reconcile_safes, *, supplied_anchor=None,
        lease=None, stage=None, refresh=None):
        config, store = self.config, self.store
        def diagnostic(value):
            if stage is not None:
                stage(value)
        diagnostic('indexer-version')
        await self.database.ensure_schema()
        reset = await ensure_identity(self.database, config)
        if supplied_anchor and not config['archiveFreeFinalizedMode']:
            raise ValueError('A supplied finalized anchor requires archive-free finalized mode')
        diagnostic('finalized-anchor')
        if config['archiveFreeFinalizedMode']:
            anchor = finalized_anchor({'number': supplied_anchor['blockNumber'], 'hash': supplied_anchor['blockHash']}) if supplied_anchor else finalized_anchor(await client.block(anchor_tag(config['chainId'])))
        else:
            anchor = None
        if lease and (not anchor or anchor['blockNumber'] != lease.anchor['blockNumber'] or anchor['blockHash'].lower() != lease.anchor['blockHash'].lower()):
            raise ValueError('Indexer gateway lease anchor was not used exactly')
        latest = anchor['blockNumber'] if anchor else await client.block_number()
        first = await resolve_start(config, client, store, latest)
        scanned = parse_integer(await store.state('last_scanned_block'))
        profile = finalized_profile({'addressScopedRawLogs': config['addressScopedRawLogs'], 'coreDeploymentStartBlock': first,
            'safeLookbackBlocks': self.safe_profile['lookbackBlocks'], 'governanceAddress': config.get('governanceAddress'),
            'safeAddresses': self.safe_profile['safeAddresses'], 'rawJournalVersion': IDENTITY['rawJournalVersion'],
            'dashboardProjectionVersion': IDENTITY['dashboardProjectionVersion'], 'safeCursorVersion': IDENTITY['safeCursorVersion'],
            'coreEventSelectors': [selector(definition) for definition in DEFINITIONS['core']],
            'governanceEventSelectors': [selector(definition) for definition in DEFINITIONS['governance']],
            'safeEventSelectors': self.safe_profile['eventSelectors']}) if anchor else None
        diagnostic('projection-plan')
        should_scan, committed_complete, committed_id = True, False, None
        if anchor:
            working = {'blockNumber': scanned, 'blockHash': await store.state('finalized_projection_block_hash'),
                'profile': await store.state('finalized_projection_profile')}
            committed = await self.committed() if lease and not reset else {'blockNumber': None, 'blockHash': None, 'profile': None, 'reconciliationId': None}
            boundary = planning_boundary(lease is not None, working, committed)
            committed_id = committed['reconciliationId'] if lease else None
            committed_complete = bool(lease and boundary['blockNumber'] == anchor['blockNumber'] and
                (boundary['blockHash'] or '').lower() == anchor['blockHash'].lower() and boundary['profile'] == profile)
            canonical = None
            if boundary['blockNumber'] is not None and boundary['blockNumber'] <= latest:
                if boundary['blockNumber'] == latest:
                    canonical = anchor['blockHash']
                else:
                    header = finalized_anchor(await client.block(boundary['blockNumber']))
                    if header['blockNumber'] != boundary['blockNumber']:
                        raise ValueError('Finalized projection cursor header returned the wrong block')
                    canonical = header['blockHash']
            plan = projection_scan(first, anchor, boundary, canonical, config['reorgWindow'], boundary['profile'] != profile)
            should_scan = plan['fromBlock'] is not None
            start = plan['fromBlock'] if should_scan else latest + 1
        else:
            start = first if scanned is None else max(first, max(0, scanned - config['reorgWindow']))
        maximum = min(config['maxBlocksPerRun'], 500) if lease else config['maxBlocksPerRun']
        end = min(start + maximum - 1, latest) if should_scan else latest
        headers, timestamps = {}, {}
        async def header(number):
            if number not in headers:
                value = await client.block(number)
                normalized = finalized_anchor(value)
                if normalized['blockNumber'] != number:
                    raise ValueError('Raw log header returned the wrong block number')
                headers[number] = {'hash': normalized['blockHash'], 'timestamp': value['timestamp']}
            return headers[number]
        domains = [('core', config['coreAddress'], 'core-address', 'core-event')]
        if config.get('governanceAddress'):
            domains.append(('governance', config['governanceAddress'], 'governance-address', 'governance-event'))
        journals = {domain: RawJournal(self.database, config['chainId'], address, IDENTITY['rawJournalVersion'])
            for domain, address, _raw_source, _event_source in domains}
        diagnostic('raw-log-journal')
        coverage = {domain: await journals[domain].prepare_replay(config['rawJournalProjectionReplay'], first, latest, header)
            if anchor else None for domain, _address, _raw_source, _event_source in domains}
        async def collect_raw(begin, stop):
            result = []
            for domain, address, source, _event_source in domains:
                previous = coverage[domain]
                async def request(value):
                    return await raw_client.logs(address, value)
                logs = await journals[domain].replay(begin, stop, previous) if previous and stop <= previous['cursorBlock'] else await journals[domain].ingest(
                    first, begin, stop, counter, source, request, header,
                    range_reduction_required if lease else approved_range_reduction, headers)
                for log in logs:
                    timestamps[log['blockNumber']] = log['blockTimestampSeconds']
                    decoded = decode_known(log, domain)
                    if decoded is not None:
                        result.append({'contractAddress': address, 'eventName': decoded['eventName'], 'blockNumber': log['blockNumber'],
                            'blockHash': log['blockHash'], 'txHash': log['transactionHash'], 'logIndex': log['logIndex'],
                            'payload': {'args': decoded['args'] or {}, 'topics': log['topics'], 'data': log['data']}})
            return result
        prepared, prepared_count = {}, 0
        if config['addressScopedRawLogs']:
            cursor = start
            while cursor <= end:
                stop = min(cursor + config['chunkSize'] - 1, end)
                logs = await collect_raw(cursor, stop)
                prepared_count += len(logs)
                if prepared_count > 50000:
                    raise ValueError('On-chain indexer event cardinality exceeds 50,000 entries per run')
                prepared[cursor] = (stop, logs)
                cursor = stop + 1
        incremental = not reset
        holder_ready = await store.ready()
        if not holder_ready:
            incremental = incremental and scanned is None
            if incremental:
                await store.clear()
                await store.put_state('holder_count', '0')
                await store.put_state('holder_cache_ready', '1')
        if should_scan and scanned is not None:
            if holder_ready and not await store.rewind(start):
                incremental = False
            await self.projection.delete_from(start)
            await store.prune_snapshots(start)
        diagnostic('dashboard-projection')
        cursor, event_count = start, 0
        while cursor <= end:
            stop = min(cursor + config['chunkSize'] - 1, end)
            if config['addressScopedRawLogs']:
                logs = prepared[cursor][1]
                event_count += len(logs)
            else:
                logs = []
                for domain, address, _raw_source, source in domains:
                    for definition in DEFINITIONS[domain]:
                        counter.plan(source); counter.log_attempt(source)
                        try:
                            rpc_logs = await client.logs(address, {'fromBlock': cursor, 'toBlock': stop}, selector(definition))
                        except (Exception, asyncio.CancelledError):
                            counter.log_failure(); raise
                        for log in rpc_logs:
                            decoded = decode_legacy(log, definition)
                            if decoded is None or log.get('blockNumber') is None or log.get('transactionHash') is None:
                                continue
                            logs.append({'contractAddress': address, 'eventName': definition['name'], 'blockNumber': int(log['blockNumber'], 16),
                                'blockHash': log.get('blockHash'), 'txHash': log['transactionHash'], 'logIndex': int(log['logIndex'], 16) if log.get('logIndex') else 0,
                                'payload': {'args': decoded['args'] or {}, 'topics': log['topics'], 'data': log['data']}})
                            event_count += 1
                            if event_count > 50000:
                                raise ValueError('On-chain indexer event cardinality exceeds 50,000 entries per run')
            for number in dict.fromkeys(log['blockNumber'] for log in logs):
                if number not in timestamps:
                    timestamps[number] = (await header(number))['timestamp'] if anchor else (await client.block(number))['timestamp']
            if anchor:
                for log in logs:
                    current = await header(log['blockNumber'])
                    if not log['blockHash'] or log['blockHash'].lower() != current['hash'].lower():
                        raise ValueError('Finalized event log block hash changed during the captured run')
            chunk_header = await header(stop) if anchor else None
            if anchor and stop == latest and chunk_header['hash'].lower() != anchor['blockHash'].lower():
                raise ValueError('Projection reached a different finalized anchor hash')
            await self.projection.persist([{**log, 'blockTimestampMs': timestamps.get(log['blockNumber'], 0) * 1000} for log in logs], incremental)
            if anchor and chunk_header:
                await self.put_cursor(stop, chunk_header['hash'], profile)
            else:
                await store.put_state('last_scanned_block', str(stop))
            cursor = stop + 1
        retention = max(0, end - config['reorgWindow'])
        if (not incremental and should_scan) or reset:
            await store.rebuild(retention)
        if should_scan or reset:
            await store.prune_deltas(retention)
        async def snapshot(value):
            if refresh is not None:
                await refresh(value, client, lease)
            else:
                await refresh_snapshot(config, value, client, self.database, lease)
        if anchor is None:
            if start > end:
                await store.put_state('last_scanned_block', str(end))
            diagnostic('state-snapshot')
            await snapshot({'blockNumber': end, 'blockHash': None, 'profile': None})
            diagnostic('safe-history')
            await reconcile_safes(counter)
            return {'finalizedAnchor': None, 'finalizedProfile': None, 'completed': True, 'dashboardHistoryProgress': None}
        diagnostic('safe-history')
        reached = await reconcile_safes(counter, anchor=anchor, profile=profile, lease=lease, committed_id=committed_id, maximum_blocks=maximum)
        indexed, finalized = await header(end), await header(latest)
        progress = history_progress({'startBlock': first, 'indexedThroughBlock': end, 'indexedThroughTimestampSeconds': indexed['timestamp'],
            'networkFinalizedBlock': latest, 'networkFinalizedTimestampSeconds': finalized['timestamp']})
        outcome = {'finalizedAnchor': anchor, 'finalizedProfile': profile, 'completed': end == latest and reached and profile is not None,
            'dashboardHistoryProgress': progress}
        if not outcome['completed']:
            return outcome
        if (not lease or committed_complete) and await self.completed.snapshot_complete(anchor, profile):
            return outcome
        diagnostic('state-snapshot')
        await snapshot({'blockNumber': latest, 'blockHash': anchor['blockHash'], 'profile': profile})
        return outcome
