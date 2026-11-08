"""Engine-owned children retain independent producer scopes and cancellation."""
import asyncio
from contextvars import ContextVar
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from cybergold_candidate.quoter.alpha_routes import AlphaRoutes, AlphaRouteError, drain_retired_callbacks
from cybergold_candidate.quoter.cooperative import QUANTUM
from cybergold_candidate.quoter.providers import route_providers
from cybergold_candidate.quoter.uniroute_routes import UnirouteLocal
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.recovery_rpc import SnapshotChanged
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

    async def test_retired_callback_close_yields_without_writes_or_blocking_sibling(self):
        driver = AlphaRoutes(Engine())
        process = SimpleNamespace()
        driver.process = process
        driver._start = AsyncMock(return_value=process)
        count = QUANTUM * 2 + 3
        entered, cancelled = set(), set()
        started, all_cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        callbacks, writes = [], []
        process.stdin = SimpleNamespace(write=lambda raw: writes.append(json.loads(raw)))

        async def quote(response, *_args, **_options):
            entered.add(response['quoteId'])
            if len(entered) == count:
                started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.add(response['quoteId'])
                if len(cancelled) == count:
                    all_cancelled.set()
                # A callback completing during close still cannot publish a
                # response for the now-retired identity.
                await release.wait()
                return {'quote': '42'}

        async def write(_process, value):
            writes.append(value)
            if value.get('operation') == 'cancel':
                return
            entry = driver.requests[value['id']]
            if value['amount'] == '1':
                for index in range(count):
                    task = asyncio.create_task(driver._answer(
                        {'id': value['id'], 'quoteId': index}, entry))
                    entry['callbacks'].add(task)
                    task.add_done_callback(entry['callbacks'].discard)
                    callbacks.append(task)
                await started.wait()
                entry['queue'].put_nowait({'operation': 'candidates', 'candidates': []})
            else:
                entry['queue'].put_nowait({'operation': 'candidates', 'candidates': [{'sibling': True}]})

        driver._quote, driver._write = quote, write
        left = driver.discover_batches(A, C, 1, BLOCK)
        right = driver.discover_batches(A, C, 2, BLOCK)
        closing = None
        try:
            self.assertEqual(await anext(left), [])
            left_entry = driver.requests['1']
            closing = asyncio.create_task(left.aclose())
            async with asyncio.timeout(1):
                while not any(task.cancelling() for task in callbacks):
                    await asyncio.sleep(0)
            self.assertLess(sum(bool(task.cancelling()) for task in callbacks), count)
            self.assertNotIn('1', driver.requests)
            self.assertIn('1', driver.retired)
            self.assertFalse(left_entry['terminal'])
            self.assertFalse(closing.done())
            # This is another real calculation on the same driver, while the
            # old query's callback finalizers remain held.
            self.assertEqual(await anext(right), [{'sibling': True}])
            await asyncio.wait_for(all_cancelled.wait(), 1)
            self.assertFalse(closing.done())
            release.set()
            await closing
            self.assertTrue(all(task.done() for task in callbacks))
            self.assertFalse(left_entry['callbacks'])
            self.assertFalse(any(row.get('operation') == 'quoteResult' for row in writes))
            self.assertIn('2', driver.requests)
            self.assertIn({'id': '1', 'operation': 'cancel'}, writes)
            right_entry = driver.requests['2']
            right_entry['terminal'] = True
            right_entry['queue'].put_nowait({'candidates': []})
            self.assertEqual(await anext(right), [])
            with self.assertRaises(StopAsyncIteration):
                await anext(right)
            self.assertFalse(driver.requests)
        finally:
            release.set()
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)
            await left.aclose()
            if '2' in driver.requests:
                driver.requests['2']['terminal'] = True
            await right.aclose()

    async def test_repeated_caller_cancel_keeps_every_retired_callback_owned(self):
        count = QUANTUM * 2 + 3
        entered, cancelled = set(), set()
        all_entered, all_cancelled = asyncio.Event(), asyncio.Event()
        release = asyncio.Event()

        async def callback(index):
            entered.add(index)
            if len(entered) == count:
                all_entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.add(index)
                if len(cancelled) == count:
                    all_cancelled.set()
                await release.wait()

        callbacks = tuple(asyncio.create_task(callback(index)) for index in range(count))
        closing = None
        try:
            await all_entered.wait()
            closing = asyncio.create_task(drain_retired_callbacks(callbacks))
            async with asyncio.timeout(1):
                while not any(task.cancelling() for task in callbacks):
                    await asyncio.sleep(0)
            self.assertLess(sum(bool(task.cancelling()) for task in callbacks), count)
            closing.cancel('first caller cancellation')
            await asyncio.sleep(0)
            closing.cancel('second caller cancellation')
            # The first chunk cannot finish until release. Reaching every
            # callback proves later chunks are cancelled before any gather wait.
            await asyncio.wait_for(all_cancelled.wait(), 1)
            self.assertFalse(closing.done())
            self.assertTrue(all(not task.done() for task in callbacks))
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await closing
            self.assertTrue(all(task.cancelled() for task in callbacks))
        finally:
            release.set()
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)
            for task in callbacks:
                task.cancel()
            await asyncio.gather(*callbacks, return_exceptions=True)

    async def test_done_callback_chunks_cooperate_and_preserve_outcome_order(self):
        loop = asyncio.get_running_loop()
        reads, observed = [], []
        count = QUANTUM * 2 + 3

        class Completed(asyncio.Future):
            def result(self):
                reads.append(self)
                if len(reads) == 1:
                    loop.call_soon(lambda: observed.append(len(reads)))
                return super().result()

        callbacks = tuple(Completed() for _ in range(count))
        ordinary = RuntimeError('ordinary callback error')
        disproof = SnapshotChanged('callback context changed')
        expected = list(range(count))
        for index, future in enumerate(callbacks):
            if index == 1:
                future.set_exception(ordinary)
                expected[index] = ordinary
            elif index == 2:
                future.set_exception(disproof)
                expected[index] = disproof
            elif index == 3:
                future.cancel()
            else:
                future.set_result(index)
        outcomes = await drain_retired_callbacks(callbacks)
        self.assertTrue(observed)
        self.assertGreater(observed[0], 0)
        self.assertLess(observed[0], len(reads))
        self.assertEqual(outcomes[:3], expected[:3])
        self.assertIsInstance(outcomes[3], asyncio.CancelledError)
        self.assertEqual(outcomes[4:], expected[4:])
        self.assertTrue(all(future.done() for future in callbacks))
        self.assertEqual(await drain_retired_callbacks(()), [])


class _CalculationPipe:
    """Controlled complete JSONL writes and a real AlphaRoutes reader."""
    def __init__(self):
        self.stdin = self
        self.stdout = asyncio.StreamReader()
        self.returncode = None
        self.frames, self.raw_frames, self.drains = [], [], []
        self.last_write = None
        self.block_result_for = None
        self.drain_entered, self.release_drain = asyncio.Event(), asyncio.Event()
        self.exited = asyncio.Event()
        self.killed = self.waited = False
        self.enqueue_error = None

    def emit(self, frame):
        self.stdout.feed_data((json.dumps(frame) + '\n').encode())

    def write(self, raw):
        frame = json.loads(raw)
        if self.enqueue_error is not None and frame == {'id': '1', 'operation': 'cancel'}:
            raise self.enqueue_error
        self.raw_frames.append(raw)
        self.frames.append(frame)
        self.last_write = frame
        if 'pools' in frame:
            self.emit({'id': frame['id'], 'operation': 'candidates',
                       'candidates': [{'query': frame['amount']}]})

    async def drain(self):
        frame = self.last_write
        self.drains.append(frame)
        if frame.get('operation') == 'quoteResult' and frame['id'] == self.block_result_for:
            self.drain_entered.set()
            await self.release_drain.wait()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.exited.set()
        self.stdout.feed_eof()

    async def wait(self):
        self.waited = True
        await self.exited.wait()
        return self.returncode


class FinalCancelEnqueueTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        process = _CalculationPipe()
        driver = AlphaRoutes(Engine())
        # Process construction is not under test. Use the actual reader,
        # CalculationSessions, callback pricing and retirement around fake IO.
        driver.process = driver.reader_process = process
        driver.reader = asyncio.create_task(driver._read(process))
        fixture = SimpleNamespace(driver=driver, process=process, sessions=[], tasks=[],
                                  releases=[process.release_drain], batches={})
        self.addAsyncCleanup(self.finish_fixture, fixture)
        return fixture

    async def finish_fixture(self, fixture):
        for release in fixture.releases:
            release.set()
        for task in fixture.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*fixture.tasks, return_exceptions=True)
        await asyncio.gather(*(session.close() for session in fixture.sessions), return_exceptions=True)
        await fixture.driver.close()
        self.assertFalse(fixture.driver.requests)
        self.assertEqual(fixture.driver.engine.semaphore._value, 8)

    def start_owner(self, fixture, amount):
        session = fixture.driver.session()
        fixture.sessions.append(session)
        fixture.batches[amount] = []
        async def consume():
            async with search_observation_scope():
                async for batch in session.discover_batches(A, C, amount, BLOCK):
                    fixture.batches[amount].append(batch)
            return fixture.batches[amount]
        task = asyncio.create_task(consume())
        fixture.tasks.append(task)
        return session, task

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    def emit_quote(self, fixture, identity, quote_id, amount):
        fixture.process.emit({'id': identity, 'operation': 'quote', 'quoteId': quote_id,
            'mode': 'exactIn', 'amount': str(amount),
            'branches': [{'amountIn': str(amount), 'hops': [{'pool': pool(), 'zeroForOne': True}]}]})

    async def test_final_cancel_owns_callbacks_but_does_not_wait_for_sibling_write(self):
        fixture = self.fixture()
        driver, process = fixture.driver, fixture.process
        process.block_result_for = '2'
        entered, finalizing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        fixture.releases.append(release)
        original = driver.engine.quote_sdk_branches
        async def quote(branches, mode, amount, block, **options):
            if amount == 12:
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    finalizing.set()
                    await release.wait()
            return await original(branches, mode, amount, block, **options)
        driver.engine.quote_sdk_branches = quote
        left, left_owner = self.start_owner(fixture, 1)
        await self.until(lambda: bool(fixture.batches[1]))
        right, right_owner = self.start_owner(fixture, 2)
        await self.until(lambda: bool(fixture.batches[2]))
        self.emit_quote(fixture, '1', 'A-result', 11)
        await self.until(lambda: any(row.get('quoteId') == 'A-result' for row in process.frames))
        self.emit_quote(fixture, '1', 'A-finalizer', 12)
        await asyncio.wait_for(entered.wait(), 1)
        self.emit_quote(fixture, '2', 'B-result', 22)
        await asyncio.wait_for(process.drain_entered.wait(), 1)
        left_entry = driver.requests['1']
        closing = asyncio.create_task(left.close())
        fixture.tasks.append(closing)
        await asyncio.wait_for(finalizing.wait(), 1)
        self.assertNotIn('1', driver.requests)
        self.assertIn('1', driver.retired)
        self.assertTrue(left_entry['callbacks'])
        self.assertFalse(closing.done())
        self.assertNotIn({'id': '1', 'operation': 'cancel'}, process.frames)
        release.set()
        # B still owns the active-write lock and has not finished its drain.
        # The old final-cancel path hangs here despite A's completed callbacks.
        await asyncio.wait_for(asyncio.shield(closing), 1)
        self.assertTrue(left_owner.cancelled())
        self.assertFalse(left_entry['callbacks'])
        self.assertTrue(driver.lock.locked())
        self.assertFalse(process.release_drain.is_set())
        self.assertFalse(right_owner.done())
        cancel = {'id': '1', 'operation': 'cancel'}
        self.assertIn(cancel, process.frames)
        self.assertNotIn(cancel, process.drains)
        a_result = next(row for row in process.frames if row.get('quoteId') == 'A-result')
        b_result = next(row for row in process.frames if row.get('quoteId') == 'B-result')
        self.assertEqual(a_result['result'], {'quote': '22'})
        self.assertEqual(b_result['result'], {'quote': '44'})
        self.assertLess(process.frames.index(a_result), process.frames.index(cancel))
        self.assertLess(process.frames.index(b_result), process.frames.index(cancel))
        self.assertFalse(any(row.get('quoteId') == 'A-finalizer' for row in process.frames))
        for raw in process.raw_frames:
            self.assertTrue(raw.endswith(b'\n'))
            self.assertEqual(raw.count(b'\n'), 1)
            self.assertIsInstance(json.loads(raw), dict)
        # Reader ordering gives a barrier after the late A frame, then after ACK.
        callbacks_before = driver.quote_callbacks
        self.emit_quote(fixture, '1', 'late-A', 99)
        process.emit({'id': '2', 'operation': 'candidates', 'candidates': [{'progress': 1}]})
        await self.until(lambda: len(fixture.batches[2]) == 2)
        self.assertEqual(driver.quote_callbacks, callbacks_before)
        self.assertIn('1', driver.retired)
        process.emit({'id': '1', 'operation': 'cancelled'})
        process.emit({'id': '2', 'operation': 'candidates', 'candidates': [{'progress': 2}]})
        await self.until(lambda: len(fixture.batches[2]) == 3)
        self.assertNotIn('1', driver.retired)
        self.assertIn('2', driver.requests)
        self.assertIs(driver.process, process)
        self.assertFalse(process.killed)
        process.release_drain.set()
        await self.until(lambda: not driver.requests['2']['callbacks'])
        process.emit({'id': '2', 'candidates': [{'final': 'B'}]})
        self.assertEqual(await asyncio.wait_for(right_owner, 1), [
            [{'query': '2'}], [{'progress': 1}], [{'progress': 2}], [{'final': 'B'}]])
        await right.close()
        self.assertEqual(driver.engine.semaphore._value, 8)
        self.assertFalse(driver.requests)

    async def test_synchronous_cancel_write_failure_fans_out_without_replacing_cancellation(self):
        fixture = self.fixture()
        driver, process = fixture.driver, fixture.process
        left, left_owner = self.start_owner(fixture, 1)
        await self.until(lambda: bool(fixture.batches[1]))
        _, right_owner = self.start_owner(fixture, 2)
        await self.until(lambda: bool(fixture.batches[2]))
        failure = BrokenPipeError('controlled cancel enqueue failure')
        process.enqueue_error = failure
        await asyncio.wait_for(left.close(), 1)
        self.assertTrue(left_owner.cancelled())
        with self.assertRaises(BrokenPipeError) as raised:
            await asyncio.wait_for(right_owner, 1)
        self.assertIs(raised.exception, failure)
        self.assertTrue(process.killed and process.waited)
        self.assertIsNone(driver.process)
        self.assertFalse(driver.requests)

    async def test_reader_owns_connection_loss_after_cancel_enqueue_returns(self):
        fixture = self.fixture()
        driver, process = fixture.driver, fixture.process
        left, left_owner = self.start_owner(fixture, 1)
        await self.until(lambda: bool(fixture.batches[1]))
        _, right_owner = self.start_owner(fixture, 2)
        await self.until(lambda: bool(fixture.batches[2]))
        await asyncio.wait_for(left.close(), 1)
        self.assertTrue(left_owner.cancelled())
        self.assertFalse(right_owner.done())
        self.assertIn({'id': '1', 'operation': 'cancel'}, process.frames)
        self.assertIn('1', driver.retired)
        self.assertFalse(process.killed)
        # Successful enqueue was no delivery/liveness proof. A later EOF is
        # observed through the unchanged engine-owned reader/error fanout.
        process.stdout.feed_eof()
        with self.assertRaisesRegex(AlphaRouteError, 'Calculation worker exited'):
            await asyncio.wait_for(right_owner, 1)
        self.assertTrue(left_owner.cancelled())
        self.assertTrue(process.killed and process.waited)
        self.assertIsNone(driver.process)
        self.assertFalse(driver.requests)

if __name__ == '__main__':
    unittest.main()
