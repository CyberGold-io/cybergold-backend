"""Actual captured plan, real Helpers/Core on an owned clone, parked discovery.

Run from the Backend checkout (Node 26 on PATH):

    PYTHONPATH=python-candidate/src python-candidate/.venv/bin/python \
      python-candidate/tests/qualification/core_funding_observed_residual.py \
      --rpc http://127.0.0.1:PORT --reuse-observation --output /tmp/core-funding.json

The default fixture records an actual pinned public Sandbox Helpers result and
actual SDK pool observations. --reuse-observation reuses that recorded root; it
does not claim a fresh owned-node root call. Changed proposals are always priced
against the supplied owned clone through production Helpers/Core. Omit the flag
or supply --root FULL_QUOTE_JSON to choose a fresh or separately observed root.
The owner prepares the disposable clone at the fixture source state. This script
does not start/reset it, send transactions, or add a CI acceptance gate.

Only eth_call/getter observations target the supplied owned-clone RPC. Contract
code, reserves, supply and fees are not replaced by a synthetic Core oracle.
The test parks optional AMM discovery, not SDK pricing or complete Helpers
simulation, to require the already-measured useful-residual alternative first.
"""
import argparse
import asyncio
from contextlib import aclosing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from web3 import AsyncWeb3

from cybergold_candidate.quote_publication import CanonicalPublication
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.core_funding import core_funding_alternatives
from cybergold_candidate.quoter.plan_simulation import project_core_inputs
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
from cybergold_candidate.rpc_transport import rpc_provider
from cybergold_candidate.uniswap_state import PoolRegistry, UniswapRpc


async def run(args):
    fixture = json.loads(Path(args.fixture).read_text())
    captured = fixture['root']
    configuration = fixture['protocolConfiguration']
    request = deepcopy(captured['request'])
    source, core = request['inputs'][0]['currency'], request['outputCurrency']
    settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID=str(configuration['chainId']),
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=core,
        NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=captured['deployment']['helpers'],
        CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS=captured['deployment']['adapter'],
        RPC_URL=args.rpc, RPC_AUTHORIZATION=None)
    # The disposable clone may need cold fork-storage hydration. Retain the
    # production provider with retries disabled and a local qualification wait.
    rpc = UniswapRpc(settings, w3=AsyncWeb3(rpc_provider(args.rpc, timeout_seconds=180)))
    registry = PoolRegistry(settings, rpc=rpc)
    for token in configuration['tokens']:
        if token.get('address'):
            registry.metadata[token['address'].lower()] = deepcopy(token)
    for chosen in captured['plan']['conversions'].values():
        for branch in chosen['branches']:
            for hop in branch['hops']:
                if 'pool' in hop:
                    pool = deepcopy(hop['pool'])
                    registry.inventory[pool['id']] = pool
    engine = RouteQuoteEngine(settings, registry)
    quoter = Quoter(settings, engine)
    producer = ready_waiter = parked_waiter = None
    evidence = {'evidenceKind': 'actual-captured-plan-real-Helpers-Core-and-SDK-on-owned-clone',
        'backendCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'sourceSha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
            Path('python-candidate/src/cybergold_candidate/quoter/core_funding.py'),
            Path('python-candidate/src/cybergold_candidate/quoter/inverse.py'),
            Path('python-candidate/src/cybergold_candidate/routing_encoding.py'))},
        'capturedObservedAt': captured['context'].get('observedAt'),
        'capturedOutput': captured['quotedOutput'], 'capturedDeployment': captured['deployment'],
        'remoteTransactions': False, 'contractStateOverrides': 'synthetic-payer-funding-only',
        'publicationEvents': [], 'candidateObservations': [], 'proposals': [],
        'helpersRpcExchanges': [], 'result': 'running'}
    event_order, parked = [], asyncio.Queue()
    sdk_observations = {}
    lower_selected, release_discovery = asyncio.Event(), asyncio.Event()
    try:
        rpc = registry.get_rpc()
        make_request = rpc.w3.provider.make_request
        async def observe_request(method, params):
            response = await make_request(method, params)
            if (method == 'eth_call' and params and isinstance(params[0], dict)
                    and params[0].get('to', '').lower() == captured['deployment']['helpers'].lower()):
                evidence['helpersRpcExchanges'].append({'method': method,
                    'params': deepcopy(params), 'response': deepcopy(response)})
            return response
        rpc.w3.provider.make_request = observe_request
        block = await rpc.w3.eth.get_block('latest')
        evidence['cloneEntry'] = {'chainId': await rpc.w3.eth.chain_id,
            'blockNumber': str(block.number), 'blockHash': block.hash.hex()}
        # Reuse a full actual observation at this source state when supplied;
        # otherwise evaluate the original body on the clone. Record its own
        # context rather than relabelling a source call as a local call.
        root = (json.loads(Path(args.root).read_text()) if args.root else
                deepcopy(captured) if args.reuse_observation else
                await quoter.candidate(request, 100, 'core-first', LATEST_BLOCK,
                    [], [], selected=captured['plan']))
        if args.root or args.reuse_observation:
            evidence['rootObservationFile'] = args.root or args.fixture
            evidence['rootObservationScope'] = 'Recorded actual observation reused; its original context is retained.'
        evidence['root'] = deepcopy(root)
        evidence['measuredCoreInputs'] = project_core_inputs(root, registry.chain)

        async def publish(frame):
            if frame['type'] != 'qualified':
                return
            value = frame['value']
            item = {'kind': 'selected', 'inputs': deepcopy(value['inputs']),
                    'quotedOutput': value['quotedOutput'],
                    'phase': value.get('searchCoverage', {}).get('selectedPhase'),
                    'retained': deepcopy(value['estimatedRetainedInputCharges'])}
            evidence['publicationEvents'].append(item)
            event_order.append(item)
            if (int(value['quotedOutput']) >= int(root['quotedOutput']) and
                    int(value['inputs'][0]['amount']) < int(root['inputs'][0]['amount'])):
                lower_selected.set()

        publication = CanonicalPublication(quoter, request, publish)
        await publication.enqueue({'type': 'candidate-repriced', 'value': root})
        await publication.publish_selected()

        async def park_optional_discovery(asset, target, amount, *positional, **options):
            item = {'kind': 'optional-discovery', 'source': asset, 'target': target,
                    'amount': str(amount),
                    'role': 'primary-market' if asset.lower() == source.lower() else 'residual-market'}
            event_order.append(item)
            parked.put_nowait(item)
            await release_discovery.wait()
            raise AssertionError('Parked optional discovery was unexpectedly released')
        quoter.conversion = park_optional_discovery

        async def produce():
            async with aclosing(core_funding_alternatives(quoter, root, LATEST_BLOCK, sdk_observations)) as proposals:
                async for proposal in proposals:
                    evidence['proposals'].append(deepcopy(proposal))
                    funded = {**request, 'inputs': deepcopy(proposal['inputs'])}
                    value = await quoter.candidate(funded, 100, 'core-first', LATEST_BLOCK,
                        [], [], selected=proposal['plan'])
                    value['request'] = deepcopy(request)
                    value.setdefault('searchCoverage', {})['selectedPhase'] = proposal['phase']
                    evidence['candidateObservations'].append(deepcopy(value))
                    await publication.enqueue({'type': 'candidate-repriced', 'value': value})
                    await publication.publish_selected()

        producer = asyncio.create_task(produce())
        ready_waiter = asyncio.create_task(lower_selected.wait())
        parked_waiter = asyncio.create_task(parked.get())
        # This is test dependency ordering, not a product timeout/funding gate.
        # The current producer fails as soon as unrelated discovery starts.
        async with asyncio.timeout(180):
            await asyncio.wait((producer, ready_waiter, parked_waiter),
                               return_when=asyncio.FIRST_COMPLETED)
        if producer.done():
            await producer
        selected_index = next((index for index, item in enumerate(event_order)
            if item['kind'] == 'selected' and int(item['quotedOutput']) >= int(root['quotedOutput'])
            and int(item['inputs'][0]['amount']) < int(root['inputs'][0]['amount'])), None)
        discovery_index = next((index for index, item in enumerate(event_order)
            if item['kind'] == 'optional-discovery'), None)
        assert selected_index is not None, 'No lower-input same-or-better-net quote selected before optional discovery.'
        assert discovery_index is None or selected_index < discovery_index, \
            'Measured useful-residual publication waited for unrelated optional discovery.'
        evidence['selected'] = deepcopy(publication.best)
        selected = publication.best
        measured = project_core_inputs(root, registry.chain)
        root_operations = {row['operation']: row for row in root['conversionObservations']}
        actual_acquisitions = {row['outputCurrency'].lower(): int(row['output'])
            for row in selected['conversionObservations'] if ':acquire:' in row['operation']}
        targets = {row['currency'].lower(): row['consumed'] + int(root_operations.get(
            f"{row['branch']}:residual:{row['index']}", {}).get('consumedInput', '0'))
            for row in measured}
        retained = {asset: sum(int(row['amount']) for row in selected['estimatedRetainedInputCharges']
                              if row['currency'].lower() == asset) for asset in targets}
        evidence['acquisitionDustAccounting'] = [{'currency': row['currency'],
            'measuredCorePlusUsefulTargetRaw': str(targets[row['currency'].lower()]),
            'actualAcquisitionOutputRaw': str(actual_acquisitions[row['currency'].lower()]),
            'acquiredAboveTargetRaw': str(actual_acquisitions[row['currency'].lower()]
                                         - targets[row['currency'].lower()]),
            'actualRetainedRaw': str(retained[row['currency'].lower()])} for row in measured]
        for asset, amount in retained.items():
            assert amount <= max(0, actual_acquisitions[asset]-targets[asset]), \
                'Retained gold exceeds acquisition rounding above the measured target.'
        assert all(not int(row['amount']) or row['currency'].lower() in targets
                   for row in selected['estimatedRetainedInputCharges']), \
            'The measured-target fixture unexpectedly retains a non-basket input.'
        evidence['inputSavedRaw'] = str(int(root['inputs'][0]['amount'])
                                         - int(selected['inputs'][0]['amount']))
        selected_file = Path(args.output).with_name(Path(args.output).stem+'-selected-quote.json')
        selected_file.write_text(json.dumps(selected, indent=2)+'\n')
        evidence['selectedQuoteFile'] = str(selected_file)
        evidence['result'] = 'passed'
    except Exception as error:
        evidence.update(result='failed', errorType=type(error).__name__, error=str(error))
        evidence['errorDiagnostics'] = public_quote_error(error)
    finally:
        for task in (producer, ready_waiter, parked_waiter):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (producer, ready_waiter, parked_waiter)
                               if task is not None), return_exceptions=True)
        evidence['eventOrder'] = event_order
        evidence['sdkPoolObservations'] = deepcopy(sdk_observations)
        await quoter.close()
        await engine.close()
        await registry.close()
        evidence['finishedAt'] = datetime.now(timezone.utc).isoformat()
        Path(args.output).write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'result': evidence['result'], 'error': evidence.get('error'),
            'rootOutput': evidence.get('root', {}).get('quotedOutput'),
            'selectedInputs': evidence.get('selected', {}).get('inputs'),
            'optionalEntered': [row for row in event_order if row['kind'] == 'optional-discovery'],
            'output': args.output}, indent=2))
    return 0 if evidence['result'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rpc', required=True)
    parser.add_argument('--fixture', default=str(Path(__file__).resolve().parents[1] /
        'fixtures/core-funding-usdt-100k-20261109.json'))
    parser.add_argument('--reuse-observation', action='store_true')
    parser.add_argument('--root', help='Full actual Helpers observation at this source state; its original context is retained')
    parser.add_argument('--output', required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
