"""Lossless concurrent registration, checked against a serial content model."""
import asyncio
from contextlib import aclosing, asynccontextmanager
from copy import deepcopy
import gc
import importlib.util
import random
import unittest
import weakref

from cybergold_candidate.quoter.bootstrap import RouteBootstrap
from cybergold_candidate.quoter.prepared_nomination import prepare_rows
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteTool

A, B = '0x'+'1'*40, '0x'+'2'*40
BLOCK = {'number': 1, 'hash': '0x'+'ab'*32}


class Empty(RouteTool):
    name = 'control'
    def discover(self, query):
        return CandidateFeed()


def rows(count=130, offset=0):
    pools = [{'id': A, 'address': A, 'protocol': 'v3', 'feePips': 500+i,
              'tickSpacing': 10, 'token0': {'address': A, 'chainId': 31338, 'decimals': 18},
              'token1': {'address': B, 'chainId': 31338, 'decimals': 6}}
             for i in range(7)]
    return [[{'amountIn': str(i+offset+1), 'hops': [{'pool': pools[i % 7], 'zeroForOne': bool(i % 2)}]}]
            for i in range(count)]


class Prepared:
    def __init__(self, pause=None, finish=None):
        self.pause, self.finish = pause, finish
        self.closed = 0
    def prepare(self, source):
        captured = deepcopy(source)
        prepared = list(prepare_rows(captured))
        async def chunks():
            try:
                for i in range(0, len(prepared), 64):
                    yield prepared[i:i+64]
                    if self.pause is not None:
                        await self.pause()
                    else:
                        await asyncio.sleep(0)
                if self.finish:
                    self.finish()
            finally:
                self.closed += 1
        return chunks()


def setup(kind=RouteBootstrap, cpu=None, amount=100):
    session = kind([Empty()], cpu=cpu or Prepared())
    session.offer_feeds(A, B, amount, BLOCK)
    original = session._queries[A, B, amount][0]
    return session, original


def snapshot(session, entries, attempts):
    return {'known': deepcopy(session._known_offers), 'origins': deepcopy(session._offer_origins),
            'originRevisions': deepcopy(session._origin_revisions),
            'revision': session.revision, 'queryRevisions': deepcopy(session._query_revisions),
            'offers': [deepcopy(e['offers']) for e in entries],
            'attemptCounts': [(a['batches'], a['candidates']) for a in attempts]}


class SerialOracle(RouteBootstrap):
    """Independent serial model: complete batches update registries once."""
    async def _prepare_and_publish(self, response, entry, attempt):
        key = entry['query'].source, entry['query'].target, entry['query'].amount
        known = self._known_offers.setdefault(key, set()) if response else set()
        origins = self._offer_origins.setdefault(key[:2], {}) if response else {}
        fresh = changed = False
        offers = []
        for row, identities in prepare_rows(deepcopy(response)):
            offers.append({'branches': row, 'origins': [attempt['provider']]})
            if identities is None:
                fresh = True
                continue
            identity, origin = identities
            fresh |= identity not in known
            changed |= identity not in known or attempt['provider'] not in origins.get(origin, ())
            known.add(identity)
            origins.setdefault(origin, set()).add(attempt['provider'])
        attempt['batches'] += 1
        attempt['candidates'] += len(offers)
        if offers:
            self._origin_revisions[key[:2]] = self._origin_revisions.get(key[:2], 0) + bool(changed)
            self._publication_sequence += 1
            entry['offers'].extend(offers)
            entry['offer_revisions'].extend([self._publication_sequence] * len(offers))
            self._ready_offer_snapshots.pop(key, None)
            if fresh:
                self._query_changed(key)


class MergeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_publisher_does_not_lose_successful_sibling(self):
        entered, release = asyncio.Event(), asyncio.Event()
        class SelectivePrepared(Prepared):
            def prepare(self, source):
                stream = super().prepare(source)
                if source[0][0]['amountIn'] != '901':
                    return stream
                async def held():
                    async with aclosing(stream):
                        async for chunk in stream:
                            yield chunk
                            entered.set()
                            await release.wait()
                return held()
        session, original = setup(cpu=SelectivePrepared())
        self.addAsyncCleanup(session.close)
        cancelled_entry = dict(original, offers=[], offer_revisions=[])
        sibling_entry = dict(original, offers=[], offer_revisions=[])
        cancelled_attempt = dict(original['attempt'], provider='cancelled-provider')
        sibling_attempt = dict(original['attempt'], provider='surviving-provider')
        cancelled_source = rows(130)
        cancelled_source[0][0]['amountIn'] = '901'
        task = asyncio.create_task(session._prepare_and_publish(cancelled_source, cancelled_entry, cancelled_attempt))
        ready = asyncio.create_task(entered.wait())
        completed, _ = await asyncio.wait((task, ready), return_when=asyncio.FIRST_COMPLETED)
        if task in completed:
            await task
        self.assertTrue(entered.is_set())
        await ready
        await session._prepare_and_publish(rows(130), sibling_entry, sibling_attempt)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(sibling_entry['offers']), 130)
        self.assertEqual(cancelled_entry['offers'], [])
        self.assertTrue(all(names == {'surviving-provider'} for names in session._offer_origins[A, B].values()))
        self.assertEqual(cancelled_attempt['batches'], 0)

    async def test_readers_observe_complete_batch_and_matching_identity_state(self):
        session, entry = setup()
        self.addAsyncCleanup(session.close)
        source = rows(1024)
        task = asyncio.create_task(session._prepare_and_publish(source, entry, entry['attempt']))
        checks = 0
        while not task.done():
            checks += 1
            if entry['offers']:
                self.assertEqual(len(entry['offers']), len(source))
                self.assertEqual(len(session._known_offers[A, B, 100]), len(source))
                self.assertEqual(len(set(entry['offer_revisions'])), 1)
            else:
                self.assertFalse(session._known_offers or session._offer_origins)
            await asyncio.sleep(0)
        await task
        self.assertGreater(checks, 1)
        self.assertEqual(len(entry['offers']), len(source))

    async def exercise(self, kind, seed, amounts=(100,)*8):
        session, original = setup(kind)
        self.addAsyncCleanup(session.close)
        rng = random.Random(seed)
        entries, attempts, sources = [], [], []
        for index, amount in enumerate(amounts):
            if (A, B, amount) not in session._queries:
                session.offer_feeds(A, B, amount, BLOCK)
            base = session._queries[A, B, amount][0]
            entry = dict(base, offers=[], offer_revisions=[])
            attempt = dict(base['attempt'], provider='p'+str(index % 3))
            source = rows(rng.randint(65, 200), rng.randrange(0, 60))
            if index % 3 == 0:
                source += deepcopy(source[:9])  # Keep duplicate nomination rows.
            entries.append(entry); attempts.append(attempt); sources.append(source)
        sibling = {'branches': rows(1, 11)[0], 'origins': ['immediate-sibling']}
        async def immediate():
            await asyncio.sleep(0)
            session._remember_offer((A, B, amounts[0]), sibling)
        await asyncio.gather(immediate(), *(session._prepare_and_publish(s, e, a)
                             for s, e, a in zip(sources, entries, attempts)))
        for source, entry in zip(sources, entries):
            self.assertEqual([o['branches'] for o in entry['offers']], source)
            self.assertEqual(len(set(entry['offer_revisions'])), 1)
        observed = snapshot(session, entries, attempts)
        # Concurrent publishers may legitimately commit in different orders.
        # Replay each observed order through the unchanged serial method: even
        # invalidation counters must agree with that independent oracle.
        oracle, _ = setup(SerialOracle)
        self.addAsyncCleanup(oracle.close)
        oracle._remember_offer((A, B, amounts[0]), sibling)
        oracle_entries, oracle_attempts = [], []
        for index, amount in enumerate(amounts):
            if (A, B, amount) not in oracle._queries:
                oracle.offer_feeds(A, B, amount, BLOCK)
            base = oracle._queries[A, B, amount][0]
            oracle_entries.append(dict(base, offers=[], offer_revisions=[]))
            oracle_attempts.append(dict(base['attempt'], provider=attempts[index]['provider']))
        order = sorted(range(len(entries)), key=lambda i: entries[i]['offer_revisions'][0])
        for i in order:
            await oracle._prepare_and_publish(sources[i], oracle_entries[i], oracle_attempts[i])
        expected = snapshot(oracle, oracle_entries, oracle_attempts)
        for field in observed:
            self.assertEqual(observed[field], expected[field], 'serial-order oracle: '+field)
        return {key: observed[key] for key in ('known', 'origins', 'offers', 'attemptCounts')}

    async def test_randomized_same_query_matches_existing_semantics(self):
        for seed in range(12):
            before = await self.exercise(SerialOracle, seed)
            after = await self.exercise(RouteBootstrap, seed)
            for field in before:
                self.assertEqual(before[field], after[field], field)

    async def test_different_amount_queries_keep_shared_pair_origins(self):
        for seed in range(6):
            amounts = (100, 200, 300, 100, 200, 400, 300, 500)
            before = await self.exercise(SerialOracle, seed, amounts)
            after = await self.exercise(RouteBootstrap, seed, amounts)
            for field in before:
                self.assertEqual(before[field], after[field], field)

    async def test_cancellation_discards_all_private_work_and_closes_stream(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def pause():
            entered.set()
            await release.wait()
        cpu = Prepared(pause)
        session, entry = setup(cpu=cpu)
        self.addAsyncCleanup(session.close)
        task = asyncio.create_task(session._prepare_and_publish(rows(), entry, entry['attempt']))
        await entered.wait()
        self.assertFalse(entry['offers'] or session._known_offers or session._offer_origins)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(cpu.closed, 1)
        self.assertFalse(entry['offers'] or session._known_offers or session._offer_origins)
        self.assertEqual(entry['attempt']['batches'], 0)

    async def test_failed_preparation_does_not_register_partial_batch(self):
        async def fail():
            raise ValueError('control preparation failure')
        session, entry = setup(cpu=Prepared(fail))
        self.addAsyncCleanup(session.close)
        with self.assertRaisesRegex(ValueError, 'control preparation failure'):
            await session._prepare_and_publish(rows(), entry, entry['attempt'])
        self.assertFalse(entry['offers'] or session._known_offers or session._offer_origins)

    async def test_hash_failure_during_final_merge_does_not_publish_partial_state(self):
        class Bomb:
            armed = False
            def __hash__(self):
                if self.armed:
                    raise ValueError('control merge hash failure')
                return 923
        bomb = Bomb()
        class Injected:
            def prepare(self, source):
                async def chunks():
                    yield [(rows(1)[0], (('valid',), bomb))]
                    await asyncio.sleep(0)
                    bomb.armed = True
                return chunks()
        session, entry = setup(cpu=Injected())
        self.addAsyncCleanup(session.close)
        with self.assertRaisesRegex(ValueError, 'control merge hash failure'):
            await session._prepare_and_publish([], entry, entry['attempt'])
        self.assertFalse(entry['offers'] or session._known_offers or session._offer_origins)
        self.assertEqual(entry['attempt']['batches'], 0)

    async def test_malformed_nominations_and_empty_batches_match_baseline(self):
        result = []
        for kind in (SerialOracle, RouteBootstrap):
            session, entry = setup(kind)
            self.addAsyncCleanup(session.close)
            for source in ([], [[{'amountIn': '7', 'hops': [{'pool': {'bad': True}}]}]], rows(2)):
                await session._prepare_and_publish(source, entry, entry['attempt'])
            result.append(snapshot(session, [entry], [entry['attempt']]))
        self.assertEqual(*result)

    async def test_capture_and_per_batch_amount_order_remain_private(self):
        source = rows()
        session, entry = setup()
        self.addAsyncCleanup(session.close)
        task = asyncio.create_task(session._prepare_and_publish(source, entry, entry['attempt']))
        await asyncio.sleep(0)
        source[0][0]['amountIn'] = 'later supplier mutation'
        await task
        self.assertEqual(entry['offers'][0]['branches'][0]['amountIn'], '1')
        exported = deepcopy(entry['offers'][0]['branches'])
        exported[0]['hops'][0]['pool']['feePips'] = 123
        self.assertEqual(entry['offers'][0]['branches'][0]['hops'][0]['pool']['feePips'], 500)


if __name__ == "__main__":
    unittest.main()
