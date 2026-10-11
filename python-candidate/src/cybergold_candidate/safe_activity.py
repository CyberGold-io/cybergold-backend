"""Read-only retained Safe view. Uses the existing schema without initializing it."""
from web3 import Web3

from .safe_abi import safe_execution_args

EXECUTION_TOPICS = {Web3.to_hex(Web3.keccak(text=name + '(bytes32,uint256)')): name
                    for name in ('ExecutionSuccess', 'ExecutionFailure')}


def decode_safe_activity(row):
    topic = row['topics'][0] if row['topics'] else None
    name = EXECUTION_TOPICS.get(topic)
    args = safe_execution_args(row) if name else None
    return {'safeAddress': row['contract_address'], 'blockNumber': row['block_number'],
            'blockHash': row['block_hash'], 'transactionHash': row['tx_hash'],
            'logIndex': row['log_index'], 'timestampSeconds': row['block_timestamp_seconds'],
            'topic': topic, 'eventName': name if args else None,
            'safeTxHash': args['safeTxHash'] if args else None,
            'paymentWei': args['payment'] if args else None}


async def select_safe_activity(connection, chain_id, addresses, lookback_blocks):
    normalized = [address.lower() for address in addresses]
    parameters = (str(chain_id), normalized)
    records = await connection.execute('''
        SELECT contract_address, block_number::text, block_hash, tx_hash, log_index,
               block_timestamp_seconds::text, topics, data
        FROM onchain_raw_logs WHERE chain_id=%s AND contract_address=ANY(%s::text[])
        ORDER BY block_number DESC, log_index DESC, contract_address ASC LIMIT 101
    ''', parameters)
    rows = await records.fetchall()
    coverage = await connection.execute('''
        SELECT contract_address, state_key, state_value FROM onchain_sync_state
        WHERE chain_id=%s AND contract_address=ANY(%s::text[])
          AND state_key IN ('raw_log_start_block','raw_log_last_scanned_block',
            'raw_log_last_scanned_block_hash','safe_execution_last_scanned_block')
    ''', parameters)
    states = await coverage.fetchall()
    ranges = []
    for address in normalized:
        values = {row['state_key']: row['state_value'] for row in states if row['contract_address'] == address}
        ranges.append({'address': address, 'journalStartBlock': values.get('raw_log_start_block'),
                       'indexedThroughBlock': values.get('raw_log_last_scanned_block'),
                       'indexedThroughBlockHash': values.get('raw_log_last_scanned_block_hash'),
                       'projectionIndexedThroughBlock': values.get('safe_execution_last_scanned_block')})
    return {'enabled': True, 'chainId': chain_id, 'source': 'retained-safe-journal',
            'projectionLookbackBlocks': str(lookback_blocks), 'coverage': ranges,
            'hasMore': len(rows) > 100, 'events': [decode_safe_activity(row) for row in rows[:100]]}


async def get_safe_activity(pool, chain_id, addresses, lookback_blocks):
    if pool is None or not addresses:
        return {'enabled': False, 'events': []}
    async with pool.connection() as connection:
        async with connection.transaction():
            await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            return await select_safe_activity(connection, chain_id, addresses, lookback_blocks)
