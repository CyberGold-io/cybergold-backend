"""Paired full-Quoter fixture matrix with genuine loopback RPC acquisition.

Run from the Backend root using its frozen Python environment and pinned Node:

PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python \
  python-candidate/tests/benchmark_parallel_matrix.py --node /path/to/node \
  --output /absolute/path/report.json

Pool and Core data are explicitly synthetic, not live acquisition evidence.
The ordinary producer 5/15-second selection clock is unchanged. No hosted key
is loaded. Failed attempts remain in the report and paired denominators.
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time

from cybergold_candidate.quoter.providers import route_providers
from cybergold_candidate.quoter.ranking import prefer_completed
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.route_observations import RouteObservations, route_observation_scope
from cybergold_candidate.uniswap_routes import pool_identity
from benchmark_matrix_fixture import BLOCK, MatrixService, LoopbackState, matrix_cases
from benchmark_parallel_route_discovery import ROOT, git


BENCHMARK_FILES = ('benchmark_matrix_fixture.py', 'benchmark_parallel_matrix.py',
                   'test_benchmark_parallel_matrix.py')


def source_bindings():
    paths = ('package.json', 'package-lock.json', 'src/uniswap-sdk', 'vendor/uniroute-public',
             'python-candidate/src/cybergold_candidate', 'python-candidate/pyproject.toml',
             'python-candidate/uv.lock', 'python-candidate/tests/quoter_fixture.py',
             'python-candidate/tests/test_universal_quote.py',
             'python-candidate/tests/benchmark_parallel_route_discovery.py')
    names = set(git('ls-files', '--', *paths).splitlines())
    names.update('python-candidate/tests/'+name for name in BENCHMARK_FILES)
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(names)}


def difference(after, before):
    """Difference independently observed transport counters, including methods."""
    result = {}
    for key, value in after.items():
        if isinstance(value, dict):
            result[key] = {name: count-before.get(key, {}).get(name, 0)
                           for name, count in value.items()
                           if count-before.get(key, {}).get(name, 0)}
        else:
            result[key] = value-before.get(key, 0)
    return result


def canonical_cache(registry):
    payload = json.dumps(registry.observed, sort_keys=True, separators=(',', ':'))
    return {'observations': len(registry.observed),
            'getterReplies': len(registry.get_rpc().reads.completed),
            'sha256': hashlib.sha256(payload.encode()).hexdigest()}


def selected_topology(value):
    conversions, uses = [], Counter()
    for operation, conversion in value['plan']['conversions'].items():
        branches = []
        for branch in conversion.get('branches', []):
            physical, native = [], []
            for hop in branch['hops']:
                if 'pool' in hop:
                    identity = json.dumps(pool_identity(hop['pool']), separators=(',', ':'))
                    physical.append(identity)
                    uses[identity] += 1
                else:
                    native.append(hop['kind'])
            branches.append({'physicalPools': physical, 'nativeTransitions': native})
        conversions.append({'operation': operation, 'branches': branches,
                            'origins': conversion.get('discoveryOrigins', [])})
    return {'conversions': conversions,
            'splitConversions': sum(len(item['branches']) > 1 for item in conversions),
            'sharedPhysicalPools': {key: count for key, count in sorted(uses.items()) if count > 1}}


def safe_failure(error):
    public = public_quote_error(error)
    return {'failureType': type(error).__name__, 'failureCode': public.get('code')}


def selected_request(request, value):
    # The selected plan may deliberately declare less funding than the input
    # maximum (e.g. a backward-prefix repair). Replay that declared acquisition,
    # as transaction preparation does, while retaining request metadata.
    return {**deepcopy(request), 'inputs': deepcopy(value['inputs'])}


async def prime(service, request):
    """The identical custom-only request primes each strategy independently."""
    before, started = service.transport.counts(), time.perf_counter()
    row = {'strategy': 'custom-only'}
    try:
        value = await service.quoter.get(deepcopy(request))
        row.update(status='completed', netOutput=value['quotedOutput'], metrics=value.get('metrics', {}))
    except Exception as error:
        row.update(status='failed', **safe_failure(error), metrics=getattr(error, 'quoter_metrics', {}))
    row['wallMs'] = round((time.perf_counter()-started)*1000, 3)
    row['serverRpc'] = difference(service.transport.counts(), before)
    return row


async def trial(case, strategy, cache_mode, repeat, node, *, rpc_delay_ms=0):
    setup, session_cpu = time.perf_counter(), os.times()
    transport = await LoopbackState(case.pools, delay_ms=rpc_delay_ms).start()
    service = MatrixService(case, transport, node, ROOT)
    suppliers = []
    row = {'case': case.name, 'family': case.family, 'strategy': strategy,
           'cacheMode': cache_mode, 'repeat': repeat, 'status': 'pending',
           'samePinnedStateSha256': case.digest}
    try:
        row['harnessSetupMs'] = round((time.perf_counter()-setup)*1000, 3)
        row['catalogBeforePrimer'] = service.catalog_state()
        if cache_mode == 'warm':
            row['primer'] = await prime(service, case.request)
        row['catalogBeforeSearch'] = service.catalog_state()
        row['catalogEventsBeforeSearch'] = deepcopy(service.catalog_events)
        row['canonicalCacheBefore'] = canonical_cache(service.registry)
        family_counts = deepcopy(service.families)
        preview_count = service.preview_calls
        if strategy == 'parallel':
            def providers():
                tools = route_providers(service.settings, service.engine)
                for tool in tools:
                    provider = getattr(tool, 'provider', tool)
                    if hasattr(provider, 'command'):
                        provider.command = [node, str(ROOT / provider.command[1]), *provider.command[2:]]
                suppliers.extend(tools)
                return tools
            service.quoter.route_provider_factory = providers
        server_before = transport.counts()
        started, python_cpu = time.perf_counter(), time.process_time()
        updates = []
        async def publish(frame):
            value = frame['value']
            updates.append({'arrivalMs': round((time.perf_counter()-started)*1000, 3),
                            'netOutput': value['quotedOutput'], 'family': value['routeFamily'],
                            'phase': value.get('searchCoverage', {}).get('selectedPhase'),
                            'origins': value.get('routeOrigins', {}).get('discoveryProviders', [])})
        try:
            value = await service.quoter.get(deepcopy(case.request), publish)
            row.update(status='completed', netOutput=value['quotedOutput'],
                       funding=value['inputs'], routeFamily=value['routeFamily'],
                       estimatedRetainedInputCharges=value.get('estimatedRetainedInputCharges', []),
                       fees=value.get('fees', {}),
                       metrics=value.get('metrics', {}), origins=value.get('routeOrigins'),
                       selectedPhase=value.get('searchCoverage', {}).get('selectedPhase'),
                       selectedTopology=selected_topology(value))
        except Exception as error:
            row.update(status='failed', **safe_failure(error), metrics=getattr(error, 'quoter_metrics', {}))
        row['wallToResultMs'] = round((time.perf_counter()-started)*1000, 3)
        row['pythonCpuMs'] = round((time.process_time()-python_cpu)*1000, 3)
        row['updates'] = updates
        row['completedCandidateFamilies'] = {key: count-family_counts.get(key, 0)
            for key, count in service.families.items() if count-family_counts.get(key, 0)}
        row['syntheticCorePreviewCalls'] = service.preview_calls-preview_count
        row['serverRpc'] = difference(transport.counts(), server_before)
        physical = row['metrics'].get('routeDiscovery', {}).get('physicalRpc', {})
        row['rpcReconciliation'] = {
            'attemptsMinusReceivedEnvelopes': physical.get('requests', 0)-row['serverRpc']['httpEnvelopes'],
            'attemptedMinusReceivedMembers': physical.get('jsonRpcMembers', 0)-row['serverRpc']['jsonRpcMembers']}
        row['canonicalCacheAfter'] = canonical_cache(service.registry)
        row['catalogAfterSearch'] = service.catalog_state()
        row['catalogEvents'] = deepcopy(service.catalog_events)
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
        # Selected-plan replay is separate from measured search work/timing.
        # It uses a fresh candidate bank with canonical observations, never a
        # provider's output number or the prior candidate's mutated pool bank.
        if row['status'] == 'completed':
            replay_started, replay_before = time.perf_counter(), transport.counts()
            recorder = RouteObservations()
            try:
                with route_observation_scope(recorder):
                    replay = await service.quoter.evaluate_selected(selected_request(case.request, value), value['plan'])
                row['selectedReplay'] = {'status': 'completed', 'netOutput': replay['quotedOutput'],
                                         'sameOutput': replay['quotedOutput'] == value['quotedOutput']}
            except Exception as error:
                row['selectedReplay'] = {'status': 'failed', **safe_failure(error)}
            row['selectedReplay'].update(wallMs=round((time.perf_counter()-replay_started)*1000, 3),
                physicalRpc=recorder.metrics, serverRpc=difference(transport.counts(), replay_before))
    finally:
        cleanup = time.perf_counter()
        try:
            await service.close()
        finally:
            await transport.close()
        row['harnessCleanupMs'] = round((time.perf_counter()-cleanup)*1000, 3)
        after_cpu = os.times()
        row['childCpuIncludingPrimerReplayCleanupMs'] = round((after_cpu.children_user+after_cpu.children_system
            - session_cpu.children_user-session_cpu.children_system)*1000, 3)
    return row


def median(rows, field):
    values = [row[field] for row in rows if row.get(field) is not None]
    return statistics.median(values) if values else None


def group_summary(rows):
    completed = [row for row in rows if row['status'] == 'completed']
    first = [row.get('metrics', {}).get('timeToFirstWholePlanMs') for row in rows]
    first = [value for value in first if value is not None]
    return {'attempted': len(rows), 'completed': len(completed), 'failed': len(rows)-len(completed),
            'completionRate': len(completed)/len(rows) if rows else None,
            'medianFirstWholePlanMs': statistics.median(first) if first else None,
            # Wall statistics include failures, not just surviving quotes.
            'medianWallToResultMs': median(rows, 'wallToResultMs'),
            'maxWallToResultMs': max((row['wallToResultMs'] for row in rows), default=None),
            'medianPythonCpuMs': median(rows, 'pythonCpuMs'),
            'medianChildCpuIncludingPrimerReplayCleanupMs': median(rows, 'childCpuIncludingPrimerReplayCleanupMs'),
            'physicalRpcAttempts': sum(row.get('metrics', {}).get('routeDiscovery', {})
                .get('physicalRpc', {}).get('requests', 0) for row in rows),
            'physicalRpcMembers': sum(row.get('metrics', {}).get('routeDiscovery', {})
                .get('physicalRpc', {}).get('jsonRpcMembers', 0) for row in rows),
            'serverRpcEnvelopes': sum(row.get('serverRpc', {}).get('httpEnvelopes', 0) for row in rows),
            'hostedApiAttempts': sum(row.get('metrics', {}).get('routeDiscovery', {})
                .get('apiRequests', {}).get('requests', 0) for row in rows),
            'selectionReasons': dict(Counter(row.get('metrics', {}).get('selectionReason', 'unknown')
                                             for row in rows))}


def summary(trials):
    groups = []
    for key in sorted({(row['case'], row['cacheMode'], row['strategy']) for row in trials}):
        case, cache_mode, strategy = key
        rows = [row for row in trials if (row['case'], row['cacheMode'], row['strategy']) == key]
        groups.append({'case': case, 'cacheMode': cache_mode, 'strategy': strategy, **group_summary(rows)})
    pairs = []
    for key in sorted({(row['case'], row['cacheMode'], row['repeat']) for row in trials}):
        paired = {row['strategy']: row for row in trials
                  if (row['case'], row['cacheMode'], row['repeat']) == key}
        left, right = paired.get('custom-only'), paired.get('parallel')
        pair = dict(zip(('case', 'cacheMode', 'repeat'), key, strict=True))
        pair.update(baselineStatus=left['status'] if left else 'missing',
                    parallelStatus=right['status'] if right else 'missing')
        both = bool(left and right and left['status'] == right['status'] == 'completed')
        pair['bothCompleted'] = both
        if left and right:
            pair.update(samePinnedState=left['samePinnedStateSha256'] == right['samePinnedStateSha256'],
                sameStartingCanonicalCache=left['canonicalCacheBefore'] == right['canonicalCacheBefore'],
                wallDeltaMs=round(right['wallToResultMs']-left['wallToResultMs'], 3),
                physicalRpcDelta=right['metrics'].get('routeDiscovery', {}).get('physicalRpc', {}).get('requests', 0)
                    - left['metrics'].get('routeDiscovery', {}).get('physicalRpc', {}).get('requests', 0))
            if 'catalogBeforeSearch' in left and 'catalogBeforeSearch' in right:
                pair['sameStartingCatalog'] = left['catalogBeforeSearch'] == right['catalogBeforeSearch']
        if both:
            baseline, result = int(left['netOutput']), int(right['netOutput'])
            incumbent = {'quotedOutput': left['netOutput'], 'inputs': left['funding']}
            candidate = {'quotedOutput': right['netOutput'], 'inputs': right['funding']}
            pair.update(outputDeltaRaw=str(result-baseline),
                outputDeltaBps=10000*(result-baseline)/baseline if baseline else None,
                sameFunding=left['funding'] == right['funding'],
                outcome='improved' if prefer_completed(candidate, incumbent, scalar=True) else
                    'worse' if prefer_completed(incumbent, candidate, scalar=True) else 'equal')
            if len(left['funding']) == len(right['funding']) == 1:
                pair['fundingDeltaRaw'] = str(int(right['funding'][0]['amount'])-int(left['funding'][0]['amount']))
            first_left = left['metrics'].get('timeToFirstWholePlanMs')
            first_right = right['metrics'].get('timeToFirstWholePlanMs')
            if first_left is not None and first_right is not None:
                pair['firstWholePlanDeltaMs'] = round(first_right-first_left, 3)
        else:
            pair['outcome'] = ('baseline-only' if pair['baselineStatus'] == 'completed' else
                'parallel-only' if pair['parallelStatus'] == 'completed' else 'neither-completed')
        pairs.append(pair)
    return {'attemptedTrials': len(trials), 'attemptedPairs': len(pairs),
            'pairedOutcomes': dict(Counter(row['outcome'] for row in pairs)),
            'groups': groups, 'paired': pairs,
            'allStrategies': {name: group_summary([row for row in trials if row['strategy'] == name])
                              for name in ('custom-only', 'parallel')}}


async def main(args):
    cases = [case for case in matrix_cases() if not args.cases or case.name in args.cases.split(',')]
    version = subprocess.check_output([args.node, '--version'], text=True).strip()
    before = source_bindings()
    report = {'schema': 'cybergold.parallel-route-tools.synthetic-acquisition-matrix.v1',
        'observedAtUTC': datetime.now(timezone.utc).isoformat(),
        'branch': git('branch', '--show-current'), 'head': git('rev-parse', 'HEAD'),
        'workingTreeStatus': git('status', '--short').splitlines(),
        'runtime': {'node': version, 'nodeExecutable': args.node,
                    'python': subprocess.check_output([os.sys.executable, '--version'], text=True).strip()},
        'scope': ['Invented pinned Mainnet-shaped pool data; loopback HTTP, not live chain or API evidence.',
            'Actual full Quoter, public RouteTool factory, AlphaRouter, published UniRoute RouteFinder and SDK pricing.',
            'Identical initial topology catalog for each pair; canonical getter/bitmap/tick observations are acquired.',
            'Delayed-catalog case starts anchor-only; the full synthetic chain state is available while ordinary discovery publishes connector identities after 300 ms.',
            'Each warm custom-only primer independently expands its own catalog before the measured strategy starts.',
            'Cold: fresh registry/getter cache/SDK. Warm: identical custom-only primer, reported separately and excluded from measured counters.',
            'New AlphaRouter and UniRoute-local supplier processes remain search-owned in both cache modes.',
            'Core preview is an explicitly synthetic producer reply through the normal callback, never an onchain observation.',
            'Pure Market fixtures make Core preview ordinarily unavailable; Market+Core fixtures evaluate both families.',
            'Both hosted tools are constructed but unconfigured; no credentials loaded and no hosted latency claim.',
            'Default producer selection clock remains 5 seconds then up to 15 seconds if no qualified candidate.',
            'Physical RPC HTTP attempts include actual loopback posts; JSON-RPC members and server receipts also reported.',
            'Primer/replay work is separate; measured wall summaries retain failed attempts.',
            'Python CPU covers measured search; fully reaped child CPU covers the complete session including any primer, replay and cleanup.',
            'Small controlled-fixture sample does not establish production economics, gas cost or production RPC savings.'],
        'selectionClockSeconds': {'initial': 5, 'maximum': 15},
        'fixtureTransport': {'kind': 'aiohttp-loopback-http-json-rpc', 'artificialDelayMs': args.rpc_delay_ms},
        'cases': [{'name': case.name, 'family': case.family, 'description': case.description,
                   'syntheticCorePreview': case.core_preview, 'block': BLOCK,
                   'request': case.request, 'stateSha256': case.digest,
                   'initialCatalog': 'anchor-only' if case.catalog_delay_ms else 'complete',
                   'controlledCatalogDelayMs': case.catalog_delay_ms,
                   'poolProtocols': dict(Counter(pool['protocol'] for pool in case.pools))} for case in cases],
        'sourceSha256Before': before, 'trials': []}
    for index, case in enumerate(cases):
        for cache_mode in args.cache_modes.split(','):
            for repeat in range(1, args.repeats+1):
                order = ('custom-only', 'parallel') if (index+repeat) % 2 else ('parallel', 'custom-only')
                for strategy in order:
                    row = await trial(case, strategy, cache_mode, repeat, args.node,
                                      rpc_delay_ms=args.rpc_delay_ms)
                    report['trials'].append(row)
                    args.output.write_text(json.dumps(report, indent=2)+'\n')
                    print(json.dumps({key: row.get(key) for key in ('case', 'cacheMode', 'repeat',
                        'strategy', 'status', 'netOutput', 'wallToResultMs')}), flush=True)
    report['sourceSha256After'] = source_bindings()
    report['sourceContentChangedDuringRun'] = before != report['sourceSha256After']
    report['summary'] = summary(report['trials'])
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'report': str(args.output), 'pairedOutcomes': report['summary']['pairedOutcomes']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=os.environ.get('CYBERGOLD_TEST_NODE', 'node'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--cases', help='Comma-separated matrix case names; default all eight.')
    parser.add_argument('--cache-modes', default='cold,warm')
    parser.add_argument('--rpc-delay-ms', type=float, default=0)
    asyncio.run(main(parser.parse_args()))
