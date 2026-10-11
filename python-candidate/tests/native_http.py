"""Disposable local image qualification with an in-container synthetic provider."""
import json
import sys
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

recovery_reference=json.loads(subprocess.check_output(['node','--import','tsx',
    str(Path(__file__).with_name('node-recovery-rpc-reference.ts'))],text=True))[0]

FIXTURE = '''
import asyncio, json, threading, time, tempfile
from pathlib import Path
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import uvicorn
import cybergold_candidate.market as market
from cybergold_candidate.serve import run
from cybergold_candidate.app import create_app
from cybergold_candidate.recovery_http import RecoveryLoader
from cybergold_candidate.telemetry import configure_logging
from cybergold_candidate.faucet import Faucet
from types import SimpleNamespace
RECOVERY_REFERENCE = RECOVERY_FIXTURE_PLACEHOLDER
configure_logging()
with tempfile.TemporaryDirectory(prefix='cybergold-legacy-faucet-') as legacy_root:
    legacy_script=Path(legacy_root)/'fund.py'
    legacy_script.write_text('#!'+sys.executable+'\\nimport json,sys\\nprint(json.dumps({"status":"ok","address":sys.argv[1],"ethWei":"1","tokens":[],"dryRun":True}))\\n')
    legacy_script.chmod(0o700)
    result=asyncio.run(Faucet(None,enabled=True,script_path=str(legacy_script),environment={'NODE_ENV':'test'}).fund('0x'+'a'*40,None,None))
    assert result['dryRun'] is True
class Provider(BaseHTTPRequestHandler):
    calls = 0
    rpc_calls = 0
    def do_POST(self):
        raw = self.rfile.read(int(self.headers['Content-Length']))
        request = json.loads(raw)
        if self.path == '/fund':
            assert self.headers['Authorization'] == 'Bearer '+'1'*64
            if request['address']=='0x'+'c'*40:time.sleep(21)
            payload={'status':'ok','address':request['address'],'ethWei':'1',
                'tokens':[{'symbol':'PAXG','amount':'1'}],'dryRun':False}
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            try:self.wfile.write(json.dumps(payload).encode())
            except BrokenPipeError:pass
            return
        if self.path == '/recovery-rpc':
            method=request['method']
            if method=='eth_chainId':value='0x7a6a'
            elif method.startswith('eth_getBlock'):
                value={'hash':RECOVERY_REFERENCE['hash'],'number':'0x20000000000001','timestamp':'0x1'}
            else:
                assert method=='eth_call'
                contract='core' if request['params'][0]['to'].lower()==RECOVERY_REFERENCE['core'] else 'governance'
                assert request['params'][1]=={'blockHash':RECOVERY_REFERENCE['hash'],'requireCanonical':True}
                value=next(route['response'] for route in RECOVERY_REFERENCE['routes']
                    if route['contract']==contract and route['selector']==request['params'][0]['data'][:10])
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':value}).encode())
            return
        if self.path.startswith('/api/v1/'):
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({'path':self.path,'method':'POST','payload':request}).encode())
            return
        Provider.rpc_calls += 1
        if request['method'] == 'eth_syncing':
            time.sleep(16)  # Exercise the existing fifteen-second RPC deadline.
        if request['method'] == 'eth_blockNumber':
            self.send_response(503); self.end_headers()
            self.wfile.write(b'supplier-private-response')
            return
        value = Provider.rpc_calls if request['method'] == 'net_peerCount' else '0x7a6a'
        self.send_response(200); self.end_headers()
        try: self.wfile.write((' '+json.dumps({'jsonrpc':'2.0','id':request['id'],'result':value})+'\\n').encode())
        except BrokenPipeError: pass
    def do_GET(self):
        if self.path.startswith('/api/v1/'):
            if '/0x'+'c'*40+'/' in self.path:
                time.sleep(16)  # Existing fifteen-second Safe service deadline.
            payload = {'path':self.path,'method':'GET'}
        elif self.path == '/gold':
            Provider.calls += 1
            if Provider.calls == 1:
                time.sleep(11)  # Exercise the existing ten-second supplier deadline.
            payload = {'symbol': 'PAXGUSDT', 'price': '3800.25'}
        else:
            payload = {'amount': 1, 'base': 'USD', 'date': '2026-09-30', 'rates': {'EUR': .86, 'CHF': .79, 'RUB': 82}}
        self.send_response(200); self.end_headers()
        try: self.wfile.write(json.dumps(payload).encode())
        except BrokenPipeError: pass
    def log_message(self, *args): pass
provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
threading.Thread(target=provider.serve_forever, daemon=True).start()
market.GOLD_URL = 'http://127.0.0.1:' + str(provider.server_port) + '/gold'
market.FX_URL = 'http://127.0.0.1:' + str(provider.server_port) + '/fx'
recovery=RecoveryLoader(SimpleNamespace(RPC_URL='http://127.0.0.1:'+str(provider.server_port)+'/recovery-rpc',
    RPC_AUTHORIZATION='Bearer fixture-private',NEXT_PUBLIC_CHAIN_ID='31338',
    NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=RECOVERY_REFERENCE['core'],
    NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=RECOVERY_REFERENCE['governance']),{})
run(create_app(rpc_url='http://127.0.0.1:' + str(provider.server_port) + '/rpc',
                      rpc_authorization='fixture-authorization',
                      safe_service_url='http://127.0.0.1:' + str(provider.server_port),recovery=recovery,
                          faucet_settings={'enabled':True,'url':'http://127.0.0.1:'+str(provider.server_port)+'/fund','token':'1'*64}), host='0.0.0.0', port=3000)
provider.shutdown(); provider.server_close()
'''
FIXTURE=FIXTURE.replace('RECOVERY_FIXTURE_PLACEHOLDER',repr(recovery_reference))
container = 'cybergold-python-market-local-fixture'
try:
    subprocess.run(['docker', 'run', '--detach', '--name', container, '--publish', '127.0.0.1::3000',
                    sys.argv[1] if len(sys.argv)>1 else 'cybergold-python-candidate:market-parity', 'python', '-c', FIXTURE], check=True, capture_output=True)
    port = subprocess.check_output(['docker', 'port', container, '3000/tcp'], text=True).strip().rsplit(':', 1)[1]
    # An unrelated route confirms HTTP startup without consuming a supplier call.
    for attempt in range(150):
        try:
            urllib.request.urlopen('http://127.0.0.1:' + port + '/fixture-startup', timeout=1)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                break
            raise
        except (OSError, ConnectionError):
            if attempt == 149: raise
            time.sleep(.2)
    start = time.monotonic()
    with urllib.request.urlopen('http://127.0.0.1:' + port + '/api/gold', timeout=15) as response:
        fallback = json.load(response)
        assert fallback['price'] == 3320 and fallback['stale'] is True
        assert response.headers['Cache-Control'] == 'no-store'
    elapsed = time.monotonic() - start
    assert 9 <= elapsed <= 13, elapsed
    with urllib.request.urlopen('http://127.0.0.1:' + port + '/api/gold', timeout=3) as response:
        gold = json.load(response)
        assert gold['price'] == 3800.25 and gold['stale'] is False
        assert response.headers['Cache-Control'] == 's-maxage=1800, stale-while-revalidate=1800'
    with urllib.request.urlopen('http://127.0.0.1:' + port + '/api/fx', timeout=3) as response:
        fx = json.load(response)
        assert fx['rates']['EUR'] == .86 and fx['stale'] is False
    def rpc(method, identifier=7, raw=None):
        request = urllib.request.Request('http://127.0.0.1:' + port + '/api/rpc', method='POST',
            data=raw or json.dumps({'jsonrpc':'2.0','id':identifier,'method':method}).encode(),
            headers={'Content-Type':'application/json'})
        try: response = urllib.request.urlopen(request, timeout=18)
        except urllib.error.HTTPError as error: response = error
        with response:
            body = response.read().decode()
            assert response.headers['Cache-Control'] == 'no-store'
            return response.status, json.loads(body), body
    status, result, body = rpc('eth_chainId')
    assert status == 200 and result['result'] == '0x7a6a' and body.startswith(' ') and body.endswith('\n')
    status, result, _ = rpc('eth_blockNumber', identifier='preserved')
    assert status == 502 and result['id'] == 'preserved' and result['error']['code'] == -32603
    assert rpc('net_peerCount')[1]['result'] == 3  # HTTP 503 was not retried.
    assert rpc('eth_sendRawTransaction')[0] == 403
    assert rpc('eth_chainId', raw=b' ' * 1048577)[0] == 413
    assert rpc('net_peerCount')[1]['result'] == 4  # Rejected bodies were not forwarded.
    rpc_start = time.monotonic()
    assert rpc('eth_syncing')[0] == 504
    rpc_elapsed = time.monotonic() - rpc_start
    assert 14 <= rpc_elapsed <= 17, rpc_elapsed
    assert rpc('net_peerCount')[1]['result'] == 6
    def safe(action,address='0x'+'a'*40):
        request=urllib.request.Request('http://127.0.0.1:'+port+'/api/safe',method='POST',
            data=json.dumps({'action':action,'safeAddress':address,'safeTxHash':'0x'+'b'*64,'payload':{'value':'1'}}).encode())
        try:response=urllib.request.urlopen(request,timeout=18)
        except urllib.error.HTTPError as error:response=error
        with response:
            assert response.headers['Cache-Control']=='no-store'
            return response.status,json.load(response)
    for action in ('safe-info','pending-transactions','executed-transactions','transaction-details'):
        status,body=safe(action)
        assert status==200 and body['method']=='GET' and body['path'].startswith('/api/v1/')
    for action in ('propose-transaction','confirm-transaction'):
        status,body=safe(action)
        assert status==200 and body['method']=='POST' and body['payload']=={'value':'1'}
    safe_start=time.monotonic()
    assert safe('safe-info','0x'+'c'*40)[0]==503
    safe_elapsed=time.monotonic()-safe_start
    assert 14 <= safe_elapsed <= 17,safe_elapsed
    def faucet(address):
        request=urllib.request.Request('http://127.0.0.1:'+port+'/api/faucet',method='POST',
            data=json.dumps({'address':address,'requestId':'11111111-1111-4111-8111-111111111111'}).encode(),
            headers={'Content-Type':'application/json','X-Real-IP':'127.0.0.1','X-Forwarded-For':'127.0.0.1',
                'Origin':'http://localhost:3030'})
        try:response=urllib.request.urlopen(request,timeout=24)
        except urllib.error.HTTPError as error:response=error
        with response:
            assert response.headers['Cache-Control']=='no-store'
            return response.status,json.load(response)
    assert faucet('0x'+'a'*40)[0]==200
    faucet_start=time.monotonic()
    assert faucet('0x'+'c'*40)[0]==504
    faucet_elapsed=time.monotonic()-faucet_start
    assert 19 <= faucet_elapsed <= 23,faucet_elapsed
    for _ in range(2):
        with urllib.request.urlopen('http://127.0.0.1:'+port+'/api/recovery/shares?holder='+recovery_reference['holder'],timeout=5) as response:
            assert response.headers['Cache-Control']=='no-store'
            assert json.load(response)==recovery_reference['outcome']['result']
    request=urllib.request.Request('http://127.0.0.1:'+port+'/api/diagnostics',method='POST',
        data=json.dumps({'operation':'quote','outcome':'failed','reason':'wallet_rejected',
            'privateBearer':'fixture-secret-value','parameters':{'secret':'fixture-secret-value'}}).encode(),
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request) as response:assert response.status==202
    with urllib.request.urlopen('http://127.0.0.1:'+port+'/metrics') as response:
        metrics=response.read().decode();assert response.headers['Cache-Control']=='no-store'
        assert 'cybergold_backend_rpc_http_attempts_total' in metrics
        assert 'cybergold_backend_market_last_fresh_timestamp_seconds' in metrics
        assert 'fixture-secret-value' not in metrics
        assert 'cybergold_backend_indexer_history_lag_blocks' not in metrics
    logs=subprocess.check_output(['docker','logs',container],stderr=subprocess.STDOUT,text=True)
    assert 'fixture-secret-value' not in logs
    records=[json.loads(line) for line in logs.splitlines() if line.startswith('{')]
    diagnostic=next(row for row in records if row.get('event')=='client_diagnostic')
    completed=next(row for row in records if row.get('operation')=='/api/diagnostics')
    assert diagnostic['requestId']==completed['requestId']
    subprocess.run(['docker', 'stop', '--time', '15', container], check=True, capture_output=True)
    code = int(subprocess.check_output(['docker', 'inspect', container, '--format', '{{.State.ExitCode}}'], text=True))
    assert code == 0, code
    print(json.dumps({'result': 'pass', 'providerDeadlineSeconds': round(elapsed, 2),
                      'fallbackNotCached': True, 'goldAndFxFresh': True, 'shutdownExitCode': code,
                      'rpcRawRelay': True, 'rpcDeadlineSeconds': round(rpc_elapsed, 2),
                      'rpcNoImplicitRetry': True, 'rpcRejectedBodiesNotForwarded': True,
                      'safeSixActionForwarding':True,'safeDeadlineSeconds':round(safe_elapsed,2),
                      'faucetLocalhostAndPrivateAdapter':True,'faucetDeadlineSeconds':round(faucet_elapsed,2),
                      'recoveryNativeWeb3SnapshotAndRepeat':True,
                      'nativeProcessMetricsAndRedactedCorrelatedDiagnostics':True,
                      'nativeLegacyFaucetSyntheticScript':True,
                      'deployedEndpointsUsed': False, 'databaseUsed': False}))
except Exception:
    subprocess.run(['docker', 'logs', '--tail', '30', container], check=False)
    raise
finally:
    subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
