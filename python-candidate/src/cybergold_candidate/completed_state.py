"""Retained gateway completion/checkpoint state, with the same schema and keys.

This is worker source, not an autonomous engine. Reading a completed receipt
reuses the retained committed/raw/Safe/snapshot checks; parsing alone is not
enough. Writes join one native PostgreSQL transaction and never rewind data.
"""
import asyncio
import json
from pathlib import Path
import re

from .gateway_lease import health_suppressed
from .indexer_policy import HASH, snapshot_matches
from .reconciliation_receipt import create_receipt, parse_receipt
from .recovery_persistence import parse_integer, read_checkpoint as recovery_checkpoint

IDENTITY = json.loads(Path(__file__).with_name('retained-identity.json').read_text())
RECEIPT_KEY = 'completed_reconciliation_receipt_v2'
CORE_COMMITTED = ('committed_finalized_block', 'committed_finalized_block_hash',
    'committed_finalized_profile', 'committed_reconciliation_id', 'committed_gateway_config_revision')
SAFE_COMMITTED = ('safe_committed_finalized_block', 'safe_committed_finalized_block_hash',
    'safe_committed_finalized_profile', 'safe_committed_reconciliation_id')
SNAPSHOT_KEYS = ('finalized_snapshot_block', 'finalized_snapshot_block_hash', 'finalized_snapshot_profile')
WORKING_KEYS = ('last_scanned_block', 'finalized_projection_block_hash', 'finalized_projection_profile',
    'raw_log_journal_version', 'raw_log_last_scanned_block', 'raw_log_last_scanned_block_hash',
    'safe_execution_cursor_version', 'safe_execution_last_scanned_block',
    'safe_execution_last_scanned_block_hash', 'safe_finalized_projection_profile')
REQUIRED_MODELS = ('onchain-dashboard-v1', 'recovery-portfolio-v5')


def checkpoint_cursor(address, state, block_key, hash_key, maximum,
                      version_key=None, version=None, profile_key=None, profile=None):
    state = state or {}
    if version_key and state.get(version_key) != version or profile_key and state.get(profile_key) != profile:
        raise ValueError('Gateway checkpoint identity is incomplete')
    block, block_hash = state.get(block_key), state.get(hash_key)
    if not block or not isinstance(block_hash, str) or not HASH.fullmatch(block_hash):
        raise ValueError('Gateway checkpoint cursor is incomplete')
    number = parse_integer(block)
    if number is None:
        raise ValueError('Gateway checkpoint cursor is invalid')
    if number < 0 or number > maximum:
        raise ValueError('Gateway checkpoint cursor is outside the lease anchor')
    return {'address': address, 'blockNumber': number, 'blockHash': block_hash.lower()}


def working_checkpoint(config, anchor, profile, states):
    safes = config['safeAddresses']
    raw = list({address.lower(): address for address in
        [config['coreAddress'], *([config['governanceAddress']] if config.get('governanceAddress') else []), *safes]}.values())
    core = checkpoint_cursor(config['coreAddress'], states.get(config['coreAddress'].lower()),
        'last_scanned_block', 'finalized_projection_block_hash', anchor['blockNumber'],
        profile_key='finalized_projection_profile', profile=profile)
    safe_cursors = [checkpoint_cursor(address, states.get(address.lower()),
        'safe_execution_last_scanned_block', 'safe_execution_last_scanned_block_hash', anchor['blockNumber'],
        'safe_execution_cursor_version', IDENTITY['safeCursorVersion'], 'safe_finalized_projection_profile', profile)
        for address in safes]
    by_safe = {cursor['address'].lower(): cursor for cursor in safe_cursors}
    raw_cursors = []
    for address in raw:
        cursor = checkpoint_cursor(address, states.get(address.lower()), 'raw_log_last_scanned_block',
            'raw_log_last_scanned_block_hash', anchor['blockNumber'], 'raw_log_journal_version', IDENTITY['rawJournalVersion'])
        expected = by_safe.get(address.lower(), core)
        if cursor['blockNumber'] != expected['blockNumber'] or cursor['blockHash'] != expected['blockHash'].lower():
            raise ValueError('Raw journal and projection checkpoint cursors do not match')
        raw_cursors.append(cursor)
    return {'coreCursor': core, 'safeCursors': safe_cursors, 'rawCursors': raw_cursors, 'profile': profile}


async def last_receipt(config, runtime, now_ms, read_state, read_addresses, read_working, snapshot_complete):
    suppressed = health_suppressed(runtime['activeGatewayReconciliationId'],
        runtime['gatewayLeaseAmbiguousUntilMs'], now_ms)
    if runtime['activeGatewayReconciliationId'] is not None and not suppressed:
        runtime['activeGatewayReconciliationId'] = None
        runtime['gatewayLeaseAmbiguousUntilMs'] = 0
    if not config or not config.get('privateGatewayClient') or suppressed:
        return None
    # Retained DB failure while fetching the stored record propagates normally;
    # invalid/incoherent records and later checkpoint failures return no receipt.
    stored = await read_state(RECEIPT_KEY)
    if not stored:
        return None
    try:
        receipt = parse_receipt(stored)
        block, block_hash, profile, identifier, revision = await asyncio.gather(
            *(read_state(key) for key in CORE_COMMITTED))
        number = parse_integer(block)
        if (number is None or str(number) != receipt['finalizedAnchor']['number']
            or (block_hash.lower() if block_hash else None) != receipt['finalizedAnchor']['hash']
            or profile != receipt['dashboardProjection']['profile'] or identifier != receipt['reconciliationId']
            or revision != receipt['gatewayConfigRevision'] or receipt['runtimeConfigId'] != config.get('runtimeConfigId')):
            return None
        safe_states = await read_addresses([cursor['address'] for cursor in receipt['safeCursors']['cursors']], SAFE_COMMITTED)
        for cursor in receipt['safeCursors']['cursors']:
            state = safe_states.get(cursor['address'], {})
            if (state.get(SAFE_COMMITTED[0]) != cursor['blockNumber']
                or (state.get(SAFE_COMMITTED[1], '').lower()) != cursor['blockHash']
                or state.get(SAFE_COMMITTED[2]) != profile or state.get(SAFE_COMMITTED[3]) != identifier):
                return None
        anchor = {'blockNumber': int(receipt['finalizedAnchor']['number']), 'blockHash': receipt['finalizedAnchor']['hash']}
        live = await read_working(anchor, profile)
        for cursor in [live['coreCursor'], *live['rawCursors'], *live['safeCursors']]:
            if cursor['blockNumber'] != anchor['blockNumber'] or cursor['blockHash'].lower() != anchor['blockHash']:
                return None
        for field in ('rawCursors', 'safeCursors'):
            category = 'rawJournal' if field == 'rawCursors' else 'safeCursors'
            if sorted(cursor['address'].lower() for cursor in live[field]) != sorted(
                cursor['address'] for cursor in receipt[category]['cursors']):
                return None
        if not await snapshot_complete(anchor, profile):
            return None
        return receipt
    except Exception:
        return None


class CompletedState:
    def __init__(self, database, config):
        self.database = database
        self.config = config

    async def read_state(self, key):
        async with self.database.connection() as connection:
            cursor = await connection.execute('''SELECT state_value FROM onchain_sync_state
                WHERE chain_id=%s AND contract_address=%s AND state_key=%s LIMIT 1''',
                (str(self.config['chainId']), self.config['coreAddress'].lower(), key))
            row = await cursor.fetchone()
            return row['state_value'] if row else None

    async def read_addresses(self, addresses, keys):
        if not addresses:
            return {}
        async with self.database.connection() as connection:
            cursor = await connection.execute('''SELECT contract_address,state_key,state_value FROM onchain_sync_state
                WHERE chain_id=%s AND contract_address=ANY(%s::text[]) AND state_key=ANY(%s::text[])''',
                (str(self.config['chainId']), [address.lower() for address in addresses], list(keys)))
            result = {}
            for row in await cursor.fetchall():
                result.setdefault(row['contract_address'].lower(), {})[row['state_key']] = row['state_value']
            return result

    async def read_working(self, anchor, profile):
        addresses = [self.config['coreAddress'], *self.config['safeAddresses']]
        if self.config.get('governanceAddress'):
            addresses.append(self.config['governanceAddress'])
        states = await self.read_addresses(list(dict.fromkeys(address.lower() for address in addresses)), WORKING_KEYS)
        return working_checkpoint(self.config, anchor, profile, states)

    async def snapshot_complete(self, anchor, profile):
        block, block_hash, stored_profile = await asyncio.gather(*(self.read_state(key) for key in SNAPSHOT_KEYS))
        async with self.database.connection() as connection:
            cursor = await connection.execute('''SELECT COUNT(*)::text AS model_count FROM (
                SELECT model_key FROM onchain_read_model_snapshots
                WHERE chain_id=%s AND contract_address=%s AND model_key=ANY(%s::text[])
                GROUP BY model_key HAVING MAX(block_number)=%s) AS completed_models''',
                (str(self.config['chainId']), self.config['coreAddress'].lower(), list(REQUIRED_MODELS), str(anchor['blockNumber'])))
            count = (await cursor.fetchone())['model_count']
            recovery = await recovery_checkpoint(connection, self.config['chainId'], self.config['coreAddress']) if self.config.get('recoveryShareV2') else None
        return snapshot_matches(**{'anchor': anchor, 'expectedProfile': profile,
            'snapshotBlockNumber': parse_integer(block), 'snapshotBlockHash': block_hash,
            'snapshotProfile': stored_profile, 'requiredSnapshotsExist': int(count) == len(REQUIRED_MODELS)}) and (
            not self.config.get('recoveryShareV2') or recovery is not None and recovery['version'] == '1'
            and recovery['blockNumber'] == anchor['blockNumber'] and recovery['blockHash'].lower() == anchor['blockHash'].lower()
            and recovery['profile'] == profile)

    async def receipt(self, runtime, now_ms):
        return await last_receipt(self.config, runtime, now_ms, self.read_state,
            self.read_addresses, self.read_working, self.snapshot_complete)

    async def build_receipt(self, lease, checkpoint, rpc_requests, started_at_ms, completed_at_ms):
        anchor = lease.finalized_anchor
        for cursor in [checkpoint['coreCursor'], *checkpoint['safeCursors'], *checkpoint['rawCursors']]:
            if cursor['blockNumber'] != anchor['blockNumber'] or cursor['blockHash'].lower() != anchor['blockHash'].lower():
                raise ValueError('Completed gateway receipt checkpoint is partial')
        config = self.config
        chain = str(config['chainId'])
        dashboard_addresses = [config['coreAddress'].lower()]
        if config.get('governanceAddress'):
            dashboard_addresses.append(config['governanceAddress'].lower())
        safe_addresses = [cursor['address'].lower() for cursor in checkpoint['safeCursors']]
        raw_addresses = [cursor['address'].lower() for cursor in checkpoint['rawCursors']]
        async def count(sql, params):
            async with self.database.connection() as connection:
                cursor = await connection.execute(sql, params)
                row = await cursor.fetchone()
                value = row.get('row_count') if row else None
                if not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]*', value):
                    raise ValueError('Reconciliation receipt count query failed')
                return value
        async def safe_count():
            if not safe_addresses:
                return '0'
            return await count('''SELECT COUNT(*)::text AS row_count FROM onchain_event_logs
                WHERE chain_id=%s AND contract_address=ANY(%s::text[]) AND event_name=ANY(%s::text[])''',
                (chain, safe_addresses, ['ExecutionSuccess', 'ExecutionFailure']))
        raw_count, event_count, execution_count, models, block, block_hash, profile = await asyncio.gather(
            count('''SELECT COUNT(*)::text AS row_count FROM onchain_raw_logs
                WHERE chain_id=%s AND contract_address=ANY(%s::text[])''', (chain, raw_addresses)),
            count('''SELECT COUNT(*)::text AS row_count FROM onchain_event_logs
                WHERE chain_id=%s AND contract_address=ANY(%s::text[])''', (chain, dashboard_addresses)),
            safe_count(),
            count('''SELECT COUNT(DISTINCT model_key)::text AS row_count FROM onchain_read_model_snapshots
                WHERE chain_id=%s AND contract_address=%s AND block_number=%s AND model_key=ANY(%s::text[])''',
                (chain, config['coreAddress'].lower(), str(anchor['blockNumber']), list(REQUIRED_MODELS))),
            *(self.read_state(key) for key in SNAPSHOT_KEYS))
        number = parse_integer(block)
        if number is None or block_hash is None:
            raise ValueError('Completed gateway state snapshot cursor is missing')
        if models != str(len(REQUIRED_MODELS)):
            raise ValueError('Completed gateway state snapshot models are incomplete')
        return create_receipt({'reconciliationId': lease.reconciliation_id,
            'gatewayConfigRevision': lease.config_revision, 'runtimeConfigId': config.get('runtimeConfigId'),
            'finalizedAnchor': anchor, 'identities': {key: IDENTITY[key] for key in
                ('databaseSchemaVersion', 'rawJournalVersion', 'dashboardProjectionVersion', 'stateSnapshotVersion', 'safeCursorVersion')},
            'rawJournal': {'trackedAddressCount': len(checkpoint['rawCursors']), 'logCount': raw_count, 'cursors': checkpoint['rawCursors']},
            'dashboardProjection': {'eventLogCount': event_count, **checkpoint['coreCursor'], 'profile': checkpoint['profile']},
            'stateSnapshot': {'modelCount': models, 'blockNumber': number, 'blockHash': block_hash, 'profile': profile or ''},
            'safeCursors': {'configuredSafeCount': len(checkpoint['safeCursors']), 'eventLogCount': execution_count,
                'cursors': checkpoint['safeCursors']}, 'rpcRequests': rpc_requests,
            'completedAtMs': completed_at_ms, 'durationMs': completed_at_ms-started_at_ms})

    async def commit(self, lease, checkpoint, receipt):
        config = self.config
        async with self.database.connection() as connection:
            async with connection.transaction():
                async def put(address, key, value):
                    await connection.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
                        VALUES (%s,%s,%s,%s) ON CONFLICT(chain_id,contract_address,state_key)
                        DO UPDATE SET state_value=EXCLUDED.state_value,updated_at=NOW()''',
                        (str(config['chainId']), address.lower(), key, value))
                core = config['coreAddress']
                for key, value in zip(CORE_COMMITTED, (str(checkpoint['coreCursor']['blockNumber']),
                    checkpoint['coreCursor']['blockHash'].lower(), checkpoint['profile'], lease.reconciliation_id, lease.config_revision), strict=True):
                    await put(core, key, value)
                for cursor in checkpoint['safeCursors']:
                    for key, value in zip(SAFE_COMMITTED, (str(cursor['blockNumber']), cursor['blockHash'].lower(),
                        checkpoint['profile'], lease.reconciliation_id), strict=True):
                        await put(cursor['address'], key, value)
                if receipt is not None:
                    await put(core, RECEIPT_KEY, json.dumps(receipt, separators=(',', ':'), ensure_ascii=False))
                else:
                    await connection.execute('''DELETE FROM onchain_sync_state
                        WHERE chain_id=%s AND contract_address=%s AND state_key=%s''',
                        (str(config['chainId']), core.lower(), RECEIPT_KEY))
