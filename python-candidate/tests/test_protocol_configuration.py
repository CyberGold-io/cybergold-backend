"""Configured anchors, cached default selection and canonical lifecycle."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.protocol_config import ProtocolConfiguration, select_adapter, APPROVAL_TOPIC
from cybergold_candidate.quote_cache import IntentSharing
from cybergold_candidate.environment import load_environment
from cybergold_candidate.helpers_router_facts import HelpersRouterFacts
from cybergold_candidate.helpers_collector import HelpersCollector
from cybergold_candidate.market_swap import MarketQuotes
from cybergold_candidate.worker_engine import WorkerEngine
from cybergold_candidate.shared_reads import SharedReads
from cybergold_candidate.protocol_facts import ProtocolFactsRpc
from cybergold_candidate.helpers_router_facts import ABI as HELPERS_ABI
from cybergold_candidate.quote_history import QuoteHistory
from cybergold_candidate.runtime import create_configured_app

CORE, HELPERS, SAFE = ('0x'+value*40 for value in ('1', '2', '3'))
NEW = '0xc2c210979674db1349f812ea116f2f6d131ab839'
OLD = '0x4edb8190232a47e45d861003672938eb7ee84a15'
CUSTOM = '0x'+'a'*40
HASH = '0x'+'b'*64


def settings(chain=1):
    return SimpleNamespace(NEXT_PUBLIC_CHAIN_ID=str(chain), NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
        NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=HELPERS, NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None,
        NEXT_PUBLIC_STAKING_DIAMOND_ADDRESS=None, NEXT_PUBLIC_GOVERNANCE_SAFE_ADDRESS=SAFE,
        RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION=None)


def context(number=20, hash=HASH):
    return {'blockNumber': str(number), 'blockHash': hash, 'observedAt': '2026-10-11T00:00:00Z'}


class Store:
    def __init__(self):
        self.scope = ''
        self.values, self.loads = {}, 0
        self.blocked = False
        self.started, self.release = asyncio.Event(), asyncio.Event()

    async def load(self, namespace):
        self.loads += 1
        values = deepcopy(self.values.get(self.scope+namespace, {}))
        self.started.set()
        if self.blocked:
            await self.release.wait()
        return values

    async def save(self, namespace, identity, value):
        values = self.values.setdefault(self.scope+namespace, {})
        current = values.get(identity)
        if (value is None or current is None
                or int(value['context']['blockNumber']) >= int(current['context']['blockNumber'])):
            values[identity] = deepcopy(value)

    async def save_protocol_configuration(self, identity, value):
        namespace = self.scope+'helpers-configuration'
        await self.save('helpers-configuration', identity, value)
        return deepcopy(self.values.get(namespace, {}).get(identity))


class Rpc:
    def __init__(self, approved=None):
        self.approved = approved or [OLD, NEW, CUSTOM]
        self.calls = []
        self.blocked, self.canonical = False, True
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.cancelled = self.closed = False

    async def block(self):
        self.calls.append('block')
        return {'number': 20, 'hash': HASH}

    async def read(self, group, address, name, block):
        self.calls.append((group, address, name, block))
        self.started.set()
        if self.blocked:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self.approved

    async def assert_canonical(self, block):
        self.calls.append('canonical')
        if not self.canonical:
            raise ValueError('changed hash')

    async def close(self):
        self.closed = True


def approval(address, approved, block, index):
    return {'block_number': str(block), 'block_hash': HASH, 'tx_hash': '0x'+'c'*64,
        'log_index': index, 'block_timestamp_seconds': '1',
        'topics': [APPROVAL_TOPIC, Web3.to_hex(Web3().codec.encode(['address'], [address]))],
        'data': Web3.to_hex(Web3().codec.encode(['bool'], [approved]))}


class Journal:
    def __init__(self, rows):
        self.rows, self.requests = rows, []

    @asynccontextmanager
    async def connection(self):
        owner = self
        class Connection:
            async def execute(self, query, params):
                owner.requests.append((query, params))
                class Cursor:
                    async def fetchall(self):
                        return sorted([row for row in owner.rows if int(row['block_number']) > int(params[2])],
                                      key=lambda row: (int(row['block_number']), row['log_index']))
                return Cursor()
        yield Connection()


class ProtocolConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_roots_catalog_and_unavailable_adapter_are_rpc_free(self):
        rpc = Rpc()
        service = ProtocolConfiguration(settings(), rpc=rpc)
        app = create_app(protocol_configuration=service)
        # A config HTTP read itself never starts a chain observation.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
            response = await client.get('/api/protocol/config')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            result = response.json()
        self.assertEqual(rpc.calls, [])
        self.assertEqual(result['contracts'], {'core': CORE, 'helpers': HELPERS, 'safe': SAFE,
            'governance': None, 'staking': None, 'uniswapAdapter': None})
        self.assertEqual(result['adapter']['status'], 'unavailable')
        tokens = {row['id']: row for row in result['tokens']}
        self.assertEqual(tokens['cygld']['address'], CORE)
        self.assertEqual(tokens['xaut']['decimals'], 6)
        self.assertNotIn('address', tokens['eth'])
        self.assertEqual(len(tokens), 7)
        self.assertNotIn('quoter', json.dumps(result).lower())
        schemas = json.loads((Path(__file__).parents[2]/'contracts/openapi.json').read_text())['components']['schemas']
        self.assertEqual(set(result), set(schemas['ProtocolConfiguration']['required']))
        await service.close()

    async def test_explicit_preference_ignores_set_order_and_unknown_capabilities(self):
        for values in ([OLD, CUSTOM, NEW], [NEW, OLD], [CUSTOM, NEW, OLD]):
            self.assertEqual(select_adapter(values), (Web3.to_checksum_address(NEW), 'uniswap-multi-protocol-v1'))
        self.assertEqual(select_adapter([OLD]), (Web3.to_checksum_address(OLD), 'uniswap-v3'))
        self.assertEqual(select_adapter([CUSTOM]), (None, None))

    async def test_default_resolution_preserves_explicit_custom_and_retained_adapters(self):
        rpc = Rpc()
        service = ProtocolConfiguration(settings(), rpc=rpc)
        await service.observe([NEW], context())
        default = await service.resolve_request({'amount': '1'})
        self.assertEqual(default['adapter'].lower(), NEW)
        for address in (OLD, CUSTOM, ''):
            request = {'adapter': address}
            self.assertIs(await service.resolve_request(request), request)
        for retained in ({'params': {'adapter': OLD}}, {'quotes': [{'adapter': OLD}, {'adapter': OLD}]}):
            self.assertEqual((await service.resolve_request({'retainedPlan': retained}))['adapter'], OLD)
        self.assertEqual(rpc.calls, [])
        await service.close()

    async def test_startup_observation_coalesces_and_config_reads_do_not_wait_for_rpc(self):
        rpc = Rpc(); rpc.blocked = True
        service = ProtocolConfiguration(settings(), rpc=rpc)
        await service.start()
        await rpc.started.wait()
        calls = [asyncio.create_task(service.refresh()) for _ in range(8)]
        self.assertEqual((await service.get())['contracts']['core'], CORE)
        self.assertIsNone((await service.get())['contracts']['uniswapAdapter'])
        calls[0].cancel()
        await asyncio.gather(calls[0], return_exceptions=True)
        self.assertFalse(rpc.cancelled)
        rpc.release.set()
        await asyncio.gather(*calls[1:])
        self.assertEqual((await service.get())['contracts']['uniswapAdapter'].lower(), NEW)
        self.assertEqual(len([call for call in rpc.calls if isinstance(call, tuple)]), 1)
        await service.close()

    async def test_actual_rpc_producer_coalesces_four_bootstrap_envelopes_and_no_config_rpc(self):
        class Provider(AsyncBaseProvider):
            def __init__(self):
                super().__init__()
                self.calls = []
                self.started, self.release = asyncio.Event(), asyncio.Event()
            async def make_request(self, method, params):
                self.calls.append((method, params))
                if method == 'eth_chainId': result = '0x1'
                elif method == 'eth_getBlockByNumber':
                    result = {'number': '0x14', 'timestamp': '0xa', 'hash': HASH}
                elif method == 'eth_call':
                    self.started.set(); await self.release.wait()
                    self.assert_getter(params)
                    result = Web3.to_hex(Web3().codec.encode(['address[]'], [[OLD, NEW]]))
                else: raise AssertionError(method)
                return {'jsonrpc': '2.0', 'id': 1, 'result': result}
            @staticmethod
            def assert_getter(params):
                assert params[0]['data'] == Web3.to_hex(Web3.keccak(text='approvedAdapters()')[:4])
                assert params[1] == {'blockHash': HASH, 'requireCanonical': True}
            async def disconnect(self): pass
        provider = Provider()
        rpc = ProtocolFactsRpc(settings(), AsyncWeb3(provider), abi=HELPERS_ABI)
        service = ProtocolConfiguration(settings(), rpc=rpc)
        calls = [asyncio.create_task(service.refresh()) for _ in range(8)]
        await provider.started.wait()
        for _ in range(5):
            self.assertIsNone((await service.get())['contracts']['uniswapAdapter'])
        calls[0].cancel(); await asyncio.gather(calls[0], return_exceptions=True)
        provider.release.set(); await asyncio.gather(*calls[1:])
        self.assertEqual([method for method, _ in provider.calls],
                         ['eth_chainId', 'eth_getBlockByNumber', 'eth_call', 'eth_getBlockByNumber'])
        for _ in range(5):
            self.assertEqual((await service.get())['contracts']['uniswapAdapter'].lower(), NEW)
        await service.refresh()
        self.assertEqual(len(provider.calls), 4)
        await service.close()

    async def test_noncanonical_observation_is_not_published_and_retry_recovers(self):
        rpc = Rpc(); rpc.canonical = False
        service = ProtocolConfiguration(settings(), rpc=rpc)
        await service.refresh()
        self.assertIsNone((await service.get())['contracts']['uniswapAdapter'])
        rpc.canonical = True
        await service.refresh()
        self.assertEqual((await service.get())['contracts']['uniswapAdapter'].lower(), NEW)
        await service.close()

    async def test_close_cancels_owned_bootstrap_without_hanging_other_runtime_domains(self):
        rpc = Rpc(); rpc.blocked = True
        service = ProtocolConfiguration(settings(), rpc=rpc)
        await service.start(); await rpc.started.wait()
        await service.close()
        self.assertTrue(rpc.cancelled)
        self.assertTrue(rpc.closed)
        self.assertEqual(service.tasks, set())

    async def test_durable_recovery_and_old_generation_pending_read_are_isolated(self):
        store = Store()
        service = ProtocolConfiguration(settings(31338), store)
        await service.observe_generation('one')
        await service.observe([NEW], context(), generation='one')
        restart = ProtocolConfiguration(settings(31338), store)
        await restart.observe_generation('one')
        await restart.load()
        self.assertEqual((await restart.get())['contracts']['uniswapAdapter'].lower(), NEW)
        store.blocked = True; store.started.clear()
        pending = asyncio.create_task(restart.load()); await store.started.wait()
        await restart.observe_generation('two')
        store.release.set(); await pending
        self.assertIsNone(restart.value)
        self.assertIsNone((await restart.get())['contracts']['uniswapAdapter'])
        await service.close(); await restart.close()

    async def test_canonical_ordered_journal_revocation_and_reorg_restart_recovery(self):
        store = Store()
        service = ProtocolConfiguration(settings(), store)
        await service.observe([OLD], context())
        journal = Journal([approval(NEW, True, 21, 2), approval(OLD, False, 21, 3),
                           approval(CUSTOM, True, 19, 1)])
        await service.apply_journal(journal)
        self.assertEqual((await service.get())['contracts']['uniswapAdapter'].lower(), NEW)
        self.assertNotIn(CUSTOM.lower(), [address.lower() for address in service.value['approved']])
        self.assertEqual(journal.requests[0][1][0:2], ('1', HELPERS.lower()))
        await service.invalidate_from(21)
        restart = ProtocolConfiguration(settings(), store)
        await restart.load()
        self.assertIsNone((await restart.get())['contracts']['uniswapAdapter'])
        await restart.observe([OLD], context(18, '0x'+'d'*64))
        await service.load()
        self.assertEqual((await service.get())['contracts']['uniswapAdapter'].lower(), OLD)
        await service.close(); await restart.close()

    async def test_facts_from_retired_fork_scope_do_not_restore_old_default(self):
        service = ProtocolConfiguration(settings(31338))
        await service.observe_generation('new')
        await service.observe_facts({'configuration': {'approvedAdapters': {'status': 'success', 'value': [NEW]}},
                                    'context': context()}, 'old')
        self.assertIsNone(service.value)
        await service.close()

    async def test_blocked_durable_load_does_not_block_configured_roots_or_default_errors(self):
        store = Store(); store.blocked = True
        service = ProtocolConfiguration(settings(), store)
        result = await service.get()
        self.assertEqual(result['contracts']['core'], CORE)
        self.assertEqual(result['tokens'][0]['address'], CORE)
        await store.started.wait()
        self.assertFalse(service.loading.done())
        from cybergold_candidate.quote_errors import QuoteFailure
        with self.assertRaises(QuoteFailure):
            await service.resolve_request({'amount': '1'})
        store.release.set(); await service.load()
        await service.close()

    async def test_newer_memory_and_serialized_saves_survive_late_old_storage(self):
        class DelayedStore(Store):
            def __init__(self):
                super().__init__()
                self.save_started, self.save_release = asyncio.Event(), asyncio.Event()
                self.block_save = False
            async def save(self, namespace, identity, value):
                scope = self.scope
                if self.block_save:
                    self.save_started.set(); await self.save_release.wait()
                self.values.setdefault(scope+namespace, {})[identity] = deepcopy(value)
        store = DelayedStore()
        service = ProtocolConfiguration(settings(), store)
        await service.observe([OLD], context(20))
        store.block_save = True
        first = asyncio.create_task(service.observe([NEW], context(21)))
        await store.save_started.wait()
        self.assertEqual((await service.get())['contracts']['uniswapAdapter'].lower(), NEW)
        await service.load()
        self.assertEqual(service.value['context']['blockNumber'], '21')
        second = asyncio.create_task(service.observe([OLD], context(22)))
        await asyncio.sleep(0)
        self.assertEqual((await service.get())['contracts']['uniswapAdapter'].lower(), OLD)
        store.save_release.set(); await asyncio.gather(first, second)
        restart = ProtocolConfiguration(settings(), store)
        await restart.load()
        self.assertEqual(restart.value['context']['blockNumber'], '22')
        self.assertEqual((await restart.get())['contracts']['uniswapAdapter'].lower(), OLD)
        await service.close(); await restart.close()

    async def test_rewind_cannot_be_resurrected_by_old_recovery_during_pending_clear(self):
        class DelayedClear(Store):
            def __init__(self):
                super().__init__()
                self.clear_started, self.clear_release = asyncio.Event(), asyncio.Event()
            async def save(self, namespace, identity, value):
                if value is None:
                    self.clear_started.set(); await self.clear_release.wait()
                await super().save(namespace, identity, value)
        store = DelayedClear()
        service = ProtocolConfiguration(settings(), store)
        await service.observe([NEW], context(21))
        clearing = asyncio.create_task(service.invalidate_from(21))
        await store.clear_started.wait()
        self.assertIsNone((await service.get())['contracts']['uniswapAdapter'])
        await service.load()
        self.assertIsNone(service.value)
        store.clear_release.set(); await clearing
        restart = ProtocolConfiguration(settings(), store)
        await restart.load()
        self.assertIsNone(restart.value)
        await service.close(); await restart.close()

    async def test_separate_api_and_worker_cache_keep_newer_durable_state_and_external_rewind(self):
        store = Store()
        api = ProtocolConfiguration(settings(), store)
        worker = ProtocolConfiguration(settings(), store)
        rpc = Rpc([OLD]); rpc.blocked = True
        pending = asyncio.create_task(worker.read_pending(rpc, {'number': 20, 'hash': HASH}))
        await rpc.started.wait()
        await api.observe([NEW], context(21))
        rpc.release.set()
        await worker.publish_pending(await pending)
        self.assertEqual(worker.value['context']['blockNumber'], '21')
        await api.load()
        self.assertEqual((await api.get())['contracts']['uniswapAdapter'].lower(), NEW)
        restart = ProtocolConfiguration(settings(), store)
        await restart.load()
        self.assertEqual(restart.value['context']['blockNumber'], '21')
        await worker.invalidate_from(21)
        await api.load()
        self.assertIsNone((await api.get())['contracts']['uniswapAdapter'])
        await worker.observe([OLD], context(18, '0x'+'d'*64))
        await api.load()
        self.assertEqual(api.value['context']['blockNumber'], '18')
        self.assertEqual((await api.get())['contracts']['uniswapAdapter'].lower(), OLD)
        await api.close(); await worker.close(); await restart.close()

    async def test_live_helpers_facts_do_not_wait_for_optional_cache_recovery(self):
        store = Store(); store.blocked = True
        configuration = ProtocolConfiguration(settings(), store,
            generation_reader=lambda: asyncio.sleep(0, result=None))
        class FactsRpc(Rpc):
            chain_id, helpers = 1, HELPERS
            async def block(self):
                return {'number': 20, 'hash': HASH, 'timestamp': 10}
            async def read(self, _group, _address, name, _block):
                return {'helperFeePpm': 0, 'permit2': SAFE, 'wrappedNative': CUSTOM,
                        'owner': SAFE, 'approvedAdapters': [NEW], 'paused': False}[name]
        facts = HelpersRouterFacts(settings(), FactsRpc(),
            configuration_observer=configuration.capture_facts)
        result = await facts.get()
        self.assertEqual(result['configuration']['paused'], {'status': 'success', 'value': False})
        self.assertEqual(result['configuration']['approvedAdapters']['value'], [NEW])
        await store.started.wait()
        self.assertIsNone(configuration.value)
        store.release.set()
        await asyncio.gather(*tuple(configuration.tasks))
        self.assertEqual((await configuration.get())['contracts']['uniswapAdapter'].lower(), NEW)
        await facts.close(); await configuration.close()

    async def test_worker_uses_existing_head_and_publishes_only_after_canonical_assertion(self):
        options = load_environment({'DATABASE_URL': 'postgresql://fixture.invalid/db',
            'NEXT_PUBLIC_CHAIN_ID': '1', 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': CORE,
            'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS': HELPERS, 'RPC_URL': 'http://fixture.invalid',
            'NEXT_PUBLIC_RPC_URL': 'http://fixture.invalid'})
        worker = WorkerEngine(None, options)
        rpc = Rpc(); rpc.canonical = False
        class Registry:
            def get_rpc(self): return rpc
            async def discover(self, _block, **_options): pass
            async def monitor(self, _block, **_options): pass
        class Recipient:
            async def refresh(self, _rpc, _block): pass
        rpc.block = lambda _number: asyncio.sleep(0, result={'number': 20, 'hash': HASH})
        worker.uniswap_registry, worker.market_recipient = Registry(), Recipient()
        worker.protocol_configuration = ProtocolConfiguration(options)
        with self.assertRaisesRegex(ValueError, 'changed hash'):
            await worker.collect_uniswap()
        self.assertIsNone(worker.protocol_configuration.value)
        rpc.canonical = True
        await worker.collect_uniswap()
        self.assertEqual((await worker.protocol_configuration.get())['contracts']['uniswapAdapter'].lower(), NEW)
        observed = len([call for call in rpc.calls if isinstance(call, tuple)])
        await worker.collect_uniswap()
        self.assertEqual(len([call for call in rpc.calls if isinstance(call, tuple)]), observed)
        self.assertEqual(rpc.calls[-1], 'canonical')
        await worker.protocol_configuration.close()

    async def test_collector_rewind_invalidates_only_the_changed_configuration_suffix(self):
        configuration = ProtocolConfiguration(settings())
        await configuration.observe([NEW], context(25))
        class Database:
            async def ensure_schema(self): pass
        class Client:
            async def block(self, number):
                return {'number': number, 'hash': HASH, 'timestamp': 10}
        config = {'chainId': 1, 'startBlock': 10, 'chunkSize': 20,
                  'maxBlocksPerRun': 20, 'reorgWindow': 2}
        collector = HelpersCollector(Database(), config, HELPERS,
                                     on_rewind=configuration.invalidate_from)
        collector.journal = SimpleNamespace(coverage=lambda: asyncio.sleep(0, result={
            'cursorBlock': 25, 'cursorBlockHash': '0x'+'d'*64}),
            ingest=lambda *_args: asyncio.sleep(0))
        rewound = []
        async def rewind(start, _first, _header): rewound.append(start)
        collector.rewind = rewind
        await collector.reconcile(Client(), Client(), anchor={'blockNumber': 26, 'blockHash': HASH})
        self.assertEqual(rewound, [23])
        self.assertIsNone(configuration.value)
        await configuration.observe([OLD], context(22))
        await collector.reconcile(Client(), Client(), anchor={'blockNumber': 26, 'blockHash': HASH})
        self.assertEqual((await configuration.get())['contracts']['uniswapAdapter'].lower(), OLD)
        await configuration.close()

    async def test_market_defaults_resolve_before_quote_and_model_identity(self):
        configuration = ProtocolConfiguration(settings())
        await configuration.observe([NEW], context())
        class Head:
            async def block(self, _hash): return {'number': 20, 'hash': HASH}
            async def assert_canonical(self, _block): pass
        rpc = Head()
        registry = SimpleNamespace(chain=1, core=CORE, inventory={},
            pending=SharedReads(), get_rpc=lambda: rpc, ensure_loaded=lambda: asyncio.sleep(0))
        market = MarketQuotes(settings(), registry, request_resolver=configuration.resolve_request)
        request = {'side': 'buy', 'mode': 'exact-in', 'counterToken': CUSTOM}
        model = await market.get_model(request)
        self.assertEqual(model['intent']['adapter'].lower(), NEW)
        async def selected(request, _update, **_options):
            return {'adapter': request['adapter']}
        market.sharing.service.get = selected
        self.assertEqual((await market.get({**request, 'amount': '1'}))['adapter'].lower(), NEW)
        await market.close(); await registry.pending.close(); await configuration.close()

    async def test_http_core_default_and_explicit_legacy_keep_their_distinct_identities(self):
        configuration = ProtocolConfiguration(settings())
        await configuration.observe([NEW], context())
        class Quoter:
            async def block(self, _hash): return {'hash': HASH}
        async def get(request, _update, **_options):
            return {'adapter': request['adapter']}
        service = SimpleNamespace(settings=settings(), routes=SimpleNamespace(rpc=Quoter()), get=get)
        shared = IntentSharing(service, request_resolver=configuration.resolve_request)
        app = create_app(quote_intent=shared)
        body = {'mode': 'issue-exact-in', 'token': CUSTOM, 'quoteToken': CUSTOM, 'native': False,
                'amount': '1', 'deadline': '10', 'orderedAssets': [], 'targets': []}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
            for address in (None, OLD):
                response = await client.post('/api/quotes/intent/stream', json={**body,
                    **({'adapter': address} if address else {})})
                frames = [json.loads(row) for row in response.text.splitlines()]
                self.assertEqual(response.status_code, 200)
                self.assertEqual(frames[-1]['value']['adapter'].lower(), address or NEW)
        await shared.close(); await configuration.close()

    async def test_config_only_generation_recovery_retires_models_before_publishing_context(self):
        class Database:
            generation = 'first'
            @asynccontextmanager
            async def connection(self): yield self
            async def execute(self, query, _params):
                self.assert_generation_query(query)
                return self
            @staticmethod
            def assert_generation_query(query): assert 'onchain_sync_state' in query
            async def fetchall(self):
                return [{'state_key': key, 'state_value': value} for key, value in (
                    ('sandbox_fork_generation', self.generation), ('sandbox_fork_block', '19'),
                    ('sandbox_fork_block_hash', HASH), ('sandbox_fork_projection_status', 'ready'))]
            async def close(self): pass
        database = Database()
        options = load_environment({'DATABASE_URL': 'postgresql://fixture.invalid/db',
            'NEXT_PUBLIC_CHAIN_ID': '31338', 'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': CORE,
            'NEXT_PUBLIC_RPC_URL': 'http://fixture.invalid'})
        history = QuoteHistory(options)
        captured, configurations = [], []
        def market(*args, **kwargs):
            value = MarketQuotes(*args, **kwargs)
            captured.append(value)
            return value
        def configuration(*args, **kwargs):
            value = ProtocolConfiguration(*args, **kwargs)
            configurations.append(value)
            return value
        with patch('cybergold_candidate.runtime.QuoteHistory', return_value=history), \
             patch('cybergold_candidate.runtime.MarketQuotes', side_effect=market), \
             patch('cybergold_candidate.runtime.ProtocolConfiguration', side_effect=configuration):
            app = create_configured_app(options, database)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
                await client.get('/api/protocol/config')
                await configurations[0].load()
                first = (await client.get('/api/protocol/config')).json()
                self.assertEqual(first['sandboxForkGeneration'], 'first')
                history.states['old'] = {'state': {}}
                captured[0].models['old'] = {'routes': []}
                captured[0].registry.observed['old'] = {}
                database.generation = 'second'
                await configurations[0].load()
                await client.get('/api/protocol/config')
                await configurations[0].load()
                second = (await client.get('/api/protocol/config')).json()
                self.assertEqual(second['sandboxForkGeneration'], 'second')
                self.assertEqual(history.generation, 'second')
                self.assertEqual(captured[0].generation, 'second')
                self.assertFalse(history.states)
                self.assertFalse(captured[0].models)
                self.assertFalse(captured[0].registry.observed)
                history.states['current'] = {}
                await client.get('/api/protocol/config')
                self.assertIn('current', history.states)
        await history.close()

    async def test_resolved_adapter_is_part_of_shared_quote_identity_before_publication(self):
        configuration = ProtocolConfiguration(settings())
        await configuration.observe([NEW], context())
        release, started = asyncio.Event(), asyncio.Event()
        class Quoter:
            async def block(self, _value): return {'hash': HASH}
        async def get(request, _update, **_kwargs):
            started.set(); await release.wait()
            return {'adapter': request['adapter']}
        service = SimpleNamespace(settings=settings(), routes=SimpleNamespace(rpc=Quoter()), get=get)
        shared = IntentSharing(service, request_resolver=configuration.resolve_request)
        first = asyncio.create_task(shared.get({'amount': '1'}, lambda _frame: asyncio.sleep(0)))
        await started.wait()
        second = asyncio.create_task(shared.get({'amount': '1'}, lambda _frame: asyncio.sleep(0)))
        async with asyncio.timeout(5):
            while shared.joined == 0:
                await asyncio.sleep(0)
        self.assertEqual(shared.started, 1)
        self.assertEqual(shared.joined, 1)
        release.set()
        results = await asyncio.gather(first, second)
        self.assertTrue(all(row['adapter'].lower() == NEW for row in results))
        await shared.close(); await configuration.close()


if __name__ == '__main__': unittest.main()
