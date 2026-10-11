import asyncio
import json
import sys
from pathlib import Path

import httpx

from cybergold_candidate.app import create_app


async def main(reference_path):
    counts = {'gold': 0, 'fx': 0}

    def supplier(request):
        feed = 'gold' if 'PAXG' in str(request.url) else 'fx'
        counts[feed] += 1
        attempt = counts[feed]
        if attempt == 1:
            return httpx.Response(503, json={})
        if attempt == 2:
            return httpx.Response(200, json={'extra': True})
        if attempt == 3:
            raise httpx.ConnectError('Fixture disconnected', request=request)
        return httpx.Response(200, json=(
            {'symbol': 'PAXGUSDT', 'price': '3800.25'} if feed == 'gold' else
            {'amount': 1, 'base': 'USD', 'date': '2026-09-30', 'rates': {'EUR': .86, 'CHF': .79, 'RUB': 82}}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as provider:
        app = create_app(client=provider, now=lambda: '2026-09-30T10:00:00.000Z')
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as api:
                results = []
                for feed in ('gold', 'fx'):
                    for index in range(6):
                        response = await api.get('/api/' + feed)
                        results.append({'feed': feed, 'index': index, 'status': response.status_code,
                                        'body': response.json(), 'contentType': response.headers['content-type'],
                                        'cacheControl': response.headers['cache-control'], 'providerCalls': counts[feed]})
                    head = await api.head('/api/' + feed)
                    results.append({'feed': feed, 'method': 'HEAD', 'status': head.status_code,
                                    'body': head.text, 'contentType': head.headers['content-type'],
                                    'cacheControl': head.headers['cache-control'], 'providerCalls': counts[feed]})
    reference = json.loads(Path(reference_path).read_text())
    assert results == reference, json.dumps({'reference': reference, 'python': results}, indent=2)
    print(f'PASS: {len(results)} actual Node/FastAPI HTTP comparisons; HTTP/invalid/transport fallback; provider call counts')


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
