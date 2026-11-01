"""Small offline Quoter comparison using real AlphaRouter and SDK subprocesses.

Run from the Backend root with its installed dependency graph and Node 26:

PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python \
  python-candidate/tests/benchmark_parallel_route_discovery.py \
  --node /absolute/path/to/node --output /absolute/output.json

Both strategies receive identical complete synthetic pool observations. Zero
physical RPC is expected from that injection; this cannot demonstrate RPC
savings, live hosted performance or a production speedup. No API key is used.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from types import SimpleNamespace

from cybergold_candidate.quoter.providers import route_providers
from cybergold_candidate.sdk_worker import SdkWorker
from quoter_fixture import service, synthetic_pool
from test_universal_quote import BLOCK, CORE, PAXG, WETH


ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = (
    'package.json', 'package-lock.json',
    'src/uniswap-sdk/alpha-provider.ts', 'src/uniswap-sdk/alpha-worker.ts',
    'src/uniswap-sdk/uniroute-local.ts', 'src/uniswap-sdk/uniroute-worker.ts',
    'src/uniswap-sdk/engine.ts', 'src/uniswap-sdk/worker.ts',
    'python-candidate/src/cybergold_candidate/quoter/alpha_routes.py',
    'python-candidate/src/cybergold_candidate/quoter/bootstrap.py',
    'python-candidate/src/cybergold_candidate/quoter/candidate_hints.py',
    'python-candidate/src/cybergold_candidate/quoter/provenance.py',
    'python-candidate/src/cybergold_candidate/quoter/search.py',
    'python-candidate/src/cybergold_candidate/quoter/hosted_routes.py',
    'python-candidate/src/cybergold_candidate/quoter/route_tools.py',
    'python-candidate/src/cybergold_candidate/quoter/custom_routes.py',
    'python-candidate/src/cybergold_candidate/quoter/uniroute_routes.py',
    'python-candidate/src/cybergold_candidate/quoter/providers.py',
    'python-candidate/src/cybergold_candidate/quoter/amm_adapter.py',
    'python-candidate/src/cybergold_candidate/route_observations.py',
    'python-candidate/src/cybergold_candidate/route_quote_engine.py',
    'python-candidate/src/cybergold_candidate/sdk_worker.py',
    'python-candidate/src/cybergold_candidate/quote_budget.py',
    'python-candidate/tests/quoter_fixture.py',
    'python-candidate/tests/benchmark_parallel_route_discovery.py',
)


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT, text=True).strip()


def bindings():
    vendor = ROOT / 'vendor/uniroute-public'
    names = {*SOURCE_FILES, *(path.relative_to(ROOT).as_posix()
        for path in vendor.rglob('*') if path.is_file())}
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(names)}


class Resources:
    def __init__(self):
        self.operations = []

    def addAsyncCleanup(self, operation):
        self.operations.append(operation)

    async def close(self):
        outcomes = await asyncio.gather(*(operation() for operation in reversed(self.operations)),
                                        return_exceptions=True)
        return [type(error).__name__ for error in outcomes if isinstance(error, BaseException)]


def fixture():
    connector = synthetic_pool(WETH, PAXG, 601, 'v3', liquidity=10**9)
    anchor = synthetic_pool(PAXG, CORE, 602, 'v4', liquidity=10**9)
    return [connector, anchor]


async def trial(strategy, amount, repeat, node):
    resources = Resources()
    quoter = service(resources, deepcopy(fixture()))
    # This is an injected fixed catalog, not a discovery/acquisition benchmark.
    quoter.seed_routes = lambda *_: None
    async def discover(*_):
        pass
    quoter.discover = discover
    quoter.engine.sdk = SdkWorker([node, str(ROOT / 'src/uniswap-sdk/worker.ts')])
    config = SimpleNamespace(**{**vars(quoter.settings),
        'CYBERGOLD_UNISWAP_API_KEY': None, 'CYBERGOLD_UNISWAP_API_SWAPPER': None})
    suppliers = []
    if strategy == 'parallel':
        def providers():
            rows = route_providers(config, quoter.engine)
            # Keep the public Query -> CandidateFeed factory exactly as used
            # by serving. Only choose this benchmark's pinned Node executable.
            for tool in rows:
                provider = getattr(tool, 'provider', tool)
                if hasattr(provider, 'command'):
                    provider.command = [node, *provider.command[1:]]
            suppliers.extend(rows)
            return rows
        quoter.route_provider_factory = providers
    request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': str(amount)}], 'outputCurrency': CORE}
    started, python_cpu, child_cpu = time.perf_counter(), time.process_time(), os.times()
    updates = []
    async def publish(frame):
        quote = frame['value']
        updates.append({'arrivalMs': round((time.perf_counter() - started) * 1000, 3),
            'netOutput': quote['quotedOutput'], 'phase': quote.get('searchCoverage', {}).get('selectedPhase'),
            'sources': quote.get('routeOrigins', {}).get('discoveryProviders', [])})
    row = {'strategy': strategy, 'repeat': repeat, 'inputRaw': str(amount), 'status': 'pending'}
    try:
        value = await quoter.get(request, publish)
        row.update(status='completed', netOutput=value['quotedOutput'],
            funding=[{'currency': 'WETH' if item['currency'].lower() == WETH.lower() else 'other',
                      'amount': item['amount']} for item in value['inputs']],
            metrics=value.get('metrics', {}), origins=value.get('routeOrigins'),
            selectedPhase=value.get('searchCoverage', {}).get('selectedPhase'))
    except Exception as error:
        row.update(status='failed', failureType=type(error).__name__,
                   metrics=getattr(error, 'quoter_metrics', {}))
    finally:
        row['wallToResultMs'] = round((time.perf_counter() - started) * 1000, 3)
        row['cleanupFailures'] = await resources.close()
        row['wallIncludingCleanupMs'] = round((time.perf_counter() - started) * 1000, 3)
        after = os.times()
        row['pythonCpuMs'] = round((time.process_time() - python_cpu) * 1000, 3)
        row['reapedChildCpuMs'] = round((after.children_user + after.children_system
            - child_cpu.children_user - child_cpu.children_system) * 1000, 3)
        row['updates'] = updates
        row['registryHeadReads'] = quoter.engine.registry.heads
        row['registryCanonicalChecks'] = quoter.engine.registry.verifications
        row['supplierCleanup'] = {}
        for tool in suppliers:
            provider = getattr(tool, 'provider', tool)
            child = getattr(provider, 'process', None)
            row['supplierCleanup'][tool.name] = {
                'closedFlag': getattr(provider, 'closed', None),
                'activeHttpClients': len(getattr(provider, 'clients', ())),
                'childRetired': child is None or child.returncode is not None}
        row['allSuppliersClosed'] = all(item['closedFlag'] is not False
            and item['activeHttpClients'] == 0 and item['childRetired']
            for item in row['supplierCleanup'].values())
    return row


def summary(trials):
    groups = {}
    for strategy in ('custom-only', 'parallel'):
        rows = [row for row in trials if row['strategy'] == strategy]
        completed = [row for row in rows if row['status'] == 'completed']
        first = [row['metrics']['timeToFirstWholePlanMs'] for row in completed
                 if row.get('metrics', {}).get('timeToFirstWholePlanMs') is not None]
        wall = [row['wallToResultMs'] for row in completed]
        groups[strategy] = {'attempted': len(rows), 'completed': len(completed),
            'failed': len(rows) - len(completed),
            'medianFirstWholePlanMs': statistics.median(first) if first else None,
            'medianWallToResultMs': statistics.median(wall) if wall else None,
            'maxWallToResultMs': max(wall) if wall else None,
            'physicalRpcAttempts': sum(row.get('metrics', {}).get('routeDiscovery', {})
                .get('physicalRpc', {}).get('requests', 0) for row in rows),
            'hostedApiAttempts': sum(row.get('metrics', {}).get('routeDiscovery', {})
                .get('apiRequests', {}).get('requests', 0) for row in rows)}
    pairs = []
    keys = sorted({(row['inputRaw'], row['repeat']) for row in trials}, key=lambda key: (int(key[0]), key[1]))
    for amount, repeat in keys:
        paired = {row['strategy']: row for row in trials if row['inputRaw'] == amount and row['repeat'] == repeat}
        left, right = paired.get('custom-only'), paired.get('parallel')
        value = {'inputRaw': amount, 'repeat': repeat,
                 'bothCompleted': bool(left and right and left['status'] == right['status'] == 'completed')}
        if value['bothCompleted']:
            baseline = int(left['netOutput'])
            value.update(outputDeltaRaw=str(int(right['netOutput']) - baseline),
                outputDeltaBps=10000 * (int(right['netOutput']) - baseline) / baseline if baseline else None,
                firstWholePlanDeltaMs=round(right['metrics']['timeToFirstWholePlanMs']
                    - left['metrics']['timeToFirstWholePlanMs'], 3),
                wallDeltaMs=round(right['wallToResultMs'] - left['wallToResultMs'], 3),
                sameFunding=left['funding'] == right['funding'])
        pairs.append(value)
    return {'strategies': groups, 'paired': pairs}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=os.environ.get('CYBERGOLD_TEST_NODE', 'node'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=2, choices=(1, 2))
    args = parser.parse_args()
    version = subprocess.check_output([args.node, '--version'], text=True).strip()
    before = bindings()
    report = {'schema': 'cybergold.shared-route-tools.offline-comparison.v1',
        'observedAtUTC': datetime.now(timezone.utc).isoformat(),
        'baselineCommit': 'e9a4803d3f882af5c88640c01cae71f10be36fb8',
        'branch': git('branch', '--show-current'), 'head': git('rev-parse', 'HEAD'),
        'workingTreeStatus': git('status', '--short').splitlines(),
        'runtime': {'node': version, 'nodeExecutable': args.node},
        'scope': ['Actual Quoter and public RouteQuery -> CandidateFeed API; fresh processes per trial.',
            'Parallel factory includes custom, AlphaRouter, local published UniRoute finder, UniRoute API and Guidestar.',
            'UniRoute local is the pinned published RouteFinder plus explicit missing-dependency bindings, not its private full optimizer.',
            'Identical complete synthetic WETH/PAXG and PAXG/CYGLD pool snapshots, fixed block/hash.',
            'Custom seed/catalog acquisition is replaced by the fixed injected catalog in both strategies.',
            'No mocked AlphaRouter or pricing. Core preview and other basket liquidity are not represented.',
            'UniRoute API and Guidestar deliberately unconfigured; no API key is loaded or used.',
            'UniRoute API integration has no documented engine selector; response engine observations are optional diagnostics.',
            'Zero physical RPC is expected from injected state and does not establish a saving.',
            'No live API latency, real acquisition cost, gas or production performance claim.',
            'Small local timing sample; concurrent qualification/system load is not controlled.',
            'Child CPU is aggregate reaped subprocess usage; Python CPU is reported separately.'],
        'fixture': {'block': BLOCK, 'inputAsset': 'WETH', 'outputAsset': 'CYGLD',
            'rawSizes': ['1000', '10000'], 'samePoolStateSha256': hashlib.sha256(
                json.dumps(fixture(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()},
        'sourceSha256Before': before, 'trials': []}
    for amount in (1000, 10000):
        for repeat in range(1, args.repeats + 1):
            order = ('custom-only', 'parallel') if repeat % 2 else ('parallel', 'custom-only')
            for strategy in order:
                row = await trial(strategy, amount, repeat, args.node)
                report['trials'].append(row)
                args.output.write_text(json.dumps(report, indent=2) + '\n')
                print(json.dumps({key: row.get(key) for key in
                    ('strategy', 'repeat', 'inputRaw', 'status', 'netOutput', 'wallToResultMs')}), flush=True)
    report['sourceSha256After'] = bindings()
    report['sourceContentChangedDuringRun'] = before != report['sourceSha256After']
    report['summary'] = summary(report['trials'])
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(args.output), 'summary': report['summary']}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
