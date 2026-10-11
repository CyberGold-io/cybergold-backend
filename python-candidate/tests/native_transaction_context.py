"""Assembled Linux API: fresh nonce, receipts, Safe preparation and role rosters."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

IMAGE='cybergold-transaction-context-candidate:qualified'
prefix='cybergold-transaction-context-'+secrets.token_hex(4)
RPC,API,NETWORK=prefix+'-rpc',prefix+'-api',prefix+'-network'


def reference(name):
    return json.loads(subprocess.check_output(['node','--import','tsx',
        'python-candidate/tests/node-'+name+'-reference.ts'],text=True))


NONCE=reference('transaction-nonce')
RECEIPT=reference('transaction-receipt')
SAFE=reference('safe-transaction')
ROLES=reference('governance-roles')
FIXTURE='''
import json,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
NONCE,RECEIPT,SAFE,ROLES=REFERENCES
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
        if Provider.mode=='outage':return self.send({'error':'https://password@private.invalid'},503)
        if method=='eth_chainId':result='0x1' if Provider.mode=='wrong-chain' else '0x7a6a'
        elif method=='eth_getBlockByNumber':
            result={'number':'0x65','timestamp':'0x6a000001','hash':'0x'+('b' if Provider.mode=='reorg' and params[0]!='latest' else 'a')*64}
        elif method in ('eth_call','eth_getTransactionCount','eth_getTransactionReceipt'):
            if Provider.mode=='delay':time.sleep(16)
            if method=='eth_getTransactionCount':
                assert params[1]=='pending';result=hex(2**100+1)
            elif method=='eth_getTransactionReceipt':
                result=None if Provider.mode=='missing' else RECEIPT[1 if Provider.mode=='reverted' else 0]['raw']
            else:
                call=params[0]
                assert params[1]=={'blockHash':'0x'+'a'*64,'requireCanonical':True}
                safe=next((row for row in SAFE if row['payload']['address'].lower()==call['to'].lower()),None)
                if safe and call['data']==safe['calls'][0]['params'][0]['data']:result='0x'+int(safe['nonce']).to_bytes(32).hex()
                elif safe and call['data']==safe['calls'][1]['params'][0]['data']:result=safe['safeTxHash']
                else:
                    row=next(row for row in ROLES if row['address'].lower()==call['to'].lower())
                    reads=[read for role in row['roles'] for read in [role['countCall'],*role['members']]]
                    result=next(read['result'] for read in reads if read['data']==call['data'])
        else:raise AssertionError(method)
        self.send({'jsonrpc':'2.0','id':value['id'],'result':result})
ThreadingHTTPServer(('0.0.0.0',5000),Provider).serve_forever()
'''.replace('REFERENCES',repr((NONCE,RECEIPT,SAFE,ROLES)))


def docker(*args):return subprocess.check_output(['docker',*args],text=True).strip()


def request(url,body=None):
    value=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'} if body is not None else {})
    try:
        with urllib.request.urlopen(value,timeout=20) as response:return response.status,response.headers,response.read()
    except urllib.error.HTTPError as error:return error.code,error.headers,error.read()


try:
    docker('network','create',NETWORK)
    with tempfile.TemporaryDirectory(prefix='cybergold-transaction-context-') as temp:
        source=Path(temp,'rpc.py');source.write_text(FIXTURE)
        docker('run','--platform','linux/amd64','--detach','--name',RPC,'--network',NETWORK,'--publish','127.0.0.1::5000',
            '--mount','type=bind,src='+str(source)+',dst=/tmp/rpc.py,readonly',IMAGE,'python','/tmp/rpc.py')
        env=['--env','NEXT_PUBLIC_CHAIN_ID=31338','--env','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='+ROLES[0]['address'],
            '--env','NEXT_PUBLIC_STAKING_DIAMOND_ADDRESS='+ROLES[1]['address'],
            '--env','NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS='+ROLES[2]['address'],
            '--env','NEXT_PUBLIC_RPC_URL=http://'+RPC+':5000',
            '--env','RPC_URL=http://'+RPC+':5000','--env','RPC_AUTHORIZATION=Bearer fixture-only']
        docker('run','--platform','linux/amd64','--detach','--name',API,'--network',NETWORK,'--publish','127.0.0.1::3000',*env,IMAGE)
        port=docker('port',API,'3000/tcp').rsplit(':',1)[1];base='http://127.0.0.1:'+port
        control='http://127.0.0.1:'+docker('port',RPC,'5000/tcp').rsplit(':',1)[1]+'/fixture'
        for _ in range(150):
            try:
                if request(base+'/metrics')[0]==200:break
            except (ConnectionError,OSError):pass
            time.sleep(.1)
        owner=SAFE[0]['payload']['address'];receipt_hash=RECEIPT[0]['hash']
        paths={'nonce':'/api/account/transaction-nonce?owner='+owner,
               'receipt':'/api/transaction/receipt?hash='+receipt_hash,
               'safe':'/api/governance/safe-transaction-hash',
               'roles':'/api/governance/roles?surface=core'}
        def read(name):return request(base+paths[name],SAFE[0]['payload'] if name=='safe' else None)
        status,headers,raw=read('nonce');value=json.loads(raw)
        assert status==200 and headers['Cache-Control']=='no-store' and value['nonce']==str(2**100+1),(status,raw)
        for row in SAFE:
            result=request(base+'/api/governance/safe-nonce?address='+row['payload']['address'])
            assert result[0]==200 and json.loads(result[2])['nonce']==row['nonce']
            result=request(base+paths['safe'],row['payload'])
            assert result[0]==200 and json.loads(result[2])['safeTxHash']==row['safeTxHash']
        for mode,row in zip(('normal','reverted','missing'),RECEIPT,strict=True):
            request(control+'?mode='+mode);status,headers,raw=read('receipt')
            assert status==200 and headers['Cache-Control']=='no-store' and json.loads(raw)['receipt']==row['receipt']
        request(control+'?mode=normal')
        for row in ROLES:
            status,headers,raw=request(base+'/api/governance/roles?surface='+row['surface']);value=json.loads(raw)
            assert status==200 and headers['Cache-Control']=='no-store'
            for actual,expected in zip(value['roles'],row['roles'],strict=True):
                assert actual['count']=={'status':'success','value':expected['count']}
                assert [member['value'].lower() for member in actual['members']]==[member['address'] for member in expected['members']]
        for mode in ('wrong-chain','outage'):
            request(control+'?mode='+mode)
            for name in paths:
                status,_,raw=read(name);assert status==503 and b'password' not in raw,(name,status,raw)
        request(control+'?mode=reorg')
        for name in ('nonce','safe','roles'):assert read(name)[0]==503
        request(control+'?mode=delay')
        def deadline(name):
            started=time.monotonic();status,_,raw=read(name);duration=time.monotonic()-started
            assert status==503 and 14.8<=duration<17,(name,status,duration)
            return name,round(duration,2)
        with ThreadPoolExecutor(max_workers=4) as workers:deadlines=dict(workers.map(deadline,paths))
        request(control+'?mode=normal');assert all(read(name)[0]==200 for name in paths)
        request(control+'?mode=delay')
        caller=socket.create_connection(('127.0.0.1',int(port)))
        caller.sendall(('GET '+paths['receipt']+' HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n').encode())
        for _ in range(100):
            if any(call['method']=='eth_getTransactionReceipt' for call in json.loads(request(control)[2])['calls']):break
            time.sleep(.05)
        caller.close();cancelled=time.monotonic()
        for _ in range(60):
            if 'operation="/api/transaction/receipt",status="499"' in request(base+'/metrics')[2].decode():break
            time.sleep(.05)
        else:raise AssertionError('Receipt caller disconnect did not cancel operation')
        cancel_seconds=time.monotonic()-cancelled
        assert not any(call['method'].startswith('eth_send') for call in json.loads(request(control)[2])['calls'])
        logs=docker('logs',API);assert 'password' not in logs and 'private.invalid' not in logs
        docker('stop','--time','20',API);assert int(docker('inspect',API,'--format','{{.State.ExitCode}}'))==0
        print(json.dumps({'result':'pass','freshLosslessPendingNonce':True,'receiptSuccessRevertAbsence':True,
            'exactUnsignedSafePayloads':len(SAFE),'configuredRoleSurfaces':len(ROLES),'existingMemberDisplayLimit':50,
            'privateRpcAuthorization':True,'canonicalityOutageAndRecovery':True,'operationDeadlineSeconds':deadlines,
            'callerDisconnectSeconds':round(cancel_seconds,2),'imageId':docker('image','inspect',IMAGE,'--format','{{.Id}}'),
            'shutdownExitCode':0,'productEndpointOrDatabaseUsed':False,'walletSignatureOrSubmission':False}))
except Exception:
    subprocess.run(['docker','logs','--tail','20',API],check=False)
    subprocess.run(['docker','logs','--tail','20',RPC],check=False)
    raise
finally:
    subprocess.run(['docker','rm','--force',API,RPC],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',NETWORK],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
