"""Marginal local UniRoute depth experiment over the existing Quoter matrix.

All data and Core producer replies are explicitly synthetic. The same ordinary
Quoter, warm-primer procedure, HTTP acquisition, SDK pricing, 5/15-second budget,
funding comparator and selected-plan replay serve every mode. No API key is used.
Run only after source freeze with the pinned Node and frozen Python environment.

Finder-only/deep-25/deep-5 keep the same CustomRoutes fallback and differ only in
the local worker's experimental command flags. Parallel uses the actual normal
factory (CustomRoutes, AlphaRouter, local UniRoute, unconfigured hosted clients).
This evaluates published UniRoute components with explicit local wiring, not a
claim to run Uniswap's unavailable private full routing service.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import subprocess

from cybergold_candidate.quoter.custom_routes import CustomRoutes
from cybergold_candidate.quoter.providers import route_providers
from cybergold_candidate.quoter.ranking import prefer_completed
from cybergold_candidate.quoter.route_tools import PendingRouteTool
from cybergold_candidate.quoter.uniroute_routes import UnirouteLocal
from benchmark_matrix_fixture import matrix_cases
from benchmark_parallel_matrix import ROOT, git, group_summary, source_bindings, trial


MODES = ('finder-only', 'deep-25', 'deep-5', 'parallel')
DEFAULT_CASES = ('core-disjoint-asymmetric-amm', 'market-split-capacity', 'core-shared-acquisition')
BENCHMARK_FILES = ('benchmark_uniroute_depth.py', 'test_benchmark_uniroute_depth.py')


def tools_for_mode(settings, engine, *, mode):
    if mode == 'parallel':
        return route_providers(settings, engine)
    flag = {'finder-only': '--finder-only', 'deep-25': '--split-percentage=25',
            'deep-5': '--split-percentage=5'}[mode]
    return [CustomRoutes(engine.registry), PendingRouteTool(UnirouteLocal(engine,
        command=['node', 'src/uniswap-sdk/uniroute-worker.ts', flag]))]


def bindings():
    result = source_bindings()
    for name in BENCHMARK_FILES:
        path = ROOT / 'python-candidate/tests' / name
        if path.exists():
            result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(result.items()))


def summary(trials):
    groups = []
    for key in sorted({(row['case'], row['cacheMode'], row['strategy']) for row in trials}):
        case, cache, mode = key
        rows = [row for row in trials if (row['case'], row['cacheMode'], row['strategy']) == key]
        work = Counter()
        for row in rows:
            for values in row.get('providerWork', {}).values():
                work.update(values)
        groups.append({'case': case, 'cacheMode': cache, 'mode': mode,
                       **group_summary(rows), 'providerWorkTotals': dict(work)})
    comparisons = []
    for key in sorted({(row['case'], row['cacheMode'], row['repeat']) for row in trials}):
        by_mode = {row['strategy']: row for row in trials
            if (row['case'], row['cacheMode'], row['repeat']) == key}
        baseline = by_mode.get('finder-only')
        for mode, candidate in sorted(by_mode.items()):
            if mode == 'finder-only':
                continue
            row = dict(zip(('case', 'cacheMode', 'repeat'), key, strict=True))
            row.update(mode=mode, baselineStatus=baseline['status'] if baseline else 'missing',
                candidateStatus=candidate['status'], bothCompleted=bool(baseline
                    and baseline['status'] == candidate['status'] == 'completed'))
            if baseline:
                row.update(samePinnedState=baseline['samePinnedStateSha256'] == candidate['samePinnedStateSha256'],
                    sameStartingCanonicalCache=baseline['canonicalCacheBefore'] == candidate['canonicalCacheBefore'],
                    sameStartingCatalog=baseline['catalogBeforeSearch'] == candidate['catalogBeforeSearch'],
                    wallDeltaMs=round(candidate['wallToResultMs']-baseline['wallToResultMs'], 3),
                    rpcAttemptDelta=candidate['metrics'].get('routeDiscovery', {}).get('physicalRpc', {}).get('requests', 0)
                        - baseline['metrics'].get('routeDiscovery', {}).get('physicalRpc', {}).get('requests', 0))
            if row['bothCompleted']:
                left = {'quotedOutput': baseline['netOutput'], 'inputs': baseline['funding']}
                right = {'quotedOutput': candidate['netOutput'], 'inputs': candidate['funding']}
                before, after = int(baseline['netOutput']), int(candidate['netOutput'])
                row.update(outcome='improved' if prefer_completed(right, left, scalar=True)
                    else 'worse' if prefer_completed(left, right, scalar=True) else 'equal',
                    outputDeltaRaw=str(after-before), outputDeltaBps=10000*(after-before)/before if before else None,
                    sameFunding=baseline['funding'] == candidate['funding'])
                if len(baseline['funding']) == len(candidate['funding']) == 1:
                    row['fundingDeltaRaw'] = str(int(candidate['funding'][0]['amount'])
                        - int(baseline['funding'][0]['amount']))
                first_left = baseline['metrics'].get('timeToFirstWholePlanMs')
                first_right = candidate['metrics'].get('timeToFirstWholePlanMs')
                if first_left is not None and first_right is not None:
                    row['firstWholePlanDeltaMs'] = round(first_right-first_left, 3)
            else:
                row['outcome'] = 'baseline-only' if row['baselineStatus'] == 'completed' else (
                    'candidate-only' if row['candidateStatus'] == 'completed' else 'neither-completed')
            comparisons.append(row)
    return {'attemptedTrials': len(trials), 'attemptedComparisons': len(comparisons),
        'outcomes': dict(Counter(row['outcome'] for row in comparisons)),
        'groups': groups, 'comparisons': comparisons}


async def main(args):
    selected = set(args.cases.split(','))
    cases = [case for case in matrix_cases() if case.name in selected]
    modes = args.modes.split(',')
    before = bindings()
    report = {'schema': 'cybergold.uniroute-local-depth.synthetic-comparison.v1',
        'observedAtUTC': datetime.now(timezone.utc).isoformat(), 'head': git('rev-parse', 'HEAD'),
        'branch': git('branch', '--show-current'), 'workingTreeStatus': git('status', '--short').splitlines(),
        'runtime': {'node': subprocess.check_output([args.node, '--version'], text=True).strip(),
                    'python': subprocess.check_output([os.sys.executable, '--version'], text=True).strip()},
        'scope': ['Synthetic pinned ABI pool observations and the unchanged synthetic Core preview model.',
            'Actual full Quoter, production loopback HTTP acquisition, actual SDK arithmetic and worker algorithms.',
            'Every isolated local mode retains the same CustomRoutes fallback; only worker command options differ.',
            'Parallel is the actual normal supplier factory, with hosted providers unconfigured and zero hosted HTTP.',
            'Warm modes receive the same independently executed custom-only primer, excluded from measured work.',
            'Existing 5/15-second whole-plan selection budget, canonicality and owned cancellation are unchanged.',
            'First and final whole-plan output/funding, physical HTTP/members, callbacks and replay are recorded.',
            'Private full UniRoute service, live hosted latency, gas ranking and production economics are not represented.',
            'Failures, missed deadlines and worse results remain in denominators; no gain is required.'],
        'modeDefinitions': {mode: {'customFallback': True,
            'otherProviders': 'normal-all-five-factory' if mode == 'parallel' else 'local-uniroute-only',
            'workerOption': {'finder-only': '--finder-only', 'deep-25': '--split-percentage=25',
                             'deep-5': '--split-percentage=5', 'parallel': 'production-default'}[mode]}
            for mode in modes},
        'cases': [{'name': case.name, 'family': case.family, 'description': case.description,
                   'stateSha256': case.digest} for case in cases],
        'sourceSha256Before': before, 'trials': []}
    for index, case in enumerate(cases):
        for cache in args.cache_modes.split(','):
            for repeat in range(1, args.repeats+1):
                # A reversed repeat gives each strategy both early and late
                # positions without varying its fixture, primer or budget.
                order = modes if (index+repeat) % 2 else list(reversed(modes))
                for mode in order:
                    row = await trial(case, mode, cache, repeat, args.node,
                        rpc_delay_ms=args.rpc_delay_ms, provider_factory=partial(tools_for_mode, mode=mode))
                    report['trials'].append(row)
                    args.output.write_text(json.dumps(report, indent=2)+'\n')
                    print(json.dumps({key: row.get(key) for key in ('case', 'cacheMode', 'repeat',
                        'strategy', 'status', 'netOutput', 'wallToResultMs')}), flush=True)
    report['sourceSha256After'] = bindings()
    report['sourceContentChangedDuringRun'] = before != report['sourceSha256After']
    report['summary'] = summary(report['trials'])
    args.output.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=os.environ.get('CYBERGOLD_TEST_NODE', 'node'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', default=','.join(DEFAULT_CASES))
    parser.add_argument('--modes', default=','.join(MODES))
    parser.add_argument('--cache-modes', default='cold,warm')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--rpc-delay-ms', type=float, default=0)
    asyncio.run(main(parser.parse_args()))
