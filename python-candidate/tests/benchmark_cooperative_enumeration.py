"""Local scheduling A/B; fixed topology, real loopback HTTP, no live services.

Run this same file with either revision's src/tests on PYTHONPATH. The sync
mode exercises the deployed iterator; async exercises its local cooperative
replacement. Transport controls do not supply economic quotes.
"""
import argparse
import asyncio
from contextlib import aclosing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

from aiohttp import web
import httpx

from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, bootstrap_scope
from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteTool
from cybergold_candidate.route_observations import (
    RouteObservations, api_exchange, origin_scope, record_api_status, route_observation_scope)
from cybergold_candidate.rpc_transport import rpc_provider
from cybergold_candidate.uniswap_api_queue import UniswapApiQueue
from test_quoter_topology_reuse import A, B, C, D, BLOCK, pool


def fixture(width):
    pools = []
    for index in range(width):
        middle = '0x' + format(index + 100, '040x')
        for fee in (500, 3000, 10000):
            pools.extend((pool(A, middle, 1000+len(pools), 'v3', fee),
                          pool(middle, B, 1001+len(pools), 'v3', fee)))
    pools.extend((pool(B, C, 9998, 'v3'), pool(C, D, 9999, 'v2')))
    return pools


async def trial(options):
    pools = fixture(options.width)
    registry = SimpleNamespace(inventory={row['id']: row for row in pools}, seed=pools[-2])
    adapter = CyberGoldAmmAdapter(SimpleNamespace(registry=registry), C)
    consumed = {'raw': 0, 'closed': False}
    if options.case == 'duplicates':
        offer = [{'amountIn': '101', 'hops': [{'pool': pools[0], 'zeroForOne': True},
            {'pool': pools[1], 'zeroForOne': pools[1]['token0']['address'] != B}]}]
        class Repeated(RouteTool):
            name = 'uniroute-api'
            def discover(self, query):
                def rows():
                    try:
                        for _ in range(options.duplicates):
                            consumed['raw'] += 1
                            yield offer
                    finally:
                        consumed['closed'] = True
                return CandidateFeed(available=rows())
        suppliers = [Repeated()]
        source, target = A, B
    else:
        suppliers = [CustomRoutes(registry)]
        source, target = A, D if options.case == 'disconnected' else C

    recorder = RouteObservations()
    session = RouteBootstrap(suppliers, catalog=registry)
    queue = UniswapApiQueue()
    release, api_entered, rpc_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    timeline, scan_started, scan_finished, emitted = [], [None], [None], [0]
    api_calls = []
    async def api(request):
        api_calls.append(time.perf_counter())
        api_entered.set()
        await release.wait()
        return web.json_response({'quote': {'route': []}})
    async def rpc(request):
        payload = await request.json()
        rpc_entered.set()
        await release.wait()
        return web.json_response({'jsonrpc': '2.0', 'id': payload['id'], 'result': '0x01'})
    app = web.Application()
    app.router.add_post('/quote', api)
    app.router.add_post('/rpc', rpc)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    provider = rpc_provider(base + '/rpc')
    started = time.perf_counter()
    def event(kind):
        timeline.append({'event': kind, 'elapsedMs': round((time.perf_counter()-started)*1000, 3),
            'emittedAtCallback': emitted[0], 'rawAtCallback': consumed['raw'],
            'beforeScanFinished': scan_finished[0] is None})
    async with httpx.AsyncClient(timeout=30) as client:
        async def api_call(index):
            with origin_scope('uniroute-api'):
                await queue.wait()
                with api_exchange():
                    response = await client.post(base + '/quote', json={'fixture': index})
                    record_api_status(response.status_code)
                event('api-response')
        async def rpc_call():
            await provider.make_request('eth_call', [])
            event('rpc-response')
        tasks = []
        lag = []
        stopped = asyncio.Event()
        async def heartbeat():
            while not stopped.is_set():
                expected = time.perf_counter() + .005
                await asyncio.sleep(.005)
                lag.append(max(0, (time.perf_counter()-expected)*1000))
        beat = None
        try:
            with route_observation_scope(recorder), bootstrap_scope(session):
                tasks = [asyncio.create_task(api_call(index)) for index in range(6)]
                tasks.append(asyncio.create_task(rpc_call()))
                await asyncio.gather(api_entered.wait(), rpc_entered.wait())
                beat = asyncio.create_task(heartbeat())
                await asyncio.sleep(0)
                release.set()
                scan_started[0] = time.perf_counter()
                digest = hashlib.sha256()
                first_ms = None
                def record(row):
                    nonlocal first_ms
                    if first_ms is None:
                        first_ms = (time.perf_counter()-scan_started[0])*1000
                    emitted[0] += 1
                    digest.update(json.dumps(row, sort_keys=True, separators=(',', ':')).encode())
                    digest.update(b'\n')
                if options.case == 'families':
                    groups = (await adapter.async_family_offers(source, target, 101, BLOCK)
                              if options.mode == 'async' else adapter.family_offers(source, target, 101, BLOCK))
                    for group in groups:
                        record(group)
                elif options.mode == 'async':
                    async with aclosing(adapter.async_nominations(source, target, 101, BLOCK, first=True)) as rows:
                        async for row in rows:
                            record(row)
                else:
                    for row in adapter.nominations(source, target, 101, BLOCK, first=True):
                        record(row)
                scan_finished[0] = time.perf_counter()
                event('scan-finished')
                await asyncio.gather(*tasks)
                stopped.set()
                await beat
        finally:
            stopped.set()
            for task in (*tasks, *([beat] if beat is not None else [])):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, *([beat] if beat is not None else []), return_exceptions=True)
            queue.close()
            await session.close()
            await provider.disconnect()
            await runner.cleanup()
    return {'mode': options.mode, 'case': options.case, 'width': options.width,
        'inputSha256': hashlib.sha256(json.dumps(pools, sort_keys=True).encode()).hexdigest(),
        'emitted': emitted[0], 'orderedStreamSha256': digest.hexdigest(),
        'scanMs': round((scan_finished[0]-scan_started[0])*1000, 3),
        'firstNominationMs': round(first_ms, 3) if first_ms is not None else None,
        'maximumLoopLagMs': round(max(lag, default=0), 3),
        'apiResponsesBeforeScanEnd': sum(row['event']=='api-response' and row['beforeScanFinished'] for row in timeline),
        'rpcResponsesBeforeScanEnd': sum(row['event']=='rpc-response' and row['beforeScanFinished'] for row in timeline),
        'apiTransportStartsMs': [round((value-started)*1000, 3) for value in api_calls],
        'apiRequests': recorder.api_metrics, 'physicalRpc': recorder.metrics,
        'providerWork': session.metrics['providers'], 'sourceIterator': consumed, 'timeline': timeline}


async def main(options):
    result = {'observedAt': datetime.now(timezone.utc).isoformat(),
        'scope': 'fixed local topology and HTTP scheduling controls; no live API/RPC or economic price claim',
        'trials': [await trial(options) for _ in range(options.repeats)]}
    Path(options.output).write_text(json.dumps(result, indent=2)+'\n')
    for row in result['trials']:
        print(json.dumps({key: row[key] for key in ('mode','case','emitted','scanMs','maximumLoopLagMs',
            'apiResponsesBeforeScanEnd','rpcResponsesBeforeScanEnd','orderedStreamSha256')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('sync','async'), required=True)
    parser.add_argument('--case', choices=('graph','duplicates','families','disconnected'), default='graph')
    parser.add_argument('--width', type=int, default=8)
    parser.add_argument('--duplicates', type=int, default=20000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', required=True)
    asyncio.run(main(parser.parse_args()))
