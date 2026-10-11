"""Actual Viem HTTP/retry comparison through standard HTTPX/Web3 boundaries."""
import asyncio
import json
import sys
import httpx
from web3.exceptions import Web3RPCError
from cybergold_candidate.indexer_rpc import IndexerProvider, IndexerRpc, should_retry


async def check(reference):
    for case in reference['policies']:
        if 'code' in case:
            error = Web3RPCError('fixture', rpc_response={'error': {'code': case['code']}})
        elif case.get('abort'):
            error = asyncio.CancelledError()
        else:
            response = httpx.Response(case['status'], request=httpx.Request('POST', 'http://synthetic'))
            error = httpx.HTTPStatusError('fixture', request=response.request, response=response)
        assert should_retry(error) == case['retry'], case
    for case in reference['cases']:
        mode = case['mode']
        attempts, payload, authorization = 0, None, None
        delays = []
        def dispatch(request):
            nonlocal attempts, payload, authorization
            attempts += 1
            payload = json.loads(request.content); payload.pop('id')
            # Web3 encodes the empty params array; Viem omits undefined params.
            payload.pop('params')
            authorization = request.headers.get('Authorization')
            if attempts > 1 and mode != 'always-fail' or mode == 'ok':
                return httpx.Response(200, json={'jsonrpc': '2.0', 'result': '0x7a6a'})
            if mode in ('empty-array', 'string', 'null', 'empty-error', 'error-string'):
                value = [] if mode == 'empty-array' else 'fixture' if mode == 'string' else None if mode == 'null' else {'error': {}} if mode == 'empty-error' else {'error': 'fixture'}
                return httpx.Response(200, content=json.dumps(value), headers={'Content-Type': 'application/json'})
            if mode == 'invalid-json':
                return httpx.Response(200, text='bad-json')
            code = -32005 if mode in ('rpc-limit', 'http-rpc-limit') else -32602
            body = json.dumps({'error': {'code': code, 'message': 'fixture'}}) if mode in ('rpc-limit', 'rpc-invalid', 'http-rpc-invalid', 'http-rpc-limit') else 'fixture'
            return httpx.Response(401 if mode == 'http401' else 200 if mode.startswith('rpc-') else 500, text=body,
                headers={'Retry-After': '2' if mode == 'retry-after' else 'Thu, 01 Oct 2026 02:00:00 GMT' if mode == 'retry-after-date' else ''})
        async def sleep(seconds):
            delays.append(seconds * 1000)
        provider = IndexerProvider('http://synthetic', 'Bearer synthetic', httpx.AsyncClient(transport=httpx.MockTransport(dispatch)))
        client = IndexerRpc(provider=provider, retry_count=0 if case['raw'] else 3, sleep=sleep)
        result, error = None, False
        try:
            result = await client.request('eth_chainId', [])
        except Exception:
            error = True
        finally:
            await client.close()
        actual = {'result': result, 'error': error, 'attempts': attempts, 'delays': delays, 'payload': payload, 'authorization': authorization}
        assert actual == case['expected'], (case, actual)
    sleeps = []
    class Failure:
        async def make_request(self, method, params):
            raise ValueError('fixture')
        async def disconnect(self):
            pass
    async def cancel_sleep(seconds):
        sleeps.append(seconds); raise asyncio.CancelledError()
    try:
        await IndexerRpc(provider=Failure(), sleep=cancel_sleep).request('eth_chainId', [])
        raise AssertionError('cancelled request continued')
    except asyncio.CancelledError:
        assert sleeps == [0.15]
    print(f"PASS: {len(reference['policies'])} retained retry classifications and {len(reference['cases'])} actual Viem/Web3 HTTP response/retry/header paths; cancellation propagates")


if __name__ == '__main__':
    asyncio.run(check(json.load(open(sys.argv[1]))))
