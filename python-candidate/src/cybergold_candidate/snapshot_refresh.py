"""Coherent state reads and atomic V2/model completion."""
from .dashboard_builder import DashboardReads
from .finalized_multicall import FinalizedMulticall, MulticallBudgetError
from .gateway_lease import restart_required, accounting_failure
from .holder_projection import HolderProjection
from .indexer_policy import finalized_anchor
from .indexer_recovery_reads import RecoveryStateReads, portfolio_model
from .recovery_persistence import read_checkpoint, reconcile_v2
from .snapshot_persistence import persist_snapshot, RECOVERY_MODEL, DASHBOARD_MODEL


async def refresh_snapshot(config, snapshot, client, database, lease=None):
    block, block_hash, profile = snapshot['blockNumber'], snapshot['blockHash'], snapshot['profile']
    target = {'blockHash': block_hash, 'requireCanonical': True} if block_hash else {'blockNumber': block}
    state_client = FinalizedMulticall(client, block_hash) if config['finalizedSnapshotMulticall'] and block_hash else client
    def terminal(error):
        return isinstance(error, MulticallBudgetError) or bool(lease and (restart_required(error) or accounting_failure(error)))
    async def assert_anchor():
        if not block_hash:
            return
        value = await client.block(block_hash=block_hash)
        normalized = finalized_anchor({'number': value['number'], 'hash': value['hash']})
        if normalized['blockNumber'] != block or normalized['blockHash'] != block_hash.lower():
            raise ValueError('Finalized state snapshot anchor changed during the run')
    store = HolderProjection(database, config)
    await assert_anchor()
    recovery = await RecoveryStateReads(config, state_client, store).snapshot(block, target, terminal)
    model = portfolio_model(config['chainId'], block, config['coreAddress'], recovery)
    dashboard = await DashboardReads(config, state_client, store).summary(block, recovery, target,
        expected_hash=block_hash, force_pinned=block_hash is not None, terminal=terminal)
    if config['recoveryShareV2']:
        async with database.connection() as connection:
            checkpoint = await read_checkpoint(connection, config['chainId'], config['coreAddress'])
    else:
        checkpoint = None
    canonical_previous = None
    if checkpoint and checkpoint['blockNumber'] < block:
        value = await client.block(checkpoint['blockNumber'])
        normalized = finalized_anchor({'number': value['number'], 'hash': value['hash']})
        if normalized['blockNumber'] != checkpoint['blockNumber']:
            raise ValueError('Recovery-share v2 checkpoint header returned the wrong block')
        canonical_previous = normalized['blockHash']
    await assert_anchor()
    async def finalize(connection):
        if config['recoveryShareV2']:
            if not block_hash or not profile:
                raise ValueError('Recovery-share v2 projection requires an exact finalized snapshot')
            await reconcile_v2(connection, config['chainId'], config['coreAddress'], block, block_hash, profile, canonical_previous)
        await persist_snapshot(connection, config['chainId'], config['coreAddress'], RECOVERY_MODEL, block, model)
        await persist_snapshot(connection, config['chainId'], config['coreAddress'], DASHBOARD_MODEL, block, dashboard)
        if block_hash and profile:
            for key, value in [('finalized_snapshot_block', str(block)), ('finalized_snapshot_block_hash', block_hash.lower()),
                ('finalized_snapshot_profile', profile)]:
                await store.put_state(key, value, connection)
    async with database.connection() as connection:
        async with connection.transaction():
            await finalize(connection)
    await store.execute("DELETE FROM onchain_api_rate_limits WHERE updated_at < NOW() - INTERVAL '5 minutes'", ())
