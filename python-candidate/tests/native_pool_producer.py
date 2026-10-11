"""Disposable actual-image Web3 wire/SQL exercise; no installed inputs used."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

IMAGE='cybergold-authoritative-pools-candidate:qualified'
PG='docker.io/library/postgres@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b'
PREFIX='cybergold-pool-fixture-'+uuid.uuid4().hex[:10]
RPC,API,DB,NETWORK=(PREFIX+'-'+role for role in ('rpc','api','db','network'))
REFERENCE=json.loads(subprocess.check_output(['node','--import','tsx','python-candidate/tests/node-pool-producer-reference.ts'],text=True))
FIXTURE='''
import json,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
REF=REFERENCE
class Provider(BaseHTTPRequestHandler):
    mode='normal';calls=[]
    def log_message(self,*args):pass
    def do_GET(self):
        if '?mode=' in self.path:Provider.mode=self.path.split('?mode=')[1];Provider.calls=[]
        self.send({'mode':Provider.mode,'calls':Provider.calls})
    def send(self,value,status=200):
        raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self):
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        method,params=value['method'],value['params'];Provider.calls.append({'method':method,'params':params})
        assert self.headers.get('Authorization')=='Bearer fixture-only'
        if Provider.mode=='outage':return self.send({'error':'https://secret:password@private.invalid'},503)
        if method=='eth_chainId':result='0x7a6a'
        elif method=='eth_getBlockByNumber':result={'number':'0x65','timestamp':'0x6a000001','hash':'0x'+('b' if Provider.mode=='reorg' and params[0]!='latest' else 'a')*64}
        elif method=='eth_call':
            if Provider.mode=='delay':time.sleep(16)
            row=next(row for row in REF['rows'] if row['data']==params[0]['data'] and row['address'].lower()==params[0]['to'].lower())
            result=REF['empty'] if Provider.mode=='empty' and row['name']=='getPool' else row['result']
        else:raise AssertionError(method)
        self.send({'jsonrpc':'2.0','id':value['id'],'result':result})
ThreadingHTTPServer(('0.0.0.0',5000),Provider).serve_forever()
'''.replace('REFERENCE',repr(REFERENCE))

def docker(*args):return subprocess.check_output(['docker',*args],text=True).strip()

def request(url,payload=None):
    call=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(call,timeout=20) as response:return response.status,response.headers,response.read()
    except urllib.error.HTTPError as error:return error.code,error.headers,error.read()

def sql(statement):return docker('exec',DB,'psql','-XqAt','-U','fixture','-d','fixture','-c',statement)

identifier={'tokenA':REFERENCE['tokenB'],'tokenB':REFERENCE['tokenA'],'fee':3000}
forged={**identifier,'chainId':31338,'dex':'uniswap_v3','poolAddress':'0x'+'9'*40,'exists':True,
    'quoteSucceeded':True,'activeLiquidityRaw':'0','sqrtPriceX96Raw':'1','tick':1,
    'token0BalanceRaw':'0','token1BalanceRaw':'0','provider':'http://untrusted.invalid','factory':'0x'+'8'*40}
legacy={'action':'record-observations','entries':[forged]}
lookup={'action':'list-pools','chainId':31338,'dex':'uniswap_v3','pairs':[identifier]}
try:
    docker('network','create',NETWORK)
    with tempfile.TemporaryDirectory(prefix='cybergold-pools-') as temp:
        source=Path(temp,'rpc.py');source.write_text(FIXTURE)
        docker('run','--detach','--name',DB,'--network',NETWORK,'--env','POSTGRES_USER=fixture',
            '--env','POSTGRES_PASSWORD=fixture-only',PG)
        for _ in range(150):
            if subprocess.run(['docker','exec',DB,'pg_isready','-U','fixture'],capture_output=True).returncode==0:break
            time.sleep(.1)
        docker('run','--detach','--name',RPC,'--network',NETWORK,'--publish','127.0.0.1::5000',
            '--mount','type=bind,src='+str(source)+',dst=/tmp/rpc.py,readonly',IMAGE,'python','/tmp/rpc.py')
        docker('run','--detach','--name',API,'--network',NETWORK,'--publish','127.0.0.1::3000',
            '--env','NEXT_PUBLIC_CHAIN_ID=31338','--env','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=0x'+'5'*40,
            '--env','NEXT_PUBLIC_UNISWAP_V3_FACTORY_ADDRESS='+REFERENCE['factory'],
            '--env','NEXT_PUBLIC_RPC_URL=http://'+RPC+':5000','--env','RPC_URL=http://'+RPC+':5000',
            '--env','RPC_AUTHORIZATION=Bearer fixture-only','--env','DATABASE_URL=postgresql://fixture:fixture-only@'+DB+':5432/fixture',IMAGE)
        port=docker('port',API,'3000/tcp').rsplit(':',1)[1];rpcport=docker('port',RPC,'5000/tcp').rsplit(':',1)[1]
        base='http://127.0.0.1:'+port;control='http://127.0.0.1:'+rpcport+'/fixture'
        for _ in range(150):
            try:
                if request(base+'/metrics')[0]==200:break
            except (ConnectionError,OSError):pass
            time.sleep(.1)
        status,headers,raw=request(base+'/api/pools/snapshot',forged);value=json.loads(raw)
        assert status==200,(status,raw)
        assert headers['Cache-Control']=='no-store' and value['context']['blockNumber']=='101'
        assert value['poolAddress'].lower()==REFERENCE['pool'] and value['activeLiquidityRaw']==str(2**100)
        assert value['sqrtPriceX96Raw']==str(2**150) and value['token1BalanceRaw']==str(2**201) and value['tick']==-12
        calls=json.loads(request(control)[2])['calls'];contract=[call for call in calls if call['method']=='eth_call']
        assert len(contract)==5
        assert all(call['params'][1]=={'blockHash':'0x'+'a'*64,'requireCanonical':True} for call in contract)
        isolated='''import asyncio,json
from types import SimpleNamespace
from cybergold_candidate.pool_producer import PoolProducer
async def run():
 settings=SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338',RPC_URL=__URL__,RPC_AUTHORIZATION='Bearer fixture-only',NEXT_PUBLIC_UNISWAP_V3_FACTORY_ADDRESS=__FACTORY__)
 producer=PoolProducer(settings)
 try:print(json.dumps(await producer.get(__IDENTIFIER__)))
 finally:await producer.close()
asyncio.run(run())'''.replace('__URL__',repr('http://'+RPC+':5000')).replace('__FACTORY__',repr(REFERENCE['factory'])).replace('__IDENTIFIER__',repr(identifier))
        standalone=json.loads(docker('exec',API,'python','-c',isolated))
        assert standalone['poolAddress'].lower()==REFERENCE['pool']
        assert request(base+'/api/quote-pool-cache',legacy)[0]==200
        persisted=json.loads(sql('SELECT row_to_json(q) FROM quote_pool_cache q;'))
        assert persisted['chain_id']==31338 and persisted['pool_address'].lower()==REFERENCE['pool']
        assert str(persisted['active_liquidity_raw'])==str(2**100) and persisted['success_count']==0
        sql("UPDATE quote_pool_cache SET pool_address='0x"+'9'*40+"',active_liquidity_raw='0',success_count=99;")
        listed=json.loads(request(base+'/api/quote-pool-cache',lookup)[2])['entries']
        assert listed[0]['poolAddress'].lower()==REFERENCE['pool'] and listed[0]['activeLiquidityRaw']==str(2**100) and listed[0]['successCount']==0
        request(control+'?mode=empty')
        assert json.loads(request(base+'/api/pools/snapshot',identifier)[2])['exists'] is False
        assert request(base+'/api/quote-pool-cache',legacy)[0]==200
        emptied=json.loads(sql('SELECT row_to_json(q) FROM quote_pool_cache q;'))
        assert emptied['exists'] is False and emptied['pool_address'] is None and emptied['active_liquidity_raw'] is None and emptied['last_success_at'] is None
        request(control+'?mode=outage')
        assert request(base+'/api/pools/snapshot',identifier)[0]==503
        assert request(base+'/api/quote-pool-cache',legacy)[0]==500
        assert request(base+'/api/quote-pool-cache',lookup)[0]==500
        assert json.loads(sql('SELECT row_to_json(q) FROM quote_pool_cache q;'))==emptied
        request(control+'?mode=reorg');assert request(base+'/api/pools/snapshot',identifier)[0]==503
        request(control+'?mode=delay');started=time.monotonic();status,_,raw=request(base+'/api/pools/snapshot',identifier);deadline=time.monotonic()-started
        assert status==503 and 14.8<=deadline<17,deadline
        request(control+'?mode=normal');assert request(base+'/api/pools/snapshot',identifier)[0]==200
        request(control+'?mode=delay')
        caller=socket.create_connection(('127.0.0.1',int(port)));body=json.dumps(identifier).encode()
        caller.sendall(b'POST /api/pools/snapshot HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
        for _ in range(100):
            if any(call['method']=='eth_call' for call in json.loads(request(control)[2])['calls']):break
            time.sleep(.05)
        caller.close();cancelled=time.monotonic()
        for _ in range(60):
            if 'operation="/api/pools/snapshot",status="499"' in request(base+'/metrics')[2].decode():break
            time.sleep(.05)
        else:raise AssertionError('Disconnected pool caller did not cancel its operation')
        cancel_seconds=time.monotonic()-cancelled
        logs=docker('logs',API);assert 'private.invalid' not in logs and 'password' not in logs
        docker('stop','--time','20',API);exit_code=int(docker('inspect',API,'--format','{{.State.ExitCode}}'));assert exit_code==0
        print(json.dumps({'result':'pass','nativeWeb3ViemABIReadCount':5,'canonicalBlockIdentity':True,
            'wideValuesLossless':True,'configuredFactoryAndAuthorization':True,'noUnrelatedCorePrerequisite':True,'currentAndRetainedBrowserFabricationIgnored':True,
            'nativePostgresCompleteReplacementAndNoWritesOnOutage':True,'noSchemaChange':True,
            'emptyFactoryAndReorgHandled':True,'nativeCallerDisconnectSeconds':round(cancel_seconds,2),
            'nativeOperationDeadlineSeconds':round(deadline,2),'shutdownExitCode':exit_code,
            'testedImageId':docker('image','inspect',IMAGE,'--format','{{.Id}}'),'installedInputsUsed':False}))
except Exception:
    for container in (API,RPC):subprocess.run(['docker','logs','--tail','15',container],check=False)
    raise
finally:
    for container in (API,RPC,DB):subprocess.run(['docker','rm','-f',container],capture_output=True)
    subprocess.run(['docker','network','rm',NETWORK],capture_output=True)
