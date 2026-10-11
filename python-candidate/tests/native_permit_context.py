"""Packaged API signing-context observations against disposable private RPC."""
import concurrent.futures
import json
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

IMAGE='cybergold-permit-context-candidate:qualified'
prefix='cybergold-permit-fixture-'+secrets.token_hex(4)
RPC,API,NETWORK=prefix+'-rpc',prefix+'-api',prefix+'-network'
CORE=json.loads(subprocess.check_output(['node','--import','tsx','python-candidate/tests/node-core-permit-reference.ts'],text=True))
PERMIT2=json.loads(subprocess.check_output(['node','--import','tsx','python-candidate/tests/node-permit2-context-reference.ts'],text=True))
FIXTURE='''
import json,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
CORE=CORE_REFERENCE;REF=PERMIT2_REFERENCE
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
            if method=='eth_getCode':result='0x6000'
            else:
                rows=[CORE['name'],*CORE['rows']] if params[0]['to']==CORE['core'] else [REF['router'],*REF['nonceRows'],*REF['allowanceRows']]
                row=next(row for row in rows if row['data']==params[0]['data'] and ('token' not in row or row['token']==params[0]['to']))
                result=row['result']
        else:raise AssertionError(method)
        self.send({'jsonrpc':'2.0','id':value['id'],'result':result})
ThreadingHTTPServer(('0.0.0.0',5000),Provider).serve_forever()
'''.replace('CORE_REFERENCE',repr(CORE)).replace('PERMIT2_REFERENCE',repr(PERMIT2))


def docker(*args):return subprocess.check_output(['docker',*args],text=True).strip()


def request(url,body=None):
    value=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'} if body is not None else {})
    try:
        with urllib.request.urlopen(value,timeout=20) as response:return response.status,response.headers,response.read()
    except urllib.error.HTTPError as error:return error.code,error.headers,error.read()


try:
    docker('network','create',NETWORK)
    with tempfile.TemporaryDirectory(prefix='cybergold-permit-') as temp:
        source=Path(temp,'rpc.py');source.write_text(FIXTURE)
        docker('run','--detach','--name',RPC,'--network',NETWORK,'--publish','127.0.0.1::5000',
               '--mount','type=bind,src='+str(source)+',dst=/tmp/rpc.py,readonly',IMAGE,'python','/tmp/rpc.py')
        docker('run','--detach','--name',API,'--network',NETWORK,'--publish','127.0.0.1::3000',
            '--env','NEXT_PUBLIC_CHAIN_ID=31338','--env','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='+CORE['core'],
            '--env','NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS='+CORE['helpers'],
            '--env','NEXT_PUBLIC_RPC_URL=http://'+RPC+':5000','--env','RPC_URL=http://'+RPC+':5000',
            '--env','RPC_AUTHORIZATION=Bearer fixture-only',IMAGE)
        port=docker('port',API,'3000/tcp').rsplit(':',1)[1];base='http://127.0.0.1:'+port
        control='http://127.0.0.1:'+docker('port',RPC,'5000/tcp').rsplit(':',1)[1]+'/fixture'
        for _ in range(150):
            try:
                if request(base+'/metrics')[0]==200:break
            except (ConnectionError,OSError):pass
            time.sleep(.1)
        def core(owner):return request(base+'/api/account/core-permit?owner='+owner)
        def permit(body):return request(base+'/api/account/permit2',body)
        status,headers,raw=core(CORE['rows'][0]['owner']);value=json.loads(raw)
        assert status==200 and headers['Cache-Control']=='no-store',(status,raw)
        assert value['nonce']==CORE['rows'][0]['value'] and value['domain']['name']==CORE['name']['value']
        assert value['domain']['version']=='1' and value['spender']==CORE['helpers']
        status,headers,raw=permit({'mode':'verify'});value=json.loads(raw)
        assert status==200 and headers['Cache-Control']=='no-store' and value['permit2']==PERMIT2['permit2'] and value['result']['code']=='0x6000'
        status,_,raw=permit({'mode':'nonce','owner':PERMIT2['owners'][0]})
        assert status==200 and json.loads(raw)['result']['nonce']=='257'
        status,_,raw=permit({'mode':'allowances','owner':PERMIT2['owners'][0],'tokens':list(reversed(PERMIT2['tokens']))})
        assert status==200 and [row['value'] for row in json.loads(raw)['result']['allowances']]==[str(2**255+1),str(2**255)]
        calls=json.loads(request(control)[2])['calls']
        reads=[call for call in calls if call['method'] in ('eth_call','eth_getCode')]
        assert len(reads)==10 and all(call['params'][1]=={'blockHash':'0x'+'a'*64,'requireCanonical':True} for call in reads)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda row:json.loads(core(row['owner'])[2]),CORE['rows']))
        assert [value['nonce'] for value in values]==[row['value'] for row in CORE['rows']]
        assert core('invalid-owner')[0]==400 and permit({'mode':'arbitrary-method'})[0]==400
        for mode in ('reorg','outage'):
            request(control+'?mode='+mode)
            for status,_,raw in (core(CORE['rows'][0]['owner']),permit({'mode':'verify'})):
                assert status==503 and 'correlationId' in json.loads(raw) and b'password' not in raw
        deadlines={}
        for operation in ('core','permit2'):
            request(control+'?mode=delay');started=time.monotonic()
            status,_,raw=core(CORE['rows'][0]['owner']) if operation=='core' else permit({'mode':'nonce','owner':PERMIT2['owners'][0]})
            duration=time.monotonic()-started;assert status==503 and 14.8<=duration<17,duration
            deadlines[operation]=round(duration,2)
        request(control+'?mode=normal');assert core(CORE['rows'][0]['owner'])[0]==200
        request(control+'?mode=delay');body=json.dumps({'mode':'verify'}).encode()
        caller=socket.create_connection(('127.0.0.1',int(port)))
        caller.sendall(b'POST /api/account/permit2 HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
        for _ in range(100):
            if any(call['method']=='eth_call' for call in json.loads(request(control)[2])['calls']):break
            time.sleep(.05)
        caller.close();cancelled=time.monotonic()
        for _ in range(60):
            if 'operation="/api/account/permit2",status="499"' in request(base+'/metrics')[2].decode():break
            time.sleep(.05)
        else:raise AssertionError('Disconnected permit caller did not cancel its operation')
        cancel_seconds=time.monotonic()-cancelled
        logs=docker('logs',API);assert 'password' not in logs and 'private.invalid' not in logs
        docker('stop','--time','20',API);assert int(docker('inspect',API,'--format','{{.State.ExitCode}}'))==0
        print(json.dumps({'result':'pass','nativeDefaultRoleCommand':True,'privateRpcAuthorization':True,
            'canonicalReads':10,'fullBitmapTraversal':True,'concurrentOwnerIsolation':True,'losslessNonceAndAllowances':True,
            'canonicalityOutageAndRecovery':True,'operationDeadlineSeconds':deadlines,'callerDisconnectSeconds':round(cancel_seconds,2),
            'imageId':docker('image','inspect',IMAGE,'--format','{{.Id}}'),'productEndpointOrDatabaseUsed':False,'walletSignatureOrSubmission':False}))
except Exception:
    subprocess.run(['docker','logs','--tail','20',API],check=False)
    subprocess.run(['docker','logs','--tail','20',RPC],check=False)
    raise
finally:
    subprocess.run(['docker','rm','--force',API,RPC],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',NETWORK],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
