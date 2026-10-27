"""Economic identity, original observations and optional storage failure."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cybergold_candidate.quoter.store import EconomicQuoteStore, normalized_economic_request


CORE, HELPERS, ADAPTER, USDT = ('0x'+str(index)*40 for index in range(1, 5))


def fixture():
    settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE,
        NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=HELPERS, CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS=ADAPTER,
        CYBERGOLD_RUNTIME_CONFIG_ID='sha256:configuration')
    store = SimpleNamespace(scope='generation:one:')
    registry = SimpleNamespace(chain=31338, core=CORE, generation='one', store=store)
    request = {'intent': 0, 'inputs': [{'currency': USDT, 'amount': '100000'}], 'outputCurrency': CORE}
    quote = {'request': deepcopy(request), 'quotedOutput': '249',
             'context': {'blockNumber': '100', 'blockHash': '0x'+'ab'*32},
             'plan': {'operations': [{'kind': 'market', 'amount': '100000'}]}}
    return settings, registry, request, quote


class EconomicQuoteStoreTests(unittest.IsolatedAsyncioTestCase):
    def test_lookup_identity_excludes_execution_head_and_transport_fields(self):
        settings, registry, request, _ = fixture()
        service = EconomicQuoteStore(settings, registry)
        initial = service.capture_scope(request)
        noisy = {**request, 'recipient': HELPERS, 'sender': USDT, 'deadline': '123',
            'slippageBps': 500, 'blockHash': 'another-head', 'refresh': True}
        noisy['inputs'] = [{'currency': USDT.upper(), 'amount': '000100000'}]
        noisy['outputCurrency'] = CORE.upper()
        self.assertEqual(service.capture_scope(noisy), initial)
        self.assertEqual(normalized_economic_request(noisy), request)

    def test_economic_request_changes_do_not_collide(self):
        settings, registry, request, _ = fixture()
        service = EconomicQuoteStore(settings, registry)
        initial = service.capture_scope(request)
        for changed in ({**request, 'intent': 1}, {**request, 'outputCurrency': HELPERS},
                        {**request, 'inputs': [{'currency': USDT, 'amount': '100001'}]},
                        {**request, 'inputs': [{'currency': HELPERS, 'amount': '100000'}]}):
            self.assertNotEqual(service.capture_scope(changed), initial)
        basket = {**request, 'intent': 2, 'inputs': request['inputs'] + [{'currency': HELPERS, 'amount': '1'}]}
        self.assertNotEqual(service.capture_scope(basket),
                            service.capture_scope({**basket, 'inputs': list(reversed(basket['inputs']))}))

    def test_deployment_generation_and_observed_fee_scope_are_separate(self):
        settings, registry, request, _ = fixture()
        fees = {'helperFeePpm': 1000}
        service = EconomicQuoteStore(settings, registry, fee_scope=lambda: fees)
        initial = service.capture_scope(request)
        fees['helperFeePpm'] = 2000
        self.assertNotEqual(service.capture_scope(request), initial)
        fees['helperFeePpm'] = 1000
        settings.CYBERGOLD_RUNTIME_CONFIG_ID = 'sha256:changed'
        self.assertNotEqual(service.capture_scope(request), initial)
        settings.CYBERGOLD_RUNTIME_CONFIG_ID = 'sha256:configuration'
        settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS = USDT
        self.assertNotEqual(service.capture_scope(request), initial)
        settings.NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS = HELPERS
        registry.generation = 'two'
        registry.store.scope = 'generation:two:'
        self.assertNotEqual(service.capture_scope(request), initial)
        self.assertEqual(initial.namespace, 'generation:one:economic-quotes')

    async def test_unconfigured_and_failed_storage_leave_ordinary_search_available(self):
        settings, registry, request, quote = fixture()
        service = EconomicQuoteStore(settings)
        self.assertIsNone(await service.lookup(request))
        self.assertFalse(await service.save(request, quote))
        async def fail():
            raise RuntimeError('private provider text must not escape')
        registry.store.prepare = fail
        service = EconomicQuoteStore(settings, registry)
        self.assertIsNone(await service.lookup(request))
        self.assertFalse(await service.save(request, quote))

    async def test_cancellation_propagates_instead_of_becoming_a_cache_miss(self):
        settings, registry, request, quote = fixture()
        async def cancel():
            raise asyncio.CancelledError()
        registry.store.prepare = cancel
        service = EconomicQuoteStore(settings, registry)
        with self.assertRaises(asyncio.CancelledError):
            await service.lookup(request)
        with self.assertRaises(asyncio.CancelledError):
            await service.save(request, quote)

    async def test_point_lookup_returns_an_owned_original_tuple_without_relabeling(self):
        settings, registry, request, quote = fixture()
        executed = []
        async def prepare():
            pass
        class Connection:
            async def execute(self, query, values):
                executed.append((query, values))
                return self
            async def fetchone(self):
                return {'payload': {'quote': quote, 'savedAt': 'later-storage-time', 'savedSequence': 5}}
        @asynccontextmanager
        async def connection():
            yield Connection()
        registry.store.prepare = prepare
        registry.store.database = SimpleNamespace(connection=connection)
        service = EconomicQuoteStore(settings, registry)
        observed = await service.lookup(request)
        self.assertEqual(observed, quote)
        observed['context']['blockHash'] = 'mutated-client-copy'
        self.assertNotEqual(observed, quote)
        self.assertEqual(len(executed), 1)
        self.assertIn('identity=%s', executed[0][0])


if __name__ == '__main__':
    unittest.main()
