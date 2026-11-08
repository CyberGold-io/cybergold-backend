"""Core construction cache warms once, follows events and owns its lifecycle."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from web3 import Web3

from cybergold_candidate.app import create_app
from cybergold_candidate.quoter.core_state import CoreQuoteState, FIELDS, CHANNEL, NAMESPACE

A, B, CORE, HELPERS, RECOVERY = ('0x'+format(i, '040x') for i in range(1, 6))


class Rpc:
    def __init__(self):
        self.calls, self.held, self.started, self.failures = [], {}, {}, {}
        self.values = dict(assets=[A, B], weights=[1_000_000, 0], conversions=[10**18, 2*10**18],
            recoveryAssets=[RECOVERY], issueFee=1000, redeemFee=2000, helperFee=3000)

    async def read_function(self, address, signature, types, args, outputs, block):
        name = next(name for name, (_, sig, _) in FIELDS.items() if sig == signature)
        self.calls.append(name)
        self.started.setdefault(name, asyncio.Event()).set()
        value = deepcopy(self.values[name])
        if name in self.held:
            await self.held[name].wait()
        if name in self.failures:
            raise self.failures[name]
        return (value,)


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def fetchall(self): return self.rows


class Db:
    def __init__(self):
        self.rows, self.notifications, self.queues, self.events = {}, [], [], []
        self.notify_failure = False
    @asynccontextmanager
    async def connection(self): yield self
    async def execute(self, sql, params):
        if 'pg_notify' in sql:
            if self.notify_failure: raise OSError('optional notification unavailable')
            self.notifications.append(params)
            for queue in self.queues:
                queue.put_nowait(SimpleNamespace(payload=params[1]))
            return Cursor([])
        address, position = params[1], tuple(params[2:4])
        return Cursor([row for row in self.events if row['address'] == address and
            (int(row['block_number']), row['log_index']) > position and row['topics'][0] in params[4]])


class Store:
    def __init__(self, database):
        self.database, self.scope, self.saves = database, 'generation:unobserved:', []
        self.failure = False
        self.hold = None
    async def load(self, namespace):
        if self.hold: await self.hold.wait()
        if self.failure: raise OSError('optional database unavailable')
        return deepcopy(self.database.rows.get((self.scope, namespace), {}))
    async def save(self, namespace, identity, value):
        if self.failure: raise OSError('optional database unavailable')
        self.saves.append(deepcopy(value))
        self.database.rows.setdefault((self.scope, namespace), {})[identity] = deepcopy(value)


class Listener:
    def __init__(self, database):
        self.queue, self.started, self.closed = asyncio.Queue(), asyncio.Event(), False
        database.queues.append(self.queue)
    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.closed = True
    async def execute(self, sql):
        assert sql == 'LISTEN '+CHANNEL
        self.started.set()
    async def notifies(self):
        while True: yield await self.queue.get()


def event(name, arguments, *, address=CORE, block=10, index=0):
    from cybergold_candidate.core_activity import EVENTS as CORE_EVENTS
    from cybergold_candidate.helpers_activity import EVENTS as HELPER_EVENTS
    definitions = CORE_EVENTS if address == CORE else HELPER_EVENTS
    topic, definition = next((t, e) for t, e in definitions.items() if e['name'] == name)
    types = [parameter['type'] for parameter in definition['inputs']]
    values = [arguments[parameter['name']] for parameter in definition['inputs']]
    return {'address': address.lower(), 'block_number': str(block), 'block_hash': '0x'+'ab'*32,
        'tx_hash': '0x'+'cd'*32, 'log_index': index, 'block_timestamp_seconds': '1',
        'topics': [topic], 'data': Web3.to_hex(Web3().codec.encode(types, values))}


class CoreQuoteStateTests(unittest.IsolatedAsyncioTestCase):
    def cache(self, *, store=None, publisher=False, database_url=None):
        rpc = Rpc()
        settings = SimpleNamespace(NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
            NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=HELPERS, DATABASE_URL=database_url)
        registry = SimpleNamespace(chain=31338, store=store, get_rpc=lambda: rpc)
        cache = CoreQuoteState(settings, registry, publisher=publisher)
        self.addAsyncCleanup(cache.close)
        return cache, rpc

    async def test_cold_start_warms_seven_fields_once_and_returns_owned_cache_hits(self):
        cache, rpc = self.cache()
        await cache.start()
        await cache.warming
        self.assertCountEqual(rpc.calls, FIELDS)
        first = await cache.get()
        first['assets'].append(RECOVERY)
        self.assertEqual((await cache.get())['assets'], [A, B])
        await cache.outputs()
        self.assertEqual(len(rpc.calls), 7)

    async def test_basis_and_descriptors_do_not_wait_for_optional_fee_or_database(self):
        database, held = Db(), asyncio.Event()
        store = Store(database)
        store.hold = held
        cache, rpc = self.cache(store=store)
        rpc.held['helperFee'] = asyncio.Event()
        await cache.start()
        value = await asyncio.wait_for(cache.get(), 1)
        self.assertEqual(value['assets'], [A, B])
        self.assertNotIn('helperFee', value)
        outputs = await asyncio.wait_for(cache.outputs(), 1)
        self.assertEqual(outputs[-1]['id'], str(int(RECOVERY, 16)))
        held.set()
        rpc.held['helperFee'].set()

    async def test_event_wakes_pending_basis_and_old_getter_cannot_overwrite_it(self):
        cache, rpc = self.cache()
        rpc.held.update(assets=asyncio.Event(), weights=asyncio.Event())
        await cache.start()
        while len(rpc.calls) < 7: await asyncio.sleep(0)
        pending = asyncio.create_task(cache.get())
        cache.apply_event('BasketConfigured', {'assets': [B], 'targetsPpm': [1_000_000],
            'cygldPerUnitFp18': [5]})
        result = await asyncio.wait_for(pending, 1)
        self.assertEqual((result['assets'], result['weights'], result['conversions']), ([B], [1_000_000], [5]))
        rpc.held['assets'].set(); rpc.held['weights'].set()
        await cache.warming
        self.assertEqual((await cache.get())['assets'], [B])
        self.assertEqual(len(rpc.calls), 7)

    async def test_warm_configuration_and_fee_events_update_without_rpc(self):
        cache, rpc = self.cache()
        await cache.start(); await cache.warming
        cache.apply_event('BasketConfigured', {'assets': [B], 'targetsPpm': [1_000_000], 'cygldPerUnitFp18': [3]})
        cache.apply_event('HelperFeeUpdated', {'newHelperFeePpm': '42'})
        cache.apply_event('IssuanceFeePpmUpdated', {'newIssuanceFeePpm': '43'})
        cache.apply_event('RedemptionFeePpmUpdated', {'newRedemptionFeePpm': '44'})
        value = await cache.get()
        self.assertEqual([value[key] for key in ('helperFee', 'issueFee', 'redeemFee')], [42, 43, 44])
        self.assertEqual(len(rpc.calls), 7)

    async def test_max_supply_event_invalidates_derived_cap_without_waiting_for_rpc(self):
        cache, rpc = self.cache()
        await cache.start()
        await cache.warming
        cache.update({'maxSupply': 20, 'effectiveCap': 20, 'supply': 10})
        cache.apply_event('MaxTotalSupplyUpdated', {'newMaxTotalSupply': 30})
        self.assertEqual(cache.value['maxSupply'], 30)
        self.assertEqual(cache.value['supply'], 10)
        self.assertNotIn('effectiveCap', cache.value)
        self.assertEqual(len(rpc.calls), 7)
        # A recovery cap can remain below the new global maximum. Preserve
        # its later ordinary observation rather than guessing that it is 30.
        cache.observe_facts({'issuanceCapacity': {
            'effectiveCygldSupplyCap': {'status': 'success', 'value': '25'}}})
        self.assertEqual((await cache.get())['effectiveCap'], 25)
        self.assertEqual(len(rpc.calls), 7)

    async def test_model_preserves_actual_erc20_and_recovery_descriptors_and_capacity(self):
        cache, rpc = self.cache()
        cache.observe_model({'assets': [A, B], 'weights': ['500000', '500000'], 'conversions': ['1', '2'],
            'available': ['0', '9'], 'supply': '20', 'maxSupply': '30', 'effectiveCap': '25',
            'recoveryShares': ['12'], 'recoveryValues': ['13'], 'descriptors': [
                {'kind': 0, 'token': A, 'id': '0'},
                {'kind': 1, 'token': CORE, 'id': str(int(RECOVERY, 16))}]})
        outputs = await cache.outputs()
        self.assertEqual([row['amount'] for row in outputs], ['0', '9', '1'])
        self.assertEqual(outputs[-1], {'kind': 1, 'token': CORE, 'id': str(int(RECOVERY, 16)), 'amount': '1'})
        self.assertEqual(cache.value['supply'], 20)
        self.assertEqual(cache.value['recoveryValues'], [13])
        cache.observe_model({'assets': [A, B], 'available': ['0', '0']})
        self.assertTrue(all(int(row['amount']) == 0 for row in (await cache.outputs())[:-1]))
        self.assertNotIn('assets', rpc.calls)
        self.assertNotIn('recoveryAssets', rpc.calls)

    async def test_protocol_facts_fan_in_includes_optional_capacity_without_getters(self):
        cache, rpc = self.cache()
        successful = lambda value: {'status': 'success', 'value': value}
        cache.observe_facts({'basket': {'assets': successful([A]), 'targetsPpm': successful(['1000000']),
            'cygldPerUnitFp18': successful(['5'])}, 'fees': {'issuancePpm': successful('1'), 'helpersPpm': successful('2')},
            'issuanceCapacity': {'totalSupply': successful('10'), 'maxTotalSupply': successful('20'),
                'effectiveCygldSupplyCap': successful('15')}})
        self.assertEqual((await cache.get())['effectiveCap'], 15)
        self.assertNotIn('assets', rpc.calls)
        self.assertNotIn('weights', rpc.calls)

    async def test_generation_restarts_pending_fields_without_returning_old_values(self):
        cache, rpc = self.cache()
        rpc.held['assets'] = asyncio.Event()
        pending = asyncio.create_task(cache.field('assets'))
        while not rpc.calls: await asyncio.sleep(0)
        rpc.values['assets'] = [B]
        await cache.observe_generation('new')
        rpc.held['assets'].set()
        self.assertEqual(await asyncio.wait_for(pending, 1), [B])
        self.assertEqual(cache.generation, 'new')
        self.assertEqual(cache.value['assets'], [B])

    async def test_component_control_failure_settles_the_shared_field_future(self):
        class Stopped(BaseException): pass
        cache, rpc = self.cache()
        failure = Stopped('ordinary owner stop')
        rpc.failures['assets'] = failure
        with self.assertRaises(Stopped) as caught:
            await asyncio.wait_for(cache.field('assets'), 1)
        self.assertIs(caught.exception, failure)
        await asyncio.sleep(0)
        self.assertNotIn('assets', cache.pending)

    async def test_store_load_never_overwrites_a_newer_local_event(self):
        database, release = Db(), asyncio.Event()
        store = Store(database); store.hold = release
        database.rows[(store.scope, NAMESPACE)] = {CORE.lower(): {'fields': {'assets': [A], 'weights': [1]}, 'revision': 1}}
        cache, _ = self.cache(store=store)
        loading = asyncio.create_task(cache.reload())
        await asyncio.sleep(0)
        cache.update({'assets': [B], 'weights': [2]})
        release.set(); await loading
        self.assertEqual((cache.value['assets'], cache.value['weights']), ([B], [2]))

    async def test_new_worker_snapshot_delivers_removed_capacity_and_amount_hints(self):
        database = Db()
        worker, rpc = self.cache(store=Store(database), publisher=True)
        api, _ = self.cache(store=Store(database))
        worker.update({**deepcopy(rpc.values), 'available': [0, 9],
            'supply': 10, 'maxSupply': 30, 'effectiveCap': 20})
        await worker.publish()
        await api.load()
        self.assertEqual(api.value['available'], [0, 9])
        worker.apply_event('Issued', {})
        await worker.publish()
        await api.reload()
        for name in ('available', 'supply', 'effectiveCap'):
            self.assertNotIn(name, api.value)
        self.assertEqual(api.value['maxSupply'], 30)
        self.assertEqual(api.value['assets'], [A, B])
        self.assertEqual(rpc.calls, [])

    async def test_new_snapshot_removals_preserve_local_observations_completed_during_load(self):
        database, release = Db(), asyncio.Event()
        worker, rpc = self.cache(store=Store(database), publisher=True)
        store = Store(database)
        api, _ = self.cache(store=store)
        worker.update({**deepcopy(rpc.values), 'available': [0, 9], 'supply': 10, 'effectiveCap': 20})
        await worker.publish()
        await api.load()
        worker.apply_event('Issued', {})
        await worker.publish()
        store.hold = release
        loading = asyncio.create_task(api.reload())
        await asyncio.sleep(0)
        api.update({'available': [3, 4], 'supply': 11})
        release.set()
        await loading
        self.assertEqual((api.value['available'], api.value['supply']), ([3, 4], 11))
        self.assertNotIn('effectiveCap', api.value)

    async def test_partial_new_basket_observation_drops_only_stale_dependent_vectors(self):
        cache, rpc = self.cache()
        await cache.start()
        await cache.warming
        cache.update({'available': [8, 9], 'supply': 10})
        rpc.values.update(assets=[B], weights=[1_000_000], conversions=[7])
        cache.observe_facts({'basket': {'assets': {'status': 'success', 'value': [B]},
            'targetsPpm': {'status': 'error'}, 'cygldPerUnitFp18': {'status': 'error'}}})
        for name in ('weights', 'conversions', 'available'):
            self.assertNotIn(name, cache.value)
        self.assertEqual(cache.value['supply'], 10)
        self.assertEqual((await cache.get())['weights'], [1_000_000])
        self.assertEqual(await cache.field('conversions'), [7])
        self.assertEqual(rpc.calls.count('assets'), 1)
        self.assertEqual(rpc.calls.count('weights'), 2)
        self.assertEqual(rpc.calls.count('conversions'), 2)

    async def test_startup_stored_seed_does_not_suppress_a_live_getter_completion(self):
        database = Db(); store = Store(database)
        store.hold = asyncio.Event()
        database.rows[(store.scope, NAMESPACE)] = {CORE.lower(): {
            'fields': {'assets': [A]}, 'revision': 1}}
        cache, rpc = self.cache(store=store)
        rpc.values['assets'] = [B]
        rpc.held['assets'] = asyncio.Event()
        await cache.start()
        while 'assets' not in rpc.calls:
            await asyncio.sleep(0)
        getter = cache.pending['assets']
        store.hold.set()
        await cache.loading
        self.assertEqual(cache.value['assets'], [A])
        rpc.held['assets'].set()
        await getter
        self.assertEqual(cache.value['assets'], [B])

    async def test_worker_publishes_only_changed_state_and_retries_notification_without_resaving(self):
        database = Db(); store = Store(database)
        cache, _ = self.cache(store=store, publisher=True)
        cache.update({'assets': [A], 'weights': [1]})
        database.notify_failure = True
        await cache.publish()
        self.assertEqual(len(store.saves), 1)
        database.notify_failure = False
        await cache.publish(); await cache.publish()
        self.assertEqual(len(store.saves), 1)
        self.assertEqual(len(database.notifications), 1)
        self.assertEqual(json.loads(database.notifications[0][1])['scope'], store.scope)
        cache.update({'weights': [2]}); await cache.publish()
        self.assertEqual((len(store.saves), len(database.notifications)), (2, 2))

    async def test_api_listener_adopts_worker_updates_and_closes_its_connection(self):
        database = Db(); api_store, worker_store = Store(database), Store(database)
        api, _ = self.cache(store=api_store, database_url='postgresql://fixture.invalid/db')
        worker, _ = self.cache(store=worker_store, publisher=True)
        listener = Listener(database)
        with patch('cybergold_candidate.quoter.core_state.AsyncConnection.connect', AsyncMock(return_value=listener)):
            await api.start(); await listener.started.wait(); await api.warming
            worker.update({'assets': [B], 'weights': [1_000_000]})
            await worker.publish()
            async with asyncio.timeout(1):
                while api.value['assets'] != [B]: await asyncio.sleep(0)
            self.assertFalse(api_store.saves)
            await api.close()
        self.assertTrue(listener.closed)
        self.assertFalse(api.tasks)
        self.assertFalse(api.pending)

    async def test_journal_event_payloads_update_worker_cache_without_repricing(self):
        database = Db(); store = Store(database)
        cache, rpc = self.cache(store=store, publisher=True)
        await cache.start(); await cache.warming
        database.events = [event('BasketConfigured', {'assets': [B], 'targetsPpm': [1_000_000],
            'goldRefGramsFp18': [10**18], 'cygldRefGramsFp18': 10**18, 'cygldPerUnitFp18': [4]}),
            event('HelperFeeUpdated', {'previousHelperFeePpm': 3, 'newHelperFeePpm': 7}, address=HELPERS)]
        await cache.apply_journal(database)
        self.assertEqual((cache.value['assets'], cache.value['helperFee']), ([B], 7))
        self.assertEqual(len(rpc.calls), 7)
        await cache.apply_journal(database)
        self.assertEqual(len(store.saves), 1)

    async def test_recovery_events_preserve_numeric_descriptor_order_without_rpc(self):
        cache, rpc = self.cache()
        await cache.start(); await cache.warming
        cache.apply_event('RecoveryActivated', {'asset': A, 'addedCoreAttachedShares': '5'})
        self.assertEqual(cache.value['recoveryAssets'], [A, RECOVERY])
        cache.apply_event('RecoveryRehabilitated', {'asset': RECOVERY})
        self.assertEqual(cache.value['recoveryAssets'], [A])
        self.assertEqual(len(rpc.calls), 7)

    async def test_generation_notification_changes_existing_scope_without_new_quote_reads(self):
        database = Db(); api_store, worker_store = Store(database), Store(database)
        api, rpc = self.cache(store=api_store, database_url='postgresql://fixture.invalid/db')
        worker, _ = self.cache(store=worker_store, publisher=True)
        listener = Listener(database)
        api.generation_observer = AsyncMock()
        with patch('cybergold_candidate.quoter.core_state.AsyncConnection.connect', AsyncMock(return_value=listener)):
            await api.start(); await listener.started.wait(); await api.warming
            calls = len(rpc.calls)
            await worker.observe_generation('new-generation')
            worker.update({**deepcopy(rpc.values), 'assets': [B], 'weights': [1_000_000]})
            await worker.publish()
            async with asyncio.timeout(1):
                while api.generation != 'new-generation' or api.value.get('assets') != [B]:
                    await asyncio.sleep(0)
            self.assertEqual(api_store.scope, worker_store.scope)
            self.assertEqual(len(rpc.calls), calls)
            api.generation_observer.assert_awaited_once_with('new-generation')
            await api.close()

    async def test_rewind_does_not_reload_the_disproved_snapshot_and_publishes_reset(self):
        database = Db(); store = Store(database)
        cache, rpc = self.cache(store=store, publisher=True)
        await cache.start(); await cache.warming
        await cache.publish()
        await cache.invalidate_from(5)
        await cache.reload()
        self.assertFalse(cache.value)
        await cache.publish()
        self.assertTrue(store.saves[-1]['reset'])
        self.assertEqual(store.saves[-1]['fields'], {})
        self.assertEqual(len(rpc.calls), 7)

    async def test_configured_runtime_fans_existing_facts_and_models_into_cache(self):
        from cybergold_candidate import runtime
        from cybergold_candidate.environment import load_environment
        settings = load_environment({'NEXT_PUBLIC_CHAIN_ID': '31338',
            'NEXT_PUBLIC_CORE_DIAMOND_ADDRESS': CORE, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS': HELPERS,
            'NEXT_PUBLIC_RPC_URL': 'http://fixture.invalid', 'DATABASE_URL': None})
        database = SimpleNamespace(close=AsyncMock())
        services = {}
        def configured_app(**values): services.update(values); return values
        with patch.object(runtime, 'create_app', side_effect=configured_app):
            runtime.create_configured_app(settings, database)
        cache = services['core_quote_state']
        self.addAsyncCleanup(cache.close)
        success = lambda value: {'status': 'success', 'value': value}
        services['protocol_facts'].on_observation({'context': {'blockHash': None, 'blockNumber': None},
            'basket': {'assets': success([A]), 'targetsPpm': success(['1000000']),
                       'cygldPerUnitFp18': success(['2'])},
            'fees': {'issuancePpm': success('3'), 'helpersPpm': success('4')}})
        self.assertEqual(cache.value['assets'], [A])
        history = services['quote_intent'].service.history
        self.assertTrue(history.facts)
        history.state_observer({'state': {'assets': [A], 'available': ['0'], 'descriptors': [
            {'kind': 1, 'token': CORE, 'id': str(int(RECOVERY, 16))}]}})
        self.assertEqual(cache.value['available'], [0])
        self.assertEqual(cache.value['recoveryAssets'], [RECOVERY])
        await services['on_shutdown']()

    async def test_shutdown_closes_owned_cache_before_engines_and_database(self):
        order = []
        class Component:
            def __init__(self, name): self.name = name
            async def start(self): order.append(self.name+'-start')
            async def close(self): order.append(self.name+'-close')
        async def database_close(): order.append('database-close')
        app = create_app(core_quote_state=Component('core-cache'), economic_quotes=Component('economic'),
            market_quotes=Component('engine'), uniswap_registry=Component('registry'), on_shutdown=database_close)
        async with app.router.lifespan_context(app): pass
        self.assertLess(order.index('economic-close'), order.index('core-cache-close'))
        self.assertLess(order.index('core-cache-close'), order.index('engine-close'))
        self.assertLess(order.index('registry-close'), order.index('database-close'))


if __name__ == '__main__': unittest.main()
