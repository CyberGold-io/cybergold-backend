"""Subscription-owned publication of completed Helpers quote observations.

The producer callback snapshots/enqueues. Delivery and execution preparation
use latest simulation observations without additional block verification.
"""
import asyncio
from copy import deepcopy

from .quoter.ranking import prefer_completed
from .quoter.provenance import merge_origins
from .quoter.reuse_estimate import attach_reuse_sample, input_limit_observed
from .quoter.types import EconomicRequest
from .recovery_rpc import SnapshotChanged
from .telemetry import observe


class CanonicalPublication:
    def __init__(self, quoter, request, publish, *, refresh=False):
        self.quoter, self.request, self.publish = quoter, request, publish
        self.refresh = refresh
        self.queue = asyncio.Queue()
        self.best = None
        self.closed = False
        self.context = None
        self.disproof = None

    def preferred(self, value):
        return prefer_completed(value, self.best, scalar=self.request['intent'] in (0, 1),
                                basket=self.request['intent'] >= 2)

    async def enqueue(self, frame):
        # This callback executes in candidate work. Do not put canonical RPC,
        # transport backpressure or SQL awaits on that producer critical path.
        if self.closed:
            return
        if frame['type'] == 'qualified':
            value = deepcopy(frame['value'])
            self.context = deepcopy(value['context'])
            self.queue.put_nowait(('candidate', value))
        elif frame['type'] == 'upper-replay-settled':
            # Ordered behind the upper candidate's canonical publication. The
            # display hint is not a quote and needs no additional chain read.
            self.queue.put_nowait(('upper-replay-settled', None))

    async def run(self):
        while (item := await self.queue.get()) is not None:
            kind, value = item
            if kind == 'stored':
                # The optional historical read may finish after current
                # Helpers pricing. It never holds or replaces that result.
                if self.best is None and not self.closed:
                    await self.publish({'type': 'qualified', 'value': value})
                continue
            if kind == 'upper-replay-settled':
                if not self.closed:
                    await self.publish({'type': kind})
                continue
            if self.closed:
                continue
            if kind == 'terminal' and self.best is not None:
                previous_limit = input_limit_observed(self.best)
                merge_origins(self.best, value)
                if not previous_limit and input_limit_observed(self.best):
                    # Equivalent terminal economics can add a paid limitation
                    # observation. Deliver the whole winner via the same owned
                    # publication path before the transport's complete frame.
                    await self.publish({'type': 'qualified', 'value': deepcopy(self.best)})
            if not self.preferred(value):
                continue
            self.best = {**attach_reuse_sample(value),
                         'observation': {'source': 'search', 'refresh': self.refresh}}
            await self.publish({'type': 'qualified', 'value': deepcopy(self.best)})


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

        publication = CanonicalPublication(service.quoter, request, publish, refresh=refresh)
        producer = asyncio.create_task(service.quoter.quote(request, publication.enqueue,
            seed=previous, seed_lookup=cache.lookup if scalar or refresh else None,
            neighbors=cache.neighbors if scalar else None,
            on_family=cache.observe_family if scalar else None))
        consumer = asyncio.create_task(publication.run())
        async def historical_offer():
            try:
                stored = await cache.lookup()
                if stored is not None:
                    offered = await service.cached_offer(request, stored, await cache.scope(),
                                                         neighbors=await cache.neighbors())
                    publication.queue.put_nowait(('stored', deepcopy(offered)))
            except Exception:
                pass  # Optional historical input cannot reject current pricing.
        historical = (asyncio.create_task(historical_offer()) if scalar and not refresh else None)
        tasks = (producer, consumer)
        owned = (*tasks, historical) if historical is not None else tasks
        terminal = None
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if consumer in done:
                # Publisher errors remain owned by this request and cancel
                # pricing; optional storage cannot conceal a transport failure.
                await consumer
            terminal = await producer
            # The returned winner completed its Helpers execution simulation.
            publication.queue.put_nowait(('terminal', deepcopy(terminal)))
            publication.queue.put_nowait(None)
            await consumer
        finally:
            publication.closed = True
            for task in owned:
                if not task.done():
                    task.cancel()
            outcomes = await asyncio.gather(*owned, return_exceptions=True)
            disproof = publication.disproof or next((error for error in outcomes
                                                     if isinstance(error, SnapshotChanged)), None)
            if disproof is not None:
                cache.completed.clear()
                if publication.context is not None:
                    disproof.economic_context = deepcopy(publication.context)
                raise disproof
            if publication.best is not None:
                if terminal is not None:
                    # A terminal tie can carry additional nomination origins.
                    merge_origins(publication.best, terminal)
                if terminal is not None and terminal.get('metrics') is not None:
                    publication.best['metrics'] = deepcopy(terminal['metrics'])
                # The service owns the optional write after all producer and
                # publication outcomes were drained. Delivery never waits SQL.
                cache.save(publication.best)
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
