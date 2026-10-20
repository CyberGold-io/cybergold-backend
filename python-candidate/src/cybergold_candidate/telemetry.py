"""Standard logging and Prometheus client, preserving bounded process labels."""
import json
import logging
import os
import re
import time
import uuid

from prometheus_client import CollectorRegistry, Counter, Histogram, Gauge, generate_latest

PATHS={
    '/api/transaction/revert',
    '/api/account/ens-name', '/api/account/ens-avatar-record',
    '/api/account/native-balance',
    '/api/account/token-balance',
    '/api/account/liquidity-positions',
    '/api/governance/target-code',
    '/api/pools/snapshot',
    '/api/quotes/basket-preview',
    '/api/quotes/basket-max',
    '/api/quotes/token-preview',
    '/api/quotes/uniswap',
    '/api/quotes/routes', '/api/quotes/routes/stream',
    '/api/quotes/trade/stream', '/api/quotes/trade/model',
    '/api/quotes/intent/stream', '/api/quotes/market',
    '/api/quotes/market/stream', '/api/quotes/market/model',
    '/api/transaction/fees',
    '/api/account/transaction-nonce',
    '/api/transaction/receipt',
    '/api/transaction/wait/head',
    '/api/transaction/wait/transaction',
    '/api/transaction/wait/receipt',
    '/api/transaction/wait/block',
    '/api/governance/roles',
    '/api/governance/safe-nonce',
    '/api/governance/safe-transaction-hash',
    '/api/governance/safe-execution',
    '/api/governance/authority',
    '/api/transaction/recovery-redemption',
    '/api/transaction/permit2-approval-gas',
    '/api/transaction/helpers-execution',
    '/api/transaction/token-approval-gas',
    '/api/protocol/recovery-assets',
    '/api/protocol/recovery-share-precision',
    '/api/protocol/facts','/api/governance/core-facts','/api/governance/helpers-facts','/api/governance/safe-principal','/api/account/wallet-balances','/api/account/core-permit','/api/account/permit2','/api/activity/core','/api/activity/safe','/api/activity/helpers','/api/dashboard/onchain-summary',
    '/api/recovery/shares','/api/gold','/api/fx','/api/rpc','/api/governance/owner-aliases',
    '/api/quote-pool-cache','/api/safe','/api/safe/events','/api/faucet','/api/diagnostics',
    '/api/internal/onchain-indexer/reconcile','/api/internal/onchain-indexer/fork-generation',
}


def observe(action):
    try:action()
    except Exception:pass  # Existing telemetry isolation boundary.


class JsonFormatter(logging.Formatter):
    def format(self,record):
        message=record.getMessage()
        try:
            fields=json.loads(message)
            if not isinstance(fields,dict):fields={'msg':message}
        except ValueError:fields={'msg':message}
        return json.dumps({'level':record.levelname.lower(),'time':int(record.created*1000),
            'pid':os.getpid(),**fields},ensure_ascii=True,separators=(',',':'))


def configure_logging(stream=None):
    logger=logging.getLogger('cybergold.candidate')
    handler=logging.StreamHandler(stream);handler.setFormatter(JsonFormatter())
    logger.handlers=[handler];logger.setLevel(logging.INFO);logger.propagate=False
    return logger


class Metrics:
    def __init__(self):
        self.registry=CollectorRegistry()
        def counter(suffix,help,labels=()):
            return Counter('cybergold_backend_'+suffix,help,labels,registry=self.registry)
        def histogram(suffix,help,labels,buckets):
            return Histogram('cybergold_backend_'+suffix,help,labels,buckets=buckets,registry=self.registry)
        self.http_requests=counter('http_requests_total','Completed backend HTTP requests, excluding metrics scrapes.',('operation','method','status'))
        self.http_duration=histogram('http_duration_seconds','Backend response duration, excluding metrics scrapes.',
            ('operation','method'),[.01,.05,.1,.25,.5,1,2.5,5,10,30,120])
        self.quote_outcomes=counter('quote_outcomes_total',
            'Logical quote subscriptions by semantic outcome, independent of HTTP status.',('operation','mode','outcome'))
        self.quote_first_executable=histogram('quote_first_executable_seconds',
            'Time until first qualified executable quote per HTTP subscription; indicative frames excluded.',
            ('operation','mode'),[.01,.05,.1,.25,.5,1,2.5,5,10,30,120])
        self.quote_stages=counter('quote_stage_events_total',
            'Subscriber qualified/invalidation/provider/terminal quote observations.',('operation','strategy','stage'))
        self.quote_provider_outcomes=counter('quote_provider_outcomes_total',
            'Provider outcomes per HTTP subscription, including losing-provider failures.',('operation','strategy','outcome'))
        self.cache_requests=counter('market_cache_requests_total','Market cache requests: hit, miss (including expiry), or coalesced in-flight refresh.',('feed','result'))
        self.shared_market_requests=counter('market_shared_cache_requests_total',
            'Optional Valkey market reads/writes; hits preserve acquisition expiry.',('feed','operation','result'))
        self.market_refreshes=counter('market_refreshes_total','Supplier refresh resolutions: fresh, fallback, or thrown error; coalesced callers count once.',('feed','outcome'))
        self.market_duration=histogram('market_refresh_duration_seconds','Supplier refresh duration including response parsing and validation.',
            ('feed',),[.05,.1,.5,1,2.5,5,10,15])
        self.market_last_fresh=Gauge('cybergold_backend_market_last_fresh_timestamp_seconds',
            'Acquisition time of the last fresh market observation in this process; absent until fresh data.',('feed',),registry=self.registry)
        self.rpc_attempts=counter('rpc_http_attempts_total','RPC proxy wire attempts by HTTP status or transport_error; HTTP 200 does not imply JSON-RPC success.',('outcome',))
        self.rpc_duration=histogram('rpc_http_duration_seconds','RPC proxy wire time to response headers or transport failure, excluding pacing and body parsing.',(),[.01,.05,.1,.25,.5,1,2.5,5,10,30])
        self.indexer_runs=counter('indexer_runs_total','Authenticated reconcile outcomes (reconciled, incomplete, deferred-cadence, busy, error).',('outcome',))
        # Register unknown unlabelled gauges only after an actual observation.
        # Prometheus client's native default zero would invent initial progress.
        self.indexer_lag=None;self.indexer_observed=None;self.indexer_reconciled=None

    def _set(self,attribute,suffix,help,value):
        metric=getattr(self,attribute)
        if metric is None:
            metric=Gauge('cybergold_backend_'+suffix,help,registry=self.registry)
            setattr(self,attribute,metric)
        metric.set(value)

    def indexer(self,result):
        def record():
            self.indexer_runs.labels(result['status']).inc();now=time.time()
            if result['status']=='reconciled':self._set('indexer_reconciled','indexer_reconciled_timestamp_seconds',
                'Time of the last reconciled outcome in this process; absent until reconciled.',now)
            progress=result.get('dashboardHistoryProgress')
            if progress:
                self._set('indexer_lag','indexer_history_lag_blocks',
                    'Dashboard history lag relative to the finalized head observed by the last run with progress.',
                    int(progress['networkFinalizedBlock'])-int(progress['indexedThroughBlock']))
                self._set('indexer_observed','indexer_progress_timestamp_seconds',
                    'Time the worker last observed dashboard history progress; absent until observed.',now)
        observe(record)

    def render(self):return generate_latest(self.registry)


class TelemetryMiddleware:
    def __init__(self,app,metrics,component,release=None):
        self.app,self.metrics,self.component,self.release=app,metrics,component,release
        # Optional observed build context. Unset/local release values do not
        # affect requests, and arbitrary environment text never becomes a header.
        self.backend_revision=(release.lower() if isinstance(release,str)
            and re.fullmatch(r'[0-9a-f]{40}',release,re.I) else None)

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['path']=='/metrics':return await self.app(scope,receive,send)
        operation=scope['path'] if scope['path'] in PATHS else 'unmatched'
        method=scope['method'] if scope['method'] in ('GET','HEAD','POST','OPTIONS') else 'other'
        request_id=str(uuid.uuid4());scope.setdefault('state',{})['request_id']=request_id
        attempt_id=next((value.decode('latin1') for key,value in scope.get('headers',[])
                         if key.lower()==b'x-cybergold-attempt-id'),None)
        if attempt_id and re.fullmatch(r'[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}',attempt_id,re.I):
            scope['state']['attempt_id']=attempt_id
        else:attempt_id=None
        started=time.monotonic();status=None
        async def forward(message):
            nonlocal status
            if message['type']=='http.response.start':
                status=message['status']
                message={**message,'headers':[(key,value) for key,value in message.get('headers',[])
                    if key.lower() not in (b'x-cybergold-request-id',b'x-cybergold-backend-revision')]
                    +[(b'x-cybergold-request-id',request_id.encode())]}
                if self.backend_revision:
                    message['headers'].append((b'x-cybergold-backend-revision',self.backend_revision.encode()))
            await send(message)
        try:await self.app(scope,receive,forward)
        except Exception:
            status=500
            observe(lambda:logging.getLogger('cybergold.candidate').error(json.dumps({
                'msg':'unhandled route failure','operation':operation,'requestId':request_id,'component':self.component})))
            raise
        finally:
            if status is not None:
                route_path=getattr(scope.get('route'),'path',None)
                operation=route_path if route_path in PATHS else 'unmatched'
                elapsed=time.monotonic()-started
                observe(lambda:self.metrics.http_requests.labels(operation,method,str(status)).inc())
                observe(lambda:self.metrics.http_duration.labels(operation,method).observe(elapsed))
                record={'msg':'request completed','operation':operation,'method':method,'statusCode':status,
                    'durationMs':elapsed*1000,'requestId':request_id,'component':self.component}
                if self.release is not None:record['release']=self.release
                if attempt_id:record['attemptId']=attempt_id
                observe(lambda:logging.getLogger('cybergold.candidate').info(json.dumps(record)))
