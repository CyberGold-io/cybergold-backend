"""Independent finalized Helpers journal; does not mutate Core projections."""
from .completed_state import IDENTITY
from .indexer_policy import anchor_tag, deployment_start, finalized_anchor, projection_scan
from .raw_ingestion import RawJournal
from .raw_journal import COVERAGE_KEYS
from .worker_rpc import approved_range_reduction


class HelpersLogCounter:
    """Separate stream accounting; the retained Core receipt stays unchanged."""
    def __init__(self):
        self.counts = {'planned': 0, 'attempts': 0, 'adaptive': 0, 'failed': 0}

    def plan(self, _source):
        self.counts['planned'] += 1

    def log_attempt(self, _source, adaptive=False):
        self.counts['attempts'] += 1
        self.counts['adaptive'] += int(adaptive)

    def log_failure(self):
        self.counts['failed'] += 1


class HelpersCollector:
    def __init__(self, database, config, address, *, on_rewind=None):
        self.database, self.config, self.address = database, config, address
        self.journal = RawJournal(database, config['chainId'], address, IDENTITY['rawJournalVersion'])
        self.on_rewind = on_rewind

    async def rewind(self, start, first, header):
        """Invalidate only this stream's changed suffix, then resume bounded work."""
        retained = await header(start - 1) if start > first else None
        scope = (str(self.config['chainId']), self.address.lower())
        async with self.database.connection() as connection:
            async with connection.transaction():
                await connection.execute('''DELETE FROM onchain_raw_logs
                    WHERE chain_id=%s AND contract_address=%s AND block_number>=%s''',
                    (*scope, str(start)))
                if retained is None:
                    await connection.execute('''DELETE FROM onchain_sync_state
                        WHERE chain_id=%s AND contract_address=%s AND state_key=ANY(%s::text[])''',
                        (*scope, list(COVERAGE_KEYS)))
                else:
                    for key, value in ((COVERAGE_KEYS[2], str(start - 1)), (COVERAGE_KEYS[3], retained['hash'])):
                        await connection.execute('''UPDATE onchain_sync_state SET state_value=%s,updated_at=NOW()
                            WHERE chain_id=%s AND contract_address=%s AND state_key=%s''',
                            (value, *scope, key))

    async def reconcile(self, client, raw_client, *, anchor=None):
        config = self.config
        await self.database.ensure_schema()
        anchor = anchor or finalized_anchor(await client.block(anchor_tag(config['chainId'])))
        latest = anchor['blockNumber']
        first = deployment_start(config['chainId'], config['startBlock'], latest)
        headers = {}

        async def header(number):
            if number not in headers:
                block = await client.block(number)
                value = finalized_anchor(block)
                if value['blockNumber'] != number:
                    raise ValueError('Helpers journal header returned the wrong block number')
                headers[number] = {'hash': value['blockHash'], 'timestamp': block['timestamp']}
            return headers[number]

        coverage = await self.journal.coverage()
        # This address has no relation to Core's last_scanned_block. Its first
        # interval always starts at the configured collection boundary.
        cursor = coverage['cursorBlock'] if coverage else None
        canonical = (await header(cursor))['hash'] if cursor is not None and cursor <= latest else None
        plan = projection_scan(first, anchor,
            {'blockNumber': cursor, 'blockHash': coverage['cursorBlockHash'] if coverage else None},
            canonical, config['reorgWindow'], False)
        start, counter = plan['fromBlock'], HelpersLogCounter()
        if start is None:
            return {'completed': True, 'indexedThroughBlock': str(latest), 'counts': counter.counts}
        if coverage and plan['reason'] in ('hash-mismatch-overlap', 'cursor-ahead-overlap'):
            await self.rewind(start, first, header)
            if self.on_rewind:
                await self.on_rewind(start)
        end = min(start + config['maxBlocksPerRun'] - 1, latest)
        while start <= end:
            stop = min(start + config['chunkSize'] - 1, end)
            if stop == latest and (await header(stop))['hash'] != anchor['blockHash'].lower():
                raise ValueError('Helpers journal reached a different finalized anchor hash')

            async def request(value):
                return await raw_client.logs(self.address, value)

            await self.journal.ingest(first, start, stop, counter, 'helpers-address',
                request, header, approved_range_reduction, headers)
            start = stop + 1
        return {'completed': end == latest, 'indexedThroughBlock': str(end), 'counts': counter.counts}
