"""Retained address-scoped ingestion/replay coordination over the raw journal."""
import asyncio

from .adaptive_logs import execute_ranges
from .indexer_policy import HASH
from .raw_journal import normalize_rpc_logs, read_coverage, read_logs, replay_coverage, replace_range, MAX_DATE_SECONDS


class RawJournal:
    def __init__(self, database, chain_id, address, version):
        self.database, self.chain_id, self.address, self.version = database, chain_id, address, version

    async def coverage(self):
        async with self.database.connection() as connection:
            return await read_coverage(connection, self.chain_id, self.address, self.version)

    async def replay(self, from_block, to_block, coverage):
        async with self.database.connection() as connection:
            return await read_logs(connection, self.chain_id, self.address, from_block, to_block, coverage)

    async def prepare_replay(self, enabled, required_start, maximum_block, read_header):
        if not enabled:
            return None
        coverage = await self.coverage()
        if coverage is None:
            return None
        if coverage['startBlock'] > required_start:
            raise ValueError('Raw journal coverage is non-authoritative until provider backfill reaches the configured recovery start')
        if coverage['cursorBlock'] > maximum_block:
            raise ValueError('Raw journal coverage is ahead of the finalized replay anchor')
        header = await read_header(coverage['cursorBlock'])
        return replay_coverage(coverage, required_start, maximum_block, header['hash'])

    async def ingest(self, authoritative_start, from_block, to_block, counter, source,
        request_logs, read_header, should_split=None, header_cache=None):
        cache = header_cache if header_cache is not None else {}

        def validate_header(header):
            if (not isinstance(header.get('hash'), str) or not HASH.fullmatch(header['hash'])
                or type(header.get('timestamp')) is not int or not 0 <= header['timestamp'] <= MAX_DATE_SECONDS):
                raise ValueError('Raw journal block header is invalid')
            return header

        async def header(number):
            if cache.get(number) is not None:
                return validate_header(cache[number])
            value = validate_header(await read_header(number))
            cache[number] = value
            return value

        counter.plan(source)
        async def request(input):
            counter.log_attempt(source, input['adaptive'])
            try:
                return await request_logs(input['range'])
            except (Exception, asyncio.CancelledError):
                counter.log_failure()
                raise

        async def validate(value, range):
            return await normalize_rpc_logs(value, self.address, range['fromBlock'], range['toBlock'], header)

        result = await execute_ranges({'fromBlock': from_block, 'toBlock': to_block}, request, validate, should_split)
        identities = set()
        logs = result['values']
        for log in logs:
            identity = (log['transactionHash'].lower(), log['logIndex'])
            if identity in identities:
                raise ValueError('Adaptive eth_getLogs ranges returned a duplicate raw log identity')
            identities.add(identity)
        logs.sort(key=lambda log: (log['blockNumber'], log['logIndex']))
        anchor = await header(to_block)
        await replace_range(self.database, chainId=self.chain_id, address=self.address,
            authoritativeStartBlock=authoritative_start, fromBlock=from_block, toBlock=to_block,
            toBlockHash=anchor['hash'], journalVersion=self.version, logs=logs)
        return logs
