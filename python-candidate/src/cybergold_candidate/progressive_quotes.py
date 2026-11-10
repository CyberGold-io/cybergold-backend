"""Subscription-owned publication of completed Helpers quote observations.

The producer callback snapshots/enqueues. Delivery and execution preparation
use latest simulation observations without additional block verification.
"""
import asyncio
from copy import deepcopy

from .quoter.types import EconomicRequest
from .quote_publication import CanonicalPublication
from .recovery_rpc import SnapshotChanged
from .quote_errors import QuoteFailure


async def progressive_quote(service, request, publish, *, refresh=False):
    request = EconomicRequest.model_validate(request).model_dump()
    cache = service.cache_feed(request)
    scalar = request['intent'] in (0, 1)
    try:
        previous = await cache.lookup() if not scalar and not refresh else None
        if previous is not None:
            offered = await service.cached_offer(request, previous, await cache.scope())
            if offered is not None:
                await publish({'type': 'qualified', 'value': deepcopy(offered)})
                return offered

        publication = CanonicalPublication(service.quoter, request, publish, refresh=refresh, cache=cache)
        neighbors = cache.memory_neighbors() if scalar else []
        # L1 history is ready before SQL or a prior producer's teardown. The
        # book ranks it alongside each subsequent private Helpers observation.
        memory = cache.memory_lookup()
        stored = ([memory] if memory is not None else []) + [row['quote'] for row in neighbors]
        if stored:
            for value in stored:
                publication._historical(value)
            # Deliver the ready selection before scheduling a search whose
            # synchronous prefix could otherwise postpone the first frame.
            await publication.publish_selected()
            await asyncio.sleep(0)
        seeds = cache.route_seeds(neighbors) if scalar else []
        consumer = asyncio.create_task(publication.run())
        producer = asyncio.create_task(service.quoter.quote(request, publication.enqueue,
            seed=previous, seed_lookup=cache.sql_lookup if scalar or refresh else None,
            neighbors=cache.sql_neighbors if scalar else None,
            on_family=publication.observe_family if scalar else None,
            on_candidate=publication.enqueue,
            **({'route_seeds': seeds} if seeds else {})))
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
