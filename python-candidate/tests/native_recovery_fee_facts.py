"""Packaged recovery-asset and fee observations against disposable private RPC."""
import json
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

IMAGE='cybergold-recovery-fee-candidate:qualified'
prefix='cybergold-recovery-fee-fixture-'+secrets.token_hex(4)
RPC,API,NETWORK=prefix+'-rpc',prefix+'-api',prefix+'-network'
CORE=json.loads(subprocess.check_output(['node','--import','tsx','python-candidate/tests/node-core-recovery-assets-reference.ts'],text=True))
FEES=json.loads(subprocess.check_output(['node','--import','tsx','python-candidate/tests/node-transaction-fees-reference.ts'],text=True))
FIXTURE='''
import json,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
CORE=CORE_REFERENCE;FEES=FEES_REFERENCE
class Provider(BaseHTTPRequestHandler):
    mode='normal';calls=[];case=2
    def log_message(self,*args):pass
    def do_GET(self):
        if '?mode=' in self.path:Provider.mode=self.path.split('?mode=')[1];Provider.calls=[]
        if '?case=' in self.path:Provider.case=int(self.path.split('?case=')[1]);Provider.calls=[]
        self.send({'mode':Provider.mode,'calls':Provider.calls})
    def send(self,value,status=200):
        raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self):
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        method,params=value['method'],value['params'];Provider.calls.append({'method':method,'params':params})
        assert self.headers.get('Authorization')=='Bearer fixture-only'
        config=FEES[Provider.case]['config']
        if Provider.mode=='outage':return self.send({'error':'https://secret:password@private.invalid'},503)
        if method=='eth_chainId':result='0x7a6a'
        elif method=='eth_getBlockByNumber':
            result={'number':'0x65','timestamp':'0x6a000001','hash':'0x'+('b' if Provider.mode=='reorg' and params[0]!='latest' else 'a')*64}
            if config['base'] is not None:result['baseFeePerGas']=hex(int(config['base']))
        elif method in ('eth_call','eth_maxPriorityFeePerGas','eth_gasPrice'):
            if Provider.mode=='delay':time.sleep(16)
            if method=='eth_call':
                assert params[0]['to']==CORE['core'] and params[0]['data']==CORE['data']
                result=CORE['empty'] if Provider.mode=='empty' else CORE['result']
            elif method=='eth_maxPriorityFeePerGas' and not config.get('fallback'):result=hex(int(config['priority']))
            elif method=='eth_gasPrice' and not config.get('gasFailure'):result=hex(int(config['gas']))
            else:return self.send({'jsonrpc':'2.0','id':value['id'],'error':{'code':-32601,'message':'https://password@private.invalid'}})
        else:raise AssertionError(method)
        self.send({'jsonrpc':'2.0','id':value['id'],'result':result})
ThreadingHTTPServer(('0.0.0.0',5000),Provider).serve_forever()
'''.replace('CORE_REFERENCE',repr(CORE)).replace('FEES_REFERENCE',repr(FEES))


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
        docker('run','--platform','linux/amd64','--detach','--name',RPC,'--network',NETWORK,'--publish','127.0.0.1::5000',
               '--mount','type=bind,src='+str(source)+',dst=/tmp/rpc.py,readonly',IMAGE,'python','/tmp/rpc.py')
        docker('run','--platform','linux/amd64','--detach','--name',API,'--network',NETWORK,'--publish','127.0.0.1::3000',
            '--env','NEXT_PUBLIC_CHAIN_ID=31338','--env','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='+CORE['core'],
            '--env','NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=0x'+('5'*40),
            '--env','NEXT_PUBLIC_RPC_URL=http://'+RPC+':5000','--env','RPC_URL=http://'+RPC+':5000',
            '--env','RPC_AUTHORIZATION=Bearer fixture-only',IMAGE)
        port=docker('port',API,'3000/tcp').rsplit(':',1)[1];base='http://127.0.0.1:'+port
        control='http://127.0.0.1:'+docker('port',RPC,'5000/tcp').rsplit(':',1)[1]+'/fixture'
        for _ in range(150):
            try:
                if request(base+'/metrics')[0]==200:break
            except (ConnectionError,OSError):pass
            time.sleep(.1)
        paths={'assets':'/api/protocol/recovery-assets','fees':'/api/transaction/fees'}
        def read(name):return request(base+paths[name])
        status,headers,raw=read('assets');value=json.loads(raw)
        assert status==200 and headers['Cache-Control']=='no-store' and value['assets']==CORE['assets'],(status,raw)
        calls=json.loads(request(control)[2])['calls']
        reads=[call for call in calls if call['method']=='eth_call']
        assert len(reads)==1 and reads[0]['params'][1]=={'blockHash':'0x'+'a'*64,'requireCanonical':True}
        request(control+'?mode=empty');assert json.loads(read('assets')[2])['assets']==[]
        request(control+'?mode=normal')
        for index,row in enumerate(FEES):
            request(control+'?case='+str(index));status,headers,raw=read('fees');value=json.loads(raw)
            if row.get('error'):
                assert status==503 and 'maxFeePerGas' not in value
            else:
                assert status==200 and headers['Cache-Control']=='no-store'
                assert {key:value[key] for key in row['fees']}==row['fees']
            assert b'password' not in raw
        request(control+'?case=2')
        for mode in ('reorg','outage'):
            request(control+'?mode='+mode)
            for name in paths:
                status,_,raw=read(name)
                assert status==503 and 'correlationId' in json.loads(raw) and b'password' not in raw
        deadlines={}
        for name in paths:
            request(control+'?mode=delay');started=time.monotonic();status,_,raw=read(name)
            duration=time.monotonic()-started;assert status==503 and 14.8<=duration<17,duration
            deadlines[name]=round(duration,2)
        request(control+'?mode=normal')
        assert all(read(name)[0]==200 for name in paths)
        request(control+'?mode=delay')
        caller=socket.create_connection(('127.0.0.1',int(port)))
        caller.sendall(b'GET /api/transaction/fees HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
        for _ in range(100):
            if any(call['method']=='eth_maxPriorityFeePerGas' for call in json.loads(request(control)[2])['calls']):break
            time.sleep(.05)
        caller.close();cancelled=time.monotonic()
        for _ in range(60):
            if 'operation="/api/transaction/fees",status="499"' in request(base+'/metrics')[2].decode():break
            time.sleep(.05)
        else:raise AssertionError('Disconnected fee caller did not cancel its operation')
        cancel_seconds=time.monotonic()-cancelled
        logs=docker('logs',API);assert 'password' not in logs and 'private.invalid' not in logs
        docker('stop','--time','20',API);assert int(docker('inspect',API,'--format','{{.State.ExitCode}}'))==0
        print(json.dumps({'result':'pass','nativeDefaultRoleCommand':True,'privateRpcAuthorization':True,
            'actualViemFeeComparisons':len(FEES),'canonicalRecoveryRead':True,'orderedAssetsAndAuthoritativeEmpty':True,
            'losslessFeesAndExistingFallback':True,'canonicalityOutageAndRecovery':True,
            'operationDeadlineSeconds':deadlines,'callerDisconnectSeconds':round(cancel_seconds,2),
            'imageId':docker('image','inspect',IMAGE,'--format','{{.Id}}'),'shutdownExitCode':0,
            'productEndpointOrDatabaseUsed':False,'walletSignatureOrSubmission':False}))
except Exception:
    subprocess.run(['docker','logs','--tail','20',API],check=False)
    subprocess.run(['docker','logs','--tail','20',RPC],check=False)
    raise
finally:
    subprocess.run(['docker','rm','--force',API,RPC],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',NETWORK],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
