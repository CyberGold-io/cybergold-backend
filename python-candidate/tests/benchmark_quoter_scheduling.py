"""Frozen-cut serving comparison; synthetic chain/Core and hosted HTTP fixtures.

Each strategy owns a fresh registry/SDK/server; warm strategies independently
run the same custom-only primer. Run this identical harness on each source cut.
No live credentials or network service is used, and no production budget,
ranking, optional work or supplier eligibility is changed.
"""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess

from quoter_scheduling_trace import ROOT, bindings, run_fixture


def aggregate(rows):
    groups = {}
    for row in rows:
        key = '/'.join((row['case'], row['cacheMode'], row['strategy']))
        group = groups.setdefault(key, {'trials': 0, 'completed': 0, 'failed': 0,
            'outputs': [], 'firstWholePlanMs': [], 'selectionMs': [], 'canonicalCompletedMs': [],
            'searchWallMs': [], 'physicalRpcAttempts': [], 'apiHttpAttempts': [],
            'quoteCallbacks': [], 'replayExact': 0, 'fullyClosed': 0})
        group['trials'] += 1
        group['completed' if row['status'] == 'completed' else 'failed'] += 1
        if row['status'] == 'completed':
            group['outputs'].append(row['output'])
        metrics = row.get('metrics', {})
        discovery = metrics.get('routeDiscovery', {})
        for target, value in (
            ('firstWholePlanMs', metrics.get('timeToFirstWholePlanMs')),
            ('selectionMs', metrics.get('selectionMs')),
            ('canonicalCompletedMs', metrics.get('canonicalCompletedMs')),
            ('searchWallMs', row.get('searchWallMs')),
            ('physicalRpcAttempts', discovery.get('physicalRpc', {}).get('requests')),
            ('apiHttpAttempts', discovery.get('apiRequests', {}).get('requests', 0)),
            ('quoteCallbacks', sum(p.get('quoteCallbacks', 0) for p in discovery.get('providers', {}).values()))):
            if value is not None:
                group[target].append(value)
        group['replayExact'] += row.get('replaySameOutput') is True
        group['fullyClosed'] += (row.get('allSuppliersClosed') is True and row.get('sdkChildRetired') is True
            and all(row.get('supplierChildrenRetired', {}).values()) and row.get('liveHttpClients') == 0)
    return groups


async def run(args):
    before = bindings()
    report = {'schemaVersion': 1,
        'scope': 'actual-serving-Quoter; synthetic immutable chain/Core; hosted HTTPX response fixtures',
        'interpretation': ['Measures CPU, scheduling and real loopback HTTP state acquisition; no live API or Core performance.',
            'Finite fixture delays are identical across source cuts and strategies, not production deadlines.',
            'First whole-plan latency does not imply equal first-output quality; updates retain economics.',
            'Independent reference is replayed after search and never injected into production candidates.',
            'Warm custom-only primers, selected replay and independent reference work are outside search counters.',
            'Warm primers use identical procedures but runtime coverage can differ; cache digests do not imply matched warm-cache A/B.',
            'Child CPU includes primer, replay and cleanup and may not be interpreted as search-only CPU.'],
        'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip(),
        'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
        'sourceSha256Before': before, 'sourceBindingCount': len(before), 'trials': []}
    for repeat in range(args.repeats):
        order = ('custom-only', 'parallel') if repeat % 2 == 0 else ('parallel', 'custom-only')
        for core in (False, True):
            for cache in ('cold', 'warm'):
                for strategy in order:
                    row = await run_fixture(node=args.node, core_preview=core, cache_mode=cache, strategy=strategy)
                    row['repeat'] = repeat + 1
                    report['trials'].append(row)
                    print(json.dumps({'trial': len(report['trials']), 'case': row['case'], 'cache': cache,
                        'strategy': strategy, 'status': row['status'], 'output': row.get('output'),
                        'firstMs': row.get('metrics', {}).get('timeToFirstWholePlanMs')}), flush=True)
                    Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    report['aggregates'] = aggregate(report['trials'])
    report['sourceSha256After'] = bindings()
    report['sourceContentChangedDuringRun'] = before != report['sourceSha256After']
    Path(args.output).write_text(json.dumps(report, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--repeats', type=int, default=2)
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
