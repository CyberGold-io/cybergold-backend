"""Isolated assembled API: preparation and fixed receipt-wait observations."""
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

IMAGE='cybergold-transaction-preparation-candidate:qualified'
prefix='cybergold-transaction-preparation-'+secrets.token_hex(4)
RPC,API,NETWORK=prefix+'-rpc',prefix+'-api',prefix+'-network'


def reference(name):
    return json.loads(subprocess.check_output(['node','--import','tsx','python-candidate/tests/node-'+name+'-reference.ts'],text=True))


AUTH=reference('governance-authority');REDEMPTION=reference('recovery-redemption');GAS=reference('permit2-approval-gas')
SAFE=reference('safe-execution');HELPERS=reference('helpers-execution')
PRECISION=reference('recovery-share-precision')
HELPERS_FACTS=reference('helpers-router-facts')
SWAP_ADAPTER='0x'+'9'*40
WAIT_HASH='0x'+'ab'*32
WAIT_TRANSACTION={'hash':WAIT_HASH,'from':'0x'+'1'*40,'to':'0x'+'2'*40,'nonce':'0x7',
    'input':'0x1234','value':hex(2**200),'gas':'0x5208','type':'0x2','maxFeePerGas':'0xb','maxPriorityFeePerGas':'0x1','blockHash':None,'blockNumber':None}
WAIT_RECEIPT={'transactionHash':WAIT_HASH,'blockHash':'0x'+'a'*64,'blockNumber':'0x65',
    'status':'0x0','logs':[],'gasUsed':'0x5208'}
FIXTURE='''
import json,time
from eth_abi import decode,encode
from web3 import Web3
from ens.constants import UNIVERSAL_RESOLVER_ADDR
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
AUTH,REDEMPTION,GAS,SAFE,HELPERS,PRECISION,HELPERS_FACTS=REFERENCES
WAIT_HASH,WAIT_TRANSACTION,WAIT_RECEIPT=WAIT_VALUES
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
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method,params=value['method'],value['params']
        Provider.calls.append({'method':method,'params':params});assert self.headers.get('Authorization')=='Bearer fixture-only'
        if Provider.mode=='outage':return self.send({'error':'https://password@private.invalid'},503)
        if method=='eth_chainId':result='0x1' if Provider.mode=='wrong-chain' else '0x7a6a'
        elif method=='eth_blockNumber':
            if Provider.mode=='delay':time.sleep(16)
            result='0x65'
        elif method in ('eth_getTransactionByHash','eth_getTransactionReceipt'):
            if Provider.mode=='delay':time.sleep(16)
            assert params==[WAIT_HASH]
            result=None if Provider.mode=='missing' else WAIT_TRANSACTION if method=='eth_getTransactionByHash' else WAIT_RECEIPT
        elif method=='eth_getBalance':
            if Provider.mode=='delay':time.sleep(16)
            assert params==[WAIT_TRANSACTION['from'],{'blockHash':'0x'+'a'*64,'requireCanonical':True}]
            result=hex(2**200)
        elif method=='eth_getCode':
            if Provider.mode=='delay':time.sleep(16)
            assert params==['0x'+'9'*40,{'blockHash':'0x'+'a'*64,'requireCanonical':True}]
            result='0x' if Provider.mode=='missing' else '0x6000'
        elif method=='eth_getBlockByNumber':
            if params[1] is True:
                if Provider.mode=='delay':time.sleep(16)
                assert params==['0x65',True]
                result=None if Provider.mode=='missing' else {'number':'0x65','hash':'0x'+'a'*64,'transactions':[WAIT_TRANSACTION]}
            else:result={'number':'0x65','timestamp':'0x6a000001','hash':'0x'+('b' if Provider.mode=='reorg' and params[0]!='latest' else 'a')*64}
        elif method in ('eth_call','eth_estimateGas'):
            if Provider.mode=='delay':time.sleep(16)
            if Provider.mode=='revert':return self.send({'jsonrpc':'2.0','id':value['id'],'error':{'code':3,'message':'execution reverted https://password@private.invalid'}})
            if method=='eth_estimateGas':
                row=next(row for row in GAS+HELPERS if any(call['method']=='eth_estimateGas' and params==call['params'] for call in row['calls']));result=hex(int(row['gas']))
            else:
                call=params[0]
                simulation=next((row for row in SAFE+HELPERS if params==row['calls'][0]['params']),None)
                if call['to'].lower()==UNIVERSAL_RESOLVER_ADDR.lower():
                    assert params[1]=={'blockHash':'0x'+'a'*64,'requireCanonical':True}
                    dns,inner=decode(['bytes','bytes'],bytes.fromhex(call['data'][10:]))
                    selector=inner[:4]
                    if selector==Web3.keccak(text='name(bytes32)')[:4]:record=encode(['string'],['alice.eth'])
                    elif selector==Web3.keccak(text='addr(bytes32)')[:4]:record=encode(['address'],[WAIT_TRANSACTION['from']])
                    elif selector==Web3.keccak(text='text(bytes32,string)')[:4]:record=encode(['string'],['ipfs://bafy-fixture'])
                    else:raise AssertionError(selector.hex())
                    result=Web3.to_hex(encode(['bytes','address'],[record,'0x'+'3'*40]))
                elif call=={'from':WAIT_TRANSACTION['from'],'to':WAIT_TRANSACTION['to'],'gas':'0x5208','nonce':'0x7','value':WAIT_TRANSACTION['value'],'data':'0x1234','maxFeePerGas':'0xb','maxPriorityFeePerGas':'0x1'}:
                    assert params[1]=='latest'
                    result=Web3.to_hex(Web3.keccak(text='Error(string)')[:4]+encode(['string'],['Synthetic rejection']))
                elif simulation:result=simulation['encoded']
                else:
                    assert params[1]=={'blockHash':'0x'+'a'*64,'requireCanonical':True}
                    redemption=next((row for row in REDEMPTION if row['call']==call),None)
                    precision=next((row for row in PRECISION if call=={'to':row['core'],'data':row['data']}),None)
                    if redemption:result=redemption['result']
                    elif precision:result=precision['result']
                    elif call==GAS[0]['helpersCall']:result=GAS[0]['helpersResult']
                    elif any(row['data']==call['data'] for row in HELPERS_FACTS['rows']):
                        result=next(row['result'] for row in HELPERS_FACTS['rows'] if row['data']==call['data'])
                    else:
                        row=next(row for row in AUTH if row['address'].lower()==call['to'].lower())
                        result=next(read['encodedResult'] for read in row['calls'] if read['data']==call['data'])
        else:raise AssertionError(method)
        self.send({'jsonrpc':'2.0','id':value['id'],'result':result})
ThreadingHTTPServer(('0.0.0.0',5000),Provider).serve_forever()
'''.replace('REFERENCES',repr((AUTH,REDEMPTION,GAS,SAFE,HELPERS,PRECISION,HELPERS_FACTS))).replace('WAIT_VALUES',repr((WAIT_HASH,WAIT_TRANSACTION,WAIT_RECEIPT)))


def docker(*args):return subprocess.check_output(['docker',*args],text=True).strip()


def request(url,body=None):
    req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'} if body is not None else {})
    try:
        with urllib.request.urlopen(req,timeout=20) as response:return response.status,response.headers,response.read()
    except urllib.error.HTTPError as error:return error.code,error.headers,error.read()


try:
    docker('network','create',NETWORK)
    with tempfile.TemporaryDirectory(prefix='cybergold-preparation-') as temp:
        source=Path(temp,'rpc.py');source.write_text(FIXTURE)
        docker('run','--platform','linux/amd64','--detach','--name',RPC,'--network',NETWORK,'--publish','127.0.0.1::5000',
            '--mount','type=bind,src='+str(source)+',dst=/tmp/rpc.py,readonly',IMAGE,'python','/tmp/rpc.py')
        env=['--env','NEXT_PUBLIC_CHAIN_ID=31338','--env','NEXT_PUBLIC_CORE_DIAMOND_ADDRESS='+AUTH[0]['address'],
            '--env','NEXT_PUBLIC_STAKING_DIAMOND_ADDRESS='+AUTH[1]['address'],
            '--env','NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS='+AUTH[2]['address'],
            '--env','NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS='+GAS[0]['helpers'],
            '--env','NEXT_PUBLIC_RPC_URL=http://'+RPC+':5000','--env','RPC_URL=http://'+RPC+':5000','--env','RPC_AUTHORIZATION=Bearer fixture-only']
        docker('run','--platform','linux/amd64','--detach','--name',API,'--network',NETWORK,'--publish','127.0.0.1::3000',*env,IMAGE)
        port=docker('port',API,'3000/tcp').rsplit(':',1)[1];base='http://127.0.0.1:'+port
        control='http://127.0.0.1:'+docker('port',RPC,'5000/tcp').rsplit(':',1)[1]+'/fixture'
        for _ in range(150):
            try:
                if request(base+'/metrics')[0]==200:break
            except (ConnectionError,OSError):pass
            time.sleep(.1)
        paths={'authority':'/api/governance/authority?surface=core&account='+AUTH[0]['account'],
               'redemption':'/api/transaction/recovery-redemption','approvalGas':'/api/transaction/permit2-approval-gas',
               'safeExecution':'/api/governance/safe-execution','helpersExecution':'/api/transaction/helpers-execution',
               'waitHead':'/api/transaction/wait/head','waitTransaction':'/api/transaction/wait/transaction?hash='+WAIT_HASH,
               'waitReceipt':'/api/transaction/wait/receipt?hash='+WAIT_HASH,'waitBlock':'/api/transaction/wait/block?blockNumber=101',
               'sharePrecision':'/api/protocol/recovery-share-precision?asset='+PRECISION[1]['asset'],
               'swapAdapter':'/api/governance/helpers-facts?adapter='+SWAP_ADAPTER,
               'proposalTarget':'/api/governance/target-code?address='+SWAP_ADAPTER,
               'nativeBalance':'/api/account/native-balance?holder='+WAIT_TRANSACTION['from'],
               'ensName':'/api/account/ens-name?holder='+WAIT_TRANSACTION['from'],
               'ensAvatar':'/api/account/ens-avatar-record?name=alice.eth',
               'transactionRevert':'/api/transaction/revert?hash='+WAIT_HASH}
        bodies={'redemption':REDEMPTION[1]['payload'],'approvalGas':GAS[1]['payload'],
                'safeExecution':SAFE[0]['payload'],'helpersExecution':HELPERS[-1]['payload']}
        def read(name):return request(base+paths[name],bodies.get(name))
        for row in AUTH:
            status,headers,raw=request(base+'/api/governance/authority?surface='+row['surface']+'&account='+row['account']);value=json.loads(raw)
            assert status==200 and headers['Cache-Control']=='no-store'
            assert value['safeWallet']['value'].lower()==row['safe'] and value['accountCanPause']['value'] is True
            assert value['accountCanUnpause']['value'] is False and value['safeCanUnpause']['value'] is True
        for row in REDEMPTION:
            status,headers,raw=request(base+paths['redemption'],row['payload']);value=json.loads(raw)
            assert status==200 and headers['Cache-Control']=='no-store' and value['rawOut']==row['rawOut']
        for row in PRECISION:
            status,headers,raw=request(base+'/api/protocol/recovery-share-precision?asset='+row['asset']);value=json.loads(raw)
            assert status==200 and headers['Cache-Control']=='no-store' and value['shareDecimals']==row['shareDecimals']
        status,headers,raw=read('swapAdapter');value=json.loads(raw)
        assert status==200 and headers['Cache-Control']=='no-store'
        assert value['adapter']=={'address':SWAP_ADAPTER,'codePresent':{'status':'success','value':True}}
        assert SWAP_ADAPTER in value['configuration']['approvedAdapters']['value']
        status,headers,raw=read('proposalTarget');value=json.loads(raw)
        assert status==200 and headers['Cache-Control']=='no-store' and value['hasCode'] is True
        for row in GAS:
            status,headers,raw=request(base+paths['approvalGas'],row['payload']);value=json.loads(raw)
            assert status==200 and headers['Cache-Control']=='no-store' and value['gas']==row['gas']
        for name,rows,field in (('safeExecution',SAFE,'success'),('helpersExecution',HELPERS,'gas')):
            for row in rows:
                status,headers,raw=request(base+paths[name],row['payload']);value=json.loads(raw)
                assert status==200 and headers['Cache-Control']=='no-store'
                assert value[field]==(row['result'] if name=='safeExecution' else row['gas'])
        for name,field,expected in (('waitHead','blockNumber','101'),('waitTransaction','transaction',WAIT_TRANSACTION),
                ('waitReceipt','receipt',WAIT_RECEIPT),('waitBlock','block',{'number':'0x65','hash':'0x'+'a'*64,'transactions':[WAIT_TRANSACTION]})):
            status,headers,raw=read(name)
            assert status==200 and headers['Cache-Control']=='no-store' and json.loads(raw)[field]==expected
        for name,field,expected in (('nativeBalance','balance',str(2**200)),('ensName','name','alice.eth'),('ensAvatar','avatarRecord','ipfs://bafy-fixture')):
            status,headers,raw=read(name)
            assert status==200 and headers['Cache-Control']=='no-store' and json.loads(raw)[field]==expected
        status,headers,raw=read('transactionRevert');value=json.loads(raw)
        assert status==200 and headers['Cache-Control']=='no-store' and value['data'].startswith('0x08c379a0') and value['reverted'] is False
        request(control+'?mode=missing')
        status,_,raw=read('swapAdapter')
        assert status==200 and json.loads(raw)['adapter']['codePresent']=={'status':'success','value':False}
        status,_,raw=read('proposalTarget')
        assert status==200 and json.loads(raw)['hasCode'] is False
        for name,field in (('waitTransaction','transaction'),('waitReceipt','receipt'),('waitBlock','block')):
            status,_,raw=read(name);assert status==200 and json.loads(raw)[field] is None
        for mode in ('wrong-chain','outage','reorg'):
            request(control+'?mode='+mode)
            for name in paths:
                status,_,raw=read(name);expected=200 if mode=='reorg' and (name.startswith('wait') or name=='transactionRevert') else 503
                assert status==expected and b'password' not in raw,(name,status,raw)
        request(control+'?mode=revert')
        status,_,raw=read('transactionRevert');assert status==200 and json.loads(raw)['reverted'] is True and json.loads(raw)['data'] is None and b'password' not in raw
        assert all(read(name)[0]==503 for name in ('redemption','approvalGas','safeExecution','helpersExecution'))
        request(control+'?mode=delay')
        def deadline(name):
            start=time.monotonic();status,_,raw=read(name);duration=time.monotonic()-start
            assert status==503 and 14.8<=duration<17,(name,status,duration,raw)
            return name,round(duration,2)
        with ThreadPoolExecutor(max_workers=len(paths)) as workers:deadlines=dict(workers.map(deadline,paths))
        request(control+'?mode=normal');assert all(read(name)[0]==200 for name in paths)
        request(control+'?mode=delay')
        caller=socket.create_connection(('127.0.0.1',int(port)))
        caller.sendall(('GET '+paths['authority']+' HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n').encode())
        for _ in range(100):
            if any(call['method']=='eth_call' for call in json.loads(request(control)[2])['calls']):break
            time.sleep(.05)
        caller.close();start=time.monotonic()
        for _ in range(60):
            if 'operation="/api/governance/authority",status="499"' in request(base+'/metrics')[2].decode():break
            time.sleep(.05)
        else:raise AssertionError('Caller disconnect did not cancel authority operation')
        cancelled=round(time.monotonic()-start,2)
        request(control+'?mode=delay')
        caller=socket.create_connection(('127.0.0.1',int(port)))
        caller.sendall(('GET '+paths['waitReceipt']+' HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n').encode())
        for _ in range(100):
            if any(call['method']=='eth_getTransactionReceipt' for call in json.loads(request(control)[2])['calls']):break
            time.sleep(.05)
        caller.close();start=time.monotonic()
        for _ in range(60):
            if 'operation="/api/transaction/wait/receipt",status="499"' in request(base+'/metrics')[2].decode():break
            time.sleep(.05)
        else:raise AssertionError('Caller disconnect did not cancel receipt-wait operation')
        wait_cancelled=round(time.monotonic()-start,2)
        assert not any(call['method'].startswith('eth_send') for call in json.loads(request(control)[2])['calls'])
        logs=docker('logs',API);assert 'password' not in logs and 'private.invalid' not in logs
        docker('stop','--time','20',API);assert int(docker('inspect',API,'--format','{{.State.ExitCode}}'))==0
        print(json.dumps({'result':'pass','configuredAuthoritySurfaces':3,'exactRecoveryPayloads':3,'actualViemApprovalGasCases':3,
            'exactSafeExecutionPayloads':3,'actualViemHelpersOperations':7,'actualViemHelpersGasCases':14,
            'fixedReceiptWaitOperations':4,'nativeReceiptWaitAbsence':True,'losslessNativeWireObjects':True,
            'actualViemRecoveryPrecisionCases':len(PRECISION),
            'freshSwapAdapterCodeAndApproval':True,'nativeEmptyAdapterCode':True,
            'proposalTargetCodeClassification':True,'nativeBalanceWithoutTokenFanout':True,
            'nativeEnsForwardVerificationAndAvatarRecord':True,'fixedHashRevertReplay':True,
            'canonicalityOutageRevertAndRecovery':True,'privateRpcAuthorization':True,'operationDeadlineSeconds':deadlines,
            'callerDisconnectSeconds':cancelled,'imageId':docker('image','inspect',IMAGE,'--format','{{.Id}}'),
            'receiptWaitDisconnectSeconds':wait_cancelled,
            'shutdownExitCode':0,'productEndpointOrDatabaseUsed':False,'walletSignatureOrSubmission':False}))
except Exception:
    subprocess.run(['docker','logs','--tail','20',API],check=False)
    subprocess.run(['docker','logs','--tail','20',RPC],check=False)
    raise
finally:
    subprocess.run(['docker','rm','--force',API,RPC],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',NETWORK],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
