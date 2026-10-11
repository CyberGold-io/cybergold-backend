"""Retained recovery HTTP pagination and lazy private RPC ownership."""
import math
import os
import re
import time

from aiohttp import ClientResponseError
from fastapi.responses import JSONResponse
from web3 import Web3

from .recovery_reader import RecoveryPortfolioReader, SCHEMA
from .recovery_rpc import RecoveryApiError, RecoveryRpc
from .alias_dates import date_milliseconds

EMPTY={'enabled':False,'status':'not-configured','schemaVersion':SCHEMA,'chainId':'','collection':None,
    'snapshotBlock':None,'snapshotBlockHash':None,'complete':False,'nextOffset':None,'totalAssets':'0',
    'corePaused':None,'fund':None,'balances':[],'pools':[]}


class RecoveryLoader:
    def __init__(self,settings,environment=None):
        self.settings=settings;self.environment=environment if environment is not None else os.environ
        self.rpc=None;self.load=None

    async def get(self,holder,offset=0,block_hash=None):
        mode=self.environment.get('RECOVERY_PORTFOLIO_MODE')
        if mode=='not-configured' and self.environment.get('NODE_ENV')!='production':return EMPTY
        if mode and mode!='rpc':raise RecoveryApiError('Recovery portfolio profile is invalid')
        if self.load is None:
            self.rpc=RecoveryRpc(self.settings)
            self.load=RecoveryPortfolioReader(self.rpc)
        return await self.load.get(holder,offset,block_hash)

    async def close(self):
        if self.load:await self.load.close()
        if self.rpc:await self.rpc.close()


async def handle_recovery(request,load,now=time.time):
    def response(body,status=200,retry=None):
        headers={'Cache-Control':'no-store'}
        if retry:headers['Retry-After']=str(retry)
        return JSONResponse(body,status_code=status,headers=headers)
    # URLSearchParams.get selects the first occurrence, like the retained route.
    params={key:request.query_params.getlist(key)[0] for key in request.query_params}
    holder=params.get('holder')
    if not holder:return response({'error':'holder query parameter is required'},400)
    offset=params.get('offset','0');block_hash=params.get('blockHash')
    if (not re.fullmatch(r'(0|[1-9][0-9]{0,77})',offset) or int(offset)>=2**256
        or block_hash is not None and not re.fullmatch(r'0x[0-9a-fA-F]{64}',block_hash)
        or offset!='0' and block_hash is None):
        return response({'error':'Invalid recovery page; continuation requires its blockHash'},400)
    try:
        if not re.fullmatch(r'0x[a-fA-F0-9]{40}',holder):raise ValueError()
        holder=Web3.to_checksum_address(holder)
    except (ValueError,TypeError):return response({'error':'holder query parameter must be a valid address'},400)
    try:return response(await load.get(holder,int(offset),block_hash))
    except ClientResponseError as failure:
        if failure.status==429:
            raw=(failure.headers or {}).get('Retry-After');retry=30
            try:
                seconds=int(raw) if raw and re.fullmatch(r'[0-9]+',raw) else math.ceil((date_milliseconds(raw)-now()*1000)/1000) if raw else 30
                if 0<seconds<=2**53-1:retry=seconds
            except (ValueError,TypeError,OverflowError):pass
            return response({'error':'Recovery RPC capacity is temporarily unavailable'},429,retry)
        return response({'error':'Recovery-share RPC snapshot is unavailable'},503)
    except RecoveryApiError as failure:return response({'error':str(failure)},failure.status,failure.retry)
    except Exception:return response({'error':'Recovery-share RPC snapshot is unavailable'},503)
