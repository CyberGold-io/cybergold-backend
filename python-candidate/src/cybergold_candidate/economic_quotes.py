"""Shared economic observations and explicit current-state quote refresh."""
import asyncio
from fastapi.responses import JSONResponse

from .basket_preview import InvalidPreview
from .quoter.types import EconomicRequest
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


class EconomicQuotes:
    def __init__(self, quoter, store, *, observe_scope=None):
        self.quoter, self.store = quoter, store
        self.observe_scope = observe_scope

    async def get(self, request, *, refresh=False):
        request = EconomicRequest.model_validate(request).model_dump()
        # This captures existing deployment/generation/fee scope, not the head.
        if self.observe_scope is not None:
            await self.observe_scope()
        await self.quoter.engine.registry.ensure_loaded()
        scope = self.store.capture_scope(request)
        previous = await self.store.lookup(request, scope=scope)
        if previous is not None and not refresh:
            return {**previous, 'observation': {'source': 'stored', 'refresh': False}}
        value = await self.quoter.quote(request, seed=previous)
        await self.store.save(request, value, scope=scope)
        return {**value, 'observation': {'source': 'search', 'refresh': refresh}}


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
