"""Read-only local comparison; no production feature flags or reset commands.

PYTHONPATH=src .venv/bin/python tests/benchmark_quote_experiments.py --help
Live mode must run through Ops' existing authenticated_rpc.py wrapper. It uses
the captured public request cohort and App's public configuration, never keys.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import time
import urllib.request
from types import SimpleNamespace

import httpx
from web3 import AsyncWeb3

from cybergold_candidate.quote_intent import QuoteIntent
from cybergold_candidate.quote_cache import VerifiedGrossSeed
from cybergold_candidate.quote_experiments import BasketMath, GrossSeeds, IntentSharing, RecentGroups, SharingQuoterRpc, bracket_step, midpoint_step, ceil_scale_step, upper_secant_step, local_secant_step
from cybergold_candidate.route_search import RouteSearch, RouteSearchRpc, WETH
from cybergold_candidate.shared_reads import SharedReads


from cybergold_candidate.quote_correction import delayed_local_step

VARIANTS = ('baseline', 'quoter-sharing', 'intent-sharing', 'neighbor', 'repeat-seed', 'interpolation',
            'bracket', 'midpoint', 'basket-math', 'route-math', 'completed-math', 'recent-groups', 'sharing+neighbor', 'sharing+math', 'production-sharing',
            'ceil-scale', 'upper-secant', 'local-secant', 'delayed-local')

CORRECTIONS = {'bracket': bracket_step, 'midpoint': midpoint_step,
               'ceil-scale': ceil_scale_step, 'upper-secant': upper_secant_step,
               'local-secant': local_secant_step, 'delayed-local': delayed_local_step}


def public_settings(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        key, sep, raw = line.partition('=')
        key = key.strip()
        if sep and key.startswith('NEXT_PUBLIC_'):
            parts = shlex.split(raw, comments=True)
            values[key] = parts[0] if parts else ''
    values.update(RPC_URL=os.environ['DISTANT_FORKNET_RPC_URL'], RPC_AUTHORIZATION=None)
    return SimpleNamespace(**values)


async def main(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {'observedAt': datetime.now(timezone.utc).isoformat(),
                'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                'sourceDirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True)),
                'transport': 'local synthetic ABI fixture' if args.fixture else 'local backend through existing authenticated loopback adapter to remote Sandbox broker',
                'scope': 'Thirty rounds per fixture path/variant by default: ten fresh distinct amounts, ten identical sequential requests, ten three-client overlapping cohorts (50 samples). First fresh trial has empty experiment banks; later fresh amounts can use earlier organic hints. Provider/connection warm-up is excluded. Live pilot uses the requested rounds. Fixture RTT is an explicitly injected delay, not production latency. No wallet, transaction, fork override or completed Sandbox exact cache. Counters describe calls offered to transport, including cancelled in-flight work; broker internals are unobserved.',
                'fixtureDelayMs': args.delay_ms if args.fixture else None, 'samples': []}
    if args.fixture:
        from test_quote_intent import Provider, QuoteWire, SETTINGS, ASSET_C, request
        settings = SETTINGS
        templates = {(mode, asset): request(mode) for mode in ('issue-exact-in','issue-exact-out','redeem-exact-in','redeem-exact-out') for asset in ('WETH','generic')}
        for (mode, asset), payload in templates.items():
            if asset == 'generic':
                payload['token'] = payload['quoteToken'] = ASSET_C
                for target in payload['targets']:
                    target['inputAsset' if mode == 'issue-exact-in' else 'outputAsset'] = ASSET_C
    else:
        settings = public_settings(args.public_env)
        captured = json.loads(Path(args.evidence).read_text())
        with urllib.request.urlopen(captured['origin']+'/api/protocol/facts', timeout=30) as response:
            facts = json.load(response)
        settings.NEXT_PUBLIC_CHAIN_ID = str(facts['context']['chainId'])
        settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS = facts['core']
        settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS = facts['helpers']
        settings.NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS = args.quoter
        document['configurationContext'] = facts['context']
        contracts = captured['publicContracts']
        templates = {}
        shared_capture = Path(args.evidence).with_name('sandbox-intent-sharing.json')
        samples = captured['samples'] + (json.loads(shared_capture.read_text())['samples'] if shared_capture.exists() else [])
        for row in samples:
            if row['status'] != 'completed':
                continue
            key = (row['mode'], 'WETH' if row['asset'] == 'WETH' else 'generic')
            payload = deepcopy(row['request'])
            for name in ('token','quoteToken','adapter'):
                payload[name] = contracts.get(payload[name], payload[name])
            payload['orderedAssets'] = [contracts.get(a,a) for a in payload['orderedAssets']]
            for target in payload['targets']:
                for name in ('inputAsset','outputAsset'):
                    target[name] = contracts.get(target[name],target[name])
            templates.setdefault(key, payload)
    variants = args.variants.split(',')
    def save():
        output.write_text(json.dumps(document, indent=2)+'\n')
    for (mode, asset), template in templates.items():
        if args.paths and f'{mode}/{asset}' not in args.paths.split(','):
            continue
        services = {}
        for variant in variants:
            quoter_shared = variant in ('quoter-sharing','route-math','completed-math','sharing+neighbor','sharing+math','production-sharing')
            rpc_type = SharingQuoterRpc if quoter_shared else RouteSearchRpc
            counters = {'batchCalls':0,'batchReads':0,'providerReadsRequested':0,'providerReadsIssued':0,'providerCoalesced':0,'providerHttpCalls':0}
            if args.fixture:
                provider, wire = Provider(), QuoteWire()
                wire.send_original = wire.send
                async def delayed(req, wire=wire):
                    await asyncio.sleep(args.delay_ms/1000)
                    return await wire.send_original(req)
                original = provider.make_request
                provider.reads = SharedReads()
                async def delayed_provider(method, params, original=original, provider=provider, counters=counters):
                    async def transport():
                        counters['providerHttpCalls'] += 1
                        await asyncio.sleep(args.delay_ms/1000)
                        return await original(method, params)
                    if method == 'eth_call' and isinstance(params[1],dict) and 'blockHash' in params[1]:
                        return await provider.reads.one(json.dumps([method,params],sort_keys=True),transport)
                    return await transport()
                provider.make_request = delayed_provider
                rpc = rpc_type(settings, AsyncWeb3(provider), httpx.AsyncClient(transport=httpx.MockTransport(delayed)))
            else:
                rpc = rpc_type(settings)
                manager = rpc.w3.provider._request_session_manager
                post = manager.async_make_post_request
                async def counted_post(*parts, post=post, counters=counters, **kwargs):
                    counters['providerHttpCalls'] += 1
                    return await post(*parts, **kwargs)
                manager.async_make_post_request = counted_post
            if variant in ('route-math','completed-math','production-sharing'):
                rpc.retain_completed = True
            batch = rpc.call_batch
            async def counted_batch(calls, block, batch=batch, counters=counters):
                counters['batchCalls'] += 1
                counters['batchReads'] += len(calls)
                return await batch(calls, block)
            rpc.call_batch = counted_batch
            read = rpc.w3.provider.make_request
            async def counted_read(method, params, read=read, rpc=rpc, counters=counters):
                counters['providerReadsRequested'] += 1
                sharing = getattr(rpc.w3.provider, 'reads', None)
                key = json.dumps([method,params], sort_keys=True)
                pending = sharing and method == 'eth_call' and key in sharing.pending
                counters['providerCoalesced' if pending else 'providerReadsIssued'] += 1
                return await read(method, params)
            rpc.w3.provider.make_request = counted_read
            seeds = GrossSeeds(interpolate=variant == 'interpolation',exact=variant=='repeat-seed') if variant in ('neighbor','repeat-seed','interpolation','sharing+neighbor') else None
            if variant == 'production-sharing':
                seeds = VerifiedGrossSeed()
            math = BasketMath() if variant in ('basket-math','completed-math','sharing+math','production-sharing') else None
            routes = RouteSearch(settings, rpc, group_planner=RecentGroups() if variant == 'recent-groups' else None)
            intent = QuoteIntent(settings, routes, seeds=seeds, basket_math=math,
                                 correction=CORRECTIONS.get(variant))
            shared = IntentSharing(intent) if variant in ('intent-sharing','sharing+neighbor','sharing+math','production-sharing') else None
            service = shared or intent
            await rpc.block(None)  # Consistent connection/metadata warm-up outside trials.
            services[variant] = (service, routes, counters, math, shared)
        try:
            for index in range(args.samples):
                order = variants[index % len(variants):]+variants[:index % len(variants)]
                phase = ('fresh','warm','overlap')[index % 3]
                amount = int(template['amount']) + (index//3+1)*(10 if args.fixture else 1000)
                payload = deepcopy(template)
                payload['deadline'] = '1792000000' if args.fixture else str(int(time.time())+600)
                payload['amount'] = str(amount)
                old_sum = sum(int(t['amount']) for t in payload['targets'])
                if old_sum:
                    allocated = 0
                    for j, target in enumerate(payload['targets']):
                        raw = amount-allocated if j == len(payload['targets'])-1 else amount*int(target['amount'])//old_sum
                        allocated += raw
                        target['amount'] = str(raw)
                for variant in order:
                    service, routes, counters, math, shared = services[variant]
                    before = dict(counters)
                    sharing_before = dict(getattr(routes.rpc, 'counts', {}))
                    math_before = math.hits if math else 0
                    joined_before = shared.joined if shared else 0
                    async def call(client):
                        started = time.perf_counter()
                        row = {'variant':variant,'mode':mode,'asset':asset,'phase':phase,'index':index,'client':client,'amount':str(amount)}
                        async def update(event):
                            if event['type'] == 'estimate':
                                row.setdefault('firstEstimateMs',round(1000*(time.perf_counter()-started),3))
                        try:
                            client_payload = {**payload,'deadline':str(int(payload['deadline'])+client)} if phase == 'overlap' and args.different_deadlines else payload
                            result = await service.get(client_payload, update)
                            row.update(status='completed',finalMs=round(1000*(time.perf_counter()-started),3),
                                       context=result['context'], metrics=result['metrics'],
                                       value={key:result[key] for key in ('displayAmount','executionAmount','maximumInputAmount')},
                                       outputMinimum=result['preview'].get('minimumAmountOut'),
                                       finalQuoteDigest=hashlib.sha256(json.dumps(result['quotes'],sort_keys=True).encode()).hexdigest())
                        except Exception as error:
                            row.update(status='failure',errorType=type(error).__name__,finalMs=round(1000*(time.perf_counter()-started),3))
                        return row
                    rows = await asyncio.gather(*(call(client) for client in range(3 if phase == 'overlap' else 1)))
                    delta = {key:counters[key]-before[key] for key in counters}
                    delta['issuedReads'] = delta['batchReads']+delta['providerHttpCalls']
                    delta['httpEnvelopes'] = delta['batchCalls']+delta['providerHttpCalls']
                    delta['quoterSharing'] = {k:v-sharing_before.get(k,0) for k,v in getattr(routes.rpc,'counts',{}).items()}
                    delta['basketMathHits'] = (math.hits if math else 0)-math_before
                    delta['intentJoins'] = (shared.joined if shared else 0)-joined_before
                    rows[0]['cohortTransport'] = delta
                    document['samples'].extend(rows)
                    save()
                if index % 3 == 2:
                    print(json.dumps({'path':f'{mode}/{asset}','completedRound':index+1,'variants':variants}), flush=True)
        finally:
            for service, routes, _, math, shared in services.values():
                if shared: await shared.close()
                if math: await math.close()
                await routes.close()
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', action='store_true')
    parser.add_argument('--delay-ms', type=float, default=4)
    parser.add_argument('--samples', type=int, default=30)
    parser.add_argument('--variants', default=','.join(VARIANTS))
    parser.add_argument('--paths')
    parser.add_argument('--different-deadlines',action='store_true',help='Use a distinct execution deadline for each concurrent client')
    parser.add_argument('--public-env')
    parser.add_argument('--quoter', default='0x61fFE014bA17989E743c5F6cB21bF9697530B21e', help='Previously verified public V3 QuoterV2 address; independent of App fixture configuration')
    parser.add_argument('--evidence')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    asyncio.run(main(args))
