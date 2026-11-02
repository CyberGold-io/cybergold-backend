"""Backward exact-output planning for a partial linear exact-input path."""
from copy import deepcopy

from ..market_fee import get_market_fee_rate, quoted_fee
from ..route_work_slots import engine_work
from .discovery import market_plan, paths


async def repair_prefix(quoter, request, trace, block, *, origins=None):
    route = deepcopy(trace.route)
    partial = next((index for index, row in enumerate(trace.hops)
                    if index > 0 and row.consumed < row.funded), None)
    if partial is None:
        return None
    target = trace.hops[partial].consumed
    if target <= 0:
        return None
    for row in reversed(trace.hops[:partial]):
        if row.pre_state is None:
            return None
        pool = deepcopy(row.pre_state)
        async with engine_work(quoter.engine.semaphore):
            value = await quoter.engine.sdk.request({'operation': 'quote', 'pools': [pool],
                'poolId': pool['id'], 'mode': 'exactOut', 'amount': str(target),
                'zeroForOne': row.hop['zeroForOne']})
        # This is an amount proposal, not an SDK certification. Integer
        # overdelivery, shared-pool effects and partial fills are measured by
        # the complete Helpers execution before the proposal can be selected.
        target = int(value['amountIn'])
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
