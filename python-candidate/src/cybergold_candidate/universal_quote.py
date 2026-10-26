"""Compatibility adapter for the existing universal exact-input HTTP contract.

The production component is quoter.Quoter. Keep this import/route adapter while
existing consumers migrate; both names reference the same implementation.
"""
from fastapi.responses import JSONResponse

from .basket_preview import InvalidPreview
from .exact_input_plan import UniversalExactInputRequest
from .quote_errors import public_quote_error
from .quoter import Quoter
from .quoter.search import CORE_SHARES, PAXG, identity_template, paths, route_candidates
from .routing_encoding import ZERO

UniversalQuotes = Quoter


async def handle_universal_quote(request, service):
    try:
        value = UniversalExactInputRequest.model_validate(await request.json()).model_dump()
    except (ValueError, TypeError):
        return JSONResponse({'error': 'Invalid universal exact-input request.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    try:
        result = await service.get(value)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except InvalidPreview as error:
        return JSONResponse({'error': str(error)}, status_code=400, headers={'Cache-Control': 'no-store'})
    except Exception as error:
        return JSONResponse(public_quote_error(error), status_code=503, headers={'Cache-Control': 'no-store'})
