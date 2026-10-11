"""Retained projected log insertion and conditional holder updates."""
import json
import math

from .holder_projection import HolderProjection, transfer_args


def postgres_timestamp(milliseconds):
    # Node pg serializes a JS Date, including extended Gregorian years. Keep
    # the already-normalized block timestamp lossless without datetime's year cap.
    value = math.trunc(milliseconds)
    seconds, fraction = divmod(value, 1000)
    days, day_seconds = divmod(seconds, 86400)
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + (3 if mp < 10 else -9)
    year += month <= 2
    hour, remainder = divmod(day_seconds, 3600)
    minute, second = divmod(remainder, 60)
    return (f'{year if year > 0 else 1-year:04}-{month:02}-{day:02} '
        f'{hour:02}:{minute:02}:{second:02}.{fraction:03}+00:00' + (' BC' if year <= 0 else ''))


class EventProjection:
    def __init__(self, database, config):
        self.database, self.config = database, config
        self.holder = HolderProjection(database, config)

    async def persist(self, logs, update_holders=False):
        for entry in logs:
            # Payload arguments use the qualified ABI decoder's existing wire
            # representation (wide ABI integers are decimal strings).
            async with self.database.connection() as connection:
                cursor = await connection.execute('''INSERT INTO onchain_event_logs
                    (chain_id,contract_address,event_name,block_number,block_hash,tx_hash,log_index,block_timestamp,payload)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(chain_id,tx_hash,log_index) DO NOTHING''',
                    (self.holder.chain, entry['contractAddress'].lower(), entry['eventName'], str(entry['blockNumber']),
                        entry['blockHash'], entry['txHash'].lower(), entry['logIndex'],
                        postgres_timestamp(entry['blockTimestampMs']), json.dumps(entry['payload'], separators=(',', ':'))))
                inserted = cursor.rowcount
                # The connection commits the event and its holder effects together.
                # A failed transfer must not leave an inserted deduplication key.
                if update_holders and inserted > 0 and entry['eventName'] == 'Transfer':
                    transfer = transfer_args(entry['payload'])
                    if transfer is not None:
                        await self.holder.apply_transfer(transfer, {'blockNumber': entry['blockNumber'],
                            'txHash': entry['txHash'], 'logIndex': entry['logIndex']}, connection)

    async def delete_from(self, from_block, additional_addresses=()):
        config = self.config
        addresses = [self.holder.core, *([config['governanceAddress'].lower()] if config.get('governanceAddress') else []),
            *[address.lower() for address in additional_addresses]]
        await self.holder.execute('''DELETE FROM onchain_event_logs
            WHERE chain_id=%s AND contract_address=ANY(%s::text[]) AND block_number>=%s''',
            (self.holder.chain, addresses, str(from_block)))
