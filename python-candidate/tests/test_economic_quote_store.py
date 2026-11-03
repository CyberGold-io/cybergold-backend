"""Economic identity, original observations and optional storage failure."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
import unittest
import os
import json
from uuid import uuid4

from cybergold_candidate.quoter.store import EconomicQuoteStore, normalized_economic_request
from cybergold_candidate.quoter.path_families import quote_path_family


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
    async def test_larger_cached_budget_can_be_the_best_fitting_lower_quote(self):
        settings, registry, request, _ = fixture()
        service = EconomicQuoteStore(settings, registry)
        quotes, headers, executed = {}, [], []
        for amount, funding, output in [(95000, 95000, 99), (105000, 105000, 1),
                                         (110000, 90000, 100), (120000, 80000, 100)]:
            candidate = {**request, 'inputs': [{'currency': USDT, 'amount': str(amount)}]}
            identity = service.capture_scope(candidate).identity
            quotes[identity] = {'request': candidate, 'inputs': [{'currency': USDT, 'amount': str(funding)}],
                                'quotedOutput': str(output)}
            headers.append({'identity': identity, 'request': candidate,
                            'funded_input': str(funding), 'quoted_output': str(output)})
        async def prepare():
            pass
        class Connection:
            async def execute(self, query, values):
                executed.append((query, values))
                return self
            async def fetchall(self):
                if len(executed) == 1:
                    return headers
                return [{'identity': key, 'quote': quotes[key]} for key in executed[-1][1][-1]]
        @asynccontextmanager
        async def connection():
            yield Connection()
        registry.store.prepare = prepare
        registry.store.database = SimpleNamespace(connection=connection)
        selected = {row['side']: row for row in await service.neighbors(request)}
        self.assertEqual(selected['lower']['quote']['inputs'][0]['amount'], '80000')
        self.assertEqual(selected['lower']['quote']['request']['inputs'][0]['amount'], '120000')
        self.assertEqual(selected['upper']['quote']['request']['inputs'][0]['amount'], '105000')
        self.assertEqual(len(executed), 2)

    async def test_better_lower_output_is_not_hidden_by_a_nearer_bad_quote(self):
        settings, registry, request, _ = fixture()
        service = EconomicQuoteStore(settings, registry)
        quotes = {}
        headers = []
        # A recent, nearby poor result must not crowd out the smaller useful
        # plan. Integer outputs also exceed floating-point exact precision.
        for amount, output in [(95000, 3643), (10000, 78948539895713944454),
                               (110000, 5), (120000, 999999999999999999999)]:
            req = {**request, 'inputs': [{'currency': USDT, 'amount': str(amount)}]}
            key = service.capture_scope(req).identity
            quotes[key] = {'request': req, 'quotedOutput': str(output)}
            headers.append({'identity': key, 'request': req, 'quoted_output': str(output)})
        executed = []
        async def prepare():
            pass
        class Connection:
            async def execute(self, query, values):
                executed.append((query, values))
                return self
            async def fetchall(self):
                if len(executed) == 1:
                    return headers
                return [{'identity': key, 'quote': quotes[key]} for key in executed[-1][1][-1]]
        @asynccontextmanager
        async def connection():
            yield Connection()
        registry.store.prepare = prepare
        registry.store.database = SimpleNamespace(connection=connection)
        selected = {row['side']: row for row in await service.neighbors(request)}
        self.assertEqual(selected['lower']['quote']['request']['inputs'][0]['amount'], '10000')
        self.assertEqual(selected['upper']['quote']['request']['inputs'][0]['amount'], '110000')
        self.assertEqual(len(executed), 2)
        self.assertEqual(len(executed[-1][1][-1]), 2)

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
        self.assertEqual(await service.neighbors(request), [])
        async def fail():
            raise RuntimeError('private provider text must not escape')
        registry.store.prepare = fail
        service = EconomicQuoteStore(settings, registry)
        self.assertIsNone(await service.lookup(request))
        self.assertFalse(await service.save(request, quote))
        self.assertEqual(await service.neighbors(request), [])

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
        with self.assertRaises(asyncio.CancelledError):
            await service.neighbors(request)

    async def test_point_lookup_returns_an_owned_original_tuple_without_relabeling(self):
        settings, registry, request, quote = fixture()
        quote['routeOrigins'] = {'economicEvaluator': 'cybergold-quoter',
            'discoveryProviders': ['cybergold-custom', 'uniswap-alpharouter'],
            'conversions': {'0:market': ['cybergold-custom', 'uniswap-alpharouter']}}
        quote['metrics'] = {'routeDiscovery': {'physicalRpc': {'requests': 7}, 'elapsedMs': 321.5}}
        executed = []
        async def prepare():
            pass
        class Connection:
            async def execute(self, query, values):
                executed.append((query, values))
                return self
            async def fetchall(self):
                return [{'payload': {'quote': quote, 'savedAt': 'later-storage-time', 'savedSequence': 5}}]
        @asynccontextmanager
        async def connection():
            yield Connection()
        registry.store.prepare = prepare
        registry.store.database = SimpleNamespace(connection=connection)
        service = EconomicQuoteStore(settings, registry)
        observed = await service.lookup(request)
        self.assertEqual(observed, quote)
        self.assertEqual(observed['routeOrigins'], quote['routeOrigins'])
        self.assertEqual(observed['metrics'], quote['metrics'])
        observed['context']['blockHash'] = 'mutated-client-copy'
        self.assertNotEqual(observed, quote)
        self.assertEqual(len(executed), 1)
        self.assertIn('identity=ANY(%s)', executed[0][0])


@unittest.skipUnless(os.environ.get('CYBERGOLD_TEST_POSTGRES_DSN'),
                     'Optional disposable PostgreSQL fixture is not configured.')
class EconomicQuoteFamilyPostgresTests(unittest.IsolatedAsyncioTestCase):
    """Actual JSONB SQL over an explicitly supplied disposable test database.

    Every test owns a unique namespace and deletes only its own fixture rows.
    No application database or server deployment configuration is read.
    """
    async def asyncSetUp(self):
        import psycopg
        from psycopg.rows import dict_row
        dsn = os.environ['CYBERGOLD_TEST_POSTGRES_DSN']
        @asynccontextmanager
        async def connection():
            async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
                yield conn
        settings, registry, self.request, _ = fixture()
        async def prepare():
            pass
        registry.store = SimpleNamespace(scope='family-cache-test:'+uuid4().hex+':',
            prepare=prepare, database=SimpleNamespace(connection=connection))
        self.connection, self.registry = connection, registry
        self.subject = EconomicQuoteStore(settings, registry)
        async with connection() as conn:
            await conn.execute('''CREATE TABLE IF NOT EXISTS cybergold_uniswap_state (
                chain_id BIGINT NOT NULL, core_address TEXT NOT NULL, namespace TEXT NOT NULL,
                identity TEXT NOT NULL, payload JSONB NOT NULL,
                PRIMARY KEY(chain_id,core_address,namespace,identity))''')

    async def asyncTearDown(self):
        scope = self.subject.capture_scope(self.request)
        async with self.connection() as conn:
            await conn.execute('DELETE FROM cybergold_uniswap_state WHERE chain_id=%s AND core_address=%s AND namespace=ANY(%s)',
                (scope.chain, scope.core, [scope.namespace, scope.namespace+'-sequence']))

    def quote(self, maximum, output, family, *, funding=None):
        request = {**self.request, 'inputs': [{'currency': USDT, 'amount': str(maximum)}]}
        funding = maximum if funding is None else funding
        # Mixed bodies still belong to Core. A dormant zero-Core branch must
        # not relabel a pure Market observation as Core.
        branches = ([{'kind': 0, 'amountIn': '1'}, {'kind': 1, 'amountIn': str(funding-1)}]
                    if family == 'core' else [{'kind': 0, 'amountIn': '0'}, {'kind': 1, 'amountIn': str(funding)}])
        return {'request': request, 'inputs': [{'currency': USDT, 'amount': str(funding)}],
            'quotedOutput': str(output), 'context': {'blockNumber': None, 'blockHash': None, 'observedAt': family},
            'fees': {'family-fixture': family}, 'routeOrigins': {'family-fixture': family},
            'plan': {'allocations': deepcopy(branches), 'body': {'branches': branches}, 'conversions': {}}}

    async def save(self, quote):
        self.assertTrue(await self.subject.save(quote['request'], quote))

    async def test_old_single_row_and_new_slots_keep_newest_whole_quote_per_semantic_family(self):
        old = self.quote(100000, 300, 'core')
        scope = self.subject.capture_scope(old['request'])
        async with self.connection() as conn:
            await conn.execute('INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)',
                (scope.chain, scope.core, scope.namespace, scope.identity,
                 json.dumps({'quote': old, 'savedSequence': 1})))
            await conn.execute('INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)',
                (scope.chain, scope.core, scope.namespace+'-sequence', 'commits', json.dumps({'sequence': 1})))
        market, core = self.quote(100000, 200, 'market'), self.quote(100000, 150, 'core')
        await self.save(market)
        self.assertEqual(await self.subject.lookup(self.request), old)
        await self.save(core)
        # A newer lower-priced Core observation replaces only that logical
        # Core point. Its older high price cannot hide the new Market winner.
        self.assertEqual(await self.subject.lookup(self.request), market)
        neighbors = await self.subject.neighbors(self.request)
        self.assertEqual([(row['family'], row['side']) for row in neighbors], [('market', 'lower'), ('core', 'lower')])
        self.assertEqual([row['quote'] for row in neighbors], [market, core])
        self.assertEqual([quote_path_family(row['quote']) for row in neighbors], ['market', 'core'])
        async with self.connection() as conn:
            cursor = await conn.execute('SELECT identity FROM cybergold_uniswap_state WHERE namespace=%s', (scope.namespace,))
            self.assertEqual({row['identity'] for row in await cursor.fetchall()},
                             {scope.identity, scope.identity+':market', scope.identity+':core'})

    async def test_limit_one_retains_both_families_and_prunes_the_previous_request_together(self):
        self.subject.limit = 1
        market, core = self.quote(100000, 200, 'market'), self.quote(100000, 150, 'core')
        await self.save(market); await self.save(core)
        self.assertEqual(len(await self.subject.neighbors(self.request)), 2)
        newer_market, newer_core = self.quote(110000, 201, 'market'), self.quote(110000, 151, 'core')
        await self.save(newer_market); await self.save(newer_core)
        self.assertIsNone(await self.subject.lookup(self.request))
        self.assertEqual(await self.subject.lookup(newer_market['request']), newer_market)
        neighbors = await self.subject.neighbors(newer_market['request'])
        self.assertEqual([row['quote'] for row in neighbors], [newer_market, newer_core])
        self.assertEqual(len(neighbors), 2)

    async def test_each_family_supplies_best_funded_lower_and_nearest_strictly_higher_upper(self):
        for quote in [self.quote(80000, 100, 'market'), self.quote(130000, 160, 'market', funding=70000),
                      self.quote(110000, 130, 'market'), self.quote(200000, 999, 'market'),
                      self.quote(90000, 120, 'core'), self.quote(120000, 140, 'core')]:
            await self.save(quote)
        neighbors = await self.subject.neighbors(self.request)
        self.assertEqual([(row['family'], row['side']) for row in neighbors],
                         [('market', 'lower'), ('market', 'upper'), ('core', 'lower'), ('core', 'upper')])
        self.assertEqual([row['quote']['inputs'][0]['amount'] for row in neighbors],
                         ['70000', '110000', '90000', '120000'])
        self.assertEqual([row['quote']['quotedOutput'] for row in neighbors], ['160', '130', '120', '140'])
        self.assertEqual(len({row['identity'] for row in neighbors}), 4)

    async def test_partial_quote_retains_both_neighbor_roles_and_its_limited_upper_estimate(self):
        from cybergold_candidate.quoter.reuse_estimate import CachedEconomicEstimates
        quote = self.quote(50000, 8355, 'market', funding=47300)
        quote['searchCoverage'] = {'inputLimitObserved': True}
        await self.save(quote)
        requested = {**self.request, 'inputs': [{'currency': USDT, 'amount': '49000'}]}
        neighbors = await self.subject.neighbors(requested)
        self.assertEqual([(row['family'], row['side']) for row in neighbors],
                         [('market', 'lower'), ('market', 'upper')])
        self.assertEqual(len({row['identity'] for row in neighbors}), 1)
        self.assertEqual([row['quote'] for row in neighbors], [quote, quote])
        # Each role is an owned projection; the payload is selected from SQL
        # once, and Quoter deduplicates physical replay by resized topology.
        neighbors[0]['quote']['quotedOutput'] = 'changed-reader-copy'
        self.assertEqual(neighbors[1]['quote']['quotedOutput'], '8355')
        result = await CachedEconomicEstimates(self.subject, CORE).get_model({
            'side': 'buy', 'mode': 'exact-in', 'counterToken': USDT,
            'native': False, 'amount': '49000'})
        self.assertEqual(result['models'], [])
        self.assertEqual(result['estimate']['amount'], '8355')
        self.assertEqual(result['estimate']['referenceInput'], '47300')
        self.assertEqual(result['estimate']['sourceRequestedInput'], '50000')
        self.assertEqual(result['estimate']['context'], quote['context'])

    async def test_known_limited_lower_beats_a_different_nearest_upper_without_scaling_unknown_lowers(self):
        from cybergold_candidate.quoter.reuse_estimate import CachedEconomicEstimates
        limited = self.quote(70000, 8355, 'market', funding=47300)
        limited['searchCoverage'] = {'inputLimitObserved': True}
        nearer = self.quote(50000, 7950, 'market', funding=45000)
        unknown = self.quote(48000, 9999999, 'core')
        for quote in (limited, nearer, unknown):
            await self.save(quote)
        requested = {**self.request, 'inputs': [{'currency': USDT, 'amount': '49000'}]}
        neighbors = await self.subject.neighbors(requested)
        self.assertEqual([(row['family'], row['side'], row['quote']['quotedOutput']) for row in neighbors],
                         [('market', 'lower', '8355'), ('market', 'upper', '7950'), ('core', 'lower', '9999999')])
        result = await CachedEconomicEstimates(self.subject, CORE).get_model({
            'side': 'buy', 'mode': 'exact-in', 'counterToken': USDT,
            'native': False, 'amount': '49000'})
        self.assertEqual(result['estimate']['amount'], '8355')
        self.assertEqual(result['estimate']['referenceInput'], '47300')
        self.assertEqual(result['estimate']['sourceRequestedInput'], '70000')
        self.assertEqual(result['estimate']['context'], limited['context'])


if __name__ == '__main__':
    unittest.main()
