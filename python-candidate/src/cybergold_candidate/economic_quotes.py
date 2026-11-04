"""Shared economic observations and explicit current-state quote refresh."""
import asyncio
from copy import deepcopy
import json
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect

from .basket_preview import InvalidPreview
from .quoter.types import EconomicRequest
from .quoter.reuse_estimate import attach_reuse_sample
from .quoter.dormant_routes import with_dormant_routes
from .quoter.ranking import prefer_completed
from .quoter.path_families import quote_path_family
from .quoter.provenance import merge_origins
from .recovery_rpc import SnapshotChanged
from .trade_observation import QuoteObservation, failure
from .telemetry import operation_work, observe


def economic_intent(value):
    return {'mode': 'issue-exact-in' if value['intent'] in (0, 2) else 'redeem-exact-in',
            'assetCount': len(value['inputs']), 'inputs': value['inputs']}


def work_evidence(work, **values):
    try:
        return {**values, 'rpc': work.snapshot()}
    except Exception:
        return values


async def observed_json(request, intent, execute, *, kind, source, phase, invalid_status=400):
    """Keep JSON product behavior while using the existing safe outcome sink."""
    observation = QuoteObservation(request, intent)
    def evidence(work, **values):
        return work_evidence(work, requestInputs=intent.get('inputs', []), **values)
    with operation_work() as work:
        try:
            result = await request_operation(request, execute)
        except (asyncio.CancelledError, ClientDisconnect) as error:
            observe(lambda: observation.finish('cancelled', frame={'economicEvidence': evidence(work,
                operationKind=kind, resultSource=source, operationPhase=phase)}))
            if isinstance(error, ClientDisconnect):
                return Response(status_code=499)
            raise
        except InvalidPreview as error:
            payload = (failure(request, error, observation.operation, payload={'error': str(error)})
                       if invalid_status is not None else observation.error(error))
            observe(lambda: observation.finish('failed', frame={**payload, 'economicEvidence': evidence(work,
                operationKind=kind, resultSource=source, operationPhase=phase,
                producerMetrics=getattr(error, 'quoter_metrics', None))}))
            return JSONResponse({key: value for key, value in payload.items() if key != 'type'},
                                status_code=invalid_status if invalid_status is not None else 503,
                                headers={'Cache-Control': 'no-store'})
        except Exception as error:
            payload = observation.error(error)
            observe(lambda: observation.finish('failed', frame={**payload, 'economicEvidence': evidence(work,
                operationKind=kind, resultSource=source, operationPhase=phase,
                producerMetrics=getattr(error, 'quoter_metrics', None))}))
            return JSONResponse({key: value for key, value in payload.items() if key != 'type'},
                                status_code=503, headers={'Cache-Control': 'no-store'})
        if kind == 'quoter' and result.get('observation', {}).get('source') == 'stored':
            source, phase = 'stored-quote', 'lookup'
        observe(lambda: observation.finish('succeeded', strategy='universal' if kind != 'fast-estimator' else 'none',
            frame={'value': result, 'economicEvidence': evidence(work,
                operationKind=kind, resultSource=source, operationPhase=phase)}))
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})


async def request_operation(request, execute):
    """After body parsing, the JSON client owns its operation until delivery."""
    async def disconnected():
        while (await request.receive())['type'] != 'http.disconnect':
            pass
    operation = asyncio.create_task(execute())
    caller = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((operation, caller), return_when=asyncio.FIRST_COMPLETED)
        if operation in done:
            return await operation
        await caller
        raise ClientDisconnect()
    finally:
        for task in (operation, caller):
            if not task.done():
                task.cancel()
        await asyncio.gather(operation, caller, return_exceptions=True)


class CacheFeed:
    """Optional request inputs with one shared deployment-scope observation.

    Feed cancellation does not cancel a sibling's scope observation. The
    request owns preparation until a completed quote transfers it to the
    service's background writer; shutdown drains both kinds of work.
    """
    def __init__(self, service, request):
        self.service, self.request = service, request
        self.preparing = service._own(service._capture_scope(request))
        self.transferred = False
        self.completed = {}
        self.reads = {}

    async def scope(self):
        return await asyncio.shield(self.preparing)

    async def _read(self, name, missing):
        if name not in self.reads:
            async def read():
                try:
                    scope = await self.scope()
                    return (await getattr(self.service.store, name)(self.request, scope=scope)
                            if scope is not None else missing)
                except Exception:
                    return missing
            self.reads[name] = self.service._own(read())
        # The historical publisher and current search share this observation;
        # cancelling either waiter does not cancel its sibling's SQL reader.
        try:
            return deepcopy(await asyncio.shield(self.reads[name]))
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            # An independently cancelled optional reader is a cache miss. It
            # does not transfer its cancellation to a live quote subscriber.
            return deepcopy(missing)

    async def lookup(self):
        return await self._read('lookup', None)

    async def neighbors(self):
        return await self._read('neighbors', [])

    def remember(self, value):
        family = quote_path_family(value)
        previous = self.completed.get(family)
        if prefer_completed(value, previous, scalar=self.request['intent'] in (0, 1),
                            basket=self.request['intent'] >= 2):
            self.completed[family] = deepcopy(value)
        else:
            merge_origins(previous, value)
            if (previous['inputs'] == value['inputs'] and previous['quotedOutput'] == value['quotedOutput']
                    and value.get('metrics') is not None):
                previous['metrics'] = deepcopy(value['metrics'])

    async def observe_family(self, value):
        # Helpers completed this value. Capturing a losing path family must not
        # publish a worse incumbent or wait for SQL on the producer path.
        self.remember(value)

    def save(self, value):
        self.remember(value)
        self.flush()

    def flush(self):
        if not self.completed:
            return
        values = [attach_reuse_sample(value) for value in self.completed.values()]
        self.completed = {}
        self.transferred = True
        self.service._own(self._save(values))

    async def _save(self, values):
        try:
            scope = await self.scope()
            if scope is not None:
                for value in values:
                    try:
                        await self.service.store.save(self.request, value, scope=scope)
                    except Exception:
                        pass  # One optional family write cannot suppress its sibling.
        except Exception:
            pass  # Optional storage cannot revoke a completed Helpers result.
        finally:
            await self._close_scope()

    async def _close_scope(self):
        if not self.preparing.done():
            self.preparing.cancel()
        await asyncio.gather(self.preparing, return_exceptions=True)

    async def close(self):
        reads = tuple(self.reads.values())
        for task in reads:
            if not task.done():
                task.cancel()
        await asyncio.gather(*reads, return_exceptions=True)
        if not self.transferred:
            await self._close_scope()


class EconomicQuotes:
    def __init__(self, quoter, store, *, observe_scope=None):
        self.quoter, self.store = quoter, store
        self.observe_scope = observe_scope
        self.background = set()

    def _own(self, operation):
        task = asyncio.create_task(operation)
        self.background.add(task)
        def finished(done):
            self.background.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        return task

    async def _capture_scope(self, request):
        try:
            # Existing deployment/generation/fee scope, never a quote head.
            if self.observe_scope is not None:
                await self.observe_scope()
            await self.quoter.engine.registry.ensure_loaded()
            return self.store.capture_scope(request)
        except Exception:
            return None

    def cache_feed(self, request):
        return CacheFeed(self, request)

    async def close(self):
        tasks = tuple(self.background)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def cached_offer(self, request, previous, scope, *, neighbors=None):
        """Offer the better complete stored tuple, preserving its observation.

        An old poor exact-budget row must not mask a better fitting quote.
        This remains a DB-only historical lookup. Scalar offers seed ordinary
        optimization of both path families as well as explicit Refresh.
        """
        offered = previous
        if request['intent'] in (0, 1):
            try:
                rows = (await self.store.neighbors(request, scope=scope)) if neighbors is None else neighbors
                for neighbor in rows:
                    if neighbor['side'] == 'lower' and prefer_completed(neighbor['quote'], offered, scalar=True):
                        offered = {**deepcopy(neighbor['quote']), 'request': deepcopy(request)}
            except Exception:
                pass  # Optional neighbor failure leaves the exact cache hit.
        if offered is None:
            return None
        offered = with_dormant_routes(offered, getattr(self.quoter.engine.registry, 'seed', None))
        return {**attach_reuse_sample(offered), 'observation': {'source': 'stored', 'refresh': False}}

    async def get(self, request, *, refresh=False):
        request = EconomicRequest.model_validate(request).model_dump()
        cache = self.cache_feed(request)
        scalar = request['intent'] in (0, 1)
        try:
            # Scalar JSON waits for current pricing, so no historical SQL read
            # belongs ahead of its producer. Its two optional feeds start with
            # exploration. Basket cache behavior remains unchanged.
            previous = await cache.lookup() if not scalar and not refresh else None
            if previous is not None:
                return await self.cached_offer(request, previous, await cache.scope())
            value = attach_reuse_sample(await self.quoter.quote(request, seed=previous,
                seed_lookup=cache.lookup if scalar or refresh else None,
                neighbors=cache.neighbors if scalar else None,
                on_family=cache.observe_family if scalar else None))
            cache.save(value)
            return {**value, 'observation': {'source': 'search', 'refresh': refresh}}
        except SnapshotChanged:
            cache.completed.clear()
            raise
        finally:
            cache.flush()
            await cache.close()

    async def progressive(self, request, publish, *, refresh=False):
        from .progressive_quotes import progressive_quote
        return await progressive_quote(self, request, publish, refresh=refresh)


async def handle_economic_quote(request, service):
    try:
        payload = await request.json()
        refresh = payload.get('refresh', False)
        if not isinstance(refresh, bool):
            raise ValueError('refresh must be boolean')
        value = EconomicRequest.model_validate(payload).model_dump()
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({'error': 'Invalid economic quote request.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    return await observed_json(request, economic_intent(value), lambda: service.get(value, refresh=refresh),
        kind='quoter', source='refresh' if refresh else 'search', phase='current-state-search')


async def handle_economic_quote_stream(request, service):
    from .progressive_quotes import OwnedStreamingResponse
    from .recovery_rpc import SnapshotChanged
    try:
        payload = await request.json()
        refresh = payload.get('refresh', False)
        if not isinstance(refresh, bool):
            raise ValueError('refresh must be boolean')
        value = EconomicRequest.model_validate(payload).model_dump()
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({'error': 'Invalid economic quote request.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    intent = economic_intent(value)
    observation = QuoteObservation(request, intent, strategy='universal')
    async def events():
        queue = asyncio.Queue()
        incumbent = None
        async def publish(frame):
            nonlocal incumbent
            if frame['type'] == 'qualified':
                incumbent = deepcopy(frame['value'])
            queue.put_nowait(observation.event(frame))
        async def produce():
            nonlocal incumbent
            with operation_work() as work:
                def finish(outcome, frame=None, producer_metrics=None):
                    facts = {'value': incumbent or {}, **(frame or {})}
                    if not isinstance(facts.get('value'), dict):
                        facts['value'] = {}
                    stored = incumbent and incumbent.get('observation', {}).get('source') == 'stored'
                    facts['economicEvidence'] = work_evidence(work, requestInputs=intent['inputs'],
                        operationKind='quoter', resultSource='stored-quote' if stored else 'refresh' if refresh else 'search',
                        operationPhase='lookup' if stored else 'current-state-search',
                        producerMetrics=producer_metrics)
                    observe(lambda: observation.finish(outcome, strategy='universal', frame=facts))
                try:
                    result = await service.progressive(value, publish, refresh=refresh)
                    finish('succeeded', {'value': result})
                    await publish({'type': 'complete', 'value': result})
                except asyncio.CancelledError:
                    finish('cancelled')
                    raise
                except Exception as error:
                    if isinstance(error, SnapshotChanged):
                        context = getattr(error, 'economic_context', None)
                        if context is not None:
                            await publish({'type': 'invalidated', 'context': deepcopy(context)})
                        incumbent = None
                    payload = observation.error(error)
                    finish('failed', payload, getattr(error, 'quoter_metrics', None))
                    await publish(payload)
                finally:
                    queue.put_nowait(None)
        task = asyncio.create_task(produce())
        try:
            while (frame := await queue.get()) is not None:
                yield json.dumps(frame, separators=(',', ':'))+'\n'
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            observe(lambda: observation.finish('cancelled'))
    return OwnedStreamingResponse.create(events())


async def handle_tx_preparation(request, service):
    from .tx_preparation import TransactionPreparationRequest
    try:
        value = TransactionPreparationRequest.model_validate(await request.json()).model_dump(exclude_none=True)
    except (ValueError, TypeError):
        return JSONResponse({'error': 'Invalid transaction preparation request.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    return await observed_json(request, economic_intent(value['quote']['request']), lambda: service.prepare(value),
        kind='transaction-preparation', source='prepared-transaction', phase='selected-plan-replay')


async def handle_economic_estimate(request, service):
    from .trade_quote import TradeModelRequest, validate
    try:
        value = TradeModelRequest.model_validate(await request.json()).model_dump()
        validate(value, model=True)
    except (ValueError, TypeError):
        return JSONResponse({'error': 'Invalid trade quote input.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    return await observed_json(request, value, lambda: service.get_model(value),
        kind='fast-estimator', source='fast-estimate', phase='advisory-estimate', invalid_status=None)
