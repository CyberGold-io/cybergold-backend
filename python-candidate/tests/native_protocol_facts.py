"""Assembled API/default role command against an owned synthetic HTTP provider."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

IMAGE='cybergold-protocol-facts-candidate:qualified'
RPC='cybergold-protocol-facts-rpc'
API='cybergold-protocol-facts-api'
NETWORK='cybergold-protocol-facts-fixture'
REFERENCE=json.loads(subprocess.check_output(['node','--import','tsx','python-candidate/tests/node-protocol-facts-reference.ts'],text=True))
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
            row=next(row for row in REF['rows'] if row['data']==params[0]['data'])
            if Provider.mode=='partial' and row['name'] in ('basketTargetsPpm','name'):
                return self.send({'jsonrpc':'2.0','id':value['id'],'error':{'code':-32000,'message':'https://secret:password@private.invalid'}})
            result=row['result']
        else:raise AssertionError(method)
        self.send({'jsonrpc':'2.0','id':value['id'],'result':result})
ThreadingHTTPServer(('0.0.0.0',5000),Provider).serve_forever()
'''.replace('REFERENCE',repr(REFERENCE))

def docker(*args):return subprocess.check_output(['docker',*args],text=True).strip()

def get(url):
    try:
        with urllib.request.urlopen(url,timeout=20) as response:return response.status,response.headers,response.read()
    except urllib.error.HTTPError as error:return error.code,error.headers,error.read()

try:
    docker('network','create',NETWORK)
    with tempfile.TemporaryDirectory(prefix='cybergold-facts-') as temp:
        source=Path(temp,'rpc.py');source.write_text(FIXTURE)
        docker('run','--detach','--name',RPC,'--network',NETWORK,'--publish','127.0.0.1::5000','--mount','type=bind,src='+str(source)+',dst=/tmp/rpc.py,readonly',IMAGE,'python','/tmp/rpc.py')
        docker('run','--detach','--name',API,'--network',NETWORK,'--publish','127.0.0.1::3000',
            '--env','NEXT_PUBLIC_CHAIN_ID=31338','--env','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='+REFERENCE['core'],
            '--env','NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS='+REFERENCE['helpers'],
            '--env','NEXT_PUBLIC_RPC_URL=http://'+RPC+':5000','--env','RPC_URL=http://'+RPC+':5000',
            '--env','RPC_AUTHORIZATION=Bearer fixture-only',IMAGE)
        port=docker('port',API,'3000/tcp').rsplit(':',1)[1];rpcport=docker('port',RPC,'5000/tcp').rsplit(':',1)[1]
        base='http://127.0.0.1:'+port;control='http://127.0.0.1:'+rpcport+'/fixture'
        for _ in range(150):
            try:
                if get(base+'/metrics')[0]==200:break
            except (ConnectionError,OSError):pass
            time.sleep(.1)
        status,headers,raw=get(base+'/api/protocol/facts?provider=http://untrusted.invalid&target=0x0')
        assert status==200,(status,raw);value=json.loads(raw)
        assert headers['Cache-Control']=='no-store'
        assert value['context']['blockNumber']=='101' and value['reference']['value']==str(2**180)
        calls=json.loads(get(control)[2])['calls'];contract=[call for call in calls if call['method']=='eth_call']
        assert len(contract)==17
        assert all(call['params'][1]=={'blockHash':'0x'+'a'*64,'requireCanonical':True} for call in contract)
        assert all(call['params'][0]['to'].lower() in [REFERENCE['core'],REFERENCE['helpers'],*REFERENCE['assets']] for call in contract)
        get(control+'?mode=partial');status,_,raw=get(base+'/api/protocol/facts')
        assert status==200 and json.loads(raw)['basket']['targetsPpm']['status']=='failure'
        for mode in ('reorg','outage'):
            get(control+'?mode='+mode);status,_,raw=get(base+'/api/protocol/facts')
            assert status==503 and 'correlationId' in json.loads(raw) and b'password' not in raw
        get(control+'?mode=delay');started=time.monotonic();status,_,raw=get(base+'/api/protocol/facts');deadline=time.monotonic()-started
        assert status==503 and 14.8<=deadline<17,deadline
        get(control+'?mode=normal');assert get(base+'/api/protocol/facts')[0]==200
        get(control+'?mode=delay')
        caller=socket.create_connection(('127.0.0.1',int(port)))
        caller.sendall(b'GET /api/protocol/facts HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
        for _ in range(100):
            if any(call['method']=='eth_call' for call in json.loads(get(control)[2])['calls']):break
            time.sleep(.05)
        caller.close();cancelled=time.monotonic()
        for _ in range(60):
            metrics=get(base+'/metrics')[2].decode()
            if 'operation="/api/protocol/facts",status="499"' in metrics:break
            time.sleep(.05)
        else:raise AssertionError('Disconnected facts caller did not cancel its operation')
        cancel_seconds=time.monotonic()-cancelled
        logs=docker('logs',API);assert 'password' not in logs and 'private.invalid' not in logs
        docker('stop','--time','20',API);exit_code=int(docker('inspect',API,'--format','{{.State.ExitCode}}'));assert exit_code==0
        print(json.dumps({'result':'pass','nativeDefaultRoleCommand':True,'nativeConfiguredPrivateAuthorization':True,
            'nativeCanonicalWireReadCount':17,'nativeLosslessAndPartialFacts':True,'nativeCanonicalityOutageAndRecovery':True,
            'nativeCallerDisconnectSeconds':round(cancel_seconds,2),'nativeOperationDeadlineSeconds':round(deadline,2),'shutdownExitCode':exit_code,'testedImageId':docker('image','inspect',IMAGE,'--format','{{.Id}}'),
            'installedEndpointsOrDatabaseUsed':False}))
except Exception:
    subprocess.run(['docker','logs','--tail','30',API],check=False)
    subprocess.run(['docker','logs','--tail','30',RPC],check=False)
    subprocess.run(['docker','exec',API,'python','-c','import asyncio; from cybergold_candidate.environment import load_environment; from cybergold_candidate.protocol_facts import ProtocolFacts; asyncio.run(ProtocolFacts(load_environment()).get())'],check=False)
    raise
finally:
    for container in (API,RPC):subprocess.run(['docker','rm','-f',container],capture_output=True)
    subprocess.run(['docker','network','rm',NETWORK],capture_output=True)
