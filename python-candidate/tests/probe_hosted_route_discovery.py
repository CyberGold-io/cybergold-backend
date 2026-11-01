"""Quote-only hosted routing and fresh Mainnet route-engine experiments.

Run through Ops' existing dedicated read-only authenticated RPC adapter:

  ./scripts/with-authenticated-rpc.sh --cwd /path/to/backend -- \\
    env PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python \\
    python-candidate/tests/probe_hosted_route_discovery.py --mode paired-rpc \\
    --node /path/to/node --output /private/tmp/routing-probe.json

Use --mode hosted for UniRoute API + Guidestar only. The optional
--api-env-file reads selected assignments as data, never executes shell, and
does not copy credentials into the report or another file. The canonical
CYBERGOLD_UNISWAP_API_KEY environment setting takes precedence. Missing keys
produce an explicit unavailable result and zero hosted HTTP attempts.

The paired experiment uses fresh production PoolRegistry/RPC/SDK/provider
instances for each trial and the same finalized Mainnet block. It compares
exact-input WETH/USDC market routes, not Core previews, gas-adjusted economics,
the full Quoter scheduler, production traffic or transaction execution. The
remote hosted API cannot be block-pinned: only its nominated topology is
replayed at our pinned block. No remote output amount becomes a local price.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import statistics
import subprocess
import time
from types import SimpleNamespace

from cybergold_candidate.quoter.bootstrap import ProviderUnavailable
from cybergold_candidate.quoter.amm import price_path
from cybergold_candidate.quoter.amm_adapter import CyberGoldAmmAdapter, adapt_candidates
from cybergold_candidate.quoter.candidate_hints import normalize_hints
from cybergold_candidate.quoter.discovery import route_identity
from cybergold_candidate.quoter.providers import route_providers
from cybergold_candidate.quoter.route_tools import RouteQuery
from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.quote_budget import QuoteBudget, SearchStopped, budget_context, current_budget
from cybergold_candidate.routing_encoding import split_runtime, weighted_routes
from cybergold_candidate.route_observations import RouteObservations, origin_scope, route_observation_scope
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.sdk_worker import SdkWorker
from cybergold_candidate.uniswap_state import PoolRegistry, UniswapRpc


ROOT = Path(__file__).resolve().parents[2]
WETH = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
USDC = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
# A quote-only public identity; no wallet, key, balance or signing is created.
QUOTE_ONLY_SWAPPER = '0x0000000000000000000000000000000000000001'
HOSTED = frozenset(('uniroute-api', 'uniswap-guidestar'))
SETTING_NAMES = frozenset(('CYBERGOLD_UNISWAP_API_KEY', 'CYBERGOLD_UNISWAP_API_SWAPPER',
                           'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS'))
SOURCE_PATHS = ('package.json', 'package-lock.json', 'src/uniswap-sdk', 'vendor/uniroute-public',
    'python-candidate/pyproject.toml', 'python-candidate/uv.lock',
    'python-candidate/src/cybergold_candidate',
    'python-candidate/tests/probe_hosted_route_discovery.py',
    'python-candidate/tests/test_probe_hosted_route_discovery.py')


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT, text=True).strip()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def bindings():
    names = set(git('ls-files', '--', *SOURCE_PATHS).splitlines())
    names.add(Path(__file__).relative_to(ROOT).as_posix())
    names.add('python-candidate/tests/test_probe_hosted_route_discovery.py')
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(names)}


def selected_settings(path=None, environment=None):
    """Only read API assignments; never source a file or serialize its values."""
    selected = {}
    if path is not None:
        for line in path.read_text().splitlines():
            words = shlex.split(line, comments=True)
            if words[:1] == ['export']:
                words.pop(0)
            if not words or '=' not in words[0]:
                continue
            name, value = words[0].split('=', 1)
            if name in SETTING_NAMES:
                selected[name] = value
    env = os.environ if environment is None else environment
    selected.update({name: env[name] for name in SETTING_NAMES if name in env})
    selected.setdefault('CYBERGOLD_UNISWAP_API_SWAPPER', QUOTE_ONLY_SWAPPER)
    return SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=None,
        RPC_URL=env.get('MAINNET_RPC_URL'), RPC_AUTHORIZATION=None,
        NEXT_PUBLIC_UNISWAP_V3_FACTORY_ADDRESS=None, **selected)


def configuration(settings, path):
    return {'apiKeyConfigured': bool(getattr(settings, 'CYBERGOLD_UNISWAP_API_KEY', None)),
        'apiCredentialSource': 'environment' if os.environ.get('CYBERGOLD_UNISWAP_API_KEY')
            else 'selected-file' if path is not None else 'unconfigured',
        'rpcConfigured': bool(settings.RPC_URL),
        'rpcTransport': 'existing-ops-authenticated-adapter',
        'swapperRole': 'fixed-quote-only-public-address' if settings.CYBERGOLD_UNISWAP_API_SWAPPER
            == QUOTE_ONLY_SWAPPER else 'configured-public-address'}


def candidate_key(branches):
    return tuple((route['sharePpm'], route_identity(branch['hops']))
        for branch, route in zip(branches, weighted_routes(branches), strict=True))


def normalized_candidates(branches, source, target, origin):
    offers = normalize_hints([{'branches': branches, 'origins': [origin]}], source, target)
    # Generic AMM normalization only; this probe has no Core or anchor policy.
    return adapt_candidates(offers, source, None)


class OneCandidateAdapter(CyberGoldAmmAdapter):
    def __init__(self, engine, branches, origin):
        super().__init__(engine, None)
        self.branches, self.origin = branches, origin

    def nominations(self, *_args, **_kwargs):
        return [(self.branches, [self.origin])]


async def price_candidate(engine, branches, source, target, amount, block, *, origin='cybergold-custom', canonical=None):
    """Reuse serving's native, integer split and private shared-pool replay."""
    adapter = OneCandidateAdapter(engine, branches, origin)
    capture = {}
    async def price(*arguments):
        return await price_path(engine, *arguments)
    _, output, retained = await adapter.convert(source, target, amount, block, {},
        {} if canonical is None else canonical, capture=capture, price_path=price)
    consumed = int(capture['_observation']['consumedInput'])
    return {'amountIn': str(consumed), 'amountOut': str(output),
        'fullyFilled': consumed == amount and not retained,
        'runtimeBranchFunding': split_runtime(amount, capture['template']['routes']),
        'physicalInputCurrency': capture['template']['inputCurrency']}


def pool_proof(registry):
    rows = []
    for state in registry.observed.values():
        rows.append({'protocol': state['protocol'],
            'poolReference': state.get('address') or state['id'],
            'token0': state['token0']['address'], 'token1': state['token1']['address'],
            'feePips': state['feePips'], 'context': state['context'],
            'snapshotSha256': digest(state), 'bitmapWords': len(state.get('bitmapWords', [])),
            'initializedTicks': len(state.get('ticks', []))})
    return sorted(rows, key=lambda row: (row['protocol'], row['poolReference']))


async def trial(settings, block, strategy, amount, repeat, node):
    recorder = RouteObservations()
    budget = current_budget()
    registry = PoolRegistry(settings)
    # A fresh Market catalog; no Core seed or persisted observations are used.
    registry.inventory.clear()
    engine = RouteQuoteEngine(settings, registry,
        sdk=SdkWorker([node, str(ROOT / 'src/uniswap-sdk/worker.ts')]))
    tools, tasks = [], []
    queue = asyncio.Queue()
    started = time.perf_counter()
    elapsed = lambda: round((time.perf_counter() - started) * 1000, 3)
    row = {'strategy': strategy, 'repeat': repeat, 'inputRaw': str(amount), 'status': 'pending',
        'sources': {}, 'nominations': 0, 'candidates': 0, 'uniqueCandidates': 0,
        'duplicateCandidates': 0, 'fullyFundedQuotes': 0, 'partialQuotes': 0,
        'pricingFailures': {}, 'timeToFirstFullyFundedQuoteMs': None, 'best': None}
    failures, seen, canonical = Counter(), {}, {}

    async def supply(tool):
        state = row['sources'][tool.name] = {'status': 'pending', 'startedMs': elapsed(),
            'completedMs': None, 'candidates': 0}
        try:
            with origin_scope(tool.name):
                feed = tool.discover(RouteQuery(WETH, USDC, amount, block))
                for candidate in feed.available:
                    state['candidates'] += 1
                    queue.put_nowait(('candidate', tool.name, candidate))
                    await asyncio.sleep(0)
                if feed.pending is not None:
                    candidates = await budget.discovery(feed.pending)
                    attribution = getattr(candidates, 'engine_attribution', None)
                    if attribution is not None:
                        state['engineAttribution'] = attribution
                    for candidate in candidates:
                        state['candidates'] += 1
                        queue.put_nowait(('candidate', tool.name, candidate))
                        await asyncio.sleep(0)
            state['status'] = 'completed' if state['candidates'] else 'empty'
        except ProviderUnavailable:
            state['status'] = 'unavailable'
        except SearchStopped:
            state['status'] = 'stopped'
        except SnapshotChanged as error:
            state['status'] = 'snapshot-changed'
            queue.put_nowait(('disproof', tool.name, error))
            raise
        except asyncio.CancelledError:
            state['status'] = 'cancelled'
            raise
        except Exception as error:
            state.update(status='error', failureType=type(error).__name__)
        finally:
            state['completedMs'] = elapsed()
            state['durationMs'] = round(state['completedMs'] - state['startedMs'], 3)
            queue.put_nowait(('done', tool.name, None))

    try:
        with route_observation_scope(recorder):
            # The shared pin is re-read inside each fresh producer's existing
            # clock, rather than supplying a free per-trial context/cache.
            await budget.prepare(registry.get_rpc().block(block['hash']))
            if strategy != 'hosted-only':
                await budget.discovery(engine.connector_inventory(WETH, USDC, block, include_core=False))
            row['catalogAcquisitionMs'] = elapsed()
            row['acquiredPools'] = len(registry.inventory)
            tools = route_providers(settings, engine)
            if strategy == 'custom-only':
                tools = [tool for tool in tools if tool.name == 'cybergold-custom']
            elif strategy == 'hosted-only':
                tools = [tool for tool in tools if tool.name in HOSTED]
            for tool in tools:
                provider = getattr(tool, 'provider', tool)
                if hasattr(provider, 'command'):
                    provider.command = [node, *provider.command[1:]]
            tasks = [asyncio.create_task(supply(tool)) for tool in tools]
            pending = len(tasks)
            while pending:
                kind, source, raw = await budget.discovery(queue.get())
                if kind == 'done':
                    pending -= 1
                    continue
                if kind == 'disproof':
                    raise raw
                row['nominations'] += 1
                for branches, origins in normalized_candidates(raw, WETH, USDC, source):
                    row['candidates'] += 1
                    key = candidate_key(branches)
                    if key in seen:
                        row['duplicateCandidates'] += 1
                        if row['best'] is not None and seen[key] is row['best']:
                            row['best']['sources'] = sorted(set(row['best']['sources']) | set(origins))
                        continue
                    row['uniqueCandidates'] += 1
                    seen[key] = None
                    try:
                        with origin_scope('cybergold-quoter'):
                            quote = await budget.discovery(price_candidate(engine, branches,
                                WETH, USDC, amount, block, origin=source, canonical=canonical))
                        if not quote['fullyFilled']:
                            row['partialQuotes'] += 1
                            continue
                        if not budget.qualified():
                            raise SearchStopped()
                        row['fullyFundedQuotes'] += 1
                        if row['timeToFirstFullyFundedQuoteMs'] is None:
                            row['timeToFirstFullyFundedQuoteMs'] = elapsed()
                        result = {'amountIn': quote['amountIn'], 'amountOut': quote['amountOut'],
                            'sources': origins, 'branches': len(branches),
                            'hops': sum(len(branch['hops']) for branch in branches),
                            'topologySha256': digest(key), 'observedAtMs': elapsed(),
                            'runtimeBranchFunding': quote['runtimeBranchFunding']}
                        seen[key] = result
                        if row['best'] is None or int(result['amountOut']) > int(row['best']['amountOut']):
                            row['best'] = result
                    except SnapshotChanged:
                        raise
                    except Exception as error:
                        failures[type(error).__name__] += 1
            await asyncio.gather(*tasks)
            row['status'] = 'completed'
    except SearchStopped:
        row['status'] = 'completed' if row['best'] is not None else 'no-fully-funded-quote'
    except Exception as error:
        row.update(status='failed', failureType=type(error).__name__)
        if isinstance(error, SnapshotChanged):
            row['best'] = None
    finally:
        budget.finish_selection('complete')
        row['selectionWorkEndedMs'] = elapsed()
        for task in tasks:
            if not task.done():
                task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        if any(isinstance(error, SnapshotChanged) for error in outcomes):
            row.update(status='failed', failureType='SnapshotChanged', best=None)
        try:
            with route_observation_scope(recorder):
                await registry.get_rpc().assert_canonical(block)
            budget.canonical_done()
            row['canonicalityVerified'] = True
            row['observedPools'] = pool_proof(registry)
        except Exception as error:
            row.update(status='failed', failureType=type(error).__name__, best=None,
                       canonicalityVerified=False)
        row['completionMs'] = elapsed()
        operations = [tool.close() for tool in tools] + [engine.close(), registry.close()]
        cleanup = await asyncio.gather(*operations, return_exceptions=True)
        row['cleanupFailures'] = [type(error).__name__ for error in cleanup if isinstance(error, BaseException)]
        row['supplierCleanup'] = {}
        for tool in tools:
            provider = getattr(tool, 'provider', tool)
            child = getattr(provider, 'process', None)
            row['supplierCleanup'][tool.name] = {'activeHttpClients': len(getattr(provider, 'clients', ())),
                'childRetired': child is None or child.returncode is not None,
                'closedFlag': getattr(provider, 'closed', None)}
        row['sdkChildRetired'] = engine.sdk.process is None or engine.sdk.process.returncode is not None
        row['allResourcesClosed'] = not row['cleanupFailures'] and row['sdkChildRetired'] and all(
            state['activeHttpClients'] == 0 and state['childRetired'] and state['closedFlag'] is not False
            for state in row['supplierCleanup'].values())
        row['physicalRpc'], row['apiRequests'] = recorder.metrics, recorder.api_metrics
        row['pricingFailures'] = dict(failures)
        row['includingCleanupMs'] = elapsed()
        budget.cleanup_done()
    return row


async def budgeted_trial(*arguments, **keywords):
    # Identical existing 5/15 policy; qualification here is only an AMM route,
    # not a whole economic Quoter plan or its fees/eligibility.
    budget = QuoteBudget()
    with budget_context(budget):
        row = await budget.produce(trial(*arguments, **keywords))
    row['routeSelectionBudget'] = {'policy': 'existing-5-15-seconds',
        'qualification': 'canonical-fully-funded-amm-conversion', **budget.timings()}
    return row


def paired_summary(trials):
    pairs = []
    for amount, repeat in sorted({(row['inputRaw'], row['repeat']) for row in trials}):
        strategies = {row['strategy']: row for row in trials
            if (row['inputRaw'], row['repeat']) == (amount, repeat)}
        if not {'custom-only', 'parallel'} <= strategies.keys():
            continue
        left, right = strategies['custom-only'], strategies['parallel']
        result = {'inputRaw': amount, 'repeat': repeat,
            'comparable': left['status'] == right['status'] == 'completed'
                and left['best'] is not None and right['best'] is not None}
        if result['comparable']:
            old, new = int(left['best']['amountOut']), int(right['best']['amountOut'])
            result.update(outputDeltaRaw=str(new-old), outputDeltaBps=10000*(new-old)/old if old else None,
                firstQuoteDeltaMs=round(right['timeToFirstFullyFundedQuoteMs']
                    - left['timeToFirstFullyFundedQuoteMs'], 3),
                completionDeltaMs=round(right['completionMs'] - left['completionMs'], 3),
                rpcAttemptDelta=right['physicalRpc']['requests'] - left['physicalRpc']['requests'])
        pairs.append(result)
    summaries = {}
    for strategy in sorted({row['strategy'] for row in trials}):
        rows = [row for row in trials if row['strategy'] == strategy]
        completed = [row for row in rows if row['status'] == 'completed' and row['best'] is not None]
        summaries[strategy] = {'attempted': len(rows), 'fullyFundedResults': len(completed),
            'medianFirstQuoteMs': statistics.median(row['timeToFirstFullyFundedQuoteMs']
                for row in completed) if completed else None,
            'medianCompletionMs': statistics.median(row['completionMs'] for row in rows),
            'rpcHttpAttempts': sum(row['physicalRpc']['requests'] for row in rows),
            'hostedHttpAttempts': sum(row['apiRequests']['requests'] for row in rows)}
    return {'strategies': summaries, 'paired': pairs}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('availability', 'hosted', 'paired-rpc'), default='availability')
    parser.add_argument('--api-env-file', type=Path)
    parser.add_argument('--node', default='node')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--block-hash')
    parser.add_argument('--repeats', type=int, default=1, choices=(1, 2))
    args = parser.parse_args()
    before = bindings()
    report = {'schema': 'cybergold.hosted-and-live-route-probe.v1',
        'observedAtUTC': datetime.now(timezone.utc).isoformat(), 'mode': args.mode,
        'head': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
        'branch': git('branch', '--show-current'), 'sourceSha256Before': before,
        'scope': ['Read-only quote/topology requests and canonical SDK simulation only.',
            'No trades, approvals, signing, deployments, secret relocation or production state writes.',
            'Fresh registry, SDK and provider resources for every trial; no database or persisted observations.',
            'Upstream broker/provider caches and background network load are not controlled by this experiment.',
            'One pinned finalized Mainnet block/hash, direct/via-WETH connector acquisition, WETH/USDC pair.',
            'Pure Market route-engine experiment; not full Quoter/Core economics, gas ranking or production traffic.',
            'Hosted remote observations are not block-pinned; remote amounts and execution payloads are ignored.',
            'UniRoute API has no documented engine selector; actual engine evidence is optional diagnostics.',
            'Equal requested input; only fully funded canonical quotes are compared for output quality.',
            'Physical RPC counts are HTTP attempts and JSON-RPC members, not Multicall inner calls.',
            'Wrapper startup/identity probe is outside trial counts; pinned-context acquisition is reported separately.',
            'Shared reads are charged to the first issuing owner; provider benefits are not duplicated.',
            'Existing 5/15-second QuoteBudget reused; qualification is a fully funded AMM route, not a whole Quoter plan.',
            'No extra deadline, retry, route ranking policy or required metadata is introduced.'],
        'trials': []}
    try:
        settings = selected_settings(args.api_env_file)
        report['configuration'] = configuration(settings, args.api_env_file)
        if args.mode == 'availability':
            report['status'] = 'available' if report['configuration']['apiKeyConfigured'] else 'api-key-unavailable'
        elif args.mode == 'hosted' and not report['configuration']['apiKeyConfigured']:
            report.update(status='api-key-unavailable', apiRequests={'requests': 0},
                providers={name: {'status': 'unavailable', 'reason': 'api-key-unconfigured'} for name in sorted(HOSTED)})
        elif not settings.RPC_URL:
            report['status'] = 'read-only-tooling-rpc-unavailable'
        else:
            report['nodeVersion'] = subprocess.check_output([args.node, '--version'], text=True).strip()
            context = RouteObservations()
            rpc = UniswapRpc(settings)
            try:
                with route_observation_scope(context):
                    block = await rpc.block(args.block_hash or 'finalized')
                    await rpc.assert_canonical(block)
            finally:
                await rpc.close()
            report['contextAcquisitionPhysicalRpc'] = context.metrics
            report['block'] = {'chainId': 1, 'blockNumber': str(block['number']), 'blockHash': block['hash'],
                'selection': 'specified-hash' if args.block_hash else 'finalized'}
            report['pair'] = {'input': 'WETH', 'output': 'USDC', 'tokenIn': WETH, 'tokenOut': USDC}
            amounts = (10**16,) if args.mode == 'hosted' else (10**16, 10**17)
            for amount in amounts:
                for repeat in range(1, args.repeats+1):
                    strategies = ('hosted-only',) if args.mode == 'hosted' else (
                        ('custom-only', 'parallel') if repeat % 2 else ('parallel', 'custom-only'))
                    for strategy in strategies:
                        row = await budgeted_trial(settings, block, strategy, amount, repeat, args.node)
                        report['trials'].append(row)
                        args.output.write_text(json.dumps(report, indent=2)+'\n')
                        print(json.dumps({name: row[name] for name in
                            ('strategy', 'repeat', 'inputRaw', 'status', 'completionMs')}), flush=True)
            report.update(status='completed-with-failures' if any(row['status'] != 'completed'
                for row in report['trials']) else 'completed', summary=paired_summary(report['trials']))
    except Exception as error:
        # Never expose environment values, URLs, response payloads or arbitrary
        # library exception text. Ordinary errors remain visible by type.
        report.update(status='failed', failureType=type(error).__name__)
    finally:
        report['sourceSha256After'] = bindings()
        report['sourceContentChangedDuringRun'] = before != report['sourceSha256After']
        args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'report': str(args.output), 'status': report['status']}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
