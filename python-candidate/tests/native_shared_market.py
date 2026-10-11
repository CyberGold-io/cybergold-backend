"""Two real API processes, standard Valkey and owned synthetic suppliers."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

IMAGE = 'cybergold-shared-market-candidate:qualified'
VALKEY = 'valkey/valkey@sha256:48332870af354a799964c0012ae1194a0bf2bf894eb508f945810596dc2d8d11'
PREFIX = 'cybergold-market-fixture'
NETWORK = PREFIX + '-network'
CONTAINERS = []
PROVIDER = '''
import json,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    calls={'gold':0,'fx':0};fail=False;lock=threading.Lock()
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path.startswith('/control'):
            if 'fail=1' in self.path:Handler.fail=True
            if 'fail=0' in self.path:Handler.fail=False
            body={'calls':Handler.calls,'fail':Handler.fail}
        else:
            feed='gold' if 'gold' in self.path else 'fx'
            with self.lock:Handler.calls[feed]+=1
            time.sleep(.1)
            body=({'symbol':'PAXGUSDT','price':'3000'} if feed=='gold' else
                {'amount':1,'base':'USD','date':'2026-10-01','rates':{'EUR':.9,'CHF':.85,'RUB':90}})
        raw=json.dumps(body).encode();self.send_response(503 if Handler.fail and not self.path.startswith('/control') else 200)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
ThreadingHTTPServer(('0.0.0.0',5000),Handler).serve_forever()
'''
API = '''
import os,httpx
from cybergold_candidate.app import create_app
from cybergold_candidate.shared_market import SharedMarketCache
from cybergold_candidate.serve import run
class FixtureSupplier(httpx.AsyncClient):
    async def get(self,url,**kwargs):
        feed='gold' if 'PAXGUSDT' in url else 'fx'
        return await super().get('http://cybergold-market-fixture-provider:5000/'+feed,**kwargs)
cache_url=os.environ.get('CYBERGOLD_MARKET_CACHE_URL')
run(create_app(client=FixtureSupplier(),shared_market=SharedMarketCache(cache_url,31338) if cache_url else None),host='0.0.0.0',port=3000)
'''

def docker(*args):return subprocess.check_output(['docker',*args],text=True).strip()
def get(url):
    with urllib.request.urlopen(url,timeout=15) as response:return response.headers,json.load(response)
def start(name,*args):
    CONTAINERS.append(name)
    return docker('run','--detach','--name',name,'--network',NETWORK,*args)
def base(name,port):return 'http://127.0.0.1:'+docker('port',name,str(port)+'/tcp').rsplit(':',1)[1]
def wait(url):
    for _ in range(600):
        try:
            with urllib.request.urlopen(url,timeout=1):return
        except OSError:time.sleep(.1)
    raise RuntimeError('Fixture HTTP server did not start: '+url)

try:
    docker('network','create',NETWORK)
    with tempfile.TemporaryDirectory(prefix='cybergold-market-') as directory:
        for name,source in (('provider',PROVIDER),('api',API)):Path(directory,name+'.py').write_text(source)
        start(PREFIX+'-provider','--publish','127.0.0.1::5000','--mount','type=bind,src='+directory+'/provider.py,dst=/tmp/fixture.py,readonly',IMAGE,'python','/tmp/fixture.py')
        control=base(PREFIX+'-provider',5000)+'/control';wait(control)
        cache_name=PREFIX+'-cache'
        start(cache_name,'--platform','linux/amd64',VALKEY,'valkey-server','--protected-mode','no','--save','','--appendonly','no','--maxmemory','32mb','--maxmemory-policy','allkeys-lru')
        for _ in range(100):
            try:
                if docker('exec',cache_name,'valkey-cli','ping')=='PONG':break
            except subprocess.CalledProcessError:pass
            time.sleep(.1)
        observations={}
        def api(name,enabled):
            options=['--publish','127.0.0.1::3000','--mount','type=bind,src='+directory+'/api.py,dst=/tmp/fixture.py,readonly']
            if enabled:options+=['--env','CYBERGOLD_MARKET_CACHE_URL=valkey://'+cache_name+':6379/0']
            start(name,*options,IMAGE,'python','/tmp/fixture.py')
            url=base(name,3000);wait(url+'/metrics');return url
        before=get(control)[1]['calls'].copy()
        for suffix in ('baseline-a','baseline-b'):
            url=api(PREFIX+'-'+suffix,False)
            for feed in ('gold','fx'):get(url+'/api/'+feed)
        baseline={feed:get(control)[1]['calls'][feed]-before[feed] for feed in before}
        before=get(control)[1]['calls'].copy()
        a=api(PREFIX+'-a',True);b=api(PREFIX+'-b',True)
        for feed in ('gold','fx'):
            observations[feed]=get(a+'/api/'+feed)[1]
            assert get(b+'/api/'+feed)[1]==observations[feed]
            with concurrent.futures.ThreadPoolExecutor(20) as executor:
                assert all(row[1]==observations[feed] for row in executor.map(get,[b+'/api/'+feed]*20))
        warm={feed:get(control)[1]['calls'][feed]-before[feed] for feed in before}
        assert baseline=={'gold':2,'fx':2} and warm=={'gold':1,'fx':1},(baseline,warm)
        info=docker('exec',cache_name,'valkey-cli','info','memory')
        working=int(next(line.split(':')[1] for line in info.splitlines() if line.startswith('used_memory:')))
        keys=int(docker('exec',cache_name,'valkey-cli','dbsize'));assert keys==4
        # Exercise standard allkeys-LRU under a smaller disposable pressure bound.
        docker('exec',cache_name,'valkey-cli','config','set','maxmemory','2mb')
        for number in range(60):
            subprocess.run(['docker','exec','-i',cache_name,'valkey-cli','-x','set','pressure:'+str(number)],
                           input=b'x'*50000,capture_output=True,check=True)
        statistics=docker('exec',cache_name,'valkey-cli','info','stats')
        evicted=int(next(line.split(':')[1] for line in statistics.splitlines() if line.startswith('evicted_keys:')))
        assert evicted>0
        docker('exec',cache_name,'valkey-cli','config','set','maxmemory','32mb')
        # Reestablish the exact observed fresh/last records after pressure.
        # The API's local reuse itself survives shared eviction.
        for feed,ttl in (('gold',1800),('fx',300)):
            prefix='cybergold:market:v1:chain:31338:'+feed
            docker('exec',cache_name,'valkey-cli','set',prefix+':fresh',json.dumps({'payload':observations[feed],'expiresAt':time.time()+ttl}),'px',str(ttl*1000))
            docker('exec',cache_name,'valkey-cli','set',prefix+':last',json.dumps(observations[feed]))
        # Expiry of the shared acquisition forces a supplier refresh in a new
        # process. Last-known survives and cannot become a fresh fallback.
        docker('exec',cache_name,'valkey-cli','del','cybergold:market:v1:chain:31338:gold:fresh')
        get(control+'?fail=1');c=api(PREFIX+'-c',True)
        headers,retained=get(c+'/api/gold');assert retained==observations['gold']
        assert headers['Cache-Control']=='no-store'
        calls=get(control)[1]['calls']['gold'];get(c+'/api/gold');assert get(control)[1]['calls']['gold']==calls+1
        get(control+'?fail=0')
        # Eviction/drop and cache outage both retain normal provider operation,
        # local twenty-caller coalescing and one retained response timestamp.
        docker('exec',cache_name,'valkey-cli','flushdb');d=api(PREFIX+'-d',True)
        assert get(d+'/api/fx')[1]['stale'] is False
        docker('stop',cache_name)
        e=api(PREFIX+'-e',True);before=get(control)[1]['calls']['gold'];started=time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(20) as executor:results=list(executor.map(get,[e+'/api/gold']*20))
        elapsed=time.monotonic()-started
        assert get(control)[1]['calls']['gold']==before+1
        assert all(row[1]==results[0][1] for row in results) and not results[0][1]['stale']
        metrics=urllib.request.urlopen(e+'/metrics').read().decode();assert 'operation="read",result="error"' in metrics
        docker('stop','--time','15',PREFIX+'-e');exit_code=int(docker('inspect',PREFIX+'-e','--format','{{.State.ExitCode}}'));assert exit_code==0
        print(json.dumps({'result':'pass','testedImageId':docker('image','inspect',IMAGE,'--format','{{.Id}}'),'valkeyImage':VALKEY,
            'twoApiProcessBaselineSupplierCalls':baseline,'twoApiProcessWarmSupplierCalls':warm,'sharedWorkingSetKeys':keys,'valkeyUsedMemoryBytes':working,
            'twentyCallerOutageSupplierCalls':1,'outageBatchSeconds':round(elapsed,3),'unchangedOriginalTimestamp':True,
            'failedRefreshNotCachedAndNoStore':True,'expiryEvictionAndCacheOutage':True,'nativePressureEvictedKeys':evicted,'shutdownExitCode':exit_code,'deployedEndpointsUsed':False}))
finally:
    for name in reversed(CONTAINERS):subprocess.run(['docker','rm','-f',name],capture_output=True)
    subprocess.run(['docker','network','rm',NETWORK],capture_output=True)
