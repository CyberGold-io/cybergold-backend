"""Controlled first-display opportunity using the actual producer; no live RPC."""
import asyncio
import json
from pathlib import Path
import statistics
import sys
import time

from test_route_search import ASSET_C, WETH, service, target


async def trial(mode):
    search, _, wire = service()
    started = time.perf_counter()
    first = None
    improvements = 0

    async def quote(path, amount):
        fee = int.from_bytes(path[20:23])
        await asyncio.sleep({100: .05, 500: .1, 3000: .3, 10000: .9}[fee])
        if fee == 100:
            return None
        return (10000 + fee) if mode == 'exact-in' else (20000 - fee)

    async def progress(event):
        nonlocal first, improvements
        if all(row['best'] is not None for row in event['results']):
            improvements += 1
            if first is None:
                first = (time.perf_counter() - started) * 1000

    wire.on_quote = quote
    try:
        result = await search.get({'mode': mode, 'targets': [target(WETH), target(WETH, ASSET_C)]},
                                  on_update=progress)
        final = (time.perf_counter() - started) * 1000
        return {'mode': mode, 'firstCompleteProvisionalMs': round(first, 3),
                'canonicalFinalMs': round(final, 3),
                'earlierDisplayPercent': round(100 * (1 - first / final), 2),
                'progressSnapshotsWithCompleteBasket': improvements,
                'candidateCalls': result['metrics']['candidateCalls']}
    finally:
        await search.close()


async def main():
    samples = [await trial(mode) for mode in ('exact-in', 'exact-out') for _ in range(3)]
    evidence = {'scope': 'Controlled producer with 50/100/300/900 ms candidate latency, two gold targets. '
                'First complete provisional basket versus canonical final search; no Helpers, UI, supplier or live speedup claim.',
                'samples': samples, 'medianEarlierDisplayPercent': statistics.median(
                    row['earlierDisplayPercent'] for row in samples)}
    Path(sys.argv[1]).write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
