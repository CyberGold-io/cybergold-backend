"""Synthetic RPC and the actual candidate worker inside its Linux image."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import sys
import time
import os

from eth_utils.abi import collapse_if_tuple
from web3 import Web3
import uvicorn

from cybergold_candidate.dashboard_builder import DEFINITIONS
from cybergold_candidate.indexer_state_reads import ABI as STATE_ABI
from cybergold_candidate.indexer_recovery_reads import ABI as RECOVERY_ABI
from cybergold_candidate.worker_main import create_configured_worker

CORE, SAFE, HOLDER = '0x' + '4' * 40, '0x' + '6' * 40, '0x' + '7' * 40
CODEC = Web3().codec
def block_hash(number):return '0x' + f'{number:064x}'


def fixture_log(address, abi, args, block, identity):
    topics = [Web3.to_hex(Web3.keccak(text=abi['name'] + '(' + ','.join(collapse_if_tuple(parameter) for parameter in abi['inputs']) + ')'))]
    for parameter in abi['inputs']:
        if parameter.get('indexed'):
            topics.append('0x' + CODEC.encode([collapse_if_tuple(parameter)], [args[parameter['name']]]).hex())
    non_indexed = [parameter for parameter in abi['inputs'] if not parameter.get('indexed')]
    return {'address': address, 'blockNumber': hex(block), 'blockHash': block_hash(block), 'transactionHash': block_hash(identity),
        'transactionIndex': '0x0', 'logIndex': '0x0', 'removed': False, 'topics': topics,
        'data': '0x' + CODEC.encode([collapse_if_tuple(parameter) for parameter in non_indexed], [args[parameter['name']] for parameter in non_indexed]).hex()}


TRANSFER = next(entry['abi'] for entry in DEFINITIONS['core'] if entry['name'] == 'Transfer')
SAFE_ABI = {'name': 'ExecutionSuccess', 'type': 'event', 'inputs': [{'name': 'txHash', 'type': 'bytes32', 'indexed': False}, {'name': 'payment', 'type': 'uint256', 'indexed': False}]}
LOGS = [fixture_log(CORE, TRANSFER, {'from': '0x' + '0' * 40, 'to': HOLDER, 'value': 2**200}, 100, 10000),
    fixture_log(SAFE, SAFE_ABI, {'txHash': bytes.fromhex('ab' * 32), 'payment': 9}, 101, 10001)]
FUNCTIONS = {}
for abi in [*STATE_ABI, *RECOVERY_ABI['core']]:
    signature = abi['name'] + '(' + ','.join(collapse_if_tuple(parameter) for parameter in abi['inputs']) + ')'
    FUNCTIONS[Web3.to_hex(Web3.keccak(text=signature)[:4])] = abi
AGGREGATE = Web3.to_hex(Web3.keccak(text='aggregate3((address,bool,bytes)[])')[:4])
REQUESTS = []
DELAY = {'nextBlockSeconds': 0, 'active': False}


def call(data):
    abi = FUNCTIONS[data[:10]]
    values = {'totalSupply': 2**200, 'decimals': 18, 'issuanceFeePpm': 5000, 'redemptionFeePpm': 8000, 'paused': False,
        'cygldRefGramsFp18': 10**18, 'basketAssets': [], 'basketTargetsPpm': [], 'basketGoldRefGramsFp18': [],
        'basketCygldPerUnitFp18': [], 'coreAttachedRecoveryAssets': []}
    value = values[abi['name']]
    return CODEC.encode([collapse_if_tuple(parameter) for parameter in abi['outputs']], [value])


def rpc(method, params):
    REQUESTS.append(method)
    if method == 'eth_chainId':return hex(int(os.environ.get('NEXT_PUBLIC_CHAIN_ID', '31338')))
    if method == 'eth_blockNumber':return '0x67'
    if method in ('eth_getBlockByNumber', 'eth_getBlockByHash'):
        delay = DELAY['nextBlockSeconds']
        DELAY['nextBlockSeconds'] = 0
        if delay:
            DELAY['active'] = True
            try:time.sleep(delay)
            finally:DELAY['active'] = False
        number = 103 if params[0] in ('latest', 'finalized') else int(params[0], 16)
        return {'number': hex(number), 'hash': block_hash(number), 'timestamp': hex(1000+number), 'transactions': [],
            'gasLimit': '0x1', 'gasUsed': '0x0', 'difficulty': '0x0', 'size': '0x0', 'totalDifficulty': '0x0'}
    if method == 'eth_getCode':return '0x01' if int(params[1], 16) >= 100 else '0x'
    if method == 'eth_getLogs':
        value = params[0]
        return [entry for entry in LOGS if entry['address'].lower() == value['address'].lower()
            and int(value['fromBlock'], 16) <= int(entry['blockNumber'], 16) <= int(value['toBlock'], 16)
            and (not value.get('topics') or entry['topics'][0] == value['topics'][0])]
    if method == 'eth_call':
        data = params[0]['data']
        if data[:10] == AGGREGATE:
            calls = CODEC.decode(['(address,bool,bytes)[]'], bytes.fromhex(data[10:]))[0]
            return '0x' + CODEC.encode(['(bool,bytes)[]'], [[(True, call('0x' + raw.hex())) for _address, _allow_failure, raw in calls]]).hex()
        return '0x' + call(data).hex()
    raise ValueError('Synthetic method unavailable')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):pass
    def do_GET(self):
        body = json.dumps({'requests': REQUESTS, 'delayActive': DELAY['active']}).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/fixture':
            DELAY['nextBlockSeconds'] = value['delayNextBlockSeconds']
            self.send_response(204); self.end_headers(); return
        try:result = {'jsonrpc': '2.0', 'id': value['id'], 'result': rpc(value['method'], value.get('params', []))}
        except Exception:result = {'jsonrpc': '2.0', 'id': value['id'], 'error': {'code': -32602, 'message': 'Synthetic request unavailable'}}
        body = json.dumps(result).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', 8555), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if '--rpc-only' in sys.argv:
            threading.Event().wait()
        else:
            uvicorn.run(create_configured_worker(), host='0.0.0.0', port=3001, access_log=False)
    finally:server.shutdown(); server.server_close()
