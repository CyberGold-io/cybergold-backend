"""Subscription-owned publication of completed Helpers quote observations.

The producer callback snapshots/enqueues. Delivery and execution preparation
use latest simulation observations without additional block verification.
"""
import asyncio
from copy import deepcopy

from .quoter.types import EconomicRequest
from .quoter.reuse_routes import funded_route_identity
from .quoter.quote_book import QuoteBook
from .recovery_rpc import SnapshotChanged
from .quote_errors import QuoteFailure


class CanonicalPublication:
    def __init__(self, quoter, request, publish, *, refresh=False, cache=None):
        self.quoter, self.request, self.publish = quoter, request, publish
        self.refresh, self.cache = refresh, cache
        self.queue = asyncio.Queue()
        registry = getattr(getattr(quoter, 'engine', None), 'registry', None)
        self.book = QuoteBook(request, refresh=refresh, seed=getattr(registry, 'seed', None))
        self.best = None
        self.closed = False
        self.private_observations = False
        self.context = self.disproof = None
        self.book.on_observation = self._accept_observation
        self.book.on_history = self._accept_history
        if cache is not None:
            cache.bind(self.book)

    def _current(self, frame):
        frame = {**frame, '_candidateIdentity': frame.get('_candidateIdentity') or funded_route_identity(frame['value'])}
        if self.cache is not None:
            self.cache.announce(frame)
        else:
            self._accept_observation(frame, max(self.book.versions.values(), default=0) + 1)

    def _accept_observation(self, frame, version):
        if frame.get('type') == 'candidate-repriced':
            self.private_observations = True
        value, identity = frame['value'], frame['_candidateIdentity']
        replaces = frame.get('_replacesIdentity')
        self.book.versions[identity] = version
        if replaces is not None:
            self.book.versions[replaces] = version
        previous = self.book.winner()
        self.book.observe(value, identity=identity, replaces=replaces)
        if self.cache is not None:
            if replaces is not None:
                self.cache.forget_pending(replaces)
            if value is None:
                self.cache.forget_pending(identity)
        if value is not None:
            self.context = deepcopy(value['context'])
        elif previous is not None:
            self.disproof = deepcopy(previous['context'])
        self._remember_families()
        self.queue.put_nowait(('changed', None))

    def _accept_history(self, value, sequence):
        if self.book.observe(value, current=False, sequence=sequence):
            self.queue.put_nowait(('changed', None))

    def _historical(self, value):
        try:
            observation = self.cache.historical_observation(value) if self.cache is not None else (value, None)
            if observation is not None:
                self.book.observe(observation[0], current=False, sequence=observation[1])
        except (KeyError, TypeError, ValueError):
            pass  # An incomplete old cache row cannot interrupt ordinary search.

    def _remember_families(self):
        if self.cache is not None:
            for value, current in self.book.family_values().values():
                if current:
                    self.cache.remember(value, version=self.book.versions.get(funded_route_identity(value)))

    async def observe_family(self, value):
        if funded_route_identity(value) not in self.book.observed:
            await self.enqueue({'type': 'candidate-repriced', 'value': value})

    async def enqueue(self, frame):
        if self.closed:
            return
        if frame['type'] == 'candidate-repriced':
            self._current(frame)
        elif frame['type'] == 'qualified':
            # Legacy/scripted producers retain their ordinary callback. Real
            # Quoter observations enter through the private on_candidate hook.
            previous = self.book.rows.get(funded_route_identity(frame['value']))
            if previous is None or previous[0] != frame['value']:
                self._current(frame)
            self.queue.put_nowait(('changed', None))
        elif frame['type'] == 'upper-replay-settled':
            self.queue.put_nowait(('upper-replay-settled', None))

    async def run(self):
        while (item := await self.queue.get()) is not None:
            kind, value = item
            if self.closed:
                continue
            if kind == 'upper-replay-settled':
                await self.publish({'type': kind})
                continue
            if kind == 'stored':
                self._historical(value)
            elif kind == 'stored-batch':
                for observation in value:
                    self._historical(observation)
            elif kind == 'candidate':
                self._current({'value': value})
            elif kind == 'terminal':
                if not self.private_observations or funded_route_identity(value) not in self.book.observed:
                    self._current({'value': value})
                else:
                    self.book.finish(value)
                self._remember_families()
            winner = self.book.winner()
            if winner == self.best and not (winner is None and self.disproof is not None):
                continue
            previous, self.best = self.best, winner
            if winner is not None:
                await self.publish({'type': 'qualified', 'value': deepcopy(winner)})
            elif previous is not None or self.disproof is not None:
                await self.publish({'type': 'invalidated', 'context': deepcopy(
                    previous['context'] if previous is not None else self.disproof)})
                self.disproof = None


async def progressive_quote(service, request, publish, *, refresh=False):
    request = EconomicRequest.model_validate(request).model_dump()
    cache = service.cache_feed(request)
    scalar = request['intent'] in (0, 1)
    try:
        previous = await cache.lookup() if not scalar and not refresh else None
        if previous is not None:
            offered = await service.cached_offer(request, previous, await cache.scope())
            await publish({'type': 'qualified', 'value': deepcopy(offered)})
            return offered

        publication = CanonicalPublication(service.quoter, request, publish, refresh=refresh, cache=cache)
        neighbors = cache.memory_neighbors() if scalar else []
        seeds = cache.route_seeds(neighbors) if scalar else []
        # L1 history is ready before SQL or a prior producer's teardown. The
        # book ranks it alongside each subsequent private Helpers observation.
        memory = cache.memory_lookup()
        stored = ([memory] if memory is not None else []) + [row['quote'] for row in neighbors]
        if stored:
            for value in stored:
                publication._historical(value)
            publication.queue.put_nowait(('changed', None))
        producer = asyncio.create_task(service.quoter.quote(request, publication.enqueue,
            seed=previous, seed_lookup=cache.sql_lookup if scalar or refresh else None,
            neighbors=cache.sql_neighbors if scalar else None,
            on_family=publication.observe_family if scalar else None,
            on_candidate=publication.enqueue,
            **({'route_seeds': seeds} if seeds else {})))
        consumer = asyncio.create_task(publication.run())
        async def historical_offer():
            async def offer(read, *, nearby):
                try:
                    value = await read()
                    values = [row['quote'] for row in value] if nearby else [value]
                    publication.queue.put_nowait(('stored-batch', [quote for quote in values if quote is not None]))
                except Exception:
                    pass
            readers = (asyncio.create_task(offer(cache.sql_lookup, nearby=False)),
                       asyncio.create_task(offer(cache.sql_neighbors, nearby=True)))
            try:
                await asyncio.gather(*readers)
            finally:
                for reader in readers:
                    if not reader.done(): reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
        historical = asyncio.create_task(historical_offer()) if scalar else None
        owned = (producer, consumer, historical) if historical is not None else (producer, consumer)
        try:
            done, _ = await asyncio.wait((producer, consumer), return_when=asyncio.FIRST_COMPLETED)
            if consumer in done:
                await consumer
            try:
                terminal = await producer
            except Exception:
                # Deliver any already-observed winner or paid empty-book
                # invalidation before the ordinary producer error frame.
                publication.queue.put_nowait(None)
                await consumer
                raise
            publication.queue.put_nowait(('terminal', deepcopy(terminal)))
            publication.queue.put_nowait(None)
            await consumer
        finally:
            publication.closed = True
            for task in owned:
                if not task.done(): task.cancel()
            outcomes = await asyncio.gather(*owned, return_exceptions=True)
            disproof = next((error for error in outcomes if isinstance(error, SnapshotChanged)), None)
            if disproof is not None:
                if publication.context is not None:
                    disproof.economic_context = deepcopy(publication.context)
                raise disproof
        if publication.best is None:
            raise QuoteFailure('quote-no-route')
        return deepcopy(publication.best)
    finally:
        cache.flush()
        await cache.close()


class OwnedStreamingResponse:
    """Factory returning NDJSON with explicit disconnect ownership on ASGI 2.4.

    Starlette's ASGI 2.4 path otherwise notices disconnect only on the next send;
    an idle refinement must also stop immediately when its caller disconnects.
    """
    @staticmethod
    def create(events):
        from fastapi.responses import StreamingResponse
        class Response(StreamingResponse):
            async def __call__(self, scope, receive, send):
                streaming = asyncio.create_task(self.stream_response(send))
                disconnected = asyncio.create_task(self.listen_for_disconnect(receive))
                tasks = (streaming, disconnected)
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        await task
                except OSError:
                    pass  # Client closed its socket; finally still owns cleanup.
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await self.body_iterator.aclose()
                if self.background is not None:
                    await self.background()
        return Response(events, media_type='application/x-ndjson',
                        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
