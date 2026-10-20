"""Find a fully funded exact-input route using the existing SDK as oracle.

All arithmetic here is integer budget selection. AMM fees, ticks, shared-pool
replay and settlement remain owned by the SDK quote supplied by the caller.
"""
from .sdk_worker import SdkInputTooSmall


_BELOW_MINIMUM = object()


async def maximum_filled_input(budget, initial, probe, *, cached=None):
    """Return a verified fill boundary below an already-unfillable budget."""
    async def observe(amount):
        try:
            return await probe(amount)
        except SdkInputTooSmall:
            # Integer AMM output can round to zero below a route's minimum.
            # That moves the search upward; it does not establish exhaustion.
            return _BELOW_MINIMUM

    if cached is not None and 0 < cached < budget:
        value = await observe(cached)
        if value is not None and value is not _BELOW_MINIMUM:
            return cached, value
    lower, upper = 0, budget
    best_amount, best = 0, None
    spent = int(initial['amountIn'])
    if 0 < spent < upper:
        value = await observe(spent)
        if value is None:
            upper = spent
        else:
            lower = spent
            if value is not _BELOW_MINIMUM:
                best_amount, best = lower, value
            # Confirm the next raw unit instead of assuming rounded SDK spend
            # is the greatest fully consumable funding amount.
            if lower+1 < upper:
                next_value = await observe(lower+1)
                if next_value is None:
                    upper = lower+1
                else:
                    lower += 1
                    if next_value is not _BELOW_MINIMUM:
                        best_amount, best = lower, next_value
    while upper-lower > 1:
        middle = (lower+upper)//2
        value = await observe(middle)
        if value is None:
            upper = middle
        else:
            lower = middle
            if value is not _BELOW_MINIMUM:
                best_amount, best = lower, value
    return best_amount, best
