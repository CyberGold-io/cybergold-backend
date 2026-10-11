"""Retained control routes; the complete durable worker engine remains pending."""
import json
import logging
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .aliases import JS_WHITESPACE
from .rpc_http import parse_json
from .telemetry import Metrics, TelemetryMiddleware, observe
from .worker_contract import authorize_worker,parse_reconcile,reconcile_response,parse_fork_request

NO_STORE={'Cache-Control':'no-store'}


def diagnostic(error):
    def safe(message):
        return (0<len(message.encode('utf-16-le',errors='surrogatepass'))//2<=240
            and not re.search(r'[\r\n]|[a-z][a-z0-9+.-]*://|\b(?:bearer|authorization|password|passwd|secret|credential|api[ _-]?key|database[ _-]?url|rpc[ _-]?url)\b|\b[A-Za-z0-9_-]{25,}\b',message,re.I))
    if not isinstance(error,Exception):return 'unexpected-worker-error'
    for value in [str(error),getattr(error,'shortMessage',None)]:
        if isinstance(value,str) and safe(value.strip(JS_WHITESPACE)):return value.strip(JS_WHITESPACE)
    return 'unexpected-worker-error'


def create_worker_app(controller,token,release=None):
    """Controller supplies retained engine operations, with no synthetic readiness."""
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    metrics=Metrics();app.state.metrics=metrics
    app.add_middleware(TelemetryMiddleware,metrics=metrics,component='worker',release=release)

    def response(body,status=200,headers=None):return JSONResponse(body,status_code=status,headers={**NO_STORE,**(headers or {})})
    def failure(request):
        decision=authorize_worker(request.headers.get('authorization'),token)
        if decision=='not-configured':return response({'error':'On-chain indexer worker is not configured'},503)
        if decision!='authorized':return response({'error':'Unauthorized'},401)
        return None
    def report(context,error):
        observe(lambda:logging.getLogger('cybergold.candidate').error(json.dumps({'msg':context,'diagnostic':diagnostic(error)})))

    @app.api_route('/metrics',methods=['GET','HEAD'])
    async def metrics_route():return Response(metrics.render(),headers={**NO_STORE,'Content-Type':'text/plain; version=0.0.4; charset=utf-8'})

    @app.api_route('/api/internal/onchain-indexer/reconcile',methods=['GET','HEAD','POST'])
    async def reconcile(request:Request):
        rejected=failure(request)
        if rejected is not None:return rejected
        if request.method in ('GET','HEAD'):
            try:
                receipt=await controller.last_receipt()
                if receipt is None:return response({'error':'Completed on-chain indexer reconciliation is unavailable'},503)
                return response(receipt)
            except Exception as error:
                report('On-chain indexer health check failed',error)
                return response({'error':'On-chain indexer health check failed'},503)
        requested=request.query_params.get('diagnostic')=='1';stage='request-parsing'
        def on_stage(value):
            nonlocal stage
            stage=value
        try:
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>4096:raise ValueError('Internal reconcile request is too large')
            parsed=parse_reconcile(raw,request.headers.get('content-type'),request.headers.get('content-length'))
            force=request.query_params.get('force')=='1' if parsed['legacy'] else parsed['mode']=='require-worker-run'
            result=await controller.run_once(force,on_stage if requested else None)
            metrics.indexer(result)
            # Product gauges refresh after a committed run, without delaying its response.
            if result['status']=='reconciled':observe(controller.refresh_product_metrics)
            envelope=reconcile_response(result,parsed['legacy'])
            return response(envelope['body'],envelope['httpStatus'],{'Retry-After':envelope['retryAfter']} if envelope['retryAfter'] else None)
        except Exception as error:
            observe(lambda:metrics.indexer_runs.labels('error').inc())
            report('On-chain indexer worker failed',error)
            return response({'error':'On-chain indexer worker failed',**({'diagnostic':diagnostic(error),'stage':stage} if requested else {})},503)

    @app.api_route('/api/internal/onchain-indexer/fork-generation',methods=['GET','HEAD','POST'])
    async def fork(request:Request):
        rejected=failure(request)
        if rejected is not None:return rejected
        if request.method in ('GET','HEAD'):
            try:return response({'kind':'cybergold-sandbox-fork-generation-status','formatVersion':1,'current':await controller.fork_status()})
            except Exception as error:
                report('Sandbox fork generation status failed',error)
                return response({'error':'Sandbox fork generation status failed'},503)
        try:
            if not request.headers.get('content-type','').lower().startswith('application/json'):
                raise ValueError('Sandbox fork request content type is invalid')
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>1024:raise ValueError('Sandbox fork request exceeds 1024 bytes')
            # Node Buffer.toString does not strip BOM for this existing route.
            parsed=parse_fork_request(parse_json(raw.decode('utf-8',errors='replace')))
        except Exception:return response({'error':'Invalid Sandbox fork generation request'},400)
        try:
            result=await controller.transition(parsed)
            if result['status']=='busy':return response({'status':'busy'},409,{'Retry-After':'1'})
            plan=result.get('plan')
            return response({'status':result['status'],**({'plan':{'kind':plan['kind'],
                'invalidateFrom':str(plan['invalidateFrom']),
                'retainedThrough':str(plan['retainedThrough']) if plan['retainedThrough'] is not None else None}} if result['status']=='applied' else {})})
        except Exception as error:
            report('Sandbox fork generation transition failed',error)
            return response({'error':'Sandbox fork generation transition failed'},503)

    return app
