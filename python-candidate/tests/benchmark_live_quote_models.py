"""Read-only paired Sandbox quote/model experiment through the existing RPC wrapper.

Capture predictions before training. Record optional background work separately
from final latency. No calibration swap, reset, wallet or deployment command.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import subprocess
from pathlib import Path
import time
import urllib.request

from benchmark_quote_experiments import public_settings
from cybergold_candidate.quote_cache import BasketMath, IntentSharing, VerifiedGrossSeed
from cybergold_candidate.quote_history import QuoteHistory
from cybergold_candidate.quote_intent import QuoteIntent
from cybergold_candidate.market_swap import MarketQuotes
from cybergold_candidate.route_search import RouteSearch, RouteSearchRpc


async def main(args):
    output = Path(args.output)
    source_root = Path(__file__).parents[1] / 'src/cybergold_candidate'
    document = {'observedAt': datetime.now(timezone.utc).isoformat(),
                'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                'sourceFiles': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_root.glob('quote_*.py')}, 'scope':
                'Local source through the read-only authenticated adapter to remote Sandbox. Paired baseline/production math; three distinct amounts per path. Predictions are captured before answers. Optional state acquisition is after completion and charged separately. Workstation RTT is not deployed App latency.',
                'samples': []}
    def save():
        output.write_text(json.dumps(document, indent=2)+'\n')
    save()
    captured = json.loads(Path(args.evidence).read_text())
    origin = captured['origin']
    with urllib.request.urlopen(origin+'/api/protocol/facts', timeout=30) as response:
        facts = json.load(response)
    settings = public_settings(args.public_env)
    settings.NEXT_PUBLIC_CHAIN_ID = str(facts['context']['chainId'])
    settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS = facts['core']
    settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS = facts['helpers']
    settings.NEXT_PUBLIC_UNISWAP_QUOTER_ADDRESS = args.quoter
    contracts = captured['publicContracts']
    templates = {}
    supplemental = Path(args.evidence).with_name('sandbox-intent-sharing.json')
    samples = captured['samples'] + (json.loads(supplemental.read_text())['samples'] if supplemental.exists() else [])
    for row in samples:
        if row['status'] != 'completed':
            continue
        key = (row['mode'], row['asset'])
        value = deepcopy(row['request'])
        for name in ('token', 'quoteToken', 'adapter'):
            value[name] = contracts.get(value[name], value[name])
        value['orderedAssets'] = [contracts.get(a, a) for a in value['orderedAssets']]
        for target in value['targets']:
            for name in ('inputAsset', 'outputAsset'):
                target[name] = contracts.get(target[name], target[name])
        templates.setdefault(key, value)
    baseline_routes = RouteSearch(settings, RouteSearchRpc(settings), engine=MarketQuotes(settings))
    routes = RouteSearch(settings, RouteSearchRpc(settings), engine=MarketQuotes(settings))
    history = QuoteHistory(settings)
    history.facts_observed(facts)
    baseline = QuoteIntent(settings, baseline_routes)
    upgraded = IntentSharing(QuoteIntent(settings, routes, basket_math=BasketMath(), seeds=VerifiedGrossSeed(), history=history))
    try:
        for (mode, asset), template in templates.items():
            if args.paths and f'{mode}/{asset}' not in args.paths.split(','):
                continue
            for index in range(args.samples):
                amount = int(template['amount']) + args.offset + index * 1000
                value = deepcopy(template)
                value['amount'], value['deadline'] = str(amount), str(int(time.time())+600)
                total = sum(int(t['amount']) for t in value['targets'])
                allocated = 0
                for i, target in enumerate(value['targets']):
                    raw = amount-allocated if i == len(value['targets'])-1 else amount*int(target['amount'])//total
                    target['amount'], allocated = str(raw), allocated+raw
                packet = history.packet(value)
                for variant, service in ([('baseline', baseline), ('production', upgraded)] if index % 2 == 0 else
                                         [('production', upgraded), ('baseline', baseline)]):
                    frames = []
                    row = {'mode': mode, 'asset': asset, 'index': index, 'variant': variant, 'request': value,
                           'packetBeforeAnswer': packet if variant == 'production' else None}
                    started = time.perf_counter()
                    async def update(frame):
                        frames.append({'type': frame['type'], 'arrivedMs': round((time.perf_counter()-started)*1000, 3)})
                    try:
                        result = await service.get(value, update)
                        row.update(status='completed', finalMs=round((time.perf_counter()-started)*1000, 3),
                                   context=result['context'], metrics=result['metrics'],
                                   displayAmount=result['executionAmount'] if mode == 'issue-exact-in' else result['displayAmount'],
                                   outputMinimum=result['preview'].get('minimumAmountOut'))
                    except Exception as error:
                        row.update(status='failure', errorType=type(error).__name__, finalMs=round((time.perf_counter()-started)*1000, 3))
                    row['frames'] = frames
                    if variant == 'production':
                        before = history.reads, history.envelopes
                        background_started = time.perf_counter()
                        await asyncio.gather(*list(history.tasks.values()), return_exceptions=True)
                        row['background'] = {'stateReads': history.reads-before[0], 'stateEnvelopes': history.envelopes-before[1],
                            'elapsedAfterFinalMs': round((time.perf_counter()-background_started)*1000, 3),
                            'hasProtocol': bool(history.states), 'measuredRouteBaselines': len(history.baselines)}
                    document['samples'].append(row)
                    save()
                    print(json.dumps({k: row[k] for k in ('mode', 'asset', 'index', 'variant', 'status', 'finalMs')}), flush=True)
    finally:
        await upgraded.close()
        await routes.close()
        await baseline_routes.close()
        await routes.engine.close()
        await baseline_routes.engine.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-env', required=True)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--paths')
    parser.add_argument('--offset', type=int, default=43111)
    parser.add_argument('--quoter', default='0x61fFE014bA17989E743c5F6cB21bF9697530B21e')
    parser.add_argument('--output', required=True)
    asyncio.run(main(parser.parse_args()))
