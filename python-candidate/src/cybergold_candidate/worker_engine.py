"""Retained Ops-triggered worker, configuration, cadence and native DB lock."""
import asyncio
import copy
import json
import logging
import time

from .completed_state import CompletedState
from .core_collector import CoreCollector
from .finalized_multicall import ContractClient
from .fork_control import ForkControl
from .fork_recovery import mark_ready, read_generation
from .helpers_collector import HelpersCollector
from .indexing_budget import IndexingRpcPacer, MAX_BLOCKS_PER_RUN, REQUESTS_PER_HOUR
from .indexer_rpc import direct_rpc
from .runtime import dashboard_enabled, safe_history_profile
from .safe_collector import SafeIndexer, EVENTS
from .reconciliation_receipt import RpcCounter
from .uniswap_state import PoolRegistry, UniswapStore
from .market_swap import DailyRecipientCache


def indexer_config(settings):
    if not dashboard_enabled(settings):
        return None
    def bounded(name, fallback, maximum):
        value = int(getattr(settings, name)) if getattr(settings, name) is not None else fallback
        return fallback if value <= 0 else min(value, maximum)
    finalized = settings.ONCHAIN_INDEXER_ARCHIVE_FREE_FINALIZED_MODE == '1'
    interval = settings.ONCHAIN_INDEXER_RECONCILE_INTERVAL_MS
    return {'chainId': int(settings.NEXT_PUBLIC_CHAIN_ID), 'coreAddress': settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS,
        'governanceAddress': settings.NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS,
        'rpcUrl': settings.ONCHAIN_INDEXER_RPC_URL or settings.RPC_URL or settings.NEXT_PUBLIC_RPC_URL,
        'startBlock': int(settings.ONCHAIN_INDEXER_START_BLOCK or 0), 'chunkSize': bounded('ONCHAIN_INDEXER_CHUNK_SIZE', 2000, 10000),
        'maxBlocksPerRun': bounded('ONCHAIN_INDEXER_MAX_BLOCKS_PER_RUN', 20000, 50000), 'reorgWindow': bounded('ONCHAIN_INDEXER_REORG_WINDOW', 12, 256),
        'reconcileIntervalMs': float(interval) if interval is not None and float(interval) != 0 else 60000 if finalized else 30000,
        'archiveFreeFinalizedMode': finalized, 'addressScopedRawLogs': settings.ONCHAIN_INDEXER_ADDRESS_SCOPED_RAW_LOGS == '1',
        'rawJournalProjectionReplay': settings.ONCHAIN_INDEXER_RAW_JOURNAL_REPLAY_ENABLED == '1',
        'recoveryShareV2': settings.ONCHAIN_INDEXER_RECOVERY_SHARE_V2_ENABLED == '1',
        'finalizedSnapshotMulticall': settings.ONCHAIN_INDEXER_FINALIZED_MULTICALL_ENABLED == '1',
        # Current runtimes use ordinary authenticated RPC configuration. The
        # already-qualified lease modules remain historical coexistence source.
        'privateGatewayClient': None, 'runtimeConfigId': settings.CYBERGOLD_RUNTIME_CONFIG_ID or None}


class WorkerEngine:
    def __init__(self, database, settings, *, now_ms=None, rpc_factory=None):
        self.database, self.settings = database, settings
        self.config = indexer_config(settings)
        self.now_ms = now_ms or (lambda: time.time() * 1000)
        self.rpc_factory = rpc_factory or (lambda raw=False: direct_rpc(settings, raw_logs=raw))
        self.runtime = {'reconcilePromise': None, 'lastReconciledAtMs': 0, 'lastRpcRequestCounts': None,
            'lastReconciliationReceipt': None, 'activeGatewayReconciliationId': None, 'gatewayLeaseAmbiguousUntilMs': 0}
        self.product_metrics = None
        self.pending_runs = set()
        self.helpers_progress = None
        self.collection_config = {**self.config, 'maxBlocksPerRun': MAX_BLOCKS_PER_RUN} if self.config else None
        self.indexing_pacer = IndexingRpcPacer()
        self.uniswap_registry = None
        self.market_recipient = None
        self.protocol_configuration = None

    async def collect_uniswap(self, force=False):
        if self.uniswap_registry is None:
            store = UniswapStore(self.database, self.config['chainId'], self.config['coreAddress'])
            self.uniswap_registry = PoolRegistry(self.settings, store=store)
            self.market_recipient = DailyRecipientCache(store, self.settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS)
            from .protocol_config import ProtocolConfiguration
            configuration_store = UniswapStore(self.database, self.config['chainId'], self.config['coreAddress'])
            self.protocol_configuration = ProtocolConfiguration(self.settings, configuration_store)
        registry = self.uniswap_registry
        if self.config['chainId'] == 31338:
            async with self.database.connection() as connection:
                stored = await read_generation(connection, self.config['coreAddress'].lower())
            generation = stored['anchor']['generation'] if stored else None
            if generation is not None and generation != registry.generation:
                await registry.observe_generation(generation)
                self.market_recipient.reset()
            await self.protocol_configuration.observe_generation(generation)
        rpc = registry.get_rpc()
        rpc.before_request = self.indexing_pacer.acquire
        block = await rpc.block(None)
        await registry.discover(block, force=force, max_blocks=self.collection_config['maxBlocksPerRun'])
        await registry.monitor(block, max_blocks=self.collection_config['maxBlocksPerRun'])
        await self.market_recipient.refresh(rpc, block)
        try:
            pending = await self.protocol_configuration.read_pending(rpc, block)
        except Exception:
            pending = None
        await rpc.assert_canonical(block)
        await self.protocol_configuration.publish_pending(pending)

    async def collect_helpers(self, anchor):
        address = self.settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS
        if not address or not self.config['archiveFreeFinalizedMode'] or not self.config['addressScopedRawLogs']:
            return
        rpc, raw = self.rpc_factory(), self.rpc_factory(True)
        rpc.before_request = raw.before_request = self.indexing_pacer.acquire
        before = self.indexing_pacer.attempts
        try:
            self.helpers_progress = await HelpersCollector(self.database, self.collection_config, address,
                on_rewind=self.protocol_configuration.invalidate_from if self.protocol_configuration else None).reconcile(
                ContractClient(rpc), raw, anchor=anchor)
            if self.protocol_configuration:
                try:
                    await self.protocol_configuration.apply_journal(self.database)
                except Exception:
                    pass
            self.helpers_progress.update({'rpcAttempts': self.indexing_pacer.attempts - before,
                                          'rpcRequestsPerHour': REQUESTS_PER_HOUR})
            logging.getLogger('cybergold.candidate').info(json.dumps({
                'context': 'helpers-indexer', **self.helpers_progress}))
        finally:
            if raw is not rpc:
                await raw.close()
            await rpc.close()

    async def last_receipt(self):
        if self.config is None:
            return None
        addresses, _lookback = safe_history_profile(self.settings)
        return await CompletedState(self.database, {**self.config, 'safeAddresses': addresses}).receipt(self.runtime, self.now_ms())

    async def reconcile(self, counter, force, stage=None, supplied_anchor=None):
        if self.runtime['reconcilePromise'] is not None:
            return await asyncio.shield(self.runtime['reconcilePromise'])
        if not force and self.now_ms() - self.runtime['lastReconciledAtMs'] < self.config['reconcileIntervalMs']:
            return None
        async def run():
            addresses, lookback = safe_history_profile(self.settings)
            safe = SafeIndexer(self.database, self.settings)
            profile = {'safeAddresses': addresses, 'lookbackBlocks': lookback, 'eventSelectors': [topic for _name, topic in EVENTS]}
            collector = CoreCollector(self.database, self.collection_config, profile)
            rpc = self.rpc_factory()
            raw = self.rpc_factory(True) if self.config['addressScopedRawLogs'] else rpc
            rpc.before_request = raw.before_request = self.indexing_pacer.acquire
            before = self.indexing_pacer.attempts
            try:
                async def safes(counter, **options):
                    return await safe.reconcile(counter, before_request=self.indexing_pacer.acquire, **options)
                outcome = await collector.reconcile(counter, ContractClient(rpc), raw, safes,
                    supplied_anchor=supplied_anchor, stage=stage)
                self.runtime['lastReconciledAtMs'] = self.now_ms()
                logging.getLogger('cybergold.candidate').info(json.dumps({
                    'context': 'core-indexer', 'rpcAttempts': self.indexing_pacer.attempts - before,
                    'rpcRequestsPerHour': REQUESTS_PER_HOUR,
                    'maxBlocksPerRun': MAX_BLOCKS_PER_RUN,
                    'dashboardHistoryProgress': outcome.get('dashboardHistoryProgress') if outcome else None}))
                return outcome
            finally:
                if raw is not rpc:
                    await raw.close()
                await rpc.close()
        self.runtime['reconcilePromise'] = asyncio.create_task(run())
        try:
            return await asyncio.shield(self.runtime['reconcilePromise'])
        finally:
            # An HTTP caller cancellation does not abandon the canonical run.
            pending = self.runtime['reconcilePromise']
            if pending.done():
                self.runtime['reconcilePromise'] = None
            else:
                pending.add_done_callback(lambda _done: self.runtime.update(reconcilePromise=None))

    async def run_once(self, force=True, stage=None, *, supplied_anchor=None, gateway_expectation=None):
        # The complete operation owns the existing lock, including completion
        # writes and Helpers collection. It survives an HTTP caller cancellation.
        task = asyncio.create_task(self._run_once(force, stage, supplied_anchor=supplied_anchor,
                                                 gateway_expectation=gateway_expectation))
        self.pending_runs.add(task)
        def finished(done):
            self.pending_runs.discard(done)
            if not done.cancelled():
                done.exception()  # Observe failures even after the caller disconnected.
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _run_once(self, force=True, stage=None, *, supplied_anchor=None, gateway_expectation=None):
        def diagnostic(value):
            if stage is not None:
                stage(value)
        diagnostic('configuration')
        if self.config is None:
            raise ValueError('On-chain indexer worker configuration is incomplete')
        diagnostic('database-schema')
        await self.database.ensure_schema()
        diagnostic('advisory-lock')
        key = 'onchain-indexer:' + str(self.config['chainId']) + ':' + self.config['coreAddress'].lower()
        async with self.database.advisory_lock(key) as acquired:
            if not acquired:
                return {'status': 'busy', 'dashboardHistoryProgress': None}
            counter = RpcCounter()
            try:
                if gateway_expectation is not None:
                    raise ValueError('A gateway expectation is forbidden when gateway mode is disabled')
                diagnostic('reconciliation')
                outcome = await self.reconcile(counter, force, stage, supplied_anchor)
                if outcome is None and force:
                    raise ValueError('Forced on-chain indexer reconciliation did not run')
            finally:
                self.runtime['lastRpcRequestCounts'] = copy.deepcopy(counter.counts)
            if outcome and outcome['completed'] and self.config['chainId'] == 31338:
                async with self.database.connection() as connection:
                    async with connection.transaction():
                        await mark_ready(connection, self.config['coreAddress'], outcome['finalizedAnchor']['blockNumber'] if outcome['finalizedAnchor'] else 0)
            if outcome is not None:
                try:
                    await self.collect_uniswap(force=force)
                except Exception:
                    logging.getLogger('cybergold.candidate').error(json.dumps({
                        'context': 'uniswap-indexer', 'errorClassification': 'collection-failed'}))
                try:
                    await self.collect_helpers(outcome.get('finalizedAnchor'))
                except Exception:
                    # Core/Safe completion and fork readiness are independent
                    # of this new stream's provider/backfill failures. Retry on
                    # the next ordinary run; never log provider/credential text.
                    self.helpers_progress = {'error': True}
                    logging.getLogger('cybergold.candidate').error(json.dumps({
                        'context': 'helpers-indexer', 'errorClassification': 'collection-failed'}))
            return {'status': 'deferred-cadence' if outcome is None else 'reconciled' if outcome['completed'] else 'incomplete',
                'dashboardHistoryProgress': outcome['dashboardHistoryProgress'] if outcome else None}

    def fork(self):
        return ForkControl(self.database, self.config, self.runtime, lambda _config: self.rpc_factory())

    async def fork_status(self):
        return await self.fork().status()

    async def transition(self, input):
        return await self.fork().transition(input)

    def refresh_product_metrics(self):
        if self.product_metrics is not None:
            self.product_metrics.refresh()

    async def close(self):
        if self.pending_runs:
            await asyncio.shield(asyncio.gather(*tuple(self.pending_runs), return_exceptions=True))
        if self.runtime['reconcilePromise'] is not None:
            await asyncio.gather(self.runtime['reconcilePromise'], return_exceptions=True)
        if self.product_metrics is not None:
            await self.product_metrics.close()
        if self.uniswap_registry:
            await self.uniswap_registry.close()
        if self.market_recipient:
            await self.market_recipient.close()
        if self.protocol_configuration:
            await self.protocol_configuration.close()
        await self.database.close()
