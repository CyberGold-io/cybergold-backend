"""Engine-owned children retain independent producer scopes and cancellation."""
import asyncio
from contextvars import ContextVar
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.quoter.alpha_routes import AlphaRoutes, AlphaRouteError
from cybergold_candidate.quoter.cooperative import QUANTUM
from cybergold_candidate.quoter.providers import route_providers
from cybergold_candidate.quoter.uniroute_routes import UnirouteLocal
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.search_observations import current_search_observations, search_observation_scope
from cybergold_candidate.shared_reads import SharedReads
from test_alpha_routes import A, B, C, BLOCK, Engine, pool
from test_universal_quote import settings


OWNER = ContextVar('optimizer_test_owner', default=None)


class OptimizerSessionTests(unittest.IsolatedAsyncioTestCase):
    def engine(self):
        oracle = Engine([pool(), pool(A, B, 500), pool(B, C)])
        oracle.registry.pending = SharedReads()
        engine = RouteQuoteEngine(settings(), oracle.registry, sdk=SimpleNamespace(close=AsyncMock()))
        engine.quote_sdk_branches = oracle.quote_sdk_branches
        self.addAsyncCleanup(engine.close)
        self.addAsyncCleanup(oracle.registry.pending.close)
        return engine, oracle

    async def test_factory_is_lazy_and_sessions_keep_scopes_and_diagnostics(self):
        engine, oracle = self.engine()
        first, second = route_providers(settings(), engine), route_providers(settings(), engine)
        self.addAsyncCleanup(self.close_tools, first + second)
        for cls in (AlphaRoutes, UnirouteLocal):
            with self.subTest(provider=cls.name):
                left = next(tool.provider for tool in first if tool.name == cls.name)
                right = next(tool.provider for tool in second if tool.name == cls.name)
                self.assertIsNot(left, right)
                self.assertIs(left.driver, right.driver)
                self.assertIsNone(left.driver.process)
                original = oracle.quote_sdk_branches
                scopes, seen = {}, []
                async def quote(*args, **options):
                    owner = OWNER.get()
                    self.assertIs(current_search_observations(), scopes[owner])
                    seen.append(owner)
                    return await original(*args, **options)
                engine.quote_sdk_branches = quote
                candidates = []
                child = None
                for name, session in (('first', left), ('second', right)):
                    token = OWNER.set(name)
                    try:
                        async with search_observation_scope() as scope:
                            scopes[name] = scope
                            candidates.append(await session.discover(A, C, 10007, BLOCK))
                    finally:
                        OWNER.reset(token)
                    current = left.driver.process
                    self.assertIsNone(current.returncode)
                    if child is not None:
                        self.assertIs(current, child)
                    child = current
                    await session.close()
                    self.assertIsNone(child.returncode)
                self.assertEqual(candidates[0], candidates[1])
                self.assertEqual(set(seen), {'first', 'second'})
                self.assertEqual(left.diagnostics['workerQueries'], 1)
                self.assertEqual(right.diagnostics['workerQueries'], 1)
                self.assertGreater(left.diagnostics['quoteCallbacks'], 0)
                self.assertEqual(left.diagnostics['quoteCallbacks'], right.diagnostics['quoteCallbacks'])
                # A reused process receives the current catalog on every query.
                added = pool(A, C, 10000, protocol='v2' if cls is UnirouteLocal else 'v3')
                engine.registry.inventory[added['id']] = added
                sent = []
                original_write = left.driver._write
                async def write(process, value):
                    if 'pools' in value:
                        sent.append(value['pools'])
                    return await original_write(process, value)
                left.driver._write = write
                third = left.driver.session()
                token = OWNER.set('third')
                try:
                    async with search_observation_scope() as scope:
                        scopes['third'] = scope
                        self.assertTrue(await third.discover(A, C, 10007, BLOCK))
                finally:
                    OWNER.reset(token)
                    left.driver._write = original_write
                    await third.close()
                self.assertIn(added['id'], [row['id'] for row in sent[-1]])
                self.assertIs(left.driver.process, child)
                self.assertEqual(left.diagnostics['workerQueries'], 1)
                async with asyncio.timeout(1):
                    while left.driver.retired:
                        await asyncio.sleep(0)
                self.assertFalse(left.driver.retired)
        children = [driver.process for driver in engine._route_optimizers.values()]
        await engine.close()
        self.assertTrue(all(child.returncode is not None for child in children))
        self.assertEqual(engine.semaphore._value, 8)

    async def close_tools(self, tools):
        await asyncio.gather(*(tool.close() for tool in tools))

    async def test_cancel_one_active_owner_preserves_other_then_failure_restarts(self):
        for cls in (AlphaRoutes, UnirouteLocal):
            with self.subTest(provider=cls.name):
                engine, oracle = self.engine()
                driver = engine.route_optimizer(cls)
                left, right = driver.session(), driver.session()
                entered, release = asyncio.Event(), asyncio.Event()
                original = oracle.quote_sdk_branches
                async def quote(*args, **options):
                    if OWNER.get() == 'held':
                        entered.set()
                        await release.wait()
                    return await original(*args, **options)
                engine.quote_sdk_branches = quote
                async def discover(session, name):
                    token = OWNER.set(name)
                    try:
                        async with search_observation_scope():
                            return await session.discover(A, C, 10007, BLOCK)
                    finally:
                        OWNER.reset(token)
                first = asyncio.create_task(discover(left, 'held'))
                await asyncio.wait_for(entered.wait(), 5)
                child = driver.process
                survivor = asyncio.create_task(discover(right, 'survivor'))
                while len(driver.requests) != 2:
                    await asyncio.sleep(0)
                await left.close()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                self.assertTrue(await asyncio.wait_for(survivor, 5))
                self.assertIs(driver.process, child)
                self.assertIsNone(child.returncode)
                await right.close()
                self.assertIs(driver.process, child)
                entered.clear()
                broken = asyncio.create_task(discover(left, 'held'))
                await asyncio.wait_for(entered.wait(), 2)
                child.kill()
                with self.assertRaises(AlphaRouteError):
                    await asyncio.wait_for(broken, 2)
                await child.wait()
                self.assertTrue(await asyncio.wait_for(discover(right, 'restart'), 5))
                self.assertIsNot(driver.process, child)
                self.assertFalse(driver.requests)
                self.assertEqual(engine.semaphore._value, 8)
                await engine.close()

    async def test_buffered_frames_yield_without_changing_order(self):
        driver = AlphaRoutes(Engine())
        count = QUANTUM * 4 + 3
        waiting = asyncio.Event()
        class Buffered:
            def __init__(self): self.index = 0
            async def readline(self):
                if self.index == count:
                    await waiting.wait()
                index = self.index
                self.index += 1
                return (json.dumps({'id': '1', 'operation': 'candidates', 'candidates': [index]})+'\n').encode()
        process = SimpleNamespace(stdout=Buffered())
        queue = asyncio.Queue()
        driver.requests['1'] = {'process': process, 'queue': queue}
        reader = asyncio.create_task(driver._read(process))
        try:
            await asyncio.sleep(0)
            # The already-buffered stream cannot consume every frame in one turn.
            self.assertGreater(queue.qsize(), 0)
            self.assertLess(queue.qsize(), count)
            while queue.qsize() != count:
                await asyncio.sleep(0)
            self.assertEqual([queue.get_nowait()['candidates'][0] for _ in range(count)], list(range(count)))
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)

    async def test_cleanup_ack_is_not_a_terminal_or_next_query_gate(self):
        engine, _ = self.engine()
        driver = engine.route_optimizer(AlphaRoutes)
        # Deliberately never acknowledge cleanup: a slow child must not hold
        # normal terminal delivery, the next owner, or service shutdown.
        driver.command = [sys.executable, '-u', '-c', '''import json, sys
for line in sys.stdin:
    value = json.loads(line)
    if value.get('operation') != 'cancel':
        print(json.dumps({'id': value['id'], 'candidates': []}), flush=True)
''']
        first, second = driver.session(), driver.session()
        self.assertEqual(await asyncio.wait_for(first.discover(A, C, 10007, BLOCK), 1), [])
        child = driver.process
        self.assertIn('1', driver.retired)
        await first.close()
        self.assertEqual(await asyncio.wait_for(second.discover(A, C, 10007, BLOCK), 1), [])
        self.assertIs(driver.process, child)
        self.assertIn('1', driver.retired)
        await asyncio.wait_for(engine.close(), 1)
        self.assertIsNotNone(child.returncode)
        self.assertFalse(driver.retired or driver.requests)


if __name__ == '__main__':
    unittest.main()
