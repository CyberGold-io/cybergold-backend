"""Actual Linux API/default command, synthetic private RPC, no product endpoint."""
import concurrent.futures
import json
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

IMAGE = 'cybergold-safe-principal-candidate:qualified'
prefix = 'cybergold-safe-principal-fixture-'+secrets.token_hex(4)
RPC, API, NETWORK = prefix+'-rpc', prefix+'-api', prefix+'-network'
REFERENCE = json.loads(subprocess.check_output(['node','--import','tsx','python-candidate/tests/node-safe-principal-reference.ts'],text=True))
FIXTURE = '''
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
        elif method in ('eth_call','eth_getCode'):
            if Provider.mode=='delay':time.sleep(16)
            if Provider.mode=='partial' and method=='eth_call' and params[0]['data']=='0xe75235b8':return self.send({'jsonrpc':'2.0','id':value['id'],'error':{'code':-32000,'message':'private-password'}})
            address=params[0]['to'] if method=='eth_call' else params[0]
            row=next(row for row in REF['rows'] if row['address'].lower()==address.lower())
            result=row['code'] if method=='eth_getCode' else next(call['result'] for call in row['calls'] if call['data']==params[0]['data'])
        else:raise AssertionError(method)
        self.send({'jsonrpc':'2.0','id':value['id'],'result':result})
ThreadingHTTPServer(('0.0.0.0',5000),Provider).serve_forever()
'''.replace('REFERENCE',repr(REFERENCE))


def docker(*args):
    return subprocess.check_output(['docker',*args],text=True).strip()


def get(url):
    try:
        with urllib.request.urlopen(url,timeout=20) as response:
            return response.status,response.headers,response.read()
    except urllib.error.HTTPError as error:
        return error.code,error.headers,error.read()


try:
    docker('network','create',NETWORK)
    with tempfile.TemporaryDirectory(prefix='cybergold-safe-principal-') as temp:
        source=Path(temp,'rpc.py');source.write_text(FIXTURE)
        docker('run','--detach','--name',RPC,'--network',NETWORK,'--publish','127.0.0.1::5000',
               '--mount','type=bind,src='+str(source)+',dst=/tmp/rpc.py,readonly',IMAGE,'python','/tmp/rpc.py')
        docker('run','--detach','--name',API,'--network',NETWORK,'--publish','127.0.0.1::3000',
            '--env','NEXT_PUBLIC_CHAIN_ID=31338','--env','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='+REFERENCE['core'],
            '--env','NEXT_PUBLIC_RPC_URL=http://'+RPC+':5000','--env','RPC_URL=http://'+RPC+':5000',
            '--env','RPC_AUTHORIZATION=Bearer fixture-only',IMAGE)
        port=docker('port',API,'3000/tcp').rsplit(':',1)[1]
        base='http://127.0.0.1:'+port
        control='http://127.0.0.1:'+docker('port',RPC,'5000/tcp').rsplit(':',1)[1]+'/fixture'
        route='/api/governance/safe-principal?address='+REFERENCE['core']
        for _ in range(150):
            try:
                if get(base+'/metrics')[0]==200:break
            except (ConnectionError,OSError):pass
            time.sleep(.1)
        status,headers,raw=get(base+route);value=json.loads(raw)
        assert status==200 and headers['Cache-Control']=='no-store',(status,raw)
        fields={key:value[key] for key in ('code','owners','threshold')}
        assert fields['code']['value']=='0x6001' and fields['threshold']['value']=='1'
        assert fields['owners']['value']==[REFERENCE['rows'][1]['address']]
        reads=[call for call in json.loads(get(control)[2])['calls'] if call['method'] in ('eth_call','eth_getCode')]
        assert len(reads)==3 and all(call['params'][1]=={'blockHash':'0x'+'a'*64,'requireCanonical':True} for call in reads)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda row:json.loads(get(base+'/api/governance/safe-principal?address='+row['address'])[2]),REFERENCE['rows']))
        assert [value['threshold']['value'] for value in values]==['1',str(2**200)]
        assert [value['code']['value'] for value in values]==['0x6001','0x6002']
        get(control+'?mode=partial');status,_,raw=get(base+route)
        assert status==200 and json.loads(raw)['threshold']['status']=='failure' and b'password' not in raw
        for mode in ('reorg','outage'):
            get(control+'?mode='+mode);status,_,raw=get(base+route)
            assert status==503 and 'correlationId' in json.loads(raw) and b'password' not in raw
        get(control+'?mode=delay');started=time.monotonic();status,_,raw=get(base+route);deadline=time.monotonic()-started
        assert status==503 and 14.8<=deadline<17,deadline
        get(control+'?mode=normal');assert get(base+route)[0]==200
        get(control+'?mode=delay')
        caller=socket.create_connection(('127.0.0.1',int(port)))
        caller.sendall(('GET '+route+' HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n').encode())
        for _ in range(100):
            if any(call['method']=='eth_call' for call in json.loads(get(control)[2])['calls']):break
            time.sleep(.05)
        caller.close();cancelled=time.monotonic()
        for _ in range(60):
            if 'operation="/api/governance/safe-principal",status="499"' in get(base+'/metrics')[2].decode():break
            time.sleep(.05)
        else:raise AssertionError('Disconnected principal caller did not cancel its operation')
        cancel_seconds=time.monotonic()-cancelled
        logs=docker('logs',API);assert 'password' not in logs and 'private.invalid' not in logs
        docker('stop','--time','20',API);exit_code=int(docker('inspect',API,'--format','{{.State.ExitCode}}'));assert exit_code==0
        print(json.dumps({'result':'pass','nativeDefaultRoleCommand':True,'privateAuthorization':True,
            'canonicalPrincipalReads':3,'concurrentReads':True,'losslessThresholdAndPartialUnknowns':True,
            'canonicalityOutageAndRecovery':True,'callerDisconnectSeconds':round(cancel_seconds,2),
            'operationDeadlineSeconds':round(deadline,2),'shutdownExitCode':exit_code,
            'imageId':docker('image','inspect',IMAGE,'--format','{{.Id}}'),'productEndpointOrDatabaseUsed':False}))
except Exception:
    subprocess.run(['docker','logs','--tail','20',API],check=False)
    subprocess.run(['docker','logs','--tail','20',RPC],check=False)
    raise
finally:
    subprocess.run(['docker','rm','--force',API,RPC],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',NETWORK],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
