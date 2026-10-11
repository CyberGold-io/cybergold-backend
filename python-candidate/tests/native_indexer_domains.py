"""Qualify collector/RPC/Multicall/state domains in the actual Linux image."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parents[2]
CODE = '''
import asyncio,json,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,'/fixture')
import test_safe_collector,test_indexer_rpc,test_finalized_multicall,test_indexer_state,test_indexer_recovery,test_dashboard_builder,test_indexer_event_codec,test_worker_engine
from cybergold_candidate.indexer_rpc import IndexerRpc
from cybergold_candidate.worker_rpc import approved_range_reduction
import httpx
fixture=json.load(sys.stdin)
requests={};authorizations=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests[self.path]=requests.get(self.path,0)+1
        authorizations.append(self.headers.get('Authorization'))
        if self.path=='/redirect':
            self.send_response(307);self.send_header('Location','/retry');self.end_headers();return
        if self.path=='/slow':time.sleep(11)
        status=200;body={'result':'0x7a6a'}
        if self.path=='/retry' and requests[self.path]==1:status=500;body={'error':'fixture'}
        if self.path=='/raw':status=413;body={'error':'fixture'}
        if self.path=='/rpc-error':status=500;body={'error':{'code':-32602,'message':'fixture'}}
        if self.path=='/header':body={'result':{'number':'0x67','hash':'0x'+'a'*64,'timestamp':'0x44f'}}
        payload=json.dumps(body).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers()
        try:self.wfile.write(payload)
        except BrokenPipeError:pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
url='http://127.0.0.1:'+str(server.server_port)
async def run():
    await test_safe_collector.check(fixture['safe'])
    await test_indexer_rpc.check(fixture['rpc'])
    await test_finalized_multicall.check(fixture['multicall'])
    await test_indexer_state.check(fixture['state'])
    await test_indexer_recovery.check(fixture['recovery'])
    await test_dashboard_builder.check(fixture['dashboard'])
    test_indexer_event_codec.check(fixture['events'])
    await test_worker_engine.check(fixture['engine'])
    for path in ['/retry','/redirect']:
        client=IndexerRpc(url+path,'Bearer synthetic')
        try:assert await client.chain_id()==31338
        finally:await client.close()
    assert requests['/retry']==3 and requests['/redirect']==1
    client=IndexerRpc(url+'/raw','Bearer synthetic',retry_count=0)
    try:
        try:await client.logs('0x'+'1'*40,{'fromBlock':100,'toBlock':103})
        except httpx.HTTPStatusError as error:assert approved_range_reduction(error)
        else:raise AssertionError('raw HTTP 413 was accepted')
    finally:await client.close()
    assert requests['/raw']==1
    client=IndexerRpc(url+'/rpc-error','Bearer synthetic')
    try:
        try:await client.chain_id()
        except Exception as error:assert error.rpc_response['error']['code']==-32602
        else:raise AssertionError('RPC error body was accepted')
    finally:await client.close()
    assert requests['/rpc-error']==1
    client=IndexerRpc(url+'/header','Bearer synthetic')
    try:
        assert await client.block(103)=={'number':103,'hash':'0x'+'a'*64,'timestamp':1103}
        assert await client.block(block_hash='0x'+'a'*64)=={'number':103,'hash':'0x'+'a'*64,'timestamp':1103}
    finally:await client.close()
    client=IndexerRpc(url+'/slow','Bearer synthetic',retry_count=0)
    started=time.monotonic()
    try:
        try:await client.chain_id()
        except httpx.ReadTimeout:pass
        else:raise AssertionError('worker deadline was not applied')
    finally:await client.close()
    elapsed=time.monotonic()-started
    assert 9.5<elapsed<11 and requests['/slow']==1
    assert all(value=='Bearer synthetic' for value in authorizations)
    return {'nativeHttpRetryAndRawSingleAttempt':True,'nativeJsonRpcErrorPrecedesHttpStatus':True,
        'nativePrivateHeaderAndRedirect':True,'nativeWorkerRpcDeadlineSeconds':round(elapsed,2)}
try:result=asyncio.run(run())
finally:server.shutdown();server.server_close()
print('RESULT:'+json.dumps(result))
'''


if __name__ == '__main__':
    fixture = dict(zip(['safe', 'rpc', 'multicall', 'state', 'recovery', 'dashboard', 'events', 'engine'], [json.loads(Path(path).read_text()) for path in sys.argv[1:]], strict=True))
    image = 'cybergold-python-candidate:market-parity'
    output = subprocess.check_output(['docker', 'run', '--rm', '--interactive',
        '--mount', 'type=bind,source=' + str(ROOT / 'python-candidate/tests') + ',target=/fixture,readonly',
        '--entrypoint', 'python', image, '-c', CODE], input=json.dumps(fixture), text=True)
    assert output.count('PASS:') == 8, output
    result = json.loads(output.rsplit('RESULT:', 1)[1])
    identifier = subprocess.check_output(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'], text=True).strip()
    print(json.dumps({'result': 'pass', 'nativeSafeCollectorComparisons': len(fixture['safe']),
        'nativeRpcRetryClassifications': len(fixture['rpc']['policies']), 'nativeRpcResponseComparisons': len(fixture['rpc']['cases']),
        'nativeMulticallPlans': len(fixture['multicall']['plans']), 'nativeMulticallQueueComparisons': len(fixture['multicall']['cases']),
        'nativeStateReadsComparisons': len(fixture['state']), 'nativeRecoveryReadsComparisons': len(fixture['recovery']),
        'nativeDashboardBuilderComparisons': len(fixture['dashboard']), 'nativeIndexerEventCodecComparisons': len(fixture['events']),
        'nativeWorkerEngineConfigurations': len(fixture['engine']['configCases']), 'nativeWorkerEngineRuns': len(fixture['engine']['runs']), **result,
        'testedImageId': identifier, 'installedEndpointsOrDatabaseUsed': False}))
