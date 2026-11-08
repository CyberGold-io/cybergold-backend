"""Read-only 1/4/8 caller bursts with the actual pool-worker collection path."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


async def main(args):
    sys.path.insert(0, str(args.source / 'python-candidate/src'))
    from cybergold_candidate.environment import load_environment
    from cybergold_candidate.quoter import Quoter
    from cybergold_candidate.route_quote_engine import RouteQuoteEngine
    from cybergold_candidate.sdk_worker import SdkWorker
    from cybergold_candidate.uniswap_state import PoolRegistry
    from cybergold_candidate.worker_engine import WorkerEngine
    from cybergold_candidate.indexing_budget import IndexingRpcPacer
    from cybergold_candidate.market_swap import DailyRecipientCache
    from cybergold_candidate.protocol_config import ProtocolConfiguration
    core = '0x601da021cAF3DB5AA63e700D239b5935C370601d'
    settings = load_environment({'RPC_URL': os.environ['MAINNET_RPC_URL'],
        'NEXT_PUBLIC_RPC_URL': os.environ['MAINNET_RPC_URL'], 'NEXT_PUBLIC_CHAIN_ID': '1',
        'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': core,
        'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS': '0x30e9aFD21A30B2629BE33508A131AC890368f534',
        'CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS': '0x1B5905175d6a64ABa6C170a1CD52e5DD555C35a8'})
    request = {'intent': 0, 'inputs': [{'currency': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
                                     'amount': '100000000'}], 'outputCurrency': core}
    registry = PoolRegistry(settings); rpc = registry.get_rpc(); original = rpc.block
    async def pinned(_):
        return await original(hex(26299298))
    rpc.block = pinned
    sdk = SdkWorker(['node', str(args.sdk_source / 'src/uniswap-sdk/worker.ts')])
    engine = RouteQuoteEngine(settings, registry, sdk=sdk)
    q = Quoter(settings, engine, **({'exploration_seed': 1700} if args.variant != 'baseline' else {}))
    result = {'variant': args.variant, 'scope': __doc__, 'rows': [], 'bootstrap': [], 'worker': {}, 'finished': False}
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    worker_registry = worker_task = None
    try:
        seed = None
        for attempt in range(3):
            try:
                seed = await q.get(request, seed=seed)
                result['bootstrap'].append({'attempt': attempt, 'status': 'success', 'output': seed['quotedOutput']})
                break
            except Exception as error:
                result['bootstrap'].append({'attempt': attempt, 'status': type(error).__name__})
        if seed is None:
            raise RuntimeError('No bootstrap quote')
        worker_registry = PoolRegistry(settings)
        worker_registry.inventory = deepcopy(registry.inventory)
        worker_registry.observed = deepcopy(registry.observed)
        worker_registry.metadata = deepcopy(registry.metadata)
        worker_registry.discovery_month = datetime.now(timezone.utc).strftime('%Y-%m')
        worker_rpc = worker_registry.get_rpc(); worker_original = worker_rpc.block
        async def worker_block(_):
            return await worker_original(hex(26299298))
        worker_rpc.block = worker_block
        worker = WorkerEngine.__new__(WorkerEngine)
        worker.settings = settings; worker.config = {'chainId': 1}; worker.uniswap_registry = worker_registry
        worker.collection_config = {'maxBlocksPerRun': 20000}
        worker.indexing_pacer = IndexingRpcPacer()
        worker.market_recipient = DailyRecipientCache(None, settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS)
        worker.protocol_configuration = ProtocolConfiguration(settings)
        async def collect():
            started = time.monotonic()
            try:
                await worker.collect_uniswap()
                result['worker']['status'] = 'complete'
            except asyncio.CancelledError:
                result['worker']['status'] = 'cancelled-after-bursts'
                raise
            except Exception as error:
                result['worker'].update(status='failed', errorType=type(error).__name__)
            finally:
                result['worker']['totalMs'] = round((time.monotonic() - started) * 1000, 3)
        worker_task = asyncio.create_task(collect())
        for callers in [1, 4, 8]:
            async def search(index):
                started = time.monotonic()
                row = {'callers': callers, 'index': index, 'seedOutput': seed['quotedOutput']}
                try:
                    value = await q.get(request, seed=seed)
                    row.update(status='success', output=value['quotedOutput'], funding=value['inputs'], metrics=value['metrics'],
                        incumbentPreserved=int(value['quotedOutput']) >= int(seed['quotedOutput']))
                except Exception as error:
                    row.update(status='failed', errorType=type(error).__name__)
                row.update(totalMs=round((time.monotonic()-started)*1000, 3),
                    pythonPeakRss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                if sdk.process is not None:
                    row['sdkResidentKiB'] = int(subprocess.check_output(['ps', '-o', 'rss=', '-p', str(sdk.process.pid)], text=True).strip())
                result['rows'].append(row); save()
            await asyncio.gather(*(search(index) for index in range(callers)))
            print(json.dumps({'callers': callers, 'finished': len(result['rows'])}), flush=True)
        try:
            await asyncio.wait_for(asyncio.shield(worker_task), timeout=30)
        except TimeoutError:
            worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
        result['finished'] = True
    finally:
        if worker_task is not None and not worker_task.done():
            worker_task.cancel(); await asyncio.gather(worker_task, return_exceptions=True)
        if worker_registry is not None:
            await worker_registry.close()
        await engine.close(); await registry.close()
        result['ownedSdkClosed'] = sdk.process is None
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.cwd())
    parser.add_argument('--sdk-source', type=Path, default=Path.cwd())
    parser.add_argument('--variant', choices=['baseline', 'implementation'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
