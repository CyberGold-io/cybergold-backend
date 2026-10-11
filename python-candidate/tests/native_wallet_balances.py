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

IMAGE = 'cybergold-wallet-balances-candidate:qualified'
prefix = 'cybergold-wallet-fixture-'+secrets.token_hex(4)
RPC, API, NETWORK = prefix+'-rpc', prefix+'-api', prefix+'-network'
REFERENCE = json.loads(subprocess.check_output(['node','--import','tsx','python-candidate/tests/node-wallet-balances-reference.ts'],text=True))
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
        elif method=='eth_call':
            if Provider.mode=='delay':time.sleep(16)
            row=next(row for row in REF['rows'] if row['data']==params[0]['data'])
            result=row['partialNativeResult'] if Provider.mode=='partial' else row['result']
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
    with tempfile.TemporaryDirectory(prefix='cybergold-wallet-') as temp:
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
        legacy_route='/api/account/wallet-balances?'+urllib.parse.urlencode({'holder':REFERENCE['rows'][0]['holder']})
        route=legacy_route+'&purpose=display'
        for _ in range(150):
            try:
                if get(base+'/metrics')[0]==200:break
            except (ConnectionError,OSError):pass
            time.sleep(.1)
        status,headers,raw=get(base+route);value=json.loads(raw)
        assert status==200 and headers['Cache-Control']=='no-store',(status,raw)
        assert len(value['tokens'])==6 and all(row['balance']['value']==str(2**255) for row in value['tokens'])
        assert value['native']['value']==str(2**200)
        calls=json.loads(get(control)[2])['calls']
        assert len(calls)==2 and calls[0]['method']=='eth_getBlockByNumber'
        assert all(call['method']!='eth_chainId' for call in calls)
        balances=[call for call in calls if call['method'] in ('eth_call','eth_getBalance')]
        assert len(balances)==1 and balances[0]['method']=='eth_call'
        assert balances[0]['params'][0]['to'].lower()==REFERENCE['multicall']
        assert balances[0]['params'][0]['data']==REFERENCE['rows'][0]['data']
        assert balances[0]['params'][1]=={'blockHash':'0x'+'a'*64,'requireCanonical':True}
        assert get(base+'/api/account/wallet-balances?holder=not-an-address')[0]==400
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda row:json.loads(get(base+'/api/account/wallet-balances?holder='+row['holder']+'&purpose=display')[2]),REFERENCE['rows']))
        assert [value['native']['value'] for value in values]==[str(2**200),str(2**200+1)]
        get(control+'?mode=partial');status,_,raw=get(base+route)
        assert status==200 and json.loads(raw)['native']['status']=='failure' and b'password' not in raw
        get(control+'?mode=reorg');assert get(base+route)[0]==200
        for mode in ('reorg','outage'):
            get(control+'?mode='+mode)
            status,_,raw=get(base+(legacy_route+'&purpose=swap-preflight' if mode=='reorg' else route))
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
            if 'operation="/api/account/wallet-balances",status="499"' in get(base+'/metrics')[2].decode():break
            time.sleep(.05)
        else:raise AssertionError('Disconnected wallet caller did not cancel its operation')
        cancel_seconds=time.monotonic()-cancelled
        logs=docker('logs',API);assert 'password' not in logs and 'private.invalid' not in logs
        docker('stop','--time','20',API);exit_code=int(docker('inspect',API,'--format','{{.State.ExitCode}}'));assert exit_code==0
        print(json.dumps({'result':'pass','nativeDefaultRoleCommand':True,'privateAuthorization':True,
            'canonicalBalanceCalls':1,'multicallMembers':7,'concurrentHolderIsolation':True,'losslessAndPartialBalances':True,
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
