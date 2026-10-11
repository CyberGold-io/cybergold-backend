"""Retained projection identity initialization, preserving legacy slot values."""
from .completed_state import IDENTITY
from .holder_projection import HolderProjection
from .indexer_policy import identity_transition

KEYS = {
    'rawJournalVersion': 'raw_journal_version',
    'dashboardProjectionVersion': 'dashboard_projection_version',
    'stateSnapshotVersion': 'state_snapshot_version',
    'legacyIndexerVersion': 'indexer_version',
    'legacyGovernanceAddress': 'governance_address',
    'dashboardProjectionGovernanceAddress': 'dashboard_projection_governance_address'}


async def ensure_identity(database, config):
    holder = HolderProjection(database, config)
    governance = config['governanceAddress'].lower() if config.get('governanceAddress') is not None else 'none'
    async with database.connection() as connection:
        async with connection.transaction():
            rows = await holder.execute('''SELECT state_key,state_value FROM onchain_sync_state
                WHERE chain_id=%s AND contract_address=%s AND state_key=ANY(%s::text[])''',
                (holder.chain, holder.core, list(KEYS.values())), connection)
            stored = {row['state_key']: row['state_value'] for row in rows}
            transition = identity_transition({name: stored.get(key) for name, key in KEYS.items()},
                {**{name: IDENTITY[name] for name in ['rawJournalVersion','dashboardProjectionVersion','stateSnapshotVersion']},
                    'governanceAddress': governance})
            if transition['resetProjection']:
                await holder.clear(connection)
            elif transition['resetStateSnapshots']:
                await holder.clear_snapshots(connection)
            if transition['restartScanFromDeployment']:
                old = stored.get(KEYS['dashboardProjectionGovernanceAddress'], stored.get(KEYS['legacyGovernanceAddress']))
                if old is not None and old != 'none':
                    await holder.execute('DELETE FROM onchain_event_logs WHERE chain_id=%s AND contract_address=%s',
                        (holder.chain, old.lower()), connection)
                await holder.execute('DELETE FROM onchain_sync_state WHERE chain_id=%s AND contract_address=%s AND state_key=%s',
                    (holder.chain, holder.core, 'last_scanned_block'), connection)
            if transition['initializeRawJournalIdentity']:
                await holder.put_state(KEYS['rawJournalVersion'], IDENTITY['rawJournalVersion'], connection)
            if transition['initializeStateSnapshotIdentity'] or transition['resetStateSnapshots']:
                await holder.put_state(KEYS['stateSnapshotVersion'], IDENTITY['stateSnapshotVersion'], connection)
            for key, value in [(KEYS['dashboardProjectionVersion'], IDENTITY['dashboardProjectionVersion']),
                (KEYS['legacyIndexerVersion'], IDENTITY['dashboardIndexerVersion']),
                (KEYS['dashboardProjectionGovernanceAddress'], governance)]:
                if stored.get(key) != value:
                    await holder.put_state(key, value, connection)
            if KEYS['legacyGovernanceAddress'] not in stored:
                await holder.put_state(KEYS['legacyGovernanceAddress'], governance, connection)
            return transition['resetProjection']
