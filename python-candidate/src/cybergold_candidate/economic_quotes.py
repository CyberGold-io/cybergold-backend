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
from .quoter.reuse_routes import funded_route_identity
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
    """One operation owns its SQL feeds; completed observations enter L1 now."""
    def __init__(self, service, request):
        self.service, self.request = service, request
        self.preparing = service._own(service._capture_scope(request))
        self.transferred = False
        self.completed, self.pending, self.reads = {}, {}, {}
        self.saving = None
        self.book = None
        self.closed = False

    def local_scope(self, request=None):
        try:
            return self.service.store.capture_scope(request or self.request)
        except Exception:
            return None

    def bind(self, book):
        self.book = book
        register = getattr(self.service.store, 'register_book', None)
        scope = self.local_scope()
        if register is not None and scope is not None:
            register(scope, book)
        def prepared(task):
            if not self.closed and register is not None and not task.cancelled():
                scope = task.result()
                if scope is not None:
                    register(scope, book)
        self.preparing.add_done_callback(prepared)

    def memory_lookup(self):
        read = getattr(self.service.store, 'memory_lookup', None)
        scope = self.local_scope()
        return read(self.request, scope=scope) if read is not None and scope is not None else None

    def memory_neighbors(self):
        read = getattr(self.service.store, 'memory_neighbors', None)
        scope = self.local_scope()
        return read(self.request, scope=scope) if read is not None and scope is not None else []

    def historical_observation(self, value):
        canonical = getattr(self.service.store, 'historical_observation', None)
        scope = self.local_scope()
        return canonical(scope, value) if canonical is not None and scope is not None else (value, None)

    def route_seeds(self, neighbors=None):
        rows, seen = [], set()
        for row in self.memory_neighbors() if neighbors is None else neighbors:
            quote = row['quote']
            identity = funded_route_identity(quote)
            if identity not in seen:
                seen.add(identity)
                rows.append(deepcopy(quote))
        return rows

    async def scope(self):
        return await asyncio.shield(self.preparing)

    async def _read(self, name, missing):
        if name not in self.reads:
            async def read():
                try:
                    scope = await self.scope()
                    operation = getattr(self.service.store, 'load_'+name, None) or getattr(self.service.store, name)
                    return await operation(self.request, scope=scope) if scope is not None else missing
                except Exception:
                    return missing
            self.reads[name] = self.service._own(read())
            track = getattr(self.service.store, 'track_io', None)
            if track is not None:
                track(self.reads[name])
        try:
            return deepcopy(await asyncio.shield(self.reads[name]))
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            return deepcopy(missing)

    async def sql_lookup(self):
        return await self._read('lookup', None)

    async def sql_neighbors(self):
        return await self._read('neighbors', [])

    async def lookup(self):
        memory = self.memory_lookup()
        return memory if memory is not None else await self.sql_lookup()

    async def neighbors(self):
        return self.memory_neighbors() or await self.sql_neighbors()

    def forget(self, identity):
        scope = self.local_scope()
        forget = getattr(self.service.store, 'forget', None)
        if forget is not None and scope is not None:
            forget(identity, scope=scope)
        self.forget_pending(identity)

    def forget_pending(self, identity):
        for family, value in list(self.completed.items()):
            if funded_route_identity(value) == identity:
                self.completed.pop(family, None)
                self.pending.pop(family, None)

    def announce(self, frame):
        scope = self.local_scope()
        announce = getattr(self.service.store, 'announce', None)
        if announce is not None and scope is not None:
            announce(self.request, frame, self.book, scope=scope)
        else:
            version = max(self.book.versions.values(), default=0) + 1
            self.book.on_observation(frame, version)

    def remember(self, value, *, version=None):
        family, identity = quote_path_family(value), funded_route_identity(value)
        previous = self.completed.get(family)
        if previous == value:
            return
        request = value.get('request', self.request)
        scope = self.local_scope(request)
        remember = getattr(self.service.store, 'remember', None)
        if remember is not None and scope is not None:
            if version is not None:
                if version < self.service.store.latest_version(scope, identity):
                    return
                remember(request, value, scope=scope, version=version)
            else:
                remember(request, value, scope=scope)
        same = previous is not None and funded_route_identity(previous) == identity
        if same or prefer_completed(value, previous, scalar=self.request['intent'] in (0, 1),
                                     basket=self.request['intent'] >= 2):
            self.completed[family] = deepcopy(value)
            self.pending[family] = (deepcopy(value), version)
            self.flush()
        else:
            merge_origins(previous, value)

    async def observe_family(self, value):
        self.remember(value)

    def save(self, value):
        self.remember(value)

    def flush(self):
        if self.pending and (self.saving is None or self.saving.done()):
            self.transferred = True
            self.saving = self.service._own(self._save())
            track = getattr(self.service.store, 'track_io', None)
            if track is not None:
                track(self.saving)

    async def _save(self):
        try:
            scope = await self.scope()
            if scope is not None:
                while self.pending:
                    values, self.pending = list(self.pending.values()), {}
                    for value, version in values:
                        try:
                            request = value.get('request', self.request)
                            selected = (self.service.store.point_scope(scope, request)
                                        if hasattr(self.service.store, 'point_scope') else scope)
                            write = getattr(self.service.store, 'persist', None)
                            if write is not None:
                                await write(request, attach_reuse_sample(value), scope=selected, version=version)
                            else:
                                await self.service.store.save(request, attach_reuse_sample(value), scope=selected)
                        except Exception:
                            pass
        except Exception:
            pass
        finally:
            await self._close_scope()

    async def _close_scope(self):
        if not self.preparing.done():
            self.preparing.cancel()
        await asyncio.gather(self.preparing, return_exceptions=True)

    async def close(self):
        self.closed = True
        unregister = getattr(self.service.store, 'unregister_book', None)
        if unregister is not None and self.book is not None:
            unregister(self.book)
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
        close = getattr(self.store, 'close', None)
        if close is not None:
            await close()

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
        async def ignore(_frame):
            pass
        return await self.progressive(request, ignore, refresh=refresh)

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
            elif frame['type'] == 'invalidated':
                incumbent = None
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
