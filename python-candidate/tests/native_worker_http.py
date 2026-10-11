"""Native worker control image fixture, with synthetic engine operations only."""
import json
import subprocess
import time
import urllib.request
import urllib.error

FIXTURE='''
import uvicorn
from cybergold_candidate.worker_http import create_worker_app
from cybergold_candidate.telemetry import configure_logging
configure_logging()
class Controller:
    async def last_receipt(self):return {'fixture':'receipt'}
    async def run_once(self,force,on_stage):return {'status':'busy','dashboardHistoryProgress':None}
    def refresh_product_metrics(self):pass
    async def fork_status(self):return None
    async def transition(self,input):return {'status':'prepared'}
uvicorn.run(create_worker_app(Controller(),'a'*32,'fixture-release'),host='0.0.0.0',port=3000,access_log=False)
'''
container='cybergold-python-worker-control-fixture'
try:
    subprocess.run(['docker','run','--detach','--name',container,'--publish','127.0.0.1::3000',
        'cybergold-python-candidate:market-parity','python','-c',FIXTURE],check=True,capture_output=True)
    port=subprocess.check_output(['docker','port',container,'3000/tcp'],text=True).strip().rsplit(':',1)[1]
    root='http://127.0.0.1:'+port
    for attempt in range(50):
        try:
            with urllib.request.urlopen(root+'/metrics',timeout=1):break
        except OSError:
            if attempt==49:raise
            time.sleep(.2)
    def call(method,path,body=None,auth=None):
        request=urllib.request.Request(root+path,method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json',**({'Authorization':auth} if auth else {})})
        try:response=urllib.request.urlopen(request,timeout=2)
        except urllib.error.HTTPError as error:response=error
        with response:return response.status,json.load(response),response.headers
    path='/api/internal/onchain-indexer/reconcile'
    assert call('GET',path)[0]==401
    assert call('GET',path,auth='Bearer '+'a'*32)[:2]==(200,{'fixture':'receipt'})
    status,body,headers=call('POST',path,{'kind':'cybergold-b2b-reconcile-request','formatVersion':1,'mode':'require-worker-run'},'Bearer '+'a'*32)
    assert status==409 and body['status']=='busy' and headers['Retry-After']=='1'
    assert headers['Cache-Control']=='no-store'
    assert call('GET','/api/internal/onchain-indexer/fork-generation',auth='Bearer '+'a'*32)[1]['current'] is None
    with urllib.request.urlopen(root+'/metrics') as response:
        metrics=response.read().decode()
        assert 'cybergold_backend_indexer_runs_total{outcome="busy"} 1.0' in metrics
        assert 'cybergold_backend_indexer_history_lag_blocks' not in metrics
        assert 'Bearer' not in metrics
    subprocess.run(['docker','stop','--time','15',container],check=True,capture_output=True)
    code=int(subprocess.check_output(['docker','inspect',container,'--format','{{.State.ExitCode}}'],text=True))
    assert code==0
    print(json.dumps({'result':'pass','nativeWorkerControlRoutes':True,'workerBusyNotReady':True,
        'memoryOnlyMetricsAndUnknownProgress':True,'shutdownExitCode':code,
        'fullIndexerEngineQualified':False,'installedEndpointsOrDatabaseUsed':False}))
finally:subprocess.run(['docker','rm','-f',container],capture_output=True)
