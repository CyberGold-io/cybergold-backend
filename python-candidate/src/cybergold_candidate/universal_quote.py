"""Compatibility adapter for the existing universal exact-input HTTP contract.

The production component is quoter.Quoter. Keep this import/route adapter while
existing consumers migrate; both names reference the same implementation.
"""
from fastapi.responses import JSONResponse

from .exact_input_plan import UniversalExactInputRequest
from .quoter import Quoter
from .quoter.search import CORE_SHARES, PAXG, identity_template, paths, route_candidates
from .routing_encoding import ZERO

class UniversalQuotes(Quoter):
    """Temporary execution-shaped contract adapter around the one Quoter."""

    async def candidate(self, request, *args, core_sale_bounds=None, **kwargs):
        value = await super().candidate(request, *args, **kwargs)
        if 'deadline' not in request:
            return value
        from .tx_preparation import compile_execution
        return compile_execution(value, recipient=request['recipient'], deadline=request['deadline'],
            slippage=request.get('slippageBps', 100),
            minimum=core_sale_bounds['minimumOutput'] if core_sale_bounds else None,
            accepted_core=core_sale_bounds['expectedOutputs'] if core_sale_bounds else None)

    async def get(self, request, on_update=None, *, core_sale_bounds=None):
        from .tx_preparation import compile_execution
        legacy = UniversalExactInputRequest.model_validate(request).model_dump()
        def encode(value):
            result = compile_execution(value, recipient=legacy['recipient'], deadline=legacy['deadline'],
                slippage=legacy['slippageBps'],
                minimum=core_sale_bounds['minimumOutput'] if core_sale_bounds else None,
                accepted_core=core_sale_bounds['expectedOutputs'] if core_sale_bounds else None)
            if core_sale_bounds:
                result['searchCoverage']['coreSharesPercent'] = [100]
            return result
        async def update(frame):
            if on_update:
                await on_update({**frame, 'value': encode(frame['value'])})
        result = await self.quote(legacy, update, core_only=bool(core_sale_bounds))
        return encode(result)

    async def scalar_request(self, request, on_update=None):
        buy = request['side'] == 'buy'
        counter = ZERO if request.get('native') else request['counterToken']
        return await self.get({'intent': 0 if buy else 1,
            'inputs': [{'currency': counter if buy else self.core, 'amount': request['amount']}],
            'outputCurrency': self.core if buy else counter, 'recipient': request['recipient'],
            'deadline': request['deadline'], 'slippageBps': request.get('slippageBps', 100)}, on_update)

    async def core_sale_from_legacy(self, request, legacy, on_update=None):
        from copy import deepcopy
        from .quote_budget import budget_context, QuoteBudget
        provider = legacy['providerQuote']
        value = {'intent': 1, 'inputs': [{'currency': self.core, 'amount': provider['executionAmount']}],
            'outputCurrency': ZERO if request.get('native') else request['counterToken'],
            'recipient': request['recipient'], 'deadline': request['deadline'],
            'slippageBps': request.get('slippageBps', 100)}
        bounds = {'minimumOutput': legacy['outputMinimum'],
                  'expectedOutputs': deepcopy(provider['expectedCoreOutputs'])}
        with budget_context(QuoteBudget()):
            return await self.get(value, on_update, core_sale_bounds=bounds)


async def handle_universal_quote(request, service):
    try:
        value = UniversalExactInputRequest.model_validate(await request.json()).model_dump()
    except (ValueError, TypeError):
        return JSONResponse({'error': 'Invalid universal exact-input request.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    from .economic_quotes import observed_json, economic_intent
    return await observed_json(request, economic_intent(value), lambda: service.get(value),
        kind='quoter', source='search', phase='current-state-search')
