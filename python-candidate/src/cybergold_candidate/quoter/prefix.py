"""Backward exact-output planning for a partial linear exact-input path."""
from copy import deepcopy

from ..market_fee import get_market_fee_rate, quoted_fee
from .discovery import market_plan, paths
from .inverse import inverse_hops


async def backward_input(quoter, trace):
    """Propose source funding from the existing measured partial-hop trace.

    Each inverse observes that occurrence's private pre-swap pool state. The
    result is a nomination; a complete forward execution still owns validity.
    """
    partial = next((index for index, row in enumerate(trace.hops)
                    if index > 0 and row.consumed < row.funded), None)
    if partial is None:
        return None
    target = trace.hops[partial].consumed
    if target <= 0:
        return None
    hops = trace.hops[:partial]
    if any(row.pre_state is None for row in hops):
        return None
    return await inverse_hops(quoter, hops, target)


async def repair_prefix(quoter, request, trace, block, *, origins=None):
    target = await backward_input(quoter, trace)
    if target is None:
        return None
    route = deepcopy(trace.route)
    source, output = request['inputs'][0]['currency'], request['outputCurrency']
    if request['intent'] == 1:
        target += quoted_fee(target, get_market_fee_rate(quoter.engine.registry.chain, source, output, 'exact-in'))
    if not 0 < target < int(request['inputs'][0]['amount']):
        return None
    physical = next((hop for hop in route if 'pool' in hop), None)
    if physical is not None and route and 'pool' in route[0]:
        physical_source = physical['pool']['token0' if physical['zeroForOne'] else 'token1']['address']
        leading = paths([], source, physical_source)
        if leading:
            route = leading[0] + route
    return [{**request['inputs'][0], 'amount': str(target)}], market_plan(source, output, route, target, origins=origins)
