"""Subscription-owned canonical publication beside the unchanged Quoter.

The producer callback only snapshots/enqueues. Canonical reads and delivery run
in a separate owned consumer, never inside the producer's selection budget.
"""
import asyncio
from copy import deepcopy
import json
import logging

from .quoter.ranking import prefer_completed
from .quoter.reuse_estimate import attach_reuse_sample
from .quoter.types import EconomicRequest
from .quote_errors import public_quote_error
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
        if not self.closed and frame['type'] == 'qualified':
            value = deepcopy(frame['value'])
            self.context = deepcopy(value['context'])
            self.queue.put_nowait((False, value))

    async def run(self):
        while (item := await self.queue.get()) is not None:
            canonical, value = item
            if self.closed or not self.preferred(value):
                continue
            if not canonical:
                context = value['context']
                try:
                    await self.quoter.engine.registry.get_rpc().assert_canonical({
                        'number': int(context['blockNumber']), 'hash': context['blockHash']})
                except SnapshotChanged as error:
                    self.context = deepcopy(context)
                    self.disproof = error
                    raise
                except Exception as error:
                    # A failed read leaves this candidate unconfirmed. The
                    # producer and its terminal canonical assertion continue.
                    observe(lambda: logging.getLogger('cybergold.candidate').info(json.dumps({
                        'event': 'economic_quote_refinement', 'phase': 'canonical-publication',
                        'code': public_quote_error(error)['code']})))
                    continue
            if self.closed or not self.preferred(value):
                continue
            self.best = {**attach_reuse_sample(value),
                         'observation': {'source': 'search', 'refresh': self.refresh}}
            await self.publish({'type': 'qualified', 'value': deepcopy(self.best)})


async def progressive_quote(service, request, publish, *, refresh=False):
    request = EconomicRequest.model_validate(request).model_dump()
    if service.observe_scope is not None:
        await service.observe_scope()
    await service.quoter.engine.registry.ensure_loaded()
    scope = service.store.capture_scope(request)
    previous = await service.store.lookup(request, scope=scope)
    if previous is not None and not refresh:
        value = {**attach_reuse_sample(previous), 'observation': {'source': 'stored', 'refresh': False}}
        await publish({'type': 'qualified', 'value': deepcopy(value)})
        return value

    publication = CanonicalPublication(service.quoter, request, publish, refresh=refresh)
    neighbors = ((lambda: service.store.neighbors(request, scope=scope))
                 if request['intent'] in (0, 1) else None)
    producer = asyncio.create_task(service.quoter.quote(request, publication.enqueue,
                                                       seed=previous, neighbors=neighbors))
    consumer = asyncio.create_task(publication.run())
    tasks = (producer, consumer)
    terminal = None
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if consumer in done:
            # A detached publisher's disproof must reach/cancel its owning
            # producer instead of being lost in an unobserved task exception.
            await consumer
        terminal = await producer
        # The returned producer winner has already passed its canonical check.
        publication.queue.put_nowait((True, deepcopy(terminal)))
        publication.queue.put_nowait(None)
        await consumer
    finally:
        publication.closed = True
        for task in tasks:
            if not task.done():
                task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        disproof = publication.disproof or next((error for error in outcomes
                                                 if isinstance(error, SnapshotChanged)), None)
        if disproof is not None:
            if publication.context is not None:
                disproof.economic_context = deepcopy(publication.context)
            raise disproof
        if publication.best is not None:
            if terminal is not None and terminal.get('metrics') is not None:
                # Session clocks are passive metadata; retain the exact
                # published plan/fees/funding if a terminal tie differs.
                publication.best['metrics'] = deepcopy(terminal['metrics'])
            # One optional write, only after all search/publication outcomes
            # have been drained and inspected. No shielded orphan survives stop.
            saving = asyncio.create_task(service.store.save(request, deepcopy(publication.best), scope=scope))
            try:
                await saving
            except Exception:
                pass
            finally:
                if not saving.done():
                    saving.cancel()
                await asyncio.gather(saving, return_exceptions=True)
    return deepcopy(publication.best)


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
