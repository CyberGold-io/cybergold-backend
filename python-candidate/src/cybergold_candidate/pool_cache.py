"""Retained quote-pool-cache controller and observation SQL; no authority change."""
import json
import logging
import math
from typing import Any
from typing import Literal
import uuid

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator, model_validator, ValidationError

from .raw_journal import matches, INTEGER
from .retained_reads import cached_pools
from .rpc_http import parse_json


class Pair(BaseModel):
    model_config=ConfigDict(strict=True,extra='ignore')
    tokenA:str
    tokenB:str

    @field_validator('tokenA','tokenB')
    @classmethod
    def address(cls,value):
        import re
        if not isinstance(value,str) or not re.fullmatch(r'0x[a-fA-F0-9]{40}',value):
            raise ValueError('Invalid address')
        return value


class LookupPair(Pair):
    protocol:Literal['v2','v3','v4']|None=None
    id:str|None=None
    poolId:str|None=None
    poolManager:str|None=None
    fee:int|None=None
    tickSpacing:int|None=None
    hooks:str|None=None


class Observation(Pair):
    chainId:int|float
    dex:str
    fee:int|float
    exists:bool
    poolAddress:str|None=None
    quoteSucceeded:Any=None
    activeLiquidityRaw:str|None=None
    sqrtPriceX96Raw:str|None=None
    tick:int|float|None=None
    token0BalanceRaw:str|None=None
    token1BalanceRaw:str|None=None
    protocol:Literal['v2','v3','v4']|None=None
    id:str|None=None
    poolId:str|None=None
    poolManager:str|None=None
    tickSpacing:int|None=None
    hooks:str|None=None
    poolKey:dict|None=None
    reserve0Raw:str|None=None
    reserve1Raw:str|None=None
    lpFee:int|None=None
    protocolFee:int|None=None
    marginalPrice:dict|None=None
    ticks:list[dict]|None=None
    bitmapWords:list[dict]|None=None

    @field_validator('chainId','fee','tick',mode='before')
    @classmethod
    def number(cls,value,info):
        if type(value) not in (int,float) or not math.isfinite(value):
            raise ValueError('Invalid number')
        if info.field_name != 'chainId' and int(value)!=value:
            raise ValueError('Invalid integer')
        return int(value) if int(value)==value else value

    @field_validator('dex')
    @classmethod
    def dex_value(cls,value):
        if value not in ('uniswap_v2','uniswap_v3','uniswap_v4'):raise ValueError('Invalid dex')
        return value

    @field_validator('poolAddress')
    @classmethod
    def optional_address(cls,value):
        return cls.address(value)

    @field_validator('activeLiquidityRaw','sqrtPriceX96Raw','token0BalanceRaw','token1BalanceRaw')
    @classmethod
    def uint(cls,value):
        if not matches(INTEGER,value):raise ValueError('Invalid uint string')
        return value

    @field_validator('quoteSucceeded')
    @classmethod
    def quote_success(cls,value):
        return value if type(value) is bool else None

    @model_validator(mode='before')
    @classmethod
    def complete_liquidity(cls,value):
        fields=('activeLiquidityRaw','sqrtPriceX96Raw','tick','token0BalanceRaw','token1BalanceRaw')
        if isinstance(value,dict) and value.get('dex','uniswap_v3') == 'uniswap_v3' and any(key in value for key in fields) and not all(key in value for key in fields):
            raise ValueError('Incomplete liquidity snapshot')
        return value


def normalize_observations(entries):
    unique={}
    for raw in entries:
        entry={**raw,'tokenA':raw['tokenA'].lower(),'tokenB':raw['tokenB'].lower()}
        if entry.get('poolAddress') is not None:
            entry['poolAddress']=entry['poolAddress'].lower()
        token0,token1=sorted((entry['tokenA'],entry['tokenB']))
        key=(entry['chainId'],entry['dex'],token0,token1,entry['fee'])
        current=unique.get(key)
        if current is not None:
            merged={**current,'exists':current['exists'] or entry['exists'],
                'quoteSucceeded':bool(current.get('quoteSucceeded') or entry.get('quoteSucceeded'))}
            for name in ('poolAddress','activeLiquidityRaw','sqrtPriceX96Raw','tick','token0BalanceRaw','token1BalanceRaw'):
                if entry.get(name) is not None:
                    merged[name]=entry[name]
            entry=merged
        unique[key]=entry
    return list(unique.values())


class PoolCache:
    def __init__(self,database):self.database=database

    async def list(self,chain_id,dex,pairs):
        # This route historically initializes the schema, unlike activity reads.
        await self.database.ensure_schema()
        return await cached_pools(self.database,chain_id,dex,pairs)

    async def record(self,entries):
        await self.database.ensure_schema()
        for entry in normalize_observations(entries):
            token0,token1=sorted((entry['tokenA'],entry['tokenB']))
            parameters=(entry['chainId'],entry['dex'],token0,token1,entry['fee'],entry.get('poolAddress'),
                entry['exists'],1 if entry.get('quoteSucceeded') else 0,entry.get('activeLiquidityRaw'),
                entry.get('sqrtPriceX96Raw'),entry.get('tick'),entry.get('token0BalanceRaw'),entry.get('token1BalanceRaw'))
            # Each existing observation commits independently. Do not change the
            # retained partial-success semantics during a language-only port.
            async with self.database.connection() as connection:
                await connection.execute('''INSERT INTO quote_pool_cache(chain_id,dex,token0,token1,fee,
                    pool_address,exists,success_count,active_liquidity_raw,sqrt_price_x96_raw,tick,
                    token0_balance_raw,token1_balance_raw,liquidity_checked_at,last_checked_at,last_success_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    CASE WHEN %s::text IS NOT NULL THEN NOW() ELSE NULL END,NOW(),
                    CASE WHEN %s>0 THEN NOW() ELSE NULL END)
                    ON CONFLICT(chain_id,dex,token0,token1,fee) DO UPDATE SET
                    pool_address=COALESCE(EXCLUDED.pool_address,quote_pool_cache.pool_address),
                    exists=quote_pool_cache.exists OR EXCLUDED.exists,
                    success_count=quote_pool_cache.success_count+EXCLUDED.success_count,
                    active_liquidity_raw=COALESCE(EXCLUDED.active_liquidity_raw,quote_pool_cache.active_liquidity_raw),
                    sqrt_price_x96_raw=COALESCE(EXCLUDED.sqrt_price_x96_raw,quote_pool_cache.sqrt_price_x96_raw),
                    tick=COALESCE(EXCLUDED.tick,quote_pool_cache.tick),
                    token0_balance_raw=COALESCE(EXCLUDED.token0_balance_raw,quote_pool_cache.token0_balance_raw),
                    token1_balance_raw=COALESCE(EXCLUDED.token1_balance_raw,quote_pool_cache.token1_balance_raw),
                    liquidity_checked_at=COALESCE(EXCLUDED.liquidity_checked_at,quote_pool_cache.liquidity_checked_at),
                    last_checked_at=NOW(),last_success_at=CASE WHEN EXCLUDED.success_count>0
                    THEN NOW() ELSE quote_pool_cache.last_success_at END,updated_at=NOW()''',
                    (*parameters,entry.get('activeLiquidityRaw'),parameters[7]))


async def handle_pool_cache(request,service):
    def error(message):return JSONResponse({'error':message},status_code=400)
    try:
        payload=parse_json((await request.body()).decode('utf-8-sig',errors='replace'))
    except (ValueError,UnicodeError):
        return error('Invalid JSON payload')
    if not isinstance(payload,(dict,list)):
        return error('Invalid quote-pool-cache payload')
    payload=payload if isinstance(payload,dict) else {}
    try:
        if payload.get('action')=='list-pools':
            chain=payload.get('chainId')
            pairs=payload.get('pairs')
            if type(chain) not in (int,float) or not math.isfinite(chain) or payload.get('dex') not in ('uniswap','uniswap_v2','uniswap_v3','uniswap_v4') or not isinstance(pairs,list):
                return error('Invalid pool-cache lookup payload')
            try:
                pairs=[LookupPair.model_validate(pair).model_dump(exclude_unset=True,exclude_none=True)
                       if payload['dex'] != 'uniswap_v3' or isinstance(pair,dict) and pair.get('protocol')
                       else Pair.model_validate(pair).model_dump() for pair in pairs]
            except ValidationError:
                return error('Invalid pool-cache lookup payload')
            entries=await service.list(chain,payload['dex'],pairs)
            return JSONResponse({'entries':entries},headers={'Cache-Control':'no-store'})
        if payload.get('action')=='record-observations':
            entries=payload.get('entries')
            if not isinstance(entries,list):return error('Invalid pool-cache observation payload')
            try:
                entries=[Observation.model_validate(entry).model_dump(exclude_none=True) for entry in entries]
                from .pool_producer import PoolIdentifier
                for entry in entries:
                    if entry['dex'] != 'uniswap_v3' or entry.get('protocol'):
                        PoolIdentifier.model_validate({**entry,'protocol':entry['dex'].removeprefix('uniswap_')})
            except ValidationError:
                return error('Invalid pool-cache observation payload')
            await service.record(entries)
            return JSONResponse({'ok':True})
        return error('Unknown quote-pool-cache action')
    except Exception:
        correlation=str(uuid.uuid4())
        logging.getLogger('cybergold.candidate').error(json.dumps({'correlationId':correlation,
            'context':'quote-pool-cache','errorClassification':'unexpected-error'}))
        return JSONResponse({'error':'Failed to process quote-pool-cache request.','correlationId':correlation},
                            status_code=500,headers={'Cache-Control':'no-store'})
