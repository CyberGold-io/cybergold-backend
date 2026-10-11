"""Current RPC envelope policy; not yet an installed Python RPC HTTP route."""
import math

READ_METHODS = frozenset((
    'eth_blockNumber', 'eth_call', 'eth_chainId', 'eth_estimateGas',
    'eth_feeHistory', 'eth_gasPrice', 'eth_getBalance', 'eth_getBlockByHash',
    'eth_getBlockByNumber', 'eth_getBlockReceipts', 'eth_getBlockTransactionCountByHash',
    'eth_getBlockTransactionCountByNumber', 'eth_getCode', 'eth_getLogs', 'eth_getProof',
    'eth_getStorageAt', 'eth_getTransactionByBlockHashAndIndex',
    'eth_getTransactionByBlockNumberAndIndex', 'eth_getTransactionByHash',
    'eth_getTransactionCount', 'eth_getTransactionReceipt', 'eth_maxPriorityFeePerGas',
    'eth_syncing', 'net_listening', 'net_peerCount', 'net_version', 'web3_clientVersion',
))
MAX_REQUEST_BYTES = 1024 * 1024
MAX_BATCH_SIZE = 100


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def valid_id(value):
    return value is None or isinstance(value, str) or finite_number(value)


def invalid_request():
    return {'ok': False, 'code': -32600, 'message': 'Invalid JSON-RPC request.'}


def validate_request(request):
    if (not isinstance(request, dict) or request.get('jsonrpc') != '2.0'
            or not isinstance(request.get('method'), str) or 'id' not in request
            or not valid_id(request['id'])
            or ('params' in request and not isinstance(request['params'], (list, dict)))):
        return invalid_request()
    if request['method'] not in READ_METHODS:
        return {'ok': False, 'code': -32601, 'message': 'JSON-RPC method is not allowed.'}
    return {'ok': True}


def validate_payload(payload):
    if isinstance(payload, list):
        if not 0 < len(payload) <= MAX_BATCH_SIZE:
            return invalid_request()
        for request in payload:
            result = validate_request(request)
            if not result['ok']:
                return result
        return {'ok': True}
    return validate_request(payload)


def valid_response(response):
    if (not isinstance(response, dict) or response.get('jsonrpc') != '2.0'
            or 'id' not in response or not valid_id(response['id'])
            or ('result' in response) == ('error' in response)):
        return False
    if 'error' not in response:
        return True
    error = response['error']
    return (isinstance(error, dict) and finite_number(error.get('code'))
            and isinstance(error.get('message'), str))


def valid_response_payload(payload):
    return (bool(payload) and all(valid_response(item) for item in payload)
            if isinstance(payload, list) else valid_response(payload))
