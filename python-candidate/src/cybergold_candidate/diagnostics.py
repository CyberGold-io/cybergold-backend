"""Retained browser diagnostic projection through standard Python logging."""
import json
import logging
import re
import uuid

from fastapi.responses import JSONResponse

from .rpc_http import parse_json

ENUMS={'operation':['quote','swap','wallet'],
    'outcome':['started','succeeded','failed','submitted','reverted','unconfirmed','requested'],
    'reason':['wallet_rejected','rpc_error','contract_reverted','wrong_chain','unknown'],
    'direction':['issue','redeem'],'route':['basket','token'],'inputMode':['exact-in','exact-out'],
    'walletStep':['approval','signature','transaction']}


def project(input):
    source=input if isinstance(input,dict) else {}
    result={key:source[key] for key,values in ENUMS.items() if isinstance(source.get(key),str) and source[key] in values}
    for key in ['attemptId','quoteId']:
        value=source.get(key)
        if isinstance(value,str) and re.fullmatch(r'[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}',value,re.I):result[key]=value
    value=source.get('transactionHash')
    if isinstance(value,str) and re.fullmatch(r'0x[0-9a-f]{64}',value,re.I):result['transactionHash']=value
    for key in ['durationMs','chainId','assetCount']:
        value=source.get(key)
        if type(value) in (int,float) and 0<=value<=2**53-1 and value==int(value):result[key]=value
    value=source.get('errorCode')
    if type(value) in (int,float) and -(2**53-1)<=value<=2**53-1 and value==int(value):result['errorCode']=value
    value=source.get('errorSelector')
    if isinstance(value,str) and re.fullmatch(r'0x[0-9a-fA-F]{8}',value):result['errorSelector']=value.lower()
    return result


def reject_poison(keys):
    # Existing Fastify JSON parser semantics; no new authentication predicate.
    if any(key=='__proto__' or key=='constructor' and isinstance(value,dict) and 'prototype' in value
        for key,value in keys):raise ValueError('Unsafe JSON property')
    return dict(keys)


async def handle_diagnostics(request,logger=None,release=None):
    headers={'Cache-Control':'no-store'}
    def error(status):return JSONResponse({'error':'Diagnostic could not be read.'},status_code=status,headers=headers)
    content_type=request.headers.get('content-type','').split(';',1)[0].strip().lower()
    if content_type!='application/json':return error(415)
    try:
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>1048576:return error(413)
        declared=request.headers.get('content-length')
        if declared and int(declared)!=len(raw):return error(400)
        # Match JSON.parse numbers and Fastify's standard poison-property parser.
        text=raw.decode('utf-8-sig',errors='replace')
        json.loads(text,object_pairs_hook=reject_poison)
        body=parse_json(text)
    except Exception:return error(400)
    diagnostic=project(body)
    if diagnostic.get('operation') and diagnostic.get('outcome'):
        try:
            record={**diagnostic,'event':'client_diagnostic','source':'browser','component':'api',
                'requestId':request.scope.get('state',{}).get('request_id') or str(uuid.uuid4())}
            if release is not None:record['release']=release
            (logger or logging.getLogger('cybergold.candidate')).info(json.dumps(record))
        except Exception:pass  # Telemetry cannot change product behavior.
    return JSONResponse({'accepted':True},status_code=202,headers=headers)
