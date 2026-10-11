"""Helpers settlement/admin history from its own retained raw journal."""
import json
from pathlib import Path

from eth_utils.abi import event_abi_to_log_topic
from web3 import Web3

from .core_activity import decode_journal_activity, select_core_activity

ABI = json.loads(Path(__file__).with_name('helpers-activity-abi.json').read_text())
EVENTS = {Web3.to_hex(event_abi_to_log_topic(event)): event for event in ABI}


def decode_helpers_activity(row):
    return decode_journal_activity(row, EVENTS)


async def get_helpers_activity(pool, chain_id, address):
    if pool is None or not address:
        return {'enabled': False, 'events': []}
    async with pool.connection() as connection:
        async with connection.transaction():
            await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            return await select_core_activity(connection, chain_id, address,
                decode=decode_helpers_activity, source='retained-helpers-journal')
