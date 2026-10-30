"""Backward exact-output planning for a partial linear exact-input path."""
from copy import deepcopy

from ..market_fee import get_market_fee_rate, quoted_fee
from ..route_work_slots import engine_work
from ..routing_encoding import ZERO
from ..uniswap_routes import pool_identity
from .discovery import market_plan


async def repair_prefix(quoter, request, trace, block):
    route = trace.route
    # Leading Helpers wrapping has already been removed from physical traces.
    # This constructor does not rebuild that separate native funding stage.
    if (request['inputs'][0]['currency'].lower() == ZERO or
            request['outputCurrency'].lower() == ZERO):
        return None
    if not route or any('pool' not in hop or (hop['pool'].get('hooks') or ZERO).lower() != ZERO for hop in route):
        return None
    identities = [pool_identity(hop['pool']) for hop in route]
    if len(set(identities)) != len(identities):
        return None
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
        if not value['fullyFilled'] or int(value['amountOut']) != target:
            return None
        target = int(value['amountIn'])
    source, output = request['inputs'][0]['currency'], request['outputCurrency']
    if request['intent'] == 1:
        target += quoted_fee(target, get_market_fee_rate(quoter.engine.registry.chain, source, output, 'exact-in'))
    if not 0 < target < int(request['inputs'][0]['amount']):
        return None
    return [{**request['inputs'][0], 'amount': str(target)}], market_plan(source, output, route, target)
