"""Read-only historical RPC cohort for the serving Quoter (or an archived base).

Run through Ops' authenticated RPC wrapper. Captures every attempt, including
failures. It never signs/sends, changes a remote fork, or changes service config.
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path
import resource
import sys
import time


async def run(args):
    sys.path.insert(0, str(args.source / 'python-candidate/src'))
    from cybergold_candidate.environment import load_environment
    from cybergold_candidate.quoter import Quoter
    from cybergold_candidate.quote_errors import public_quote_error
    from cybergold_candidate.route_quote_engine import RouteQuoteEngine
    from cybergold_candidate.sdk_worker import SdkWorker
    from cybergold_candidate.uniswap_state import PoolRegistry
    core = '0x601da021cAF3DB5AA63e700D239b5935C370601d'
    usdt = '0xdAC17F958D2ee523a2206206994597C13D831ec7'
    usdc = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
    paxg = '0x45804880De22913dAFE09f4980848ECE6EcbAf78'
    xaut = '0x68749665FF8D2d112Fa859AA293F07A622782F38'
    zero = '0x' + '00' * 20
    settings = load_environment({'RPC_URL': os.environ['MAINNET_RPC_URL'],
        'NEXT_PUBLIC_RPC_URL': os.environ['MAINNET_RPC_URL'], 'NEXT_PUBLIC_CHAIN_ID': '1',
        'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': core,
        'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS': '0x30e9aFD21A30B2629BE33508A131AC890368f534',
        'CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS': '0x1B5905175d6a64ABa6C170a1CD52e5DD555C35a8'})
    def scalar(intent, currency, amount):
        return {'intent': intent, 'inputs': [{'currency': currency if intent == 0 else core, 'amount': str(amount)}],
                'outputCurrency': core if intent == 0 else currency}
    cases = [('tiny-original', 26247409, scalar(0, usdt, 100000)),
        ('e4-small', 26247790, scalar(0, usdt, 10000)),
        ('e4-tiny', 26247790, scalar(0, usdt, 100000)),
        ('buy100', 26299298, scalar(0, usdt, 100000000)),
        ('buy500', 26299298, scalar(0, usdt, 500000000)),
        ('sale', 26299298, scalar(1, usdt, 10**18)),
        ('usdc', 26299299, scalar(0, usdc, 100000000)),
        ('native-buy', 26299298, scalar(0, zero, 10**15)),
        ('native-sale', 26299298, scalar(1, zero, 10**16)),
        ('basket-buy', 26299298, {'intent': 2, 'inputs': [{'currency': paxg, 'amount': str(10**16)},
            {'currency': xaut, 'amount': '1000000'}], 'outputCurrency': core}),
        ('basket-sale', 26299298, scalar(3, usdt, 10**18))]
    if args.cases:
        cases = [case for case in cases if case[0] in args.cases.split(',')]
    source_hash = hashlib.sha256()
    for path in sorted((args.source / 'python-candidate/src').rglob('*.py')):
        source_hash.update(str(path.relative_to(args.source)).encode())
        source_hash.update(path.read_bytes())
    result = {'scope': __doc__, 'variant': args.variant, 'source': str(args.source),
              'pythonSourceSha256': source_hash.hexdigest(),
              'rows': [], 'cleanup': [], 'finished': False, 'mainnetWrites': 0,
              'counterSeam': 'physical: AsyncHTTPProvider._make_request below shared-read coalescing; logicalRpc: provider facade',
              'catalogSetup': []}
    catalogs = {}
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    for repetition in range(args.repetitions):
        for name, pin, request in cases:
            registry = PoolRegistry(settings)
            sdk = SdkWorker(['node', str(args.sdk_source / 'src/uniswap-sdk/worker.ts')])
            engine = RouteQuoteEngine(settings, registry, sdk=sdk)
            options = {'exploration_seed': 1700 + repetition} if args.variant != 'baseline' else {}
            quoter = Quoter(settings, engine, **options)
            if args.catalog_first:
                catalog_key = (pin, request['intent'], request['inputs'][0]['currency'], request['outputCurrency'])
                if catalog_key not in catalogs:
                    setup = PoolRegistry(settings); setup_engine = RouteQuoteEngine(settings, setup)
                    setup_quoter = Quoter(settings, setup_engine, **options)
                    try:
                        before = time.monotonic()
                        setup_block = await setup.get_rpc().block(hex(pin))
                        assets, _ = await setup_quoter.basis(setup_block)
                        setup_quoter.seed_routes(request, assets)
                        await setup_quoter.discover(request, assets, setup_block)
                        catalogs[catalog_key] = {field: deepcopy(getattr(setup, field)) for field in (
                            'inventory', 'metadata', 'lookups', 'lookup_anchors', 'lookup_month', 'discovery_month')}
                        result['catalogSetup'].append({'case': name, 'totalMs': round((time.monotonic()-before)*1000, 3),
                            'poolObservationsCopied': 0, 'inventory': len(setup.inventory)})
                    finally:
                        await setup_engine.close(); await setup.close()
                for field, value in catalogs[catalog_key].items():
                    setattr(registry, field, deepcopy(value))
            rpc = registry.get_rpc(); original_block = rpc.block
            async def block(_number, original=original_block, number=pin):
                return await original(hex(number))
            rpc.block = block
            physical, logical = Counter(), Counter()
            original_request = rpc.w3.provider.make_request
            original_transport = rpc.w3.provider._make_request
            sizes = [0, 0]
            async def counted(method, params):
                logical[method] += 1
                return await original_request(method, params)
            async def transport(method, data):
                physical[method] += 1
                sizes[0] += len(data)
                response = await original_transport(method, data)
                sizes[1] += len(response)
                return response
            rpc.w3.provider.make_request = counted
            rpc.w3.provider._make_request = transport
            previous = None
            try:
                for condition in ['cold', 'warm']:
                    physical.clear(); logical.clear(); sizes[:] = [0, 0]; sdk_before = sdk.sequence
                    started = time.monotonic()
                    row = {'case': name, 'repetition': repetition, 'condition': condition,
                           'request': request, 'pin': pin, 'seedSupplied': previous is not None}
                    try:
                        async with asyncio.timeout(40):
                            value = await quoter.get(request, seed=previous)
                        row.update(status='success', quote=value)
                        previous = deepcopy(value)
                    except Exception as error:
                        row.update(status='failed', errorType=type(error).__name__,
                            code=public_quote_error(error).get('code'), metrics=getattr(error, 'quoter_metrics', None))
                    row.update(totalMs=round((time.monotonic()-started)*1000, 3), physical=dict(physical),
                        logicalRpc=dict(logical),
                        requestBytes=sizes[0], responseBytes=sizes[1], sdkRequests=sdk.sequence-sdk_before,
                        processPeakRss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                    result['rows'].append(row); save()
                    print(json.dumps({k: row[k] for k in ['case', 'repetition', 'condition', 'status', 'totalMs']}), flush=True)
            finally:
                if args.capture_dir:
                    args.capture_dir.mkdir(parents=True, exist_ok=True)
                    observed = deepcopy(registry.observed)
                    for pool in observed.values():
                        words = pool.get('bitmapWords', [])
                        pool['bitmapWords'] = [word for word in words if int(word['bitmap'])]
                        runs = []
                        for word in sorted(int(row['wordPosition']) for row in words if not int(row['bitmap'])):
                            if runs and runs[-1][1] + 1 == word:
                                runs[-1][1] = word
                            else:
                                runs.append([word, word])
                        pool['zeroBitmapRanges'] = runs
                    capture = {'request': request, 'quote': previous, 'inventory': registry.inventory,
                               'observed': observed, 'basis': await quoter.basis(await original_block(hex(pin)))}
                    (args.capture_dir / (name + '.json')).write_text(json.dumps(capture, separators=(',', ':')) + '\n')
                await engine.close(); await registry.close()
                result['cleanup'].append({'case': name, 'repetition': repetition, 'sdkClosed': sdk.process is None})
                save()
    result['finished'] = True; save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.cwd())
    parser.add_argument('--sdk-source', type=Path, default=Path.cwd())
    parser.add_argument('--variant', choices=['baseline', 'implementation'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--cases')
    parser.add_argument('--capture-dir', type=Path)
    parser.add_argument('--catalog-first', action='store_true')
    asyncio.run(run(parser.parse_args()))
