"""Assembled Linux API against a synthetic, authenticated Helpers provider."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

IMAGE = 'cybergold-basket-preview-candidate:qualified'
RPC, API, NETWORK = ('cybergold-basket-preview-rpc', 'cybergold-basket-preview-api', 'cybergold-basket-preview-fixture')
REFERENCE = json.loads(subprocess.check_output(['node', '--import', 'tsx',
    'python-candidate/tests/node-basket-preview-reference.ts'], text=True))
FIXTURE = '''
import json,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
REF=REFERENCE
class Provider(BaseHTTPRequestHandler):
    mode='normal';calls=[]
    def log_message(self,*args):pass
    def send(self,value,status=200):
        raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        if '?mode=' in self.path:Provider.mode=self.path.split('?mode=')[1];Provider.calls=[]
        self.send({'mode':Provider.mode,'calls':Provider.calls})
    def do_POST(self):
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        method,params=value['method'],value['params'];Provider.calls.append({'method':method,'params':params})
        assert self.headers.get('Authorization')=='Bearer fixture-only'
        if Provider.mode=='outage':return self.send({'error':'https://secret:password@private.invalid'},503)
        if method=='eth_chainId':result='0x7a6a'
        elif method=='eth_getBlockByNumber':result={'number':'0x65','hash':'0x'+('b' if Provider.mode=='reorg' and params[0]!='latest' else 'a')*64}
        elif method=='eth_call':
            if Provider.mode=='delay':time.sleep(16)
            row=next(row for row in REF['rows'] if row['data']==params[0]['data']);result=row['result']
        else:raise AssertionError(method)
        self.send({'jsonrpc':'2.0','id':value['id'],'result':result})
ThreadingHTTPServer(('0.0.0.0',5000),Provider).serve_forever()
'''.replace('REFERENCE', repr(REFERENCE))


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def request(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    value = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(value, timeout=20) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


try:
    docker('network', 'create', NETWORK)
    with tempfile.TemporaryDirectory(prefix='cybergold-basket-') as temp:
        source = Path(temp, 'rpc.py')
        source.write_text(FIXTURE)
        docker('run', '--detach', '--name', RPC, '--network', NETWORK, '--publish', '127.0.0.1::5000',
               '--mount', 'type=bind,src=' + str(source) + ',dst=/tmp/rpc.py,readonly', IMAGE, 'python', '/tmp/rpc.py')
        docker('run', '--detach', '--name', API, '--network', NETWORK, '--publish', '127.0.0.1::3000',
               '--env', 'NEXT_PUBLIC_CHAIN_ID=31338', '--env', 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=0x' + '1' * 40,
               '--env', 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=' + REFERENCE['helpers'],
               '--env', 'NEXT_PUBLIC_RPC_URL=http://' + RPC + ':5000', '--env', 'RPC_URL=http://' + RPC + ':5000',
               '--env', 'RPC_AUTHORIZATION=Bearer fixture-only', IMAGE)
        port = docker('port', API, '3000/tcp').rsplit(':', 1)[1]
        rpcport = docker('port', RPC, '5000/tcp').rsplit(':', 1)[1]
        base, control = 'http://127.0.0.1:' + port, 'http://127.0.0.1:' + rpcport + '/fixture'
        for _ in range(150):
            try:
                if request(base + '/metrics')[0] == 200:
                    break
            except (ConnectionError, OSError):
                pass
            time.sleep(.1)
        for row in REFERENCE['rows']:
            request(control + '?mode=normal')
            status, headers, raw = request(base + '/api/quotes/basket-preview?target=0x0&provider=http://untrusted.invalid', row['request'])
            assert status == 200, (status, raw)
            assert headers['Cache-Control'] == 'no-store'
            value = json.loads(raw)
            assert json.dumps(value['result']).lower() == json.dumps(row['value']).lower()
            calls = json.loads(request(control)[2])['calls']
            contract = [call for call in calls if call['method'] == 'eth_call']
            assert len(contract) == 1 and contract[0]['params'][0]['data'] == row['data']
            assert contract[0]['params'][0]['to'].lower() == REFERENCE['helpers']
            assert contract[0]['params'][1] == {'blockHash': '0x' + 'a' * 64, 'requireCanonical': True}
        for mode in ('reorg', 'outage'):
            request(control + '?mode=' + mode)
            status, _, raw = request(base + '/api/quotes/basket-preview', REFERENCE['rows'][0]['request'])
            assert status == 503 and 'correlationId' in json.loads(raw) and b'password' not in raw
        request(control + '?mode=normal')
        status, _, _ = request(base + '/api/quotes/basket-preview', {'mode': 'issue-exact-out', 'netCygldOut': str(2**256)})
        assert status == 400 and json.loads(request(control)[2])['calls'] == []
        request(control + '?mode=delay')
        started = time.monotonic()
        status, _, raw = request(base + '/api/quotes/basket-preview', REFERENCE['rows'][0]['request'])
        deadline = time.monotonic() - started
        assert status == 503 and 14.8 <= deadline < 17, (status, deadline)
        request(control + '?mode=normal')
        assert request(base + '/api/quotes/basket-preview', REFERENCE['rows'][0]['request'])[0] == 200
        request(control + '?mode=delay')
        body = json.dumps(REFERENCE['rows'][0]['request']).encode()
        caller = socket.create_connection(('127.0.0.1', int(port)))
        caller.sendall(b'POST /api/quotes/basket-preview HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
        for _ in range(100):
            if any(call['method'] == 'eth_call' for call in json.loads(request(control)[2])['calls']):
                break
            time.sleep(.05)
        caller.close()
        cancelled = time.monotonic()
        for _ in range(60):
            if 'operation="/api/quotes/basket-preview",status="499"' in request(base + '/metrics')[2].decode():
                break
            time.sleep(.05)
        else:
            raise AssertionError('Disconnected preview caller did not cancel its operation')
        cancel_seconds = time.monotonic() - cancelled
        logs = docker('logs', API)
        assert 'password' not in logs and 'private.invalid' not in logs
        docker('stop', '--time', '20', API)
        code = int(docker('inspect', API, '--format', '{{.State.ExitCode}}'))
        assert code == 0
        print(json.dumps({'result': 'pass', 'nativeDefaultRoleCommand': True, 'nativePrivateRpcAuthorization': True,
            'actualViemPreviewModes': 4, 'oneCanonicalContractCallPerPreview': True, 'losslessAmountsAndOrder': True,
            'invalidAbiInputWithoutRpc': True, 'reorgOutageRedactionRecovery': True,
            'callerDisconnectSeconds': round(cancel_seconds, 2), 'operationDeadlineSeconds': round(deadline, 2),
            'shutdownExitCode': code, 'testedImageId': docker('image', 'inspect', IMAGE, '--format', '{{.Id}}'),
            'installedEndpointsOrDatabaseUsed': False}))
finally:
    for container in (API, RPC):
        subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
    subprocess.run(['docker', 'network', 'rm', NETWORK], capture_output=True)
