"""Shared economic observations and explicit current-state quote refresh."""
import asyncio
from copy import deepcopy
import json
from fastapi.responses import JSONResponse

from .basket_preview import InvalidPreview
from .quoter.types import EconomicRequest
from .quoter.reuse_estimate import attach_reuse_sample
from .quoter.dormant_routes import with_dormant_routes
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
            result = await execute()
        except asyncio.CancelledError:
            observe(lambda: observation.finish('cancelled', frame={'economicEvidence': evidence(work,
                operationKind=kind, resultSource=source, operationPhase=phase)}))
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

    async def scope(self):
        return await asyncio.shield(self.preparing)

    async def lookup(self):
        try:
            scope = await self.scope()
            return await self.service.store.lookup(self.request, scope=scope) if scope is not None else None
        except Exception:
            return None

    async def neighbors(self):
        try:
            scope = await self.scope()
            return (await self.service.store.neighbors(self.request, scope=scope)
                    if scope is not None else {'lower': None, 'upper': None})
        except Exception:
            return {'lower': None, 'upper': None}

    def save(self, value):
        self.transferred = True
        self.service._own(self._save(deepcopy(value)))

    async def _save(self, value):
        try:
            scope = await self.scope()
            if scope is not None:
                await self.service.store.save(self.request, value, scope=scope)
        except Exception:
            pass  # Optional storage cannot revoke a completed Helpers result.
        finally:
            await self._close_scope()

    async def _close_scope(self):
        if not self.preparing.done():
            self.preparing.cancel()
        await asyncio.gather(self.preparing, return_exceptions=True)

    async def close(self):
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

    async def cached_offer(self, request, previous, scope):
        """Offer the better complete stored tuple, preserving its observation.

        An old poor exact-budget row must not mask a better fitting quote.
        This remains a DB-only historical lookup. A scalar offer below the
        requested budget seeds ordinary optimization as well as Refresh.
        """
        offered = previous
        if request['intent'] in (0, 1):
            try:
                lower = (await self.store.neighbors(request, scope=scope)).get('lower')
                if lower and int(lower['quote']['quotedOutput']) > int(previous['quotedOutput']):
                    offered = {**deepcopy(lower['quote']), 'request': deepcopy(request)}
            except Exception:
                pass  # Optional neighbor failure leaves the exact cache hit.
        offered = with_dormant_routes(offered, getattr(self.quoter.engine.registry, 'seed', None))
        return {**attach_reuse_sample(offered), 'observation': {'source': 'stored', 'refresh': False}}

    @staticmethod
    def unfilled_budget(request, quote):
        """An existing smaller-funded plan still needs the requested-amount try."""
        return request['intent'] in (0, 1) and int(quote['inputs'][0]['amount']) < int(request['inputs'][0]['amount'])

    async def get(self, request, *, refresh=False):
        request = EconomicRequest.model_validate(request).model_dump()
        cache = self.cache_feed(request)
        try:
            # A complete funded cache hit remains immediate. Smaller-funded
            # hits supply topology to the ordinary requested-budget search.
            previous = await cache.lookup() if not refresh else None
            if previous is not None:
                offered = await self.cached_offer(request, previous, await cache.scope())
                if not self.unfilled_budget(request, offered):
                    return offered
            value = attach_reuse_sample(await self.quoter.quote(request, seed=previous,
                seed_lookup=cache.lookup if refresh else None,
                neighbors=cache.neighbors if request['intent'] in (0, 1) else None))
            cache.save(value)
            return {**value, 'observation': {'source': 'search', 'refresh': refresh}}
        finally:
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
