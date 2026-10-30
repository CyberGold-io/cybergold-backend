"""Read-only matched nearby-amount searches at one historical Mainnet block.

Use Ops' authenticated tooling wrapper. The six anchor searches and twelve
matched searches never send transactions, copy a Sandbox overlay or persist
chain state. Every failed attempt is retained; there is no retry loop.
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


async def run(args):
    sys.path.insert(0, str(args.source/'python-candidate/src'))
    from cybergold_candidate.environment import load_environment
    from cybergold_candidate.quoter import Quoter
    from cybergold_candidate.quoter.reuse_estimate import arithmetic_estimate, sample_for_quote
    from cybergold_candidate.quote_errors import public_quote_error
    from cybergold_candidate.route_quote_engine import RouteQuoteEngine
    from cybergold_candidate.sdk_worker import SdkWorker
    from cybergold_candidate.uniswap_state import PoolRegistry
    core = '0x601da021cAF3DB5AA63e700D239b5935C370601d'
    usdc = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
    usdt = '0xdAC17F958D2ee523a2206206994597C13D831ec7'
    zero = '0x'+'00'*20
    settings = load_environment({'RPC_URL': os.environ['MAINNET_RPC_URL'],
        'NEXT_PUBLIC_RPC_URL': os.environ['MAINNET_RPC_URL'], 'NEXT_PUBLIC_CHAIN_ID': '1',
        'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': core,
        'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS': '0x30e9aFD21A30B2629BE33508A131AC890368f534',
        'CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS': '0x1B5905175d6a64ABa6C170a1CD52e5DD555C35a8'})
    def scalar(intent, currency, amount):
        return {'intent': intent,
            'inputs': [{'currency': currency if intent == 0 else core, 'amount': str(amount)}],
            'outputCurrency': core if intent == 0 else currency}
    cases = [('eth', 10**18, lambda amount: scalar(0, zero, amount)),
             ('usdc', 100*10**6, lambda amount: scalar(0, usdc, amount)),
             ('sale', 10**18, lambda amount: scalar(1, usdt, amount))]
    if args.cases:
        cases = [case for case in cases if case[0] in args.cases.split(',')]
    digest = hashlib.sha256()
    for path in sorted((args.source/'python-candidate/src').rglob('*.py')):
        digest.update(str(path.relative_to(args.source)).encode()); digest.update(path.read_bytes())
    result = {'scope': __doc__, 'pin': args.pin, 'rows': [], 'hints': [], 'comparisons': [],
        'sourceCommit': subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip(),
        'pythonSourceSha256': digest.hexdigest(), 'finished': False, 'mainnetWrites': 0,
        'conditions': {'cold-acquisition': 'identical learned inventory/metadata, no copied scalar pool observations',
                       'warm-acquisition': 'identical learned inventory/metadata and canonical observations'},
        'baseline': 'same current source and fixed exploration seed, without nearby seed feed',
        'counterSeam': 'physical AsyncHTTPProvider._make_request; logical provider make_request; actual SDK worker sequence',
        'cleanup': []}
    copy_fields = ('inventory', 'metadata', 'lookups', 'lookup_anchors', 'lookup_month', 'discovery_month', 'observed')
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2)+'\n')

    async def search(case, request, label, snapshot=None, neighbors=None):
        registry = PoolRegistry(settings)
        if snapshot:
            for field, value in snapshot.items():
                setattr(registry, field, deepcopy(value))
        sdk = SdkWorker(['node', str(args.source/'src/uniswap-sdk/worker.ts')])
        engine = RouteQuoteEngine(settings, registry, sdk=sdk)
        quoter = Quoter(settings, engine, exploration_seed=1700)
        rpc = registry.get_rpc()
        original_block = rpc.block
        async def pinned(_number=None):
            return await original_block(hex(args.pin))
        rpc.block = pinned
        logical, physical, sizes = Counter(), Counter(), [0, 0]
        original_request, original_transport = rpc.w3.provider.make_request, rpc.w3.provider._make_request
        async def count(method, params):
            logical[method] += 1
            return await original_request(method, params)
        async def transport(method, data):
            physical[method] += 1; sizes[0] += len(data)
            response = await original_transport(method, data)
            sizes[1] += len(response)
            return response
        rpc.w3.provider.make_request, rpc.w3.provider._make_request = count, transport
        first = None
        started, sdk_before = time.perf_counter(), sdk.sequence
        async def update(frame):
            nonlocal first
            if first is None and frame.get('type') == 'qualified':
                first = round((time.perf_counter()-started)*1000, 3)
        row = {'case': case, 'condition': label, 'request': request,
               'neighborsSupplied': neighbors is not None, 'explorationSeed': 1700}
        value = None
        try:
            async def feed():
                return deepcopy(neighbors)
            async with asyncio.timeout(45):
                value = await quoter.quote(request, update, neighbors=feed if neighbors is not None else None)
            row.update(status='success', quotedOutput=value['quotedOutput'], funding=value['inputs'],
                fees=value['fees'], retained=value['estimatedRetainedInputCharges'],
                routeFamily=value['routeFamily'], context=value['context'], metrics=value.get('metrics'))
        except Exception as error:
            row.update(status='failed', errorType=type(error).__name__, code=public_quote_error(error).get('code'),
                       metrics=getattr(error, 'quoter_metrics', None))
        finally:
            row.update(totalMs=round((time.perf_counter()-started)*1000, 3), firstExactMs=first,
                physicalRpc=dict(physical), logicalRpc=dict(logical),
                requestBytes=sizes[0], responseBytes=sizes[1], sdkRequests=sdk.sequence-sdk_before)
            acquired = {field: deepcopy(getattr(registry, field)) for field in copy_fields}
            await engine.close(); await registry.close()
            result['rows'].append(row)
            result['cleanup'].append({'case': case, 'condition': label, 'sdkClosed': sdk.process is None})
            save()
            print(json.dumps({key: row[key] for key in ('case', 'condition', 'status', 'totalMs', 'firstExactMs')}), flush=True)
        return value, acquired, row

    for case_index, (name, upper_amount, build) in enumerate(cases):
        upper, acquired, _ = await search(name, build(upper_amount), 'learn-upper')
        lower, acquired, _ = await search(name, build(upper_amount//2), 'learn-lower', acquired)
        neighbors = {'lower': {'identity': name+'-lower', 'quote': lower} if lower else None,
                     'upper': {'identity': name+'-upper', 'quote': upper} if upper else None}
        for edit_index, percent in enumerate((90, 80)):
            amount = upper_amount*percent//100
            request = build(amount)
            hint_started = time.perf_counter_ns()
            sample = sample_for_quote(upper) if upper else None
            hint = arithmetic_estimate(sample, amount) if sample else None
            result['hints'].append({'case': name, 'request': request, 'estimate': hint,
                'totalMs': round((time.perf_counter_ns()-hint_started)/1_000_000, 6),
                'rpcCalls': 0, 'sdkCalls': 0, 'sample': sample,
                'counterBasis': 'synchronous pure cached-arithmetic call, no provider/SDK access'})
            state = deepcopy(acquired)
            condition = 'cold-acquisition' if percent == 90 else 'warm-acquisition'
            if condition == 'cold-acquisition':
                state['observed'] = {}
            outcomes = {}
            order = ('ordinary', 'neighbors') if (case_index+edit_index) % 2 == 0 else ('neighbors', 'ordinary')
            for variant in order:
                _, _, row = await search(name, request, condition+'-'+variant, state,
                                        neighbors if variant == 'neighbors' else None)
                outcomes[variant] = row
            before, after = outcomes['ordinary'], outcomes['neighbors']
            result['comparisons'].append({'case': name, 'condition': condition, 'request': request,
                'bothSucceeded': before['status'] == after['status'] == 'success',
                'outputDelta': str(int(after['quotedOutput'])-int(before['quotedOutput']))
                    if before['status'] == after['status'] == 'success' else None,
                'terminalMsDelta': round(after['totalMs']-before['totalMs'], 3),
                'firstExactMsDelta': round(after['firstExactMs']-before['firstExactMs'], 3)
                    if after['firstExactMs'] is not None and before['firstExactMs'] is not None else None})
            save()
    result['finished'] = True; save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pin', type=int, default=26299298)
    parser.add_argument('--cases')
    asyncio.run(run(parser.parse_args()))
