"""Retained Safe execution-status view and database rate/concurrency policy."""
import math
import time
import json
import logging
import uuid

from fastapi.responses import JSONResponse

from .raw_journal import HASH, matches, strict_address
from .retained_reads import date_wire
from .rpc_http import parse_json
from .safe_service import truthy


class SafeEventLimitError(Exception):
    def __init__(self,message,retry):
        super().__init__(message)
        self.retry=retry


class SafeEventInputError(ValueError):
    """Fixed public validation messages, distinct from supplier exceptions."""


class SafeStatus:
    def __init__(self,database,chain_id,addresses,now_ms=lambda:time.time()*1000):
        self.database,self.chain_id,self.addresses,self.now_ms=database,chain_id,addresses,now_ms

    async def consume_rate(self,scope,maximum):
        window=math.floor(self.now_ms()/60_000)
        async with self.database.connection() as connection:
            cursor=await connection.execute('''INSERT INTO onchain_api_rate_limits(scope,window_id,request_count)
                VALUES (%s,%s,1) ON CONFLICT(scope,window_id) DO UPDATE SET
                request_count=onchain_api_rate_limits.request_count+1,updated_at=NOW()
                WHERE onchain_api_rate_limits.request_count<%s RETURNING request_count''',(scope,window,maximum))
            if await cursor.fetchone() is None:
                raise SafeEventLimitError('Safe event request rate limit exceeded.',
                    max(1,math.ceil((60_000-self.now_ms()%60_000)/1000)))

    async def get(self,address,hashes):
        if not strict_address(address):raise SafeEventInputError('Invalid Safe address.')
        if len(hashes)>64:raise SafeEventInputError('At most 64 Safe transaction hashes may be queried at once.')
        # Preserve the retained malformed stringable-array failure, as well as
        # the ordinary canonical bytes32 and duplicate-hash behavior.
        if any(isinstance(value,list) and len(value)==1 and matches(HASH,value[0]) for value in hashes):
            raise SafeEventInputError('value.toLowerCase is not a function')
        normalized=list(dict.fromkeys(value.lower() for value in hashes if matches(HASH,value)))
        if len(normalized)!=len(hashes):
            raise SafeEventInputError('Every Safe transaction hash must be a canonical bytes32 value.')
        if not normalized:return []
        addresses=self.addresses() if callable(self.addresses) else self.addresses
        if address.lower() not in addresses:
            raise SafeEventInputError('Safe address is outside the configured event-indexer policy.')
        scope=f'safe-events:{self.chain_id}:{address.lower()}'
        await self.consume_rate(f'safe-events:{self.chain_id}:global',300)
        await self.consume_rate(scope,60)
        async with self.database.connection() as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                await connection.execute("SET LOCAL statement_timeout = '2000ms'")
                lock=await connection.execute('''SELECT candidate.slot FROM generate_series(0,7) AS candidate(slot)
                    WHERE pg_try_advisory_xact_lock(hashtext(%s),candidate.slot) LIMIT 1''',(scope+':concurrency',))
                if await lock.fetchone() is None:
                    raise SafeEventLimitError('Safe event indexer is busy.',1)
                cursor=await connection.execute('''SELECT event_name,tx_hash,block_number,block_timestamp,
                    payload->'args'->>'txHash' AS safe_tx_hash FROM onchain_event_logs
                    WHERE chain_id=%s AND contract_address=%s AND event_name=ANY(%s::text[])
                    AND payload->'args'->>'txHash'=ANY(%s::text[]) ORDER BY block_number DESC,log_index DESC''',
                    (str(self.chain_id),address.lower(),['ExecutionSuccess','ExecutionFailure'],normalized))
                rows=await cursor.fetchall()
        latest={}
        for row in rows:
            key=row['safe_tx_hash'].lower()
            if key not in latest:
                latest[key]={'safeTxHash':key,'status':'failed' if row['event_name']=='ExecutionFailure' else 'executed',
                    'transactionHash':row['tx_hash'],'blockNumber':str(row['block_number']),
                    'executionDate':date_wire(row['block_timestamp'])}
        return list(latest.values())


async def handle_safe_status(request,service):
    def error(message,status=400,retry=None):
        headers={'Cache-Control':'no-store'}
        if retry is not None:headers['Retry-After']=str(retry)
        return JSONResponse({'error':message},status_code=status,headers=headers)
    declared=request.headers.get('content-length','0')
    try:
        number=float(declared)
        if math.isfinite(number) and number>16_384:return error('Safe event request body is too large.',413)
    except ValueError:
        pass
    try:
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>16_384:return error('Safe event request body is too large.',413)
        body=parse_json(raw.decode('utf-8-sig',errors='replace'))
    except Exception:
        return error('Invalid JSON payload.')
    if body is None:raise TypeError('Null Safe events request body')
    body=body if isinstance(body,dict) else {}
    if not truthy(body.get('safeAddress')):return error('Missing safeAddress.')
    if not isinstance(body.get('safeTxHashes'),list):return error('Missing safeTxHashes.')
    try:
        result=await service.get(body['safeAddress'],body['safeTxHashes'])
        return JSONResponse({'results':result},headers={'Cache-Control':'no-store'})
    except SafeEventLimitError as failure:
        return error(str(failure),429,failure.retry)
    except SafeEventInputError as failure:
        return error(str(failure),500)
    except Exception:
        correlation=str(uuid.uuid4())
        logging.getLogger('cybergold.candidate').error(json.dumps({'correlationId':correlation,
            'context':'safe-events','errorClassification':'unexpected-error'}))
        return JSONResponse({'error':'Safe event observations are temporarily unavailable.','correlationId':correlation},
                            status_code=500,headers={'Cache-Control':'no-store'})
