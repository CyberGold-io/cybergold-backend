"""Finite inert controls for scheduling/copy costs; not a live latency claim.

Run with PYTHONPATH pointing at the source arm to compare. Output is JSON;
the graph, snapshots and synchronous search delay are controlled fixtures.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
from statistics import median
import time
from types import SimpleNamespace
from unittest.mock import patch

from cybergold_candidate import pool_snapshot
from cybergold_candidate.economic_quotes import EconomicQuotes
from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.shared_reads import SharedReads
from test_economic_quote_api import SharedStore
from test_progressive_economic_quotes import ScriptedQuoter, economic_request
from test_universal_quote import Engine, Quotes
from test_quoter_topology_reuse import pool, A, B, C, D, BLOCK


async def main():
    base = await Quotes(Engine()).quote(economic_request())
    warm = []
    for _ in range(5):
        first, order = [], []
        async def script(*_args, **_kwargs):
            order.append('search')
            end = time.perf_counter() + .04
            while time.perf_counter() < end:
                pass
            return deepcopy(base)
        service = EconomicQuotes(ScriptedQuoter(script), SharedStore())
        service.store.memory_lookup = lambda *_args, **_kwargs: deepcopy(base)
        async def publish(frame):
            if not first and frame['type'] == 'qualified':
                first.append((time.perf_counter()-started)*1000)
                order.append('selected')
        started = time.perf_counter()
        result = await service.progressive(economic_request(), publish)
        warm.append({'firstSelectedMs': round(first[0], 3), 'order': order,
                     'sameOutput': result['quotedOutput'] == base['quotedOutput']})
        await service.close()

    rows = [pool(A, B, 10, 'v3'), pool(B, C, 11, 'v3')]
    currencies = [A, B, C, D] + ['0x'+format(n, '040x') for n in range(20, 30)]
    for left, source in enumerate(currencies):
        for target in currencies[left+1:]:
            rows.append(pool(source, target, len(rows)+100, 'v3'))
    registry = SimpleNamespace(inventory={row['id']: row for row in rows}, seed=rows[1])
    adapter = CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)
    from cybergold_candidate.quoter import custom_routes
    original = custom_routes.path_steps
    starts = []
    def counted(*args):
        starts.append(True)
        return original(*args)
    started = time.perf_counter()
    with patch.object(custom_routes, 'path_steps', counted):
        nominations = adapter.nominations(A, C, 100, BLOCK, market=True, first=True)
        first_route = next(nominations)
        nominations.close()
    topology = {'firstNominationMs': round((time.perf_counter()-started)*1000, 3),
                'fullGraphWalksBeforeFirst': len(starts), 'poolCount': len(rows),
                'firstPoolIds': [hop['pool']['id'] for hop in first_route[0][0]['hops']]}

    bank = {str(n): {'id': str(n), 'metadata': {'nested': [1]},
        'ticks': [{'index': i, 'liquidityNet': str(i), 'liquidityGross': str(i+1)} for i in range(4096)],
        'bitmapWords': [{'wordPosition': i, 'bitmap': str(i)} for i in range(64)]} for n in range(3)}
    copy_bank = getattr(pool_snapshot, 'copy_pool_bank', deepcopy)
    copies = []
    for _ in range(10):
        started = time.thread_time()
        copied = copy_bank(bank)
        copies.append((time.thread_time()-started)*1000)
    digest = hashlib.sha256(json.dumps(copied, sort_keys=True).encode()).hexdigest()
    copied['0']['ticks'][0]['liquidityNet'] = 'mutated'
    copied['0']['metadata']['nested'].append(2)

    reads = SharedReads()
    async def produce(_keys):
        return [{'value': 7}]
    await reads.many(['known'], produce, retain=True)
    await asyncio.sleep(0)
    started = time.perf_counter()
    with patch('asyncio.tasks.ensure_future', wraps=asyncio.tasks.ensure_future) as scheduled:
        for _ in range(1000):
            values, counts = await reads.many(['known'], produce, retain=True)
    reuse = {'reads': 1000, 'elapsedMs': round((time.perf_counter()-started)*1000, 3),
             'scheduledAwaitables': scheduled.call_count, 'returnedValue': values[0]['value'], 'reused': counts['reused']}
    await reads.close()
    print(json.dumps({'kind': 'inert-mechanism-controls', 'warmWith40msSearchCpu': warm,
        'warmFirstSelectedMedianMs': median(row['firstSelectedMs'] for row in warm),
        'topology': topology, 'copyBank': {'medianCpuMs': round(median(copies), 3), 'contentSha256': digest,
            'private': bank['0']['ticks'][0]['liquidityNet'] == '0' and bank['0']['metadata']['nested'] == [1]},
        'retainedRead': reuse}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
