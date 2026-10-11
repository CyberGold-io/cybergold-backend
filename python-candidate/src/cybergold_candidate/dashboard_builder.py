"""Retained dashboard windows and authoritative indexed product reads."""
import asyncio
import json
from pathlib import Path

from .indexer_state_reads import StateReads, token_number
from .recovery_persistence import parse_integer

RANGES = {'24H': (24, 3600000), '7D': (28, 21600000), '1M': (30, 86400000)}
DEFINITIONS = json.loads(Path(__file__).with_name('indexer-event-definitions.json').read_text())


def empty_buckets(range_name, end_ms):
    count, step = RANGES[range_name]
    start = end_ms - count * step
    return {'range': range_name, 'stepMs': step, 'windowStartMs': start, 'buckets': [
        {'bucketStartMs': start + index * step, 'mintRaw': 0, 'redeemRaw': 0,
         'transferRaw': 0, 'transferCount': 0, 'supplyRaw': 0} for index in range(count)]}


def apply_rows(window, rows, field, end_ms):
    for row in rows:
        timestamp = row['block_timestamp_ms']
        if timestamp < window['windowStartMs'] or timestamp > end_ms:
            continue
        index = (timestamp - window['windowStartMs']) // window['stepMs']
        if index == len(window['buckets']) and timestamp == end_ms:
            index -= 1
        if index < 0 or index >= len(window['buckets']):
            continue
        bucket = window['buckets'][index]
        bucket[field] += parse_integer(row['amount_raw']) or 0
        if field == 'transferRaw':
            bucket['transferCount'] += 1


def materialize(window, supply, decimals):
    total_net = sum(bucket['mintRaw'] - bucket['redeemRaw'] for bucket in window['buckets'])
    running = supply - total_net
    result = []
    for bucket in window['buckets']:
        net = bucket['mintRaw'] - bucket['redeemRaw']
        running += net
        bucket['supplyRaw'] = running
        result.append({'bucketStartMs': bucket['bucketStartMs'], 'mintCygld': token_number(bucket['mintRaw'], decimals),
            'redeemCygld': token_number(bucket['redeemRaw'], decimals), 'netCygld': token_number(net, decimals),
            'supplyCygld': token_number(running, decimals), 'transferredCygld': token_number(bucket['transferRaw'], decimals),
            'transferTxCount': bucket['transferCount']})
    return {'buckets': result, 'netIssuanceRaw': total_net}


class DashboardReads:
    def __init__(self, config, client, store, *, state_reads=None):
        self.config, self.client, self.store = config, client, store
        self.state_reads = state_reads or StateReads(config, client, store)

    async def amount_logs(self, name, address, argument, start_ms, end_ms):
        # Callers select the retained fixed argument names; the field expression
        # is part of the SQL, as in the canonical Node reader.
        rows = await self.store.execute('''SELECT FLOOR(EXTRACT(EPOCH FROM block_timestamp)*1000) AS block_timestamp_ms,
            tx_hash,payload->'args'->>''' + "'" + argument + "'" + ''' AS amount_raw FROM onchain_event_logs
            WHERE chain_id=%s AND contract_address=%s AND event_name=%s
            AND block_timestamp>='epoch'::timestamptz + %s * INTERVAL '1 millisecond'
            AND block_timestamp<='epoch'::timestamptz + %s * INTERVAL '1 millisecond'
            ORDER BY block_timestamp ASC,log_index ASC LIMIT 100001''',
            (str(self.config['chainId']), address.lower(), name, start_ms, end_ms))
        if len(rows) > 100000:
            raise ValueError('Dashboard ' + ('transfer' if name == 'Transfer' else 'amount') + '-log cardinality exceeds the App read-model policy')
        return [{**row, 'block_timestamp_ms': int(row['block_timestamp_ms'])} for row in rows]

    async def latest(self, category):
        names = [definition['name'] for definition in DEFINITIONS['core'] if definition['category'] == category]
        rows = await self.store.execute('''SELECT FLOOR(EXTRACT(EPOCH FROM block_timestamp)*1000) AS timestamp_ms,tx_hash
            FROM onchain_event_logs WHERE chain_id=%s AND contract_address=%s AND event_name=ANY(%s::text[])
            ORDER BY block_number DESC,log_index DESC LIMIT 1''',
            (str(self.config['chainId']), self.config['coreAddress'].lower(), names))
        return {'timestampMs': int(rows[0]['timestamp_ms']), 'txHash': rows[0]['tx_hash']} if rows else None

    async def summary(self, block_number, recovery, target, *, expected_hash=None, force_pinned=False, terminal=None):
        block = await self.client.block(block_hash=expected_hash) if expected_hash else await self.client.block(block_number)
        if expected_hash and (block.get('hash') or '').lower() != expected_hash.lower():
            raise ValueError('Dashboard snapshot resolved a different finalized block hash')
        now = block['timestamp'] * 1000
        start = now - RANGES['1M'][0] * RANGES['1M'][1]
        metrics, basket, issued, redeemed, transferred, logic, parameter, holders = await asyncio.gather(
            self.state_reads.core_metrics(target), self.state_reads.basket(target, force_pinned=force_pinned, terminal=terminal),
            self.amount_logs('Issued', self.config['coreAddress'], 'grossCygldOut', start, now),
            self.amount_logs('Redeemed', self.config['coreAddress'], 'netCygldIn', start, now),
            self.amount_logs('Transfer', self.config['coreAddress'], 'value', start, now),
            self.latest('logic'), self.latest('parameter'), self.store.count())
        decimals = metrics['tokenDecimals'] or 18
        series = {}
        for name in RANGES:
            window = empty_buckets(name, now)
            for rows, field in [(issued, 'mintRaw'), (redeemed, 'redeemRaw'), (transferred, 'transferRaw')]:
                apply_rows(window, rows, field, now)
            series[name] = materialize(window, metrics['totalSupplyRaw'], decimals)['buckets']
        return {'enabled': True, 'protocolLogicUpdate': logic, 'protocolParameterUpdate': parameter,
            'chainHeadBlock': str(block_number), 'snapshotBlock': str(block_number), 'chainHeadTimestampMs': now,
            'lastScannedBlock': str(block_number), 'metrics': {
                'currentTotalSupplyCygld': token_number(metrics['totalSupplyRaw'], decimals),
                'netIssuance24hCygld': sum(bucket['netCygld'] for bucket in series['24H']),
                'holderCount': None if holders is None or holders > 2**53 - 1 else holders,
                'issuanceFeePercent': None if metrics['issuanceFeePpm'] is None else float(metrics['issuanceFeePpm']) / 10000,
                'redemptionFeePercent': None if metrics['redemptionFeePpm'] is None else float(metrics['redemptionFeePpm']) / 10000,
                'paused': metrics['paused']}, 'basket': basket, 'recovery': recovery, 'series': series}
