"""Shared-fixture comparison with the actual retained Node implementation."""
import asyncio
import json
import sys
from pathlib import Path

from cybergold_candidate.market import (
    GOLD_URL, FX_URL, parse_gold_provider, parse_fx_provider,
    parse_gold_payload, parse_fx_payload, resolve_market, response_headers,
)


async def main(reference_path):
    fixtures = json.loads((Path(__file__).parents[1] / 'fixtures/market.json').read_text())
    reference = json.loads(Path(reference_path).read_text())
    parsers = {'goldProvider': parse_gold_provider, 'fxProvider': parse_fx_provider,
               'goldPayload': parse_gold_payload, 'fxPayload': parse_fx_payload}
    actual = []
    for fixture in fixtures:
        if fixture['kind'] == 'resolve':
            requests = []

            async def fetch(url):
                requests.append(url)
                if fixture['error']:
                    raise OSError('Fixture transport failure')
                return fixture['status'], fixture['value']

            result = await resolve_market(fixture['feed'], fixture['lastKnown'], fetch, lambda: fixture['now'])
            result['requests'] = requests
        else:
            result = parsers[fixture['kind']](fixture['value'])
        actual.append({'name': fixture['name'], 'result': result})
    differences = [(expected, observed) for expected, observed in zip(reference, actual, strict=True)
                   if expected != observed]
    if differences:
        raise AssertionError(json.dumps(differences, indent=2))

    # Python cancellation must still stop the caller instead of return fallback.
    started = asyncio.Event()

    async def pending(_url):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(resolve_market('gold', None, pending, lambda: 'unused'))
    await started.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError('Cancellation was swallowed')
    assert response_headers('gold', True) == {'cache-control': 's-maxage=1800, stale-while-revalidate=1800'}
    assert response_headers('fx', True) == {'cache-control': 's-maxage=300, stale-while-revalidate=300'}
    assert response_headers('gold', False) == response_headers('fx', False) == {'cache-control': 'no-store'}
    print(f'PASS: {len(fixtures)} actual Node/Python market comparisons; caller cancellation; cache headers')


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
