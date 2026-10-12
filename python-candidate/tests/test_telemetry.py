import asyncio
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

import httpx

from cybergold_candidate.app import create_app
from cybergold_candidate.cache import MarketFeed
from cybergold_candidate.telemetry import Metrics,TelemetryMiddleware,configure_logging


def values(metric,suffix=''):
    if metric is None:return []
    return [{'value':sample.value,'labels':sample.labels}
        for family in metric.collect() for sample in family.samples if sample.name==metric._name+suffix]


async def revision_headers():
    async def product(scope,receive,send):
        await send({'type':'http.response.start','status':503,'headers':[
            (b'x-cybergold-backend-revision',b'not-observed-build-context')]})
        await send({'type':'http.response.body','body':b'ordinary product failure'})
    for release,expected in [(None,None),('fixture-release',None),('A'*40,'a'*40)]:
        app=TelemetryMiddleware(product,Metrics(),'api',release)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as api:
            response=await api.get('/api/transaction/wait/head')
        assert response.status_code==503 and response.text=='ordinary product failure'
        assert response.headers.get('X-CyberGold-Backend-Revision')==expected
        assert response.headers.get('X-CyberGold-Request-Id')


async def run(path):
    reference=json.loads(Path(path).read_text());stream=io.StringIO();logger=configure_logging(stream)
    await revision_headers()
    app=create_app(release='fixture-release')
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app,raise_app_exceptions=False),base_url='http://fixture') as api:
            await api.post('/api/rpc?private=fixture-secret',content='{')
            await api.get('/private-wallet-0xabc?bearer=fixture-secret')
            for _ in range(2):
                response=await api.get('/metrics')
                assert response.status_code==200 and response.headers['cache-control']=='no-store'
                assert not any(value in response.text for value in ['fixture-secret','private-wallet','bearer','requestId'])
            http_values=values(app.state.metrics.http_requests,'_total')
            assert http_values==reference['http']
            for path in ('/api/governance/authority', '/api/transaction/recovery-redemption',
                         '/api/transaction/permit2-approval-gas'):
                response=(await api.get(path+'?surface=invalid') if path.endswith('authority')
                          else await api.post(path,json={}))
                assert response.status_code==400
                assert any(row['labels']=={'operation':path,'method':response.request.method,'status':'400'}
                           for row in values(app.state.metrics.http_requests,'_total'))
            assert (await api.post('/api/internal/onchain-indexer/reconcile')).status_code==404
            response=await api.post('/api/diagnostics',json={'operation':'quote','outcome':'failed',
                'reason':'wallet_rejected','privateBearer':'fixture-private-value','parameters':{'secret':'fixture-private-value'}})
            assert response.status_code==202
            original=app.state.metrics.http_requests.labels
            app.state.metrics.http_requests.labels=lambda *_:(_ for _ in ()).throw(ValueError('collector unavailable'))
            logger.info=lambda *_:(_ for _ in ()).throw(ValueError('logging unavailable'))
            assert (await api.post('/api/rpc',content='{')).status_code==400
            assert (await api.post('/api/diagnostics',json={'operation':'wallet','outcome':'requested'})).status_code==202
            app.state.metrics.http_requests.labels=original
    records=[json.loads(line) for line in stream.getvalue().splitlines()]
    assert 'fixture-private-value' not in stream.getvalue() and 'fixture-secret' not in stream.getvalue()
    diagnostic=next(row for row in records if row.get('event')=='client_diagnostic')
    completed=next(row for row in records if row.get('operation')=='/api/diagnostics' and row.get('msg')=='request completed')
    assert diagnostic['requestId']==completed['requestId'] and diagnostic['release']=='fixture-release'
    assert all(row.get('component')=='api' for row in records if row.get('msg')=='request completed')
    logger.handlers=[];logger.info=type(logger).info.__get__(logger)
    metrics=Metrics();clock=[0];count=0
    async def resolve(previous):
        nonlocal count
        count+=1;await asyncio.sleep(.002)
        return {'payload':{'fetchedAt':previous['fetchedAt'] if previous else '2026-09-28T00:00:00.000Z','stale':count>1},'isFresh':count==1}
    feed=MarketFeed(resolve,.02,timer=lambda:clock[0],metrics=metrics,feed='gold')
    await asyncio.gather(*(feed.get() for _ in range(20)));await feed.get();clock[0]=1
    await feed.get();await feed.get();await feed.close()
    unknown=values(metrics.indexer_lag)
    with patch('cybergold_candidate.telemetry.time.time',return_value=1790762400):
        for status,progress in [('busy',None),('incomplete',{'networkFinalizedBlock':'150','indexedThroughBlock':'100'}),
                                ('deferred-cadence',None),('reconciled',None)]:
            metrics.indexer({'status':status,'dashboardHistoryProgress':progress})
    actual={'http':http_values,'cache':values(metrics.cache_requests,'_total'),
        'refresh':values(metrics.market_refreshes,'_total'),'fresh':values(metrics.market_last_fresh),'unknown':unknown,
        'lag':values(metrics.indexer_lag),'observed':values(metrics.indexer_observed),'reconciled':values(metrics.indexer_reconciled)}
    assert actual==reference,(actual,reference)
    print('PASS: actual Node/Python process HTTP/cache/indexer metrics; unknown progress absent; memory-only scrapes; JSON correlation/redaction and telemetry failure isolation')


asyncio.run(run(sys.argv[1]))
