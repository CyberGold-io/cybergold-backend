"""Ordered exact SDK path replay with optional private reconstruction traces."""
from copy import deepcopy

from ..basket_preview import InvalidPreview
from ..route_work_slots import engine_work
from ..uniswap_routes import pool_identity
from .contracts import HopTrace, new_path_trace, current_nomination
from .bootstrap import current_bootstrap
from .route_tools import RouteQuery
from .discovery import paths


class PartialPath(InvalidPreview):
    def __init__(self, trace):
        super().__init__('Unsettled current-operation intermediate currency.')
        self.trace = trace


def pool_state(bank, pool):
    identity = pool_identity(pool)
    return next((state for state in bank.values()
                 if state.get('protocol') and pool_identity(state) == identity), None)


async def price_path(engine, route, amount, block, bank, canonical):
    trace = new_path_trace(route, amount)
    session = current_bootstrap()
    source, origins = None, ()
    leading = []
    if session is not None:
        source, origins = current_nomination()
        physical = next((hop for hop in route if 'pool' in hop), None)
        if physical is not None:
            physical_source = physical['pool']['token0' if physical['zeroForOne'] else 'token1']['address']
            source = source or physical_source
            # Helpers may own a leading native transition stripped before
            # physical replay. Retain it through the same path producer.
            native = paths([], source, physical_source)
            leading = native[0] if native and 'pool' in route[0] else []
    current, used = amount, amount
    for index, hop in enumerate(route):
        if not current:
            break
        if 'kind' in hop:
            continue
        before = deepcopy(pool_state(bank, hop['pool'])) if trace is not None else None
        async with engine_work(engine.semaphore):
            value = await engine.quote_sdk_branches([{'amountIn': str(current), 'hops': [hop]}],
                'exactIn', current, block, candidate=bank, canonical=canonical)
        debit, output = int(value['amountIn']), int(value['amountOut'])
        if trace is not None:
            # The SDK engine fills canonical observations before simulation.
            # Prefer a preceding operation's actual private state when present.
            observed = pool_state(canonical, hop['pool'])
            if before is None:
                before = deepcopy(observed)
            elif observed is not None:
                # Missing-state continuation may have filled more immutable
                # coverage during this hop. Keep private pre-swap scalars.
                for field in ('ticks', 'bitmapWords'):
                    if field in observed:
                        before[field] = deepcopy(observed[field])
            trace.hops.append(HopTrace(deepcopy(hop), current, debit, output, before))
        if index == 0:
            used = debit
        elif debit < current:
            if trace is not None:
                trace.consumed, trace.output = used, output
                raise PartialPath(trace)
            raise InvalidPreview('Unsettled current-operation intermediate currency.')
        if session is not None:
            target = hop['pool']['token1' if hop['zeroForOne'] else 'token0']['address']
            session.publish_completed(RouteQuery(source, target, amount, block),
                                      leading + route[:index+1], origins)
        current = output
    if trace is not None:
        trace.consumed, trace.output = used, current
    return used, current
