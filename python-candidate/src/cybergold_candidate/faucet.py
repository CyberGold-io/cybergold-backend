"""Existing loopback funding adapter. Backend ingress owns client bearer auth."""
import asyncio
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import signal
from time import perf_counter
import uuid

from fastapi.responses import JSONResponse
import httpx

from .raw_journal import strict_address
from .rpc_http import parse_json
from .telemetry import observe

REQUEST_ID=re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
SERVICE_URL=re.compile(r'^http://127\.0\.0\.1:([1-9][0-9]{0,4})/fund$')
DECIMAL=re.compile(r'^(0|[1-9][0-9]{0,77})$')
ERRORS={
    'DISABLED':('Fork faucet is disabled.',403),
    'INVALID_ADDRESS':('Invalid wallet address.',400),
    'INVALID_REQUEST_ID':('Invalid faucet request ID.',400),
    'INVALID_REQUESTER_IP':('Requester IP is unavailable.',400),
    'CONFIGURATION_ERROR':('Fork faucet is temporarily unavailable.',503),
    'REQUEST_REJECTED':('Fork faucet request was rejected.',400),
    'AUTHENTICATION_FAILED':('Fork faucet is temporarily unavailable.',502),
    'REQUEST_CONFLICT':('Fork faucet request conflicts with an existing request.',409),
    'REQUEST_IN_PROGRESS':('Fork faucet request is still being processed.',409),
    'REQUEST_UNCERTAIN':('Fork faucet funding could not be confirmed.',409),
    'RATE_LIMITED':('Fork faucet rate limit exceeded.',429),
    'ADDRESS_QUOTA_EXHAUSTED':('Test funds quota for this wallet is exhausted.',429),
    'IP_QUOTA_EXHAUSTED':('Test funds quota for this connection is exhausted.',429),
    'GLOBAL_QUOTA_EXHAUSTED':('Sandbox test funds quota is exhausted.',429),
    'TIMEOUT':('Fork faucet request timed out.',504),
    'BAD_GATEWAY':('Fork faucet is temporarily unavailable.',502),
    'UNAVAILABLE':('Fork faucet is temporarily unavailable.',503),
    'INVALID_RESPONSE':('Fork faucet is temporarily unavailable.',502),
    'EXECUTION_FAILED':('Fork faucet execution failed.',500),
    'FUNDING_FAILED':('Fork faucet funding failed.',502),
    'CHAIN_UNAVAILABLE':('Sandbox chain is temporarily unavailable.',503),
}
ADAPTER_CODES={400:['INVALID_JSON','INVALID_REQUEST','INVALID_ADDRESS','INVALID_REQUEST_ID','INVALID_REQUESTER_IP'],
    401:['UNAUTHORIZED'],404:['NOT_FOUND'],405:['METHOD_NOT_ALLOWED'],408:['REQUEST_TIMEOUT'],
    409:['REQUEST_ID_CONFLICT','REQUEST_IN_PROGRESS','REQUEST_UNCERTAIN'],411:['LENGTH_REQUIRED'],
    413:['REQUEST_TOO_LARGE'],415:['UNSUPPORTED_MEDIA_TYPE'],
    429:['ADDRESS_QUOTA_EXHAUSTED','IP_QUOTA_EXHAUSTED','GLOBAL_QUOTA_EXHAUSTED'],
    500:['INTERNAL_ERROR'],502:['FUNDING_FAILED'],503:['CHAIN_UNAVAILABLE']}


class FaucetError(Exception):
    def __init__(self,code,retry=None,replace=False,diagnostics=None):
        message,self.status=ERRORS[code]
        super().__init__(message)
        self.code=code
        self.retry,self.replace=retry,replace
        self.diagnostics=diagnostics


def normalize_ip(value):
    try:
        # Node isIP rejects zone IDs at URL normalization and ambiguous IPv4.
        if '%' in value:return None
        address=ipaddress.ip_address(value)
        if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            mapped=int(address.ipv4_mapped)
            return f'::ffff:{mapped>>16:x}:{mapped&65535:x}'
        return address.compressed.lower()
    except (ValueError,TypeError):return None


def exact(value,keys):return isinstance(value,dict) and set(value)==set(keys)
def uint(value):return isinstance(value,str) and DECIMAL.fullmatch(value) is not None and int(value)<2**256
def json_type(headers):return headers.get('content-type','').split(';',1)[0].strip().lower()=='application/json'


def success(value,address,live=True):
    if (not exact(value,['address','dryRun','ethWei','status','tokens']) or value['status']!='ok'
        or not strict_address(value['address']) or value['address'].lower()!=address.lower()
        or not uint(value['ethWei']) or not isinstance(value['tokens'],list)
        or len(value['tokens'])>16 or type(value['dryRun']) is not bool or live and value['dryRun'] is not False):return None
    seen=set()
    for token in value['tokens']:
        if (not exact(token,['amount','symbol']) or not isinstance(token['symbol'],str)
            or not re.fullmatch(r'[A-Za-z0-9]{1,16}',token['symbol']) or not uint(token['amount'])):return None
        name=token['symbol'].upper()
        if name in seen:return None
        seen.add(name)
    return value


class Faucet:
    def __init__(self,client,enabled=False,url=None,token=None,timeout_seconds=20,
                 script_path=None,faucet_home=None,foundry_bin=None,environment=None):
        self.client,self.enabled,self.url,self.token,self.timeout_seconds=client,enabled,url,token,timeout_seconds
        self.script_path,self.faucet_home,self.foundry_bin=script_path,faucet_home,foundry_bin
        self.environment=os.environ if environment is None else environment

    @property
    def adapter_mode(self):return self.url is not None or self.token is not None

    async def fund(self,address,request_id,requester_ip):
        if not self.enabled:raise FaucetError('DISABLED')
        if not strict_address(address):raise FaucetError('INVALID_ADDRESS')
        if not self.adapter_mode:
            return await self.legacy(address)
        match=SERVICE_URL.fullmatch(self.url or '')
        if not match or int(match[1])>65535 or not re.fullmatch(r'[0-9a-f]{64}',self.token or ''):
            raise FaucetError('CONFIGURATION_ERROR')
        if not request_id or not REQUEST_ID.fullmatch(request_id):raise FaucetError('INVALID_REQUEST_ID')
        if not requester_ip or normalize_ip(requester_ip)!=requester_ip:raise FaucetError('INVALID_REQUESTER_IP')
        started=perf_counter();upstream_status=None;upstream_code=None
        def diagnostics(failure_type):
            return {'stage':'faucet-adapter','elapsedMs':round((perf_counter()-started)*1000,3),
                'failureType':failure_type,
                **({'httpStatus':upstream_status} if upstream_status is not None else {}),
                **({'upstreamErrorCode':upstream_code} if upstream_code is not None else {})}
        try:
            async with asyncio.timeout(max(.001,min(self.timeout_seconds,20))):
                async with self.client.stream('POST',self.url,follow_redirects=False,timeout=None,
                    headers={'Accept':'application/json','Authorization':'Bearer '+self.token,'Content-Type':'application/json'},
                    content=json.dumps({'address':address,'requestId':request_id,'requesterIp':requester_ip})) as response:
                    upstream_status=response.status_code
                    # Fetch redirect:error rejects redirects before parsing them.
                    if response.status_code in (301,302,303,307,308):raise FaucetError('BAD_GATEWAY')
                    if not json_type(response.headers):raise FaucetError('INVALID_RESPONSE')
                    length=response.headers.get('content-length')
                    if length is not None and (not re.fullmatch(r'[0-9]+',length) or int(length)>65536):
                        raise FaucetError('INVALID_RESPONSE')
                    raw=bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw)>65536:raise FaucetError('INVALID_RESPONSE')
                    try:value=parse_json(raw.decode('utf-8-sig',errors='strict'))
                    except (ValueError,UnicodeError):raise FaucetError('INVALID_RESPONSE') from None
                    if response.status_code==200:
                        payload=success(value,address)
                        if payload is None:raise FaucetError('INVALID_RESPONSE')
                        return payload
                    if not exact(value,['error']) or not exact(value['error'],['code','message']):
                        raise FaucetError('INVALID_RESPONSE')
                    error=value['error']
                    if (error['code'] not in ADAPTER_CODES.get(response.status_code,[]) or not isinstance(error['message'],str)
                        or not 1<=len(error['message'].encode('utf-16-le',errors='surrogatepass'))//2<=512):
                        raise FaucetError('INVALID_RESPONSE')
                    upstream_code=error['code']
                    code={400:'REQUEST_REJECTED',401:'AUTHENTICATION_FAILED',408:'TIMEOUT',409:'REQUEST_CONFLICT',
                        429:'RATE_LIMITED',502:'BAD_GATEWAY',503:'UNAVAILABLE'}.get(response.status_code,'BAD_GATEWAY')
                    if upstream_code in ('REQUEST_IN_PROGRESS','REQUEST_UNCERTAIN','ADDRESS_QUOTA_EXHAUSTED',
                        'IP_QUOTA_EXHAUSTED','GLOBAL_QUOTA_EXHAUSTED','FUNDING_FAILED','CHAIN_UNAVAILABLE'):
                        code=upstream_code
                    raw_retry=response.headers.get('retry-after','')
                    retry=int(raw_retry) if re.fullmatch(r'[0-9]{1,4}',raw_retry) and 1<=int(raw_retry)<=3600 else None
                    raise FaucetError(code,retry if response.status_code==429 else None,
                        error['code'] in ('FUNDING_FAILED','REQUEST_ID_CONFLICT','REQUEST_UNCERTAIN'))
        except FaucetError as failure:
            failure.diagnostics=diagnostics('invalid-response' if failure.code=='INVALID_RESPONSE' else 'http-error')
            raise
        except httpx.TimeoutException:raise FaucetError('TIMEOUT',diagnostics=diagnostics('provider-timeout')) from None
        except TimeoutError:raise FaucetError('TIMEOUT',diagnostics=diagnostics('backend-deadline')) from None
        except Exception:raise FaucetError('BAD_GATEWAY',diagnostics=diagnostics('transport-error')) from None

    async def legacy(self,address):
        if self.environment.get('NODE_ENV')=='production':raise FaucetError('CONFIGURATION_ERROR')
        path=self.script_path or str((Path.cwd()/'../cybergold-ops/deploy/modules/fork/fund-wallet.sh').resolve())
        if not os.access(path,os.F_OK):raise FaucetError('CONFIGURATION_ERROR')
        child_home=self.faucet_home or self.environment.get('HOME') or str(Path.home())
        child_path=self.environment.get('PATH','/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
        environment={**self.environment,'HOME':child_home,
            'PATH':(self.foundry_bin or str(Path(child_home)/'.foundry/bin'))+':'+child_path}
        process=None;stdout=bytearray();overflow=False
        async def bounded(stream,output):
            nonlocal overflow
            while chunk:=await stream.read(65536):
                remaining=1048576-len(output)
                output.extend(chunk[:remaining])
                if len(chunk)>remaining:
                    overflow=True
                    if process.returncode is None:process.send_signal(signal.SIGTERM)
        try:
            process=await asyncio.create_subprocess_exec(path,address,'--json',env=environment,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            async with asyncio.timeout(self.timeout_seconds):
                await asyncio.gather(bounded(process.stdout,stdout),bounded(process.stderr,bytearray()),process.wait())
            if process.returncode!=0 or overflow:raise RuntimeError('Legacy faucet process failed')
            try:payload=success(parse_json(stdout.decode('utf-8',errors='replace').strip()),address,False)
            except ValueError:payload=None
            if payload is None:raise FaucetError('INVALID_RESPONSE')
            return payload
        except FaucetError:raise
        except TimeoutError:raise FaucetError('TIMEOUT') from None
        except Exception:
            try:payload=parse_json(stdout.decode('utf-8',errors='replace'))
            except ValueError:payload=None
            if (exact(payload,['address','reason','status']) or exact(payload,['reason','status'])) and payload['status']=='error' and isinstance(payload['reason'],str):
                reason=payload['reason'].lower()
                if any(value in reason for value in ('cooldown','limit','max calls')):raise FaucetError('RATE_LIMITED') from None
                if 'not allowed' in reason:raise FaucetError('REQUEST_REJECTED') from None
            raise FaucetError('EXECUTION_FAILED') from None
        finally:
            if process is not None and process.returncode is None:
                process.send_signal(signal.SIGTERM)
                await process.communicate()


async def handle_faucet(request,service):
    started=perf_counter()
    def error(message,status,retry=None,replace=False,code='INVALID_REQUEST',diagnostics=None):
        correlation=str(uuid.uuid4())
        context=diagnostics or {'stage':'faucet-request','elapsedMs':round((perf_counter()-started)*1000,3),
            'failureType':'unexpected-error' if code=='INTERNAL_ERROR' else 'request-error'}
        observe(lambda:logging.getLogger('cybergold.candidate').error(json.dumps({
            'context':'faucet','correlationId':correlation,'errorClassification':code,'diagnostics':context})))
        headers={'Cache-Control':'no-store'}
        if retry is not None:headers['Retry-After']=str(retry)
        if replace:headers['X-CyberGold-Faucet-Request-Id']='replace'
        return JSONResponse({'error':message,'code':code,'correlationId':correlation},status_code=status,headers=headers)
    if not service.enabled:return error('Fork faucet is disabled.',403,code='DISABLED')
    if not json_type(request.headers):return error('Content-Type must be application/json.',415,code='UNSUPPORTED_MEDIA_TYPE')
    length=request.headers.get('content-length')
    if length is not None:
        if not re.fullmatch(r'[0-9]+',length):return error('Invalid request body.',400)
        if int(length)>512:return error('Faucet request body is too large.',413,code='REQUEST_TOO_LARGE')
    raw=bytearray()
    try:
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>512:return error('Faucet request body is too large.',413,code='REQUEST_TOO_LARGE')
        body=parse_json(raw.decode('utf-8-sig',errors='strict'))
    except Exception:return error('Invalid request body.',400)
    keys=['address','requestId']
    if (not exact(body,keys) and (service.adapter_mode or not exact(body,['address']))
        or not isinstance(body.get('address') if isinstance(body,dict) else None,str)
        or 'requestId' in body and (not isinstance(body['requestId'],str) or not REQUEST_ID.fullmatch(body['requestId']))):
        return error('Invalid request body.',400)
    requester=None
    if service.adapter_mode:
        real=request.headers.get('x-real-ip');forwarded=request.headers.get('x-forwarded-for')
        if real is not None and forwarded is not None:
            requester=normalize_ip(real.strip())
            if requester!=normalize_ip(forwarded.split(',',1)[0].strip()):requester=None
        if not requester:return error('Requester IP is unavailable.',400,code='INVALID_REQUESTER_IP')
    try:
        result=await service.fund(body['address'],body.get('requestId'),requester)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
    except FaucetError as failure:
        return error(str(failure),failure.status,failure.retry,failure.replace,failure.code,failure.diagnostics)
    except Exception:return error('Fork faucet is temporarily unavailable.',500,code='INTERNAL_ERROR')
