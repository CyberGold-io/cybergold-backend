"""Economic identity, original observations and optional storage failure."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import os
import json
from uuid import uuid4

from cybergold_candidate.quoter.store import EconomicQuoteStore, normalized_economic_request, request_identity
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
    async def test_unrelated_neighbor_headers_do_not_hash_deployment_identity(self):
        settings, registry, request, _ = fixture()
        service = EconomicQuoteStore(settings, registry)
        scope = service.capture_scope(request)
        candidates = [request, {**request, 'intent': 1}, {**request, 'outputCurrency': HELPERS},
                      {**request, 'inputs': [{'currency': HELPERS, 'amount': '100000'}]}]
        headers = [{'identity': service.capture_scope(candidate).identity, 'request': candidate,
                    'funded_input': '100000', 'quoted_output': str(10+index)}
                   for index, candidate in enumerate(candidates)]
        quote = {'request': deepcopy(request), 'inputs': deepcopy(request['inputs']), 'quotedOutput': '10'}
        executed = []
        async def prepare(): pass
        class Connection:
            async def execute(self, query, params):
                executed.append(params); return self
            async def fetchall(self):
                return headers if len(executed) == 1 else [{'identity': scope.identity, 'quote': quote}]
        @asynccontextmanager
        async def connection(): yield Connection()
        registry.store.prepare = prepare
        registry.store.database = SimpleNamespace(connection=connection)
        with patch('cybergold_candidate.quoter.store.request_identity', wraps=request_identity) as hashed:
            result = await service.neighbors(request, scope=scope)
        self.assertEqual(hashed.call_count, 2)  # Matching header plus its selected payload's L1 point identity.
        self.assertEqual(result, [{'family': 'market', 'side': 'lower', 'identity': scope.identity, 'quote': quote}])
        self.assertEqual(len(executed), 2)

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
        await self.subject.close()
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
        # A warm L1 answer is immediate; its independent SQL feed then merges
        # the other family's historical point without blocking ordinary work.
        self.assertEqual(await self.subject.lookup(self.request), market)
        await self.subject.load_lookup(self.request)
        self.assertEqual(await self.subject.lookup(self.request), old)
        await self.save(core)
        # A newer lower-priced Core observation replaces only that logical
        # Core point. Its older high price cannot hide the new Market winner.
        self.assertEqual(await self.subject.lookup(self.request), market)
        neighbors = await self.subject.neighbors(self.request)
        self.assertEqual([(row['family'], row['side']) for row in neighbors], [('market', 'lower'), ('core', 'lower')])
        self.assertEqual([row['quote'] for row in neighbors], [market, core])
        self.assertEqual([quote_path_family(row['quote']) for row in neighbors], ['market', 'core'])
        await asyncio.gather(*tuple(self.subject.background))
        async with self.connection() as conn:
            cursor = await conn.execute('SELECT identity FROM cybergold_uniswap_state WHERE namespace=%s', (scope.namespace,))
            self.assertEqual({row['identity'] for row in await cursor.fetchall()},
                             {scope.identity+':market', scope.identity+':core'})

    async def test_conflicting_sql_aliases_use_newest_sequence_whole_tuple_even_when_output_decreases(self):
        old = self.quote(100000, 100, 'market', funding=80000)
        new = self.quote(200000, 80, 'market', funding=80000)
        scope = self.subject.capture_scope(old['request'])
        async with self.connection() as conn:
            for sequence, quote in ((1, old), (2, new)):
                point = self.subject.capture_scope(quote['request'])
                await conn.execute('INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)',
                    (scope.chain, scope.core, scope.namespace, point.identity+':market',
                     json.dumps({'quote': quote, 'savedSequence': sequence})))
        self.assertEqual(await self.subject.load_lookup(old['request']), old)
        neighbors = await self.subject.load_neighbors(old['request'])
        self.assertEqual([row['quote'] for row in neighbors], [new, new])
        self.assertEqual(await self.subject.load_lookup(old['request']), new)
        self.assertEqual(sum(len(rows) for rows in self.subject.memory.values()), 1)
        self.assertEqual(len(next(iter(self.subject.locations.values()))), 1)

    async def test_paid_disproof_removes_persisted_candidate_and_releases_its_sql_identity_records(self):
        from cybergold_candidate.quoter.reuse_routes import funded_route_identity
        quote = self.quote(100000, 100, 'market')
        await self.save(quote)
        # Importing an actual SQL row records its alias for legacy cleanup.
        fresh = EconomicQuoteStore(self.subject.settings, self.registry, limit=1)
        self.addAsyncCleanup(fresh.close)
        await asyncio.create_task(fresh.load_lookup(self.request))
        scope = fresh.capture_scope(self.request)
        fresh.forget(funded_route_identity(quote), scope=scope)
        await asyncio.gather(*tuple(fresh.background))
        await asyncio.sleep(0)
        self.assertFalse(fresh.locations)
        self.assertFalse(fresh.retired)
        self.assertFalse(fresh.known_rows)
        self.assertIsNone(await fresh.load_lookup(self.request))

    async def test_a_writer_waiting_for_sql_counter_cannot_restore_a_later_paid_disproof(self):
        from cybergold_candidate.quoter.quote_book import QuoteBook
        from cybergold_candidate.quoter.reuse_routes import funded_route_identity
        quote = self.quote(100000, 100, 'market')
        scope = self.subject.capture_scope(self.request)
        identity = funded_route_identity(quote)
        book = QuoteBook(self.request)
        def paid(frame, version):
            book.versions[frame['_candidateIdentity']] = version
            book.observe(frame['value'], identity=frame['_candidateIdentity'])
        book.on_observation = paid
        self.subject.register_book(scope, book)
        self.addCleanup(self.subject.unregister_book, book)
        self.subject.announce(self.request, {'type': 'candidate-repriced',
            '_candidateIdentity': identity, 'value': quote}, book, scope=scope)
        version = book.versions[identity]
        waiting = asyncio.Event()
        @asynccontextmanager
        async def observed_connection():
            async with self.connection() as conn:
                async def execute(query, *args):
                    if query.lstrip().startswith('UPDATE cybergold_uniswap_state'):
                        waiting.set()
                    return await conn.execute(query, *args)
                yield SimpleNamespace(transaction=conn.transaction, execute=execute)
        self.registry.store.database.connection = observed_connection
        counter = (scope.chain, scope.core, scope.namespace+'-sequence', 'commits')
        async with self.connection() as conn:
            await conn.execute('INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)',
                               (*counter, json.dumps({'sequence': 0})))
        async with self.connection() as conn:
            async with conn.transaction():
                await conn.execute('SELECT payload FROM cybergold_uniswap_state WHERE chain_id=%s AND core_address=%s AND namespace=%s AND identity=%s FOR UPDATE', counter)
                writing = asyncio.create_task(self.subject.persist(self.request, quote, scope=scope, version=version))
                await asyncio.wait_for(waiting.wait(), 3)
                self.subject.announce(self.request, {'type': 'candidate-repriced',
                    '_candidateIdentity': identity, 'value': None}, book, scope=scope)
                self.assertIsNone(self.subject.memory_lookup(self.request))
        self.assertFalse(await asyncio.wait_for(writing, 3))
        await asyncio.gather(*tuple(self.subject.background))
        async with self.connection() as conn:
            cursor = await conn.execute('SELECT payload FROM cybergold_uniswap_state WHERE namespace=%s', (scope.namespace,))
            self.assertEqual(await cursor.fetchall(), [])

    async def test_evicted_paid_identity_suppresses_an_older_inflight_sql_snapshot_but_its_writer_still_persists(self):
        from cybergold_candidate.quoter.quote_book import QuoteBook
        from cybergold_candidate.quoter.reuse_routes import funded_route_identity
        old, paid_quote = self.quote(100000, 100, 'market'), self.quote(100000, 80, 'market')
        scope = self.subject.capture_scope(self.request)
        self.subject.limit = 1
        captured, read_release, write_waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        @asynccontextmanager
        async def observed_connection():
            async with self.connection() as conn:
                async def execute(query, *args):
                    if query.lstrip().startswith('UPDATE cybergold_uniswap_state'):
                        write_waiting.set()
                    cursor = await conn.execute(query, *args)
                    if query.lstrip().startswith('SELECT identity,payload') and not captured.is_set():
                        async def fetchall():
                            rows = await cursor.fetchall()
                            captured.set(); await read_release.wait()
                            return rows
                        return SimpleNamespace(fetchall=fetchall)
                    return cursor
                yield SimpleNamespace(transaction=conn.transaction, execute=execute)
        self.registry.store.database.connection = observed_connection
        counter = (scope.chain, scope.core, scope.namespace+'-sequence', 'commits')
        async with self.connection() as conn:
            await conn.execute('INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)',
                (scope.chain, scope.core, scope.namespace, scope.identity+':market', json.dumps({'quote': old, 'savedSequence': 1})))
            await conn.execute('INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)',
                               (*counter, json.dumps({'sequence': 1})))
        reading = asyncio.create_task(self.subject.load_lookup(self.request))
        await asyncio.wait_for(captured.wait(), 3)
        book = QuoteBook(self.request)
        def paid(frame, version):
            book.versions[frame['_candidateIdentity']] = version
            book.observe(frame['value'], identity=frame['_candidateIdentity'])
        book.on_observation = paid
        self.subject.register_book(scope, book)
        identity = funded_route_identity(paid_quote)
        self.subject.announce(self.request, {'type': 'candidate-repriced',
            '_candidateIdentity': identity, 'value': paid_quote}, book, scope=scope)
        async with self.connection() as conn:
            async with conn.transaction():
                await conn.execute('SELECT payload FROM cybergold_uniswap_state WHERE chain_id=%s AND core_address=%s AND namespace=%s AND identity=%s FOR UPDATE', counter)
                writing = asyncio.create_task(self.subject.persist(self.request, paid_quote, scope=scope,
                                                                  version=book.versions[identity]))
                await asyncio.wait_for(write_waiting.wait(), 3)
                different = self.quote(200000, 120, 'market')
                self.subject.remember(different['request'], different)
                self.subject.unregister_book(book)
                self.assertIsNone(self.subject.memory_lookup(self.request))
                self.assertEqual(len(self.subject.memory), 1)
                self.assertEqual(self.subject.retired[(self.subject.scope_key(scope), identity)]['version'], book.versions[identity])
                read_release.set()
                self.assertIsNone(await asyncio.wait_for(reading, 3))
                self.assertFalse(writing.done())
        self.assertTrue(await asyncio.wait_for(writing, 3))
        await asyncio.sleep(0)
        self.assertFalse(self.subject.retired)
        self.assertEqual(await asyncio.create_task(self.subject.load_lookup(self.request)), paid_quote)

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
        from cybergold_candidate.economic_estimate import CachedEconomicEstimates
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

    async def test_known_limited_lower_beats_a_different_nearest_upper_and_unknown_lower_stays_advisory(self):
        from cybergold_candidate.economic_estimate import CachedEconomicEstimates
        limited = self.quote(70000, 8355, 'market', funding=47300)
        limited['searchCoverage'] = {'inputLimitObserved': True}
        nearer = self.quote(50000, 7950, 'market', funding=45000)
        unknown = self.quote(48000, 100, 'core')
        for quote in (limited, nearer, unknown):
            await self.save(quote)
        requested = {**self.request, 'inputs': [{'currency': USDT, 'amount': '49000'}]}
        neighbors = await self.subject.neighbors(requested)
        self.assertEqual([(row['family'], row['side'], row['quote']['quotedOutput']) for row in neighbors],
                         [('market', 'lower', '8355'), ('market', 'upper', '7950'), ('core', 'lower', '100')])
        result = await CachedEconomicEstimates(self.subject, CORE).get_model({
            'side': 'buy', 'mode': 'exact-in', 'counterToken': USDT,
            'native': False, 'amount': '49000'})
        self.assertEqual(result['estimate']['amount'], '8355')
        self.assertEqual(result['estimate']['referenceInput'], '47300')
        self.assertEqual(result['estimate']['sourceRequestedInput'], '70000')
        self.assertEqual(result['estimate']['context'], limited['context'])


if __name__ == '__main__':
    unittest.main()
