"""Retained Sandbox fork invalidation; the caller owns its transaction."""
from .recovery_persistence import STATE_KEYS as RECOVERY_KEYS, parse_integer
from .worker_contract import fork_transition

CHAIN = '31338'
ANCHOR_KEYS = ('sandbox_fork_generation', 'sandbox_fork_block',
    'sandbox_fork_block_hash', 'sandbox_fork_projection_status')
CURSOR_PAIRS = (
    ('last_scanned_block', 'finalized_projection_block_hash'),
    ('raw_log_last_scanned_block', 'raw_log_last_scanned_block_hash'),
    ('safe_execution_last_scanned_block', 'safe_execution_last_scanned_block_hash'))
PROJECTION_KEYS = ('last_scanned_block', 'safe_execution_last_scanned_block')
DERIVED_KEYS = (
    'finalized_snapshot_block', 'finalized_snapshot_block_hash', 'finalized_snapshot_profile',
    'committed_finalized_block', 'committed_finalized_block_hash', 'committed_finalized_profile',
    'committed_reconciliation_id', 'committed_gateway_config_revision',
    'safe_committed_finalized_block', 'safe_committed_finalized_block_hash',
    'safe_committed_finalized_profile', 'safe_committed_reconciliation_id',
    'completed_reconciliation_receipt_v2', 'holder_count', 'holder_cache_ready', 'cygld_ref_grams_fp18')


async def set_state(connection, core, key, value):
    await connection.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
        VALUES (%s,%s,%s,%s) ON CONFLICT(chain_id,contract_address,state_key)
        DO UPDATE SET state_value=EXCLUDED.state_value,updated_at=NOW()''', (CHAIN, core, key, value))


async def read_generation(connection, core):
    cursor = await connection.execute('''SELECT state_key,state_value FROM onchain_sync_state
        WHERE chain_id=%s AND contract_address=%s AND state_key=ANY(%s::text[])''', (CHAIN, core, list(ANCHOR_KEYS)))
    values = {row['state_key']: row['state_value'] for row in await cursor.fetchall()}
    generation, block, block_hash, status = (values.get(key) for key in ANCHOR_KEYS)
    if not generation and not block and not block_hash:
        return None
    if not generation or not block or not block_hash:
        raise ValueError('stored Sandbox fork anchor is incomplete')
    if status not in ('ready', 'refreshing'):
        raise ValueError('stored Sandbox fork recovery status is invalid')
    number = parse_integer(block)
    if number is None:
        raise ValueError('stored Sandbox fork block is invalid')
    return {'anchor': {'generation': generation, 'forkBlock': number, 'forkBlockHash': block_hash}, 'status': status}


def same_anchor(left, right):
    return (left['generation'] == right['generation'] and left['forkBlock'] == right['forkBlock']
        and left['forkBlockHash'].lower() == right['forkBlockHash'].lower())


async def prepare_generation(connection, core, current):
    core = core.lower()
    stored = await read_generation(connection, core)
    if stored and not same_anchor(stored['anchor'], current):
        raise ValueError('stored Sandbox fork generation differs from the live pre-restart anchor')
    if stored and stored['status'] == 'refreshing':
        raise ValueError('Sandbox projection recovery is still in progress')
    for key, value in zip(ANCHOR_KEYS, (current['generation'], str(current['forkBlock']),
        current['forkBlockHash'].lower(), 'ready'), strict=True):
        await set_state(connection, core, key, value)
    return {'status': 'prepared'}


async def delete_state(connection, keys):
    await connection.execute('DELETE FROM onchain_sync_state WHERE chain_id=%s AND state_key=ANY(%s::text[])',
        (CHAIN, list(keys)))


async def rewind_cursors(connection, plan):
    if plan['kind'] == 'full-replay':
        await delete_state(connection, [*[pair[0] for pair in CURSOR_PAIRS], *[pair[1] for pair in CURSOR_PAIRS],
            'raw_log_journal_version', 'raw_log_start_block'])
        return
    cursor = await connection.execute('''SELECT contract_address,state_key,state_value FROM onchain_sync_state
        WHERE chain_id=%s AND state_key=ANY(%s::text[])''', (CHAIN, [pair[0] for pair in CURSOR_PAIRS]))
    for row in await cursor.fetchall():
        block = parse_integer(row['state_value'])
        if block is None:
            raise ValueError('Sandbox ' + row['state_key'] + ' cursor is invalid')
        if block <= plan['retainedThrough']:
            continue
        pair = next((pair for pair in CURSOR_PAIRS if pair[0] == row['state_key']), None)
        if pair is None:
            raise ValueError('Sandbox cursor identity is unknown')
        await connection.execute('''UPDATE onchain_sync_state SET state_value=%s,updated_at=NOW()
            WHERE chain_id=%s AND contract_address=%s AND state_key=%s''',
            (str(plan['retainedThrough']), CHAIN, row['contract_address'], row['state_key']))
        await set_state(connection, row['contract_address'], pair[1], plan['retainedBlockHash'])


async def can_retain_projections(connection, retained_through):
    cursor = await connection.execute('''SELECT state_key,state_value FROM onchain_sync_state
        WHERE chain_id=%s AND state_key=ANY(%s::text[])''', (CHAIN, list(PROJECTION_KEYS)))
    rows = await cursor.fetchall()
    if not any(row['state_key'] == 'last_scanned_block' for row in rows):
        return False
    for row in rows:
        block = parse_integer(row['state_value'])
        if block is None:
            raise ValueError('Sandbox ' + row['state_key'] + ' projection cursor is invalid')
        if block > retained_through:
            return False
    return True


async def apply_generation(connection, core, previous, current, deployment_start, current_hash_at_previous):
    if previous['generation'] == current['generation']:
        raise ValueError('Sandbox process generation did not change')
    core = core.lower()
    stored = await read_generation(connection, core)
    if stored is None:
        raise ValueError('Sandbox fork was not prepared before restart')
    if same_anchor(stored['anchor'], current):
        return {'status': 'already-ready' if stored['status'] == 'ready' else 'already-applied'}
    if not same_anchor(stored['anchor'], previous) or stored['status'] != 'ready':
        raise ValueError('prepared Sandbox fork anchor does not match the requested transition')
    plan = fork_transition(previous, current, deployment_start, current_hash_at_previous)
    if plan['kind'] == 'unchanged':
        raise ValueError('Sandbox process generation did not change')
    if plan['kind'] == 'reuse-prefix' and not await can_retain_projections(connection, plan['retainedThrough']):
        plan = {**plan, 'kind': 'replay-prefix'}
    await connection.execute('DELETE FROM onchain_event_logs WHERE chain_id=%s AND block_number>=%s',
        (CHAIN, str(deployment_start if plan['kind'] == 'replay-prefix' else plan['invalidateFrom'])))
    await connection.execute('DELETE FROM onchain_raw_logs WHERE chain_id=%s AND block_number>=%s',
        (CHAIN, str(plan['invalidateFrom'])))
    replay = plan['kind'] != 'reuse-prefix'
    tables = (['onchain_token_balances', 'onchain_holder_balance_deltas',
        'onchain_recovery_share_balances', 'onchain_recovery_share_balances_v2'] if replay
        else ['onchain_holder_balance_deltas']) + ['onchain_read_model_snapshots', 'quote_pool_cache']
    for table in tables:
        if table == 'onchain_holder_balance_deltas' and not replay:
            await connection.execute('DELETE FROM onchain_holder_balance_deltas WHERE chain_id=%s AND block_number>=%s',
                (CHAIN, str(plan['invalidateFrom'])))
        else:
            # Table names come only from the retained fixed list above.
            await connection.execute('DELETE FROM ' + table + ' WHERE chain_id=%s', (CHAIN,))
    await delete_state(connection, [*DERIVED_KEYS, *(RECOVERY_KEYS if replay else [])])
    if plan['kind'] == 'replay-prefix':
        await delete_state(connection, [key for pair in CURSOR_PAIRS if pair[0] in PROJECTION_KEYS for key in pair])
    await rewind_cursors(connection, plan)
    for key, value in zip(ANCHOR_KEYS, (current['generation'], str(current['forkBlock']),
        current['forkBlockHash'].lower(), 'refreshing'), strict=True):
        await set_state(connection, core, key, value)
    return {'status': 'applied', 'plan': plan}


async def mark_ready(connection, core, reached_block):
    core = core.lower()
    stored = await read_generation(connection, core)
    if stored is None or stored['status'] != 'refreshing' or reached_block < stored['anchor']['forkBlock']:
        return
    await set_state(connection, core, ANCHOR_KEYS[3], 'ready')
