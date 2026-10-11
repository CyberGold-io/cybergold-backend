"""Existing address-scoped journal validation/coverage and PostgreSQL replacement."""
import json
import re

from web3 import Web3

from .indexer_policy import HASH, MAX_BIGINT

DATA = re.compile(r'0x(?:[a-fA-F0-9]{2})*')
QUANTITY = re.compile(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)')
INTEGER = re.compile(r'(?:0|[1-9][0-9]*)')
MAX_INTEGER = 2_147_483_647
MAX_DATE_SECONDS = 8_640_000_000_000
COVERAGE_KEYS = ('raw_log_journal_version','raw_log_start_block',
                 'raw_log_last_scanned_block','raw_log_last_scanned_block_hash')


def matches(pattern,value):
    return isinstance(value,str) and pattern.fullmatch(value) is not None


def strict_address(value):
    return (isinstance(value,str) and re.fullmatch(r'0x[a-fA-F0-9]{40}',value) is not None and
            (value[2:] == value[2:].lower() or Web3.is_checksum_address(value)))


def rpc_log(value, expectedAddress, fromBlock, toBlock):
    if not isinstance(value,dict):
        raise ValueError('Address-scoped eth_getLogs returned a non-object entry')
    if not strict_address(value.get('address')) or value['address'].lower() != expectedAddress.lower():
        raise ValueError('Address-scoped eth_getLogs returned an unexpected address')
    if value.get('removed') is True:
        raise ValueError('Address-scoped eth_getLogs returned a removed log')
    if not matches(HASH,value.get('blockHash')) or not matches(HASH,value.get('transactionHash')):
        raise ValueError('Address-scoped eth_getLogs returned an incomplete log identity')
    if not matches(QUANTITY,value.get('blockNumber')) or not matches(QUANTITY,value.get('logIndex')):
        raise ValueError('Address-scoped eth_getLogs returned an invalid numeric identity')
    if not matches(DATA,value.get('data')):
        raise ValueError('Address-scoped eth_getLogs returned invalid data')
    topics = value.get('topics')
    if not isinstance(topics,list) or not all(matches(HASH,topic) for topic in topics):
        raise ValueError('Address-scoped eth_getLogs returned invalid topics')
    block, index = int(value['blockNumber'],16), int(value['logIndex'],16)
    if block > MAX_BIGINT or block < fromBlock or block > toBlock:
        raise ValueError('Address-scoped eth_getLogs returned an out-of-range log')
    if index > MAX_INTEGER:
        raise ValueError('Address-scoped eth_getLogs returned an invalid log index')
    return {'contractAddress':expectedAddress,'blockNumber':block,'blockHash':value['blockHash'].lower(),
            'transactionHash':value['transactionHash'].lower(),'logIndex':index,
            'topics':[topic.lower() for topic in topics],'data':value['data'].lower()}


async def normalize_rpc_logs(value, expectedAddress, fromBlock, toBlock, readBlockHeader):
    if not isinstance(value,list):
        raise ValueError('Address-scoped eth_getLogs returned a non-array result')
    if len(value) > 50_000:
        raise ValueError('Address-scoped eth_getLogs exceeded the raw log cardinality limit')
    parsed = [rpc_log(log,expectedAddress,fromBlock,toBlock) for log in value]
    headers, identities, normalized = {}, {}, []
    for log in parsed:
        block = log['blockNumber']
        if block not in headers:
            header = await readBlockHeader(block)
            if (not matches(HASH,header.get('hash')) or type(header.get('timestamp')) is not int or
                    not 0 <= header['timestamp'] <= MAX_DATE_SECONDS):
                raise ValueError('Address-scoped raw log block header is invalid')
            headers[block] = header
        header = headers[block]
        if header['hash'].lower() != log['blockHash'].lower():
            raise ValueError('Address-scoped eth_getLogs block hash does not match its header')
        identity = (log['transactionHash'],log['logIndex'])
        if identity in identities:
            if identities[identity] != log:
                raise ValueError('Address-scoped eth_getLogs returned conflicting duplicates')
            continue
        identities[identity] = log
        normalized.append({**log,'blockTimestampSeconds':header['timestamp']})
    return sorted(normalized,key=lambda log:(log['blockNumber'],log['logIndex']))


def canonical_integer(value,label,maximum=MAX_BIGINT):
    if not matches(INTEGER,value):
        raise ValueError(label+' is not a canonical integer')
    parsed = int(value)
    if parsed > maximum:
        raise ValueError(label+' exceeds its supported range')
    return parsed


def parse_coverage(address, expectedVersion, rows):
    if not rows:
        return None
    if len(rows) != 4:
        raise ValueError('Raw journal coverage state is incomplete')
    values = {}
    for row in rows:
        if row['state_key'] not in COVERAGE_KEYS or not isinstance(row['state_value'],str) or row['state_key'] in values:
            raise ValueError('Raw journal coverage state is ambiguous')
        values[row['state_key']] = row['state_value']
    if values[COVERAGE_KEYS[0]] != expectedVersion:
        raise ValueError('Raw journal coverage version does not match the replay profile')
    start = canonical_integer(values[COVERAGE_KEYS[1]],'Raw journal coverage start')
    cursor = canonical_integer(values[COVERAGE_KEYS[2]],'Raw journal coverage cursor')
    block_hash = values[COVERAGE_KEYS[3]]
    if not matches(HASH,block_hash):
        raise ValueError('Raw journal coverage cursor hash is invalid')
    if start > cursor:
        raise ValueError('Raw journal coverage interval is inverted')
    return {'address':address,'journalVersion':expectedVersion,'startBlock':start,
            'cursorBlock':cursor,'cursorBlockHash':block_hash.lower()}


def replay_coverage(coverage, requiredStartBlock, maximumBlock, canonicalCursorHash):
    if (requiredStartBlock < 0 or maximumBlock < requiredStartBlock or
            coverage['startBlock'] > requiredStartBlock or coverage['cursorBlock'] > maximumBlock):
        raise ValueError('Raw journal coverage does not match the replay profile')
    if coverage['cursorBlockHash'].lower() != canonicalCursorHash.lower():
        raise ValueError('Raw journal coverage cursor hash is not canonical')
    return coverage


def merge_coverage(current, address, journalVersion, authoritativeStartBlock, fromBlock, toBlock, toBlockHash):
    if current is None:
        if fromBlock != authoritativeStartBlock:
            raise ValueError('First raw journal interval must begin at its configured recovery start')
        return {'address':address,'journalVersion':journalVersion,'startBlock':fromBlock,
                'cursorBlock':toBlock,'cursorBlockHash':toBlockHash.lower()}
    if current['address'].lower() != address.lower() or current['journalVersion'] != journalVersion:
        raise ValueError('Raw journal coverage identity changed')
    prefix = current['startBlock'] > authoritativeStartBlock and fromBlock == authoritativeStartBlock and toBlock+1 == current['startBlock']
    if current['startBlock'] > authoritativeStartBlock and not prefix:
        raise ValueError('Raw journal coverage is non-authoritative; reset its coverage metadata before provider backfill')
    if fromBlock > current['cursorBlock']+1 or toBlock+1 < current['startBlock']:
        raise ValueError('Raw journal ingestion would create a coverage gap')
    return {'address':address,'journalVersion':journalVersion,'startBlock':min(fromBlock,current['startBlock']),
            'cursorBlock':max(toBlock,current['cursorBlock']),
            'cursorBlockHash':toBlockHash.lower() if toBlock >= current['cursorBlock'] else current['cursorBlockHash']}


def stored_logs(rows, address, fromBlock, toBlock, coverage):
    logs, previous = [], None
    for row in rows:
        topics = row['topics']
        if (row['contract_address'] != address.lower() or not matches(HASH,row['block_hash']) or
                not matches(HASH,row['tx_hash']) or not matches(DATA,row['data']) or
                not isinstance(topics,list) or len(topics)>4 or not all(matches(HASH,topic) for topic in topics)):
            raise ValueError('Stored raw journal log identity is invalid')
        block = canonical_integer(row['block_number'],'Stored raw journal block')
        index_value = str(row['log_index']) if type(row['log_index']) is int else row['log_index']
        index = canonical_integer(index_value,'Stored raw journal log index',MAX_INTEGER)
        seconds = canonical_integer(row['block_timestamp_seconds'],'Stored raw journal block timestamp',MAX_DATE_SECONDS)
        if block < fromBlock or block > toBlock:
            raise ValueError('Stored raw journal log is outside the replay range')
        if block == coverage['cursorBlock'] and row['block_hash'].lower() != coverage['cursorBlockHash'].lower():
            raise ValueError('Stored raw journal log contradicts its cursor hash')
        identity = (block,index,row['tx_hash'].lower())
        if previous is not None and identity <= previous:
            raise ValueError('Stored raw journal logs are not uniquely ordered')
        previous = identity
        logs.append({'contractAddress':address,'blockNumber':block,'blockHash':row['block_hash'].lower(),
                     'transactionHash':row['tx_hash'].lower(),'logIndex':index,
                     'topics':[topic.lower() for topic in topics],'data':row['data'].lower(),
                     'blockTimestampSeconds':seconds})
    return logs


async def read_coverage(connection, chainId, address, expectedVersion, for_update=False):
    cursor = await connection.execute('''SELECT state_key,state_value FROM onchain_sync_state
        WHERE chain_id=%s AND contract_address=%s AND state_key=ANY(%s::text[])'''+
        (' FOR UPDATE' if for_update else ''),(str(chainId),address.lower(),list(COVERAGE_KEYS)))
    return parse_coverage(address,expectedVersion,await cursor.fetchall())


async def read_logs(connection, chainId, address, fromBlock, toBlock, coverage):
    if (coverage['address'].lower() != address.lower() or fromBlock < coverage['startBlock'] or
            toBlock > coverage['cursorBlock'] or fromBlock > toBlock):
        raise ValueError('Raw journal replay range is outside authoritative coverage')
    cursor = await connection.execute('''SELECT contract_address,block_number::text,block_hash,tx_hash,
        log_index,topics,data,block_timestamp_seconds::text FROM onchain_raw_logs
        WHERE chain_id=%s AND contract_address=%s AND block_number BETWEEN %s AND %s
        ORDER BY block_number ASC,log_index ASC,tx_hash ASC LIMIT 50001''',
        (str(chainId),address.lower(),str(fromBlock),str(toBlock)))
    rows = await cursor.fetchall()
    if len(rows) > 50_000:
        raise ValueError('Raw journal replay exceeds its log cardinality limit')
    return stored_logs(rows,address,fromBlock,toBlock,coverage)


async def replace_range(database, chainId, address, authoritativeStartBlock, fromBlock, toBlock,
                        toBlockHash, journalVersion, logs):
    if authoritativeStartBlock < 0 or fromBlock < 0 or toBlock > MAX_BIGINT or fromBlock > toBlock:
        raise ValueError('Raw journal replacement range is inverted')
    if not matches(HASH,toBlockHash):
        raise ValueError('Raw journal replacement anchor hash is invalid')
    if any(log['contractAddress'].lower() != address.lower() or
           not fromBlock <= log['blockNumber'] <= toBlock for log in logs):
        raise ValueError('Raw journal replacement contains an out-of-scope log')
    async with database.connection() as connection:
        async with connection.transaction():
            current = await read_coverage(connection,chainId,address,journalVersion,True)
            coverage = merge_coverage(current,address,journalVersion,authoritativeStartBlock,fromBlock,toBlock,toBlockHash)
            async def state(key,value):
                await connection.execute('''INSERT INTO onchain_sync_state(chain_id,contract_address,state_key,state_value)
                    VALUES (%s,%s,%s,%s) ON CONFLICT(chain_id,contract_address,state_key)
                    DO UPDATE SET state_value=EXCLUDED.state_value,updated_at=NOW()''',
                    (str(chainId),address.lower(),key,str(value)))
            if current is None:
                await state(COVERAGE_KEYS[0],journalVersion)
            await connection.execute('''DELETE FROM onchain_raw_logs
                WHERE chain_id=%s AND contract_address=%s AND block_number BETWEEN %s AND %s''',
                (str(chainId),address.lower(),str(fromBlock),str(toBlock)))
            for offset in range(0,len(logs),500):
                batch = logs[offset:offset+500]
                values = []
                for log in batch:
                    values.extend((str(chainId),log['contractAddress'].lower(),str(log['blockNumber']),
                        log['blockHash'].lower(),log['transactionHash'].lower(),log['logIndex'],
                        json.dumps(log['topics']),log['data'].lower(),str(log['blockTimestampSeconds'])))
                await connection.execute('''INSERT INTO onchain_raw_logs(chain_id,contract_address,block_number,
                    block_hash,tx_hash,log_index,topics,data,block_timestamp_seconds) VALUES '''+
                    ','.join(['(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)']*len(batch))+'''
                    ON CONFLICT(chain_id,contract_address,tx_hash,log_index) DO UPDATE SET
                    block_number=EXCLUDED.block_number,block_hash=EXCLUDED.block_hash,topics=EXCLUDED.topics,
                    data=EXCLUDED.data,block_timestamp_seconds=EXCLUDED.block_timestamp_seconds,updated_at=NOW()
                    WHERE onchain_raw_logs.block_number IS DISTINCT FROM EXCLUDED.block_number
                    OR onchain_raw_logs.block_hash IS DISTINCT FROM EXCLUDED.block_hash
                    OR onchain_raw_logs.topics IS DISTINCT FROM EXCLUDED.topics
                    OR onchain_raw_logs.data IS DISTINCT FROM EXCLUDED.data
                    OR onchain_raw_logs.block_timestamp_seconds IS DISTINCT FROM EXCLUDED.block_timestamp_seconds''',values)
            await state(COVERAGE_KEYS[1],coverage['startBlock'])
            await state(COVERAGE_KEYS[2],coverage['cursorBlock'])
            await state(COVERAGE_KEYS[3],coverage['cursorBlockHash'].lower())
