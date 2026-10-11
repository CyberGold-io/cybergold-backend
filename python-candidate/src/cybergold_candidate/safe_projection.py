"""Retained Safe execution projection and working/committed cursor storage."""
import json

from .completed_state import IDENTITY
from .event_projection import postgres_timestamp
from .holder_projection import HolderProjection
from .recovery_persistence import parse_integer

EVENT_NAMES = ['ExecutionSuccess', 'ExecutionFailure']
VERSION_KEY = 'safe_execution_cursor_version'
BLOCK_KEY = 'safe_execution_last_scanned_block'
HASH_KEY = 'safe_execution_last_scanned_block_hash'
PROFILE_KEY = 'safe_finalized_projection_profile'
COMMITTED_KEYS = ('safe_committed_finalized_block', 'safe_committed_finalized_block_hash',
    'safe_committed_finalized_profile', 'safe_committed_reconciliation_id')


class SafeProjection:
    def __init__(self, database, chain_id, address):
        self.database, self.address = database, address.lower()
        self.store = HolderProjection(database, {'chainId': chain_id, 'coreAddress': address})

    async def cursor(self):
        return parse_integer(await self.store.state(BLOCK_KEY))

    async def cursor_hash(self):
        return await self.store.state(HASH_KEY)

    async def profile(self):
        return await self.store.state(PROFILE_KEY)

    async def committed(self):
        rows = await self.store.execute('''SELECT state_key,state_value FROM onchain_sync_state
            WHERE chain_id=%s AND contract_address=%s AND state_key=ANY(%s::text[])''',
            (self.store.chain, self.address, list(COMMITTED_KEYS)))
        values = {row['state_key']: row['state_value'] for row in rows}
        return dict(zip(('blockNumber', 'blockHash', 'profile', 'reconciliationId'),
            (parse_integer(values.get(COMMITTED_KEYS[0])), *(values.get(key) for key in COMMITTED_KEYS[1:])), strict=True))

    async def ensure_version(self):
        await self.store.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
            VALUES (%s,%s,%s,%s) ON CONFLICT(chain_id,contract_address,state_key) DO NOTHING''',
            (self.store.chain, self.address, VERSION_KEY, IDENTITY['safeCursorVersion']))
        current = await self.store.state(VERSION_KEY)
        if current is not None and current != IDENTITY['safeCursorVersion']:
            raise ValueError('Safe cursor version ' + current + ' is incompatible with ' + IDENTITY['safeCursorVersion'])
        if current is None:
            raise ValueError('Safe cursor identity could not be initialized')

    async def put_cursor(self, block, block_hash=None, profile=None):
        async with self.database.connection() as connection:
            async with connection.transaction():
                await self.store.put_state(BLOCK_KEY, str(block), connection)
                if block_hash:
                    await self.store.put_state(HASH_KEY, block_hash.lower(), connection)
                if profile:
                    await self.store.put_state(PROFILE_KEY, profile, connection)

    async def delete_from(self, block):
        await self.store.execute('''DELETE FROM onchain_event_logs WHERE chain_id=%s AND contract_address=%s
            AND event_name=ANY(%s::text[]) AND block_number>=%s''',
            (self.store.chain, self.address, EVENT_NAMES, str(block)))

    async def persist(self, logs):
        for log in logs:
            payload = {'args': {'txHash': log['safeTxHash'].lower(), 'payment': str(log['payment'])},
                'topics': log['topics'], 'data': log['data']}
            await self.store.execute('''INSERT INTO onchain_event_logs
                (chain_id,contract_address,event_name,block_number,block_hash,tx_hash,log_index,block_timestamp,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(chain_id,tx_hash,log_index)
                DO UPDATE SET contract_address=EXCLUDED.contract_address,event_name=EXCLUDED.event_name,
                block_number=EXCLUDED.block_number,block_hash=EXCLUDED.block_hash,
                block_timestamp=EXCLUDED.block_timestamp,payload=EXCLUDED.payload''',
                (self.store.chain, self.address, log['eventName'], str(log['blockNumber']), log['blockHash'],
                    log['transactionHash'].lower(), log['logIndex'], postgres_timestamp(int(log['timestamp']) * 1000),
                    json.dumps(payload, separators=(',', ':'))))
