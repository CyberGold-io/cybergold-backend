"""Retained signed-alias controller; timestamp parsing stays with its authorizer."""
import json
import logging
import re
import uuid

from fastapi.responses import JSONResponse

from .aliases import JS_WHITESPACE,AliasAuthError
from .rpc_http import parse_json


def address(value):return value if isinstance(value,str) and re.fullmatch(r'0x[a-fA-F0-9]{40}',value) else None
def length(value):return len(value.encode('utf-16-le',errors='surrogatepass'))//2


def auth(value):
    if not isinstance(value,dict):return None
    row={key:value[key].strip(JS_WHITESPACE) if isinstance(value.get(key),str) else '' for key in ('nonce','issuedAt','signature')}
    if not 1<=length(row['nonce'])<=128 or not 1<=length(row['issuedAt'])<=64 or not re.fullmatch(r'0x([a-fA-F0-9]{128}|[a-fA-F0-9]{130})',row['signature']):return None
    return row


async def handle_aliases(request,service):
    def response(body,status=200):return JSONResponse(body,status_code=status,headers={'Cache-Control':'no-store'})
    def error(message,status=400):return response({'error':message},status)
    try:body=parse_json((await request.body()).decode('utf-8-sig',errors='replace'))
    except Exception:return error('Invalid JSON payload.')
    # The retained route accesses body.action before its handled-error boundary.
    if body is None:raise TypeError('Null alias request')
    action=body.get('action') if isinstance(body,dict) else None
    if action is None or action is False or action==0 or action=='':return error('Missing action.')
    try:
        editor=address(body.get('editorAddress'))
        if action=='list':
            owners=body.get('ownerAddresses')
            if not editor or not isinstance(owners,list) or any(address(value) is None for value in owners):return error('Invalid owner alias list payload.')
            return response({'entries':await service.list(editor,owners)})
        if action in ('upsert','delete'):
            owner=address(body.get('ownerAddress'));authorization=auth(body.get('auth'))
            alias=body['alias'].strip(JS_WHITESPACE) if isinstance(body.get('alias'),str) else None
            if not editor or not owner or authorization is None or action=='upsert' and (alias is None or not 1<=length(alias)<=64):
                return error('Invalid owner alias upsert payload (alias length must be 1-64).' if action=='upsert' else 'Invalid owner alias delete payload.')
            result=await service.mutate({'action':action,'editorAddress':editor,'ownerAddress':owner,
                'alias':alias if action=='upsert' else '',**authorization})
            if action=='upsert':return response({'entry':result})
            return response({'ok':True,'deleted':result})
        return error('Unsupported action.')
    except AliasAuthError as failure:return error(str(failure),401)
    except Exception:
        correlation=str(uuid.uuid4())
        logging.getLogger('cybergold.candidate').error(json.dumps({'correlationId':correlation,
            'context':'governance-owner-aliases','errorClassification':'unexpected-error'}))
        return response({'error':'Failed to process governance owner aliases request.','correlationId':correlation},500)
