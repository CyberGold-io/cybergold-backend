"""Retained Core activity view, including the existing historical event ABI."""
import json
from pathlib import Path
import re

from eth_utils.abi import event_abi_to_log_topic
from web3 import Web3

WEB3 = Web3()
ABI = json.loads(Path(__file__).with_name('core-activity-abi.json').read_text())
EVENTS = {}
for event in ABI:
    EVENTS.setdefault(Web3.to_hex(event_abi_to_log_topic(event)), event)


def wire_value(value, parameter):
    # Standard Web3 decoding is adapted only to the established Viem JSON
    # representation: decimal strings for wide integers and checksum addresses.
    if isinstance(value, bytes):
        return '0x' + value.hex()
    array = re.fullmatch(r'(.*)\[(\d*)\]', parameter['type'])
    if array:
        return [wire_value(item, {**parameter, 'type': array[1]}) for item in value]
    if parameter['type'] == 'tuple':
        components = parameter['components']
        values = [value[component['name']] for component in components] if isinstance(value, dict) else value
        converted = [wire_value(item, component) for item, component in zip(values, components, strict=True)]
        return dict(zip((component['name'] for component in components), converted, strict=True)) if all(
            component.get('name') for component in components) else converted
    integer = re.fullmatch(r'u?int(\d*)', parameter['type'])
    if integer:
        return str(value) if int(integer[1] or 256) > 48 else value
    if parameter['type'] == 'address':
        return Web3.to_checksum_address(value)
    return value


def decode_journal_activity(row, events):
    topic = row['topics'][0] if row['topics'] else None
    name, arguments = None, None
    try:
        event = events[topic]
        log = {'topics': row['topics'], 'data': row['data'], 'logIndex': row['log_index'],
               'blockHash': row['block_hash'], 'blockNumber': int(row['block_number']),
               'transactionHash': row['tx_hash'], 'transactionIndex': 0,
               'address': '0x' + '0' * 40}
        # Viem parseAbi omits the false anonymous field; Web3 requires it.
        web3_event = {**event, 'anonymous': event.get('anonymous', False),
                      'inputs': [{**parameter, 'indexed': parameter.get('indexed', False)}
                                 for parameter in event['inputs']]}
        decoded = WEB3.eth.contract(abi=[web3_event]).events[event['name']]().process_log(log)['args']
        # The retained Viem view emits null arguments for zero-input events.
        arguments = ({parameter['name']: wire_value(decoded[parameter['name']], parameter)
                      for parameter in event['inputs']} if event['inputs'] else None)
        name = event['name']
    except Exception:
        # Retained reader intentionally leaves unknown/malformed history visible
        # with null decoded fields instead of hiding the stored record.
        pass
    return {'blockNumber': row['block_number'], 'blockHash': row['block_hash'],
            'transactionHash': row['tx_hash'], 'logIndex': row['log_index'],
            'timestampSeconds': row['block_timestamp_seconds'], 'topic': topic,
            'eventName': name, 'arguments': arguments}


def decode_core_activity(row):
    return decode_journal_activity(row, EVENTS)


async def select_core_activity(connection, chain_id, address, *, decode=decode_core_activity, source='retained-core-journal'):
    parameters = (str(chain_id), address.lower())
    records = await connection.execute('''
        SELECT block_number::text, block_hash, tx_hash, log_index,
               block_timestamp_seconds::text, topics, data
        FROM onchain_raw_logs WHERE chain_id=%s AND contract_address=%s
        ORDER BY block_number DESC, log_index DESC LIMIT 101
    ''', parameters)
    rows = await records.fetchall()
    coverage = await connection.execute('''
        SELECT state_key, state_value FROM onchain_sync_state
        WHERE chain_id=%s AND contract_address=%s
          AND state_key IN ('raw_log_start_block','raw_log_last_scanned_block','raw_log_last_scanned_block_hash')
    ''', parameters)
    state = {row['state_key']: row['state_value'] for row in await coverage.fetchall()}
    return {'enabled': True, 'chainId': chain_id, 'address': address.lower(),
            'source': source, 'journalStartBlock': state.get('raw_log_start_block'),
            'indexedThroughBlock': state.get('raw_log_last_scanned_block'),
            'indexedThroughBlockHash': state.get('raw_log_last_scanned_block_hash'),
            'hasMore': len(rows) > 100, 'events': [decode(row) for row in rows[:100]]}


async def get_core_activity(pool, chain_id, address):
    if pool is None or not address:
        return {'enabled': False, 'events': []}
    async with pool.connection() as connection:
        async with connection.transaction():
            await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            return await select_core_activity(connection, chain_id, address)
