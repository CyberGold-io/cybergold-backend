import asyncio
import json
from pathlib import Path
import sys

import httpx

from cybergold_candidate.app import create_app


async def main(path):
    reference = json.loads(Path(path).read_text())
    call = {'jsonrpc': '2.0', 'id': 7, 'method': 'eth_call', 'params': [{'to': '0x01'}, 'latest']}
    for pair in reference:
        fixture, expected = pair['fixture'], pair['result']
        attempts = 0
        forwarded_body = None
        authenticated = False

        async def supplier(request):
            nonlocal attempts, forwarded_body, authenticated
            response = (fixture.get('responses', []) + [{}] * 2)[attempts]
            attempts += 1
            forwarded_body = request.content.decode()
            authenticated = request.headers.get('authorization') == 'fixture-authorization'
            if response.get('mode') == 'connection':
                raise httpx.ConnectError('fixture-private-transport-error', request=request)
            if response.get('mode') == 'timeout':
                await asyncio.sleep(60)
            return httpx.Response(response.get('status', 200), content=response.get('body', ''), headers=response.get('headers'))

        async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as provider:
            app = create_app(client=provider, rpc_url=fixture.get('url', 'https://fixture.invalid/rpc'),
                             rpc_authorization='fixture-authorization',
                             rpc_timeout_seconds=.04 if fixture['name'] == 'supplier-timeout' else 15)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as api:
                    builder = fixture.get('builder')
                    raw = (b'\xff' if builder == 'invalid-utf8' else b' ' * 1048577 if builder == 'too-large'
                           else ('\ufeff' + json.dumps(call, separators=(',', ':'))).encode() if builder == 'bom'
                           else fixture.get('raw', json.dumps(fixture.get('payload', call), separators=(',', ':'))).encode())
                    headers = {'Content-Type': fixture.get('contentType', 'application/json')}
                    if 'declaredLength' in fixture:
                        headers['Content-Length'] = fixture['declaredLength']
                    response = await api.post('/api/rpc', content=raw, headers=headers)
                    actual = {'status': response.status_code, 'body': response.json(),
                              'cacheControl': response.headers.get('cache-control'), 'contentType': response.headers.get('content-type'),
                              'retryAfter': response.headers.get('retry-after'), 'attempts': attempts,
                              'forwardedBody': forwarded_body, 'authenticated': authenticated,
                              'redirectMode': 'error' if attempts else None}
                    assert actual == {key: value for key, value in expected.items() if key != 'text'}, (fixture['name'], actual, expected)
                    if expected['status'] < 300:
                        assert response.text == expected['text'], (fixture['name'], 'upstream raw body changed')
    print(f'PASS: {len(reference)} actual Node/FastAPI RPC HTTP comparisons; raw relay, bounded bodies, deadline and existing Sandbox retry')


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
