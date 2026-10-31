"""Nearby quote lookup on disposable local PostgreSQL, never deployed state."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import subprocess
import time
import unittest
import uuid

import psycopg
from psycopg import sql

from cybergold_candidate.database import Database
from cybergold_candidate.fork_recovery import ANCHOR_KEYS, read_generation, set_state
from cybergold_candidate.protocol_config import ProtocolConfiguration
from cybergold_candidate.quoter.reuse_estimate import CachedEconomicEstimates
from cybergold_candidate.quoter.store import EconomicQuoteStore
from cybergold_candidate.uniswap_state import PoolRegistry, UniswapStore
from test_economic_quote_store import fixture, CORE, USDT, HELPERS
from test_nearby_economic_estimates import quote_sample


class RecordingDatabase(Database):
    def __init__(self, url):
        super().__init__(url)
        self.queries = []

    @asynccontextmanager
    async def connection(self):
        async with super().connection() as connection:
            owner = self
            class Recorded:
                def __getattr__(self, name):
                    return getattr(connection, name)
                async def execute(self, query, params=None):
                    owner.queries.append((str(query), deepcopy(params)))
                    return await connection.execute(query, params)
            yield Recorded()


class NativeNearbyQuotes(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = 'cybergold-nearby-' + uuid.uuid4().hex[:12]
        subprocess.run(['docker', 'run', '--pull', 'never', '--detach', '--name', cls.container,
            '--publish', '127.0.0.1::5432', '-e', 'POSTGRES_PASSWORD=public-nearby-fixture',
            'postgres:18-alpine'], check=True, stdout=subprocess.DEVNULL)
        cls.addClassCleanup(subprocess.run, ['docker', 'rm', '--force', '--volumes', cls.container],
                            check=True, stdout=subprocess.DEVNULL)
        port = subprocess.check_output(['docker', 'port', cls.container, '5432/tcp'], text=True).strip().rsplit(':', 1)[1]
        cls.url = 'postgresql://postgres:public-nearby-fixture@127.0.0.1:' + port + '/postgres'
        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(cls.url): break
            except psycopg.OperationalError:
                if time.monotonic() > deadline: raise
                time.sleep(.1)

    async def asyncSetUp(self):
        name = 'nearby_' + uuid.uuid4().hex[:12]
        with psycopg.connect(self.url, autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        self.dsn = self.url.rsplit('/', 1)[0] + '/' + name
        self.one, self.two = RecordingDatabase(self.dsn), RecordingDatabase(self.dsn)
        self.addAsyncCleanup(self.one.close)
        self.addAsyncCleanup(self.two.close)
        self.settings, self.registry, _, _ = fixture()
        first, second = UniswapStore(self.one, 31338, CORE), UniswapStore(self.two, 31338, CORE)
        first.scope = second.scope = 'generation:one:'
        self.registry.store = first
        self.store = EconomicQuoteStore(self.settings, self.registry)
        self.peer = EconomicQuoteStore(self.settings, self.registry, store=second)
        await first.prepare()

    def request(self, amount, **changes):
        return {'intent': 0, 'inputs': [{'currency': USDT, 'amount': str(amount)}],
                'outputCurrency': CORE, **changes}

    async def save(self, amount, *, store=None, output=None, **changes):
        request = self.request(amount, **changes)
        quote = quote_sample(request=request, quotedOutput=str(output if output is not None else amount))
        # Deliberately include a large route payload. Projected neighbor headers
        # must not retrieve this payload for every one of 4,096 stored rows.
        quote['plan']['padding'] = 'x' * 32768
        assert await (store or self.store).save(request, quote)
        return request, quote

    async def test_real_neighbors_exact_hits_families_and_projected_payload_bound(self):
        for amount in (100, 500, 900, 1000):
            await self.save(amount)
        await self.save(901, inputs=[{'currency': HELPERS, 'amount': '901'}])
        await self.save(902, intent=1)
        await self.save(903, outputCurrency=HELPERS)
        self.two.queries.clear()
        selected = await self.peer.neighbors(self.request(900))
        self.assertEqual(selected['lower']['quote']['request']['inputs'][0]['amount'], '500')
        self.assertEqual(selected['upper']['quote']['request']['inputs'][0]['amount'], '1000')
        reads = [(query, args) for query, args in self.two.queries if query.lstrip().startswith('SELECT')]
        self.assertEqual(len(reads), 2)
        self.assertIn("payload->'quote'->'request' AS request", reads[0][0])
        self.assertNotIn('SELECT payload ', reads[0][0])
        self.assertEqual(len(reads[1][1][-1]), 2)
        self.assertEqual((await self.peer.lookup(self.request(900)))['quotedOutput'], '900')
        selected['upper']['quote']['quotedOutput'] = 'mutated'
        self.assertEqual((await self.store.lookup(self.request(1000)))['quotedOutput'], '1000')

    async def test_best_fitting_lower_output_keeps_nearest_upper_and_bounded_reads(self):
        await self.save(10000, output=78948539895713944454)
        await self.save(95000, output=3643)
        await self.save(110000, output=5)
        await self.save(120000, output=999999999999999999999)
        await self.save(90000, output=9999999999999999999999, intent=1)
        self.two.queries.clear()
        selected = await self.peer.neighbors(self.request(100000))
        self.assertEqual(selected['lower']['quote']['quotedOutput'], '78948539895713944454')
        self.assertEqual(selected['lower']['quote']['request']['inputs'][0]['amount'], '10000')
        self.assertEqual(selected['upper']['quote']['request']['inputs'][0]['amount'], '110000')
        reads = [(query, args) for query, args in self.two.queries if query.lstrip().startswith('SELECT')]
        self.assertEqual(len(reads), 2)
        self.assertNotIn('SELECT payload ', reads[0][0])
        self.assertEqual(len(reads[1][1][-1]), 2)

    async def test_captured_configuration_and_generation_identity(self):
        await self.save(1000)
        old = self.peer.capture_scope(self.request(900))
        self.settings.CYBERGOLD_RUNTIME_CONFIG_ID = 'changed'
        await self.save(901, output=8888)
        self.assertEqual((await self.peer.neighbors(self.request(900), scope=old))['upper']['quote']['quotedOutput'], '1000')
        self.assertEqual((await self.peer.neighbors(self.request(900)))['upper']['quote']['quotedOutput'], '8888')
        self.registry.generation = 'two'
        self.registry.store.scope = 'generation:two:'
        self.assertEqual(await self.store.neighbors(self.request(900)), {'lower': None, 'upper': None})
        self.assertEqual((await self.peer.neighbors(self.request(900), scope=old))['upper']['quote']['quotedOutput'], '1000')

    async def test_cross_connection_last_successful_tuple_and_legacy_row(self):
        async with self.one.connection() as one, self.two.connection() as two:
            a = (await (await one.execute('SELECT pg_backend_pid() AS pid')).fetchone())['pid']
            b = (await (await two.execute('SELECT pg_backend_pid() AS pid')).fetchone())['pid']
            self.assertNotEqual(a, b)
        await asyncio.gather(*(self.save(1000, store=self.store if index % 2 else self.peer, output=index)
                               for index in range(8)))
        _, final = await self.save(1000, store=self.peer, output=888)
        self.assertNotIn('reuseSample', final)
        self.assertEqual((await self.store.neighbors(self.request(900)))['upper']['quote'], final)
        self.assertEqual(await self.store.lookup(self.request(1000)), final)

    async def test_restart_recovers_durable_generation_via_existing_db_only_path(self):
        await self.one.ensure_schema()
        async with self.one.connection() as connection:
            for key, value in zip(ANCHOR_KEYS, ('one', '100', '0x'+'ab'*32, 'ready'), strict=True):
                await set_state(connection, CORE.lower(), key, value)
        await self.save(1000, output=999)
        fresh_store = UniswapStore(self.two, 31338, CORE)
        registry = PoolRegistry(self.settings, store=fresh_store)
        configuration_store = UniswapStore(self.two, 31338, CORE)
        async def generation():
            async with self.two.connection() as connection:
                value = await read_generation(connection, CORE.lower())
            result = value['anchor']['generation'] if value else None
            await registry.observe_generation(result)
            return result
        configuration = ProtocolConfiguration(self.settings, configuration_store, generation_reader=generation)
        estimates = CachedEconomicEstimates(EconomicQuoteStore(self.settings, registry), CORE,
                                            observe_scope=configuration.load)
        self.assertEqual(fresh_store.scope, 'generation:unobserved:')
        result = await estimates.get_model({'side': 'buy', 'mode': 'exact-in', 'counterToken': USDT,
                                           'native': False, 'amount': '900'})
        self.assertEqual(result['estimate']['amount'], '999')
        self.assertEqual(fresh_store.scope, 'generation:one:')
        self.assertFalse(registry.loaded)
        self.assertIsNone(registry.rpc)
        await registry.pending.close()

    async def test_existing_4096_pruning_and_neighbor_boundary(self):
        scope = self.store.capture_scope(self.request(4096))
        rows = []
        for amount in range(1, 4097):
            request = self.request(amount)
            key = self.store.capture_scope(request)
            quote = quote_sample(request=request)
            rows.append((scope.chain, scope.core, scope.namespace, key.identity,
                         json.dumps({'quote': quote, 'savedSequence': amount})))
        async with self.one.connection() as connection:
            cursor = connection.cursor()
            await cursor.executemany('INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)', rows)
            await connection.execute('''INSERT INTO cybergold_uniswap_state VALUES (%s,%s,%s,%s,%s::jsonb)''',
                (scope.chain, scope.core, scope.namespace+'-sequence', 'commits', json.dumps({'sequence': 4096})))
        await self.save(4097)
        async with self.one.connection() as connection:
            count = (await (await connection.execute('''SELECT count(*) AS count FROM cybergold_uniswap_state
                WHERE namespace=%s''', (scope.namespace,))).fetchone())['count']
        self.assertEqual(count, 4096)
        self.assertIsNone(await self.peer.lookup(self.request(1)))
        neighbors = await self.peer.neighbors(self.request(4096))
        self.assertEqual(neighbors['lower']['quote']['request']['inputs'][0]['amount'], '4095')
        self.assertEqual(neighbors['upper']['quote']['request']['inputs'][0]['amount'], '4097')


if __name__ == '__main__':
    unittest.main()
