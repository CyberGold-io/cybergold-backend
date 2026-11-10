"""Shared economic observations and explicit current-state quote refresh."""
import asyncio
from copy import deepcopy
import json
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect

from .quote_flow import stage, milestone
from .basket_preview import InvalidPreview
from .economic_quote_cache import CacheFeed
from .quoter.types import EconomicRequest
from .quoter.reuse_estimate import attach_reuse_sample
from .quoter.dormant_routes import with_dormant_routes
from .quoter.ranking import prefer_completed
from .quoter.pool_directions import conflicting_pool, quote_directions
from .recovery_rpc import SnapshotChanged
from .trade_observation import QuoteObservation, failure
from .telemetry import operation_work, observe


STREAM_KEEPALIVE_SECONDS = 15


def economic_intent(value):
    return {'mode': 'issue-exact-in' if value['intent'] in (0, 2) else 'redeem-exact-in',
            'assetCount': len(value['inputs']), 'inputs': value['inputs']}


def full_funding_observation(value, budget):
    """Optional ordered budget equality; it never admits or rejects a quote."""
    try:
        if value.get('readOnly'):
            return False
        funding = value['inputs']
        return len(funding) == len(budget) and all(
            current['currency'].lower() == requested['currency'].lower()
            and int(current['amount']) == int(requested['amount'])
            for current, requested in zip(funding, budget, strict=True))
    except Exception:
        return False


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
        with stage('http.encode', kind='cpu'):
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})


async def request_operation(request, execute):
    """After body parsing, the JSON client owns its operation until delivery."""
    async def disconnected():
        while (await request.receive())['type'] != 'http.disconnect':
            pass
    waiting = None
    async def execute_operation():
        try:
            with stage('http.operation'):
                return await execute()
        finally:
            if waiting is not None:
                waiting.ready()
    operation = asyncio.create_task(execute_operation())
    caller = asyncio.create_task(disconnected())
    try:
        with stage('http.await_result', kind='queue') as waiting:
            done, _ = await asyncio.wait((operation, caller), return_when=asyncio.FIRST_COMPLETED)
            if operation in done:
                return await operation
            await caller
            raise ClientDisconnect()
    finally:
        with stage('http.cleanup'):
            for task in (operation, caller):
                if not task.done():
                    task.cancel()
            await asyncio.gather(operation, caller, return_exceptions=True)


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
        offered = previous if previous is None or conflicting_pool(quote_directions(previous)) is None else None
        if request['intent'] in (0, 1):
            try:
                rows = (await self.store.neighbors(request, scope=scope)) if neighbors is None else neighbors
                for neighbor in rows:
                    if (neighbor['side'] == 'lower'
                            and conflicting_pool(quote_directions(neighbor['quote'])) is None
                            and prefer_completed(neighbor['quote'], offered, scalar=True)):
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
        with stage('http.parse'):
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
        with stage('http.parse'):
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
            if frame['type'] in ('qualified', 'complete') and full_funding_observation(frame.get('value'), value['inputs']):
                milestone('publication.first_full_selected')
            if frame['type'] == 'qualified':
                milestone('publication.first_selected')
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
            while True:
                keepalive = False
                with stage('publication.queue', kind='queue'):
                    try:
                        frame = await asyncio.wait_for(queue.get(), STREAM_KEEPALIVE_SECONDS)
                    except TimeoutError:
                        keepalive = True
                if keepalive:
                    # Keep idle HTTP readers active without touching the
                    # producer or publishing another quote observation.
                    state = request.scope.setdefault('state', {})
                    state.pop('quote_frame_type', None)
                    state.pop('quote_frame_full_funding', None)
                    yield '\n'
                    continue
                if frame is None:
                    break
                with stage('http.encode', kind='cpu'):
                    encoded = json.dumps(frame, separators=(',', ':'))+'\n'
                request.scope.setdefault('state', {})['quote_frame_type'] = frame['type']
                # Bind to this encoded frame, not a later callback while an
                # earlier partial frame is still queued or awaiting ASGI send.
                request.scope['state']['quote_frame_full_funding'] = (
                    frame['type'] in ('qualified', 'complete') and
                    full_funding_observation(frame.get('value'), value['inputs']))
                yield encoded
        finally:
            if not task.done():
                task.cancel()
            milestone('http.cleanup.started')
            with stage('http.cleanup'):
                await asyncio.gather(task, return_exceptions=True)
            milestone('http.cleanup.finished')
            observe(lambda: observation.finish('cancelled'))
    return OwnedStreamingResponse.create(events())


async def handle_tx_preparation(request, service):
    from .tx_preparation import TransactionPreparationRequest
    try:
        with stage('http.parse'):
            value = TransactionPreparationRequest.model_validate(await request.json()).model_dump(exclude_none=True)
    except (ValueError, TypeError):
        return JSONResponse({'error': 'Invalid transaction preparation request.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    return await observed_json(request, economic_intent(value['quote']['request']), lambda: service.prepare(value),
        kind='transaction-preparation', source='prepared-transaction', phase='selected-plan-replay')


async def handle_economic_estimate(request, service):
    from .trade_quote import TradeModelRequest, validate
    try:
        with stage('http.parse'):
            value = TradeModelRequest.model_validate(await request.json()).model_dump()
        validate(value, model=True)
    except (ValueError, TypeError):
        return JSONResponse({'error': 'Invalid trade quote input.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    return await observed_json(request, value, lambda: service.get_model(value),
        kind='fast-estimator', source='fast-estimate', phase='advisory-estimate', invalid_status=None)
