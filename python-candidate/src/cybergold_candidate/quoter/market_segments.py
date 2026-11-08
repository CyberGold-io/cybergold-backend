"""Request-local amounts for market legs whose funding is produced by Core.

The first complete Helpers execution supplies these quantities. Subsequent
exploration nominates at the observed lot; it never substitutes a router price
for complete-plan execution or adds a Core preview to quote qualification.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps


_segments = ContextVar('quoter_core_market_segments', default=None)


@contextmanager
def market_segment_scope():
    token = _segments.set({'amounts': {}, 'seen': set()})
    try:
        yield
    finally:
        _segments.reset(token)


def market_segment_entry(function):
    @wraps(function)
    async def entered(*args, **kwargs):
        with market_segment_scope():
            return await function(*args, **kwargs)
    return entered


def _key(request, share, order, operation, source, target):
    return (int(request['intent']), tuple((row['currency'].lower(), int(row['amount']))
            for row in request['inputs']), request['outputCurrency'].lower(),
            share, order, operation, source.lower(), target.lower())


def observed_market_amount(request, share, order, operation, source, target, fallback):
    state = _segments.get()
    if state is None:
        return fallback
    return state['amounts'].get(_key(request, share, order, operation, source, target), fallback)


def observed_market_revision(request, share, order):
    """Construction-cache input only; unchanged measured lots share one entry."""
    state = _segments.get()
    if state is None:
        return ()
    slot = _key(request, share, order, '', '', '')[:5]
    return tuple(sorted((*key[5:], amount) for key, amount in state['amounts'].items()
                        if key[:5] == slot))


def observe_market_segments(value, request, share, order):
    """Record Core-produced lots; request detailed ranking for each first observation.

    A repeated observation, including a return to a previously observed lot,
    does not restart the same amount-sensitive provider cohort. Its feed stays
    available through the existing Bootstrap query identity and arrival passes.
    """
    state = _segments.get()
    if state is None:
        return False
    changed = False
    for observation in value.get('conversionObservations', ()):
        operation = observation['operation']
        if ':residual:' not in operation and ':redeem:' not in operation:
            continue
        chosen = value['plan']['conversions'][operation]
        key = _key(request, share, order, operation, chosen['inputCurrency'], chosen['outputCurrency'])
        amount = int(observation['fundedInput'])
        state['amounts'][key] = amount
        query = key, amount
        if query not in state['seen']:
            state['seen'].add(query)
            # Even an actual one-unit lot receives one detailed ranking pass;
            # its first topology-only proposal did not compare alternatives.
            changed = True
    return changed
