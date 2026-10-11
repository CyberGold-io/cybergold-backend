"""Retained holder balance/delta projection and reorg rewind operations."""
from .recovery_persistence import parse_integer, parse_address, ZERO


def transfer_args(payload):
    args = payload.get('args') if isinstance(payload, dict) else None
    if not isinstance(args, dict):
        return None
    from_address, to = parse_address(args.get('from')), parse_address(args.get('to'))
    value = parse_integer(args.get('value'))
    return {'from': from_address, 'to': to, 'value': value} if from_address and to and value is not None else None


class HolderProjection:
    def __init__(self, database, config):
        self.database = database
        self.chain, self.core = str(config['chainId']), config['coreAddress'].lower()

    async def execute(self, sql, params, connection=None):
        async def run(active):
            cursor = await active.execute(sql, params)
            return await cursor.fetchall() if cursor.description else []
        if connection is not None:
            return await run(connection)
        async with self.database.connection() as active:
            return await run(active)

    async def state(self, key, connection=None):
        rows = await self.execute('''SELECT state_value FROM onchain_sync_state
            WHERE chain_id=%s AND contract_address=%s AND state_key=%s LIMIT 1''', (self.chain, self.core, key), connection)
        return rows[0]['state_value'] if rows else None

    async def state_entry(self, key):
        rows = await self.execute('''SELECT state_value,FLOOR(EXTRACT(EPOCH FROM updated_at)*1000) AS updated_at_ms
            FROM onchain_sync_state WHERE chain_id=%s AND contract_address=%s AND state_key=%s LIMIT 1''',
            (self.chain, self.core, key))
        return {'stateValue': rows[0]['state_value'], 'updatedAtMs': int(rows[0]['updated_at_ms'])} if rows else None

    async def put_state(self, key, value, connection=None):
        await self.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
            VALUES (%s,%s,%s,%s) ON CONFLICT(chain_id,contract_address,state_key)
            DO UPDATE SET state_value=EXCLUDED.state_value,updated_at=NOW()''', (self.chain, self.core, key, value), connection)

    async def clear_snapshots(self, connection=None):
        await self.execute('DELETE FROM onchain_read_model_snapshots WHERE chain_id=%s AND contract_address=%s',
            (self.chain, self.core), connection)

    async def clear(self, connection=None):
        if connection is None:
            async with self.database.connection() as connection:
                async with connection.transaction():
                    return await self.clear(connection)
        for table in ['onchain_token_balances', 'onchain_holder_balance_deltas', 'onchain_recovery_share_balances']:
            await self.execute('DELETE FROM ' + table + ' WHERE chain_id=%s AND contract_address=%s',
                (self.chain, self.core), connection)
        await self.clear_snapshots(connection)
        await self.put_state('holder_count', '0', connection)
        await self.put_state('holder_cache_ready', '0', connection)

    async def ready(self, connection=None):
        return await self.state('holder_cache_ready', connection) == '1'

    async def count(self, connection=None):
        return parse_integer(await self.state('holder_count', connection))

    async def balance(self, address, connection=None):
        rows = await self.execute('''SELECT balance_raw FROM onchain_token_balances
            WHERE chain_id=%s AND contract_address=%s AND holder_address=%s LIMIT 1''',
            (self.chain, self.core, address.lower()), connection)
        return (parse_integer(rows[0]['balance_raw']) or 0) if rows else 0

    async def put_balance(self, address, value, connection=None):
        if value == 0:
            await self.execute('''DELETE FROM onchain_token_balances
                WHERE chain_id=%s AND contract_address=%s AND holder_address=%s''', (self.chain, self.core, address.lower()), connection)
        else:
            await self.execute('''INSERT INTO onchain_token_balances(chain_id,contract_address,holder_address,balance_raw)
                VALUES (%s,%s,%s,%s) ON CONFLICT(chain_id,contract_address,holder_address)
                DO UPDATE SET balance_raw=EXCLUDED.balance_raw,updated_at=NOW()''',
                (self.chain, self.core, address.lower(), str(value)), connection)

    async def record_delta(self, address, value, meta, connection=None):
        if value == 0:
            return
        await self.execute('''INSERT INTO onchain_holder_balance_deltas
            (chain_id,contract_address,block_number,tx_hash,log_index,holder_address,delta_raw)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(chain_id,tx_hash,log_index,holder_address) DO NOTHING''',
            (self.chain, self.core, str(meta['blockNumber']), meta['txHash'].lower(), meta['logIndex'], address.lower(), str(value)), connection)

    async def apply_delta(self, address, value, meta=None, connection=None):
        if value == 0 or address.lower() == ZERO:
            return
        if connection is None:
            async with self.database.connection() as connection:
                async with connection.transaction():
                    return await self.apply_delta(address, value, meta, connection)
        current = await self.balance(address, connection)
        next_balance = max(0, current + value)
        count = await self.count(connection)
        count = count if count is not None else 0
        if current == 0 and next_balance > 0:
            count += 1
        if current > 0 and next_balance == 0:
            count -= 1
        await self.put_balance(address, next_balance, connection)
        await self.put_state('holder_count', str(max(0, count)), connection)
        if meta is not None:
            await self.record_delta(address, value, meta, connection)

    async def apply_transfer(self, transfer, meta, connection=None):
        if transfer['value'] == 0 or transfer['from'] == transfer['to']:
            return
        if connection is None:
            async with self.database.connection() as connection:
                async with connection.transaction():
                    return await self.apply_transfer(transfer, meta, connection)
        if transfer['from'].lower() != ZERO:
            await self.apply_delta(transfer['from'], -transfer['value'], meta, connection)
        if transfer['to'].lower() != ZERO:
            await self.apply_delta(transfer['to'], transfer['value'], meta, connection)

    async def rewind(self, from_block, connection=None):
        if connection is None:
            async with self.database.connection() as connection:
                async with connection.transaction():
                    return await self.rewind(from_block, connection)
        if not await self.ready(connection):
            return False
        rows = await self.execute('''SELECT COUNT(*)::text AS count FROM onchain_event_logs
            WHERE chain_id=%s AND contract_address=%s AND event_name='Transfer' AND block_number>=%s''',
            (self.chain, self.core, str(from_block)), connection)
        count = int(rows[0]['count']) if rows else 0
        deltas = await self.execute('''SELECT holder_address,delta_raw,block_number::text,tx_hash,log_index
            FROM onchain_holder_balance_deltas WHERE chain_id=%s AND contract_address=%s AND block_number>=%s
            ORDER BY block_number DESC,log_index DESC''', (self.chain, self.core, str(from_block)), connection)
        if count > 0 and not deltas:
            return False
        for row in deltas:
            delta = parse_integer(row['delta_raw'])
            if delta is not None and delta != 0:
                await self.apply_delta(row['holder_address'], -delta, connection=connection)
        await self.execute('DELETE FROM onchain_holder_balance_deltas WHERE chain_id=%s AND contract_address=%s AND block_number>=%s',
            (self.chain, self.core, str(from_block)), connection)
        return True

    async def rebuild(self, delta_retention_from=None, connection=None):
        if connection is None:
            async with self.database.connection() as connection:
                async with connection.transaction():
                    return await self.rebuild(delta_retention_from, connection)
        await self.clear(connection)
        await self.put_state('holder_count', '0', connection)
        rows = await self.execute('''SELECT block_number::text,tx_hash,log_index,payload FROM onchain_event_logs
            WHERE chain_id=%s AND contract_address=%s AND event_name='Transfer' ORDER BY block_number ASC,log_index ASC''',
            (self.chain, self.core), connection)
        for row in rows:
            transfer = transfer_args(row['payload'])
            if transfer is None or transfer['value'] == 0 or transfer['from'] == transfer['to']:
                continue
            block = int(row['block_number'])
            meta = {'blockNumber': block, 'txHash': row['tx_hash'], 'logIndex': row['log_index']}
            record = meta if delta_retention_from is None or block >= delta_retention_from else None
            if transfer['from'].lower() != ZERO:
                await self.apply_delta(transfer['from'], -transfer['value'], record, connection)
            if transfer['to'].lower() != ZERO:
                await self.apply_delta(transfer['to'], transfer['value'], record, connection)
        await self.put_state('holder_cache_ready', '1', connection)

    async def prune_deltas(self, keep_from):
        await self.execute('DELETE FROM onchain_holder_balance_deltas WHERE chain_id=%s AND contract_address=%s AND block_number<%s',
            (self.chain, self.core, str(keep_from)))

    async def prune_snapshots(self, from_block):
        await self.execute('''WITH latest_completed AS (
            SELECT model_key,MAX(block_number) AS block_number FROM onchain_read_model_snapshots
            WHERE chain_id=%s AND contract_address=%s GROUP BY model_key)
            DELETE FROM onchain_read_model_snapshots AS snapshot
            WHERE snapshot.chain_id=%s AND snapshot.contract_address=%s AND snapshot.block_number>=%s
            AND NOT EXISTS (SELECT 1 FROM latest_completed WHERE latest_completed.model_key=snapshot.model_key
                AND latest_completed.block_number=snapshot.block_number)''',
            (self.chain, self.core, self.chain, self.core, str(from_block)))
