"""Ordered exact SDK path replay with optional private reconstruction traces."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy

from ..basket_preview import InvalidPreview
from ..recovery_rpc import SnapshotChanged
from ..route_quote_engine import RouteQuoteEngine
from ..route_scheduler import raise_snapshot_disproof
from ..route_work_slots import engine_work, required_state_wait
from ..uniswap_routes import pool_identity
from ..uniswap_state import same_observed_pool
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


@asynccontextmanager
async def initial_snapshots(engine, route, block, canonical, candidate):
    """Start immutable path reads together; consume their results in hop order."""
    physical = [hop for hop in route if 'pool' in hop]
    enriched = RouteQuoteEngine.enrich_branches(engine, [{'hops': physical}])[0]['hops'] if physical else []
    pools = {id(original['pool']): resolved['pool']
             for original, resolved in zip(physical, enriched, strict=True)}

    def observed(pool):
        direct = canonical.get(pool['id'])
        return direct if direct is not None else next((state for state in canonical.values()
            if same_observed_pool(state, pool)), None)

    reads = []
    async def prepare(pool, zero_for_one):
        state = observed(pool)
        if state is None:
            state = await engine.registry.snapshot(pool, block)
        if pool['protocol'] in ('v3', 'v4'):
            try:
                word = ((int(state['tick']) // int(state['tickSpacing']))
                        + (0 if zero_for_one else 1)) >> 8
                state = await engine.registry.extend_ticks(state,
                    [{'poolId': state['id'], 'wordPositions': [word], 'ticks': []}], block)
            except SnapshotChanged:
                raise
            except Exception:
                # This first-word observation is advisory. The unchanged SDK
                # continuation still owns exact required reads and their errors.
                pass
        return state

    def merge_coverage(target, state):
        for field, key in (('bitmapWords', 'wordPosition'), ('ticks', 'index')):
            if field in state:
                rows = {int(row[key]): row for row in state[field]}
                rows.update({int(row[key]): row for row in target.get(field, [])})
                target[field] = deepcopy(list(rows.values()))

    async def acquire(pool):
        pool = pools[id(pool)]
        read = next((task for previous, task in reads if same_observed_pool(pool, previous)), None)
        if read is not None:
            async with required_state_wait():
                state = await read
            # A sibling may have filled canonical coverage while this read was
            # pending. Never replace that chosen observation with older coverage.
            if observed(pool) is None:
                canonical[pool['id']] = {**state, 'id': pool['id']}
            for bank in (canonical, candidate):
                for previous in bank.values():
                    if same_observed_pool(previous, pool):
                        # Immutable coverage can fill a repeated pool without
                        # replacing its advanced private price/tick/liquidity.
                        merge_coverage(previous, state)

    try:
        for original, resolved in zip(physical, enriched, strict=True):
            pool = resolved['pool']
            if (observed(pool) is None or pool['protocol'] in ('v3', 'v4')) and not any(
                    same_observed_pool(pool, previous) for previous, _ in reads):
                reads.append((pool, asyncio.create_task(prepare(pool, original['zeroForOne']))))
        yield acquire
    finally:
        for _, task in reads:
            if not task.done():
                task.cancel()
        outcomes = await asyncio.gather(*(task for _, task in reads), return_exceptions=True)
        raise_snapshot_disproof(outcomes)


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
    current, used, physical_index = amount, amount, 0
    async with initial_snapshots(engine, route if current else [], block, canonical, bank) as acquire:
        for index, hop in enumerate(route):
            if not current:
                break
            if 'kind' in hop:
                continue
            await acquire(hop['pool'])
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
            # Native transitions preserve raw units. The first physical pool
            # can retain source funding even when a wrap/unwrap precedes it.
            if physical_index == 0:
                used = debit
            elif debit < current:
                if trace is not None:
                    trace.consumed, trace.output = used, output
                    raise PartialPath(trace)
                raise InvalidPreview('Unsettled current-operation intermediate currency.')
            physical_index += 1
            if session is not None:
                target = hop['pool']['token1' if hop['zeroForOne'] else 'token0']['address']
                session.publish_completed(RouteQuery(source, target, amount, block),
                                          leading + route[:index+1], origins)
            current = output
    if trace is not None:
        trace.consumed, trace.output = used, current
    return used, current
