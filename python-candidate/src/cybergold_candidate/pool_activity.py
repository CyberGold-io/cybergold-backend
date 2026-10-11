"""Bounded, lossless pool activity from the registry worker's canonical logs.

This is a read model, not swap math, pool TVL or all-time volume. Each durable
pool bundle atomically contains its recent scan ranges, events and rollups.
HTTP reads never acquire logs or wait for indexing.
"""
from copy import deepcopy
import json
import re

from web3 import Web3
from .pool_producer import public_pool

EVENT_LIMIT = 1000
RANGE_LIMIT = 64
PUBLIC_EVENT_LIMIT = 100


def topic(signature):
    return Web3.to_hex(Web3.keccak(text=signature)).lower()


# Full topic plus protocol prevents the V2/V3/V4 Swap/Mint/Burn name collision.
LAYOUTS = {}


def layout(protocol, name, fields):
    signature = name+'('+','.join(field[1] for field in fields)+')'
    LAYOUTS[protocol, topic(signature)] = name, fields


for protocol, name, fields in (
    ('v2', 'Sync', [('reserve0', 'uint112', False), ('reserve1', 'uint112', False)]),
    ('v2', 'Mint', [('sender', 'address', True), ('amount0', 'uint256', False), ('amount1', 'uint256', False)]),
    ('v2', 'Burn', [('sender', 'address', True), ('amount0', 'uint256', False), ('amount1', 'uint256', False), ('to', 'address', True)]),
    ('v2', 'Swap', [('sender', 'address', True), ('amount0In', 'uint256', False), ('amount1In', 'uint256', False),
                  ('amount0Out', 'uint256', False), ('amount1Out', 'uint256', False), ('to', 'address', True)]),
    ('v3', 'Initialize', [('sqrtPriceX96', 'uint160', False), ('tick', 'int24', False)]),
    ('v3', 'Swap', [('sender', 'address', True), ('recipient', 'address', True), ('amount0', 'int256', False),
                  ('amount1', 'int256', False), ('sqrtPriceX96', 'uint160', False), ('liquidity', 'uint128', False), ('tick', 'int24', False)]),
    ('v3', 'Mint', [('sender', 'address', False), ('owner', 'address', True), ('tickLower', 'int24', True),
                  ('tickUpper', 'int24', True), ('amount', 'uint128', False), ('amount0', 'uint256', False), ('amount1', 'uint256', False)]),
    ('v3', 'Burn', [('owner', 'address', True), ('tickLower', 'int24', True), ('tickUpper', 'int24', True),
                  ('amount', 'uint128', False), ('amount0', 'uint256', False), ('amount1', 'uint256', False)]),
    ('v3', 'SetFeeProtocol', [('feeProtocol0Old', 'uint8', False), ('feeProtocol1Old', 'uint8', False),
                            ('feeProtocol0New', 'uint8', False), ('feeProtocol1New', 'uint8', False)]),
    ('v4', 'Initialize', [('id', 'bytes32', True), ('currency0', 'address', True), ('currency1', 'address', True),
                        ('fee', 'uint24', False), ('tickSpacing', 'int24', False), ('hooks', 'address', False),
                        ('sqrtPriceX96', 'uint160', False), ('tick', 'int24', False)]),
    ('v4', 'Swap', [('id', 'bytes32', True), ('sender', 'address', True), ('amount0', 'int128', False),
                  ('amount1', 'int128', False), ('sqrtPriceX96', 'uint160', False), ('liquidity', 'uint128', False),
                  ('tick', 'int24', False), ('fee', 'uint24', False)]),
    ('v4', 'ModifyLiquidity', [('id', 'bytes32', True), ('sender', 'address', True), ('tickLower', 'int24', False),
                             ('tickUpper', 'int24', False), ('liquidityDelta', 'int256', False), ('salt', 'bytes32', False)]),
    ('v4', 'ProtocolFeeUpdated', [('id', 'bytes32', True), ('protocolFee', 'uint24', False)]),
):
    layout(protocol, name, fields)


def pool_identity(pool):
    # V4 PoolId encodes its key but not its singleton deployment address.
    address = pool.get('poolManager') if pool['protocol'] == 'v4' else pool.get('address', pool['id'])
    return json.dumps([pool['protocol'], address.lower(), pool['id'].lower()], separators=(',', ':'))


def integer(value):
    return int(value, 16) if isinstance(value, str) and value.startswith('0x') else int(value)


def event_order(event):
    return int(event['blockNumber']), event['transactionIndex'], event['logIndex']


def decode_event(pool, row, codec):
    signature = row['topics'][0].lower() if row['topics'] else None
    specification = LAYOUTS.get((pool['protocol'], signature))
    if specification is None:
        return None  # Other pool logs (e.g. V2 LP transfers) are not trading activity.
    name, fields = specification
    arguments = None
    try:
        unindexed = [field for field in fields if not field[2]]
        decoded = iter(codec.decode([field[1] for field in unindexed], bytes.fromhex(row['data'][2:])))
        indexed = iter(row['topics'][1:])
        arguments = {}
        for key, kind, is_indexed in fields:
            value = codec.decode([kind], bytes.fromhex(next(indexed)[2:]))[0] if is_indexed else next(decoded)
            arguments[key] = ('0x'+value.hex() if isinstance(value, bytes) else
                              Web3.to_checksum_address(value) if kind == 'address' else str(value))
    except Exception:
        arguments = None  # Preserve malformed historical rows, like the other activity APIs.
    block_hash, transaction_hash = row['blockHash'].lower(), row['transactionHash'].lower()
    log_index = integer(row['logIndex'])
    identity = json.dumps([pool_identity(pool), block_hash, transaction_hash, log_index], separators=(',', ':'))
    return {'identity': identity, 'pool': public_pool(pool), 'blockNumber': str(integer(row['blockNumber'])),
            'blockHash': block_hash, 'transactionHash': transaction_hash,
            'transactionIndex': integer(row.get('transactionIndex', 0)), 'logIndex': log_index,
            'address': row.get('address', pool.get('poolManager', pool.get('address'))),
            'eventName': name, 'arguments': arguments, 'topics': row['topics'], 'data': row['data']}


def rollup(events):
    result = dict.fromkeys(('eventCount', 'swapCount', 'liquidityAdditionCount', 'liquidityRemovalCount',
                           'stateUpdateCount', 'feeChangeCount', 'undecodedCount'), 0)
    amounts = dict.fromkeys(('amount0InRaw', 'amount1InRaw', 'amount0OutRaw', 'amount1OutRaw',
                             'liquidityAddedRaw', 'liquidityRemovedRaw'), 0)
    for event in events:
        result['eventCount'] += 1
        args, name, protocol = event['arguments'], event['eventName'], event['pool']['protocol']
        if args is None:
            result['undecodedCount'] += 1
            continue
        if name == 'Swap':
            result['swapCount'] += 1
            for index in (0, 1):
                if protocol == 'v2':
                    incoming, outgoing = int(args[f'amount{index}In']), int(args[f'amount{index}Out'])
                else:
                    # V3 reports pool balance deltas; V4 reports caller BalanceDelta.
                    value = int(args[f'amount{index}']) * (-1 if protocol == 'v4' else 1)
                    incoming, outgoing = max(value, 0), max(-value, 0)
                amounts[f'amount{index}InRaw'] += incoming
                amounts[f'amount{index}OutRaw'] += outgoing
        elif name in ('Mint', 'Burn', 'ModifyLiquidity'):
            delta = (int(args['liquidityDelta']) if name == 'ModifyLiquidity' else
                     int(args['amount']) * (-1 if name == 'Burn' else 1) if protocol == 'v3' else 0)
            changed = any(int(args[key]) for key in ('amount0', 'amount1')) if protocol == 'v2' else abs(delta)
            adding = delta > 0 if name == 'ModifyLiquidity' else name == 'Mint' and bool(changed)
            removing = delta < 0 if name == 'ModifyLiquidity' else name == 'Burn' and bool(changed)
            result['liquidityAdditionCount'] += int(adding)
            result['liquidityRemovalCount'] += int(removing)
            amounts['liquidityAddedRaw'] += max(delta, 0)
            amounts['liquidityRemovedRaw'] += max(-delta, 0)
        elif name in ('Sync', 'Initialize'):
            result['stateUpdateCount'] += 1
        else:
            result['feeChangeCount'] += 1
    return {**result, **{key: str(value) for key, value in amounts.items()}}


def baseline(pool, block):
    return {'pool': public_pool(pool), 'baseline': {'blockNumber': str(block['number']), 'blockHash': block['hash']},
            'ranges': [], 'eventsTruncated': False}


def checkpoint(bundle):
    return (bundle['ranges'][-1] if bundle['ranges'] else bundle['baseline'])


def append_range(bundle, block, rows, codec):
    result = deepcopy(bundle)
    first = int(checkpoint(result)['blockNumber'])+1
    decoded = (decode_event(result['pool'], row, codec) for row in rows
               if not row.get('removed') and first <= integer(row['blockNumber']) <= block['number'])
    events = sorted({event['identity']: event for event in decoded if event is not None}.values(), key=event_order)
    result['ranges'].append({'startBlock': str(first), 'blockNumber': str(block['number']), 'blockHash': block['hash'],
                             'rollup': rollup(events), 'events': events})
    while len(result['ranges']) > RANGE_LIMIT:
        discarded = result['ranges'].pop(0)
        result['baseline'] = {key: discarded[key] for key in ('blockNumber', 'blockHash')}
        result['eventsTruncated'] = True
    remaining = EVENT_LIMIT
    for entry in reversed(result['ranges']):
        keep = min(remaining, len(entry['events']))
        if keep < len(entry['events']):
            result['eventsTruncated'] = True
        entry['events'] = entry['events'][-keep:] if keep else []
        remaining -= keep
    return result


def public_activity(chain, bundles):
    events, pools = [], []
    for bundle in bundles:
        ranges, point = bundle['ranges'], checkpoint(bundle)
        pool_events = [event for entry in ranges for event in entry['events']]
        events.extend(pool_events)
        pools.append({'pool': bundle['pool'], 'journalStartBlock': str(int(bundle['baseline']['blockNumber'])+1),
                      'indexedThroughBlock': point['blockNumber'], 'indexedThroughBlockHash': point['blockHash'],
                      'hasMore': bundle['eventsTruncated'],
                      'rollups': [{key: value for key, value in entry.items() if key != 'events'} for entry in ranges]})
    events.sort(key=event_order, reverse=True)
    return {'enabled': True, 'chainId': chain, 'source': 'retained-uniswap-pool-events',
            'hasMore': len(events) > PUBLIC_EVENT_LIMIT or any(pool['hasMore'] for pool in pools),
            'events': events[:PUBLIC_EVENT_LIMIT], 'pools': pools,
            'retention': {'eventsPerPool': EVENT_LIMIT, 'rangesPerPool': RANGE_LIMIT, 'publicEvents': PUBLIC_EVENT_LIMIT}}


async def get_pool_activity(store, chain, filters=None):
    if store is None:
        return {'enabled': False, 'events': [], 'pools': []}
    filters = filters or {}
    bundles = (await store.load('activity', readonly=True)).values()
    def matches(bundle):
        pool = bundle['pool']
        return all(str(pool.get({'poolId': 'id', 'poolAddress': 'address'}.get(key, key), '')).lower() == value.lower()
                   for key, value in filters.items())
    return public_activity(chain, [bundle for bundle in bundles if matches(bundle)])


def activity_filters(query):
    result = {}
    for key in ('protocol', 'poolId', 'poolAddress', 'poolManager'):
        value = query.get(key)
        if value is None:
            continue
        valid = value in ('v2', 'v3', 'v4') if key == 'protocol' else bool(re.fullmatch(
            r'0x[0-9a-fA-F]{64}' if key == 'poolId' else r'0x[0-9a-fA-F]{40}', value))
        if not valid:
            raise ValueError('Invalid '+key+' filter.')
        result[key] = value
    return result
