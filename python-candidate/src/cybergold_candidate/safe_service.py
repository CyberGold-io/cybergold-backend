"""Retained Safe Transaction Service HTTP adapter; no transaction construction."""
import asyncio
import json
import logging
import math
import re
from urllib.parse import urlsplit
import uuid

from fastapi.responses import JSONResponse

from .aliases import JS_WHITESPACE
from .rpc_http import parse_json

ADDRESS = re.compile(r'0x[a-fA-F0-9]{40}')
HASH = re.compile(r'0x[a-fA-F0-9]{64}')


def json_text(value):
    def wire(item):
        if isinstance(item,float):
            return item if math.isfinite(item) else None
        if isinstance(item,list):return [wire(child) for child in item]
        if isinstance(item,dict):return {key:wire(child) for key,child in item.items()}
        return item
    text=json.dumps(wire(value),separators=(',',':'),ensure_ascii=False,allow_nan=False)
    return re.sub(r'[\ud800-\udfff]',lambda match:'\\u'+format(ord(match[0]),'04x'),text)


class SafeJsonResponse(JSONResponse):
    def render(self,content):return json_text(content).encode()


def truthy(value):
    return not (value is None or value is False or value == '' or type(value) in (int,float) and value == 0)


class SafeService:
    def __init__(self,client,url=None,timeout_seconds=15):
        self.client=client
        self.url=(url or '').strip(JS_WHITESPACE).rstrip('/')
        self.timeout_seconds=timeout_seconds

    async def fetch(self,path,method,payload=None):
        status,body,retry = 503,None,None
        if not self.url:
            return False,status,body,retry,'unexpected-error'
        try:
            async with asyncio.timeout(self.timeout_seconds):
                parsed=urlsplit(self.url)
                if parsed.username is not None or parsed.password is not None:
                    # Retained fetch rejects credentials embedded in the URL.
                    raise ValueError('URL credentials')
                request=self.client.build_request(method,self.url+path,timeout=None,
                    headers={'Content-Type':'application/json'},
                    content=json_text(payload).encode() if method=='POST' else None)
                response=await self.client.send(request,stream=True,follow_redirects=True)
                status=response.status_code
                try:
                    header=response.headers.get('retry-after')
                    if header is not None and re.fullmatch(r'[0-9]{1,4}',header) and 1 <= int(header) <= 3600:
                        retry=int(header)
                    try:
                        raw=(await response.aread()).decode('utf-8-sig',errors='replace')
                        # Safe proposal creation returns 201 with no response body.
                        # Successful writes need no JSON result; reads still do.
                        body={} if 200 <= status < 300 and method=='POST' and not raw.strip(JS_WHITESPACE) else parse_json(raw)
                    except Exception:
                        return False,502 if 200 <= status < 300 else status,None,retry,'unexpected-error'
                    if 200 <= status < 300 and not isinstance(body,(dict,list)):
                        return False,502,None,retry,'unexpected-error'
                    return 200 <= status < 300,status,body,retry,'unspecified'
                finally:
                    await response.aclose()
        except Exception:
            # Deadline during body consumption maps to the retained JSON-read
            # failure; failure before response headers maps to 503.
            return False,502 if 200 <= status < 300 else status,None,retry,'unexpected-error'


async def handle_safe_service(request,service):
    def error(message):return SafeJsonResponse({'error':message},status_code=400,headers={'Cache-Control':'no-store'})
    try:
        body=parse_json((await request.body()).decode('utf-8-sig',errors='replace'))
    except ValueError:
        return error('Invalid JSON payload.')
    # Retained null body raises outside the route error adapter.
    if body is None:
        raise TypeError('Null Safe request body')
    body=body if isinstance(body,dict) else {}
    action=body.get('action')
    if not truthy(action):return error('Missing action.')
    reads={
        'safe-info':('','Failed to fetch Safe info.','safe-info'),
        'pending-transactions':('multisig-transactions/?executed=false&limit=100',
            'Failed to fetch pending multisig transactions.','safe-pending-transactions'),
        'executed-transactions':('multisig-transactions/?executed=true&limit=25',
            'Failed to fetch executed multisig transactions.','safe-executed-transactions')}
    address=body.get('safeAddress')
    tx_hash=body.get('safeTxHash')
    payload=body.get('payload')
    if isinstance(action,str) and action in reads:
        if not isinstance(address,str) or not ADDRESS.fullmatch(address):return error('Invalid safeAddress.')
        suffix,message,context=reads[action]
        path,method=f'/api/v1/safes/{address}/'+suffix,'GET'
    elif action=='propose-transaction':
        if not isinstance(address,str) or not ADDRESS.fullmatch(address):return error('Invalid safeAddress.')
        if not isinstance(payload,(dict,list)):return error('Invalid payload.')
        path,method=f'/api/v1/safes/{address}/multisig-transactions/','POST'
        message,context='Failed to propose multisig transaction.','safe-propose-transaction'
    elif action in ('confirm-transaction','transaction-details'):
        if not isinstance(tx_hash,str) or not HASH.fullmatch(tx_hash):return error('Invalid safeTxHash.')
        if action=='confirm-transaction':
            if not isinstance(payload,(dict,list)):return error('Invalid payload.')
            path,method=f'/api/v1/multisig-transactions/{tx_hash}/confirmations/','POST'
            message,context='Failed to confirm multisig transaction.','safe-confirm-transaction'
        else:
            path,method=f'/api/v1/multisig-transactions/{tx_hash}/','GET'
            message,context='Failed to fetch multisig transaction details.','safe-transaction-details'
    else:
        return error('Unsupported action.')
    ok,status,body,retry,classification=await service.fetch(path,method,payload)
    if ok:
        return SafeJsonResponse(body,headers={'Cache-Control':'no-store'})
    correlation=str(uuid.uuid4())
    logging.getLogger('cybergold.candidate').error(json.dumps({'correlationId':correlation,'context':context,
        'errorClassification':classification}))
    headers={'Cache-Control':'no-store'}
    if retry is not None:headers['Retry-After']=str(retry)
    return SafeJsonResponse({'error':message,'correlationId':correlation},
        status_code=status if 400 <= status <= 599 else 500,headers=headers)
