"""Held evaluation variants; production uses only quote_cache's qualified parts."""
from collections import OrderedDict

from .quote_cache import BasketMath, GrossSeeds, IntentSharing, SharingQuoterRpc

def bracket_step(points, target, proportional):
    """H2: interpolate actual verified outputs inside a current inversion bracket."""
    below = max((p for p in points if p[1] < target), key=lambda p: p[1], default=None)
    above = min((p for p in points if p[1] > target), key=lambda p: p[1], default=None)
    if below and above and below[0] < above[0]-1:
        raw = below[0] + (target-below[1])*(above[0]-below[0])//(above[1]-below[1])
        return max(below[0]+1, min(above[0]-1, raw))
    return proportional


def midpoint_step(points, target, proportional):
    """H3: aim within the existing 1% output interval, avoiding its rounding edge.

    This can consume more gross CYGLD for a little more output. Benchmarks must
    report both differences, rather than calling this an identical-price win.
    """
    gross, quoted = points[-1]
    upper = (target*10100+9999)//10000
    next_gross = gross*((target+upper)//2)//quoted
    return next_gross if next_gross != gross else proportional


class RecentGroups:
    """N10a: swap recent winners into existing small groups; preserve coverage."""
    def __init__(self):
        self.winners = OrderedDict()

    def key(self, request):
        return (request['mode'], tuple((t['inputAsset'].lower(), t['outputAsset'].lower()) for t in request['targets']))

    def observe(self, request, results):
        key = self.key(request)
        self.winners[key] = [r['best']['path'] if r['best'] else None for r in results]
        self.winners.move_to_end(key)
        while len(self.winners) > 256:
            self.winners.popitem(last=False)

    def groups(self, request, plans, groups):
        preferred = self.winners.get(self.key(request), [])
        desired = [r['callIndex'] for plan, path in zip(plans, preferred) for r in plan if r['path'] == path]
        flat = list(dict.fromkeys(desired)) + [index for group in groups for index in group if index not in desired]
        # An absent/zero-liquidity winner is not in the selected groups.
        selected = {index for group in groups for index in group}
        flat = [index for index in flat if index in selected]
        result, offset = [], 0
        for group in groups:
            result.append(flat[offset:offset+len(group)])
            offset += len(group)
        return result


def ceil_div(a, b):
    return -(-a // b)


def ceil_scale_step(points, target, proportional):
    """Directional integer rounding at the existing proportional root."""
    gross, quoted = points[-1]
    if quoted <= 0:
        return proportional
    candidate = ceil_div(gross * target, quoted)
    return candidate if candidate != gross else proportional


def upper_secant_step(points, target, proportional):
    """Use paid verified bracket, otherwise the last increasing observed slope.

    With a lower/upper bracket, interpolate toward target and round gross upward.
    Without an upper, use a paid marginal slope rather than q/g average slope.
    Nonincreasing/degenerate observations simply retain integer proportional.
    Integer floor plateaus/route changes can invalidate the predicted upper;
    every proposed gross is still checked by the existing exact forward path.
    """
    gross, quoted = points[-1]
    if quoted <= 0:
        return proportional
    candidate = ceil_scale_step(points, target, proportional)
    below = [(g, q) for g, q in points if q < target]
    above = [(g, q) for g, q in points if q > target]
    pairs = [(low, high) for low in below for high in above
             if low[0] + 1 < high[0] and low[1] < high[1]]
    if pairs:
        (low_g, low_q), (high_g, high_q) = min(pairs, key=lambda p: p[1][0] - p[0][0])
        candidate = low_g + ceil_div((target-low_q) * (high_g-low_g), high_q-low_q)
        candidate = max(low_g+1, min(high_g-1, candidate))
    else:
        # The nearest earlier distinct output gives a local slope and already
        # includes the Core/Helpers fees and adapter minima actually observed.
        previous = next(((g, q) for g, q in reversed(points[:-1])
                         if g != gross and q != quoted and (g-gross)*(q-quoted) > 0), None)
        if previous:
            previous_g, previous_q = previous
            dg, dq = gross-previous_g, quoted-previous_q
            if dq < 0:
                dg, dq = -dg, -dq
            candidate = gross + ceil_div((target-quoted)*dg, dq)
    return candidate if candidate > 0 and candidate != gross else proportional


def local_secant_step(points, target, proportional):
    """Prefer last paid local slope; cap a proposal inside any paid bracket.

    Local means consecutive distinct integer outputs, not proof of stable pool,
    fee, or Basket quantum behavior. A retained upper is a tested proposal bound;
    the new interpolated point still requires ordinary exact forward validation.
    """
    gross, quoted = points[-1]
    candidate = ceil_scale_step(points, target, proportional)
    previous = next(((g, q) for g, q in reversed(points[:-1])
                     if g != gross and q != quoted and (g-gross)*(q-quoted) > 0), None)
    if previous:
        previous_g, previous_q = previous
        dg, dq = gross-previous_g, quoted-previous_q
        if dq < 0:
            dg, dq = -dg, -dq
        candidate = gross + ceil_div((target-quoted)*dg, dq)
    # Restrict candidate arithmetic only where the paid points actually bracket
    # it. This is not permission to return an unchecked plan.
    pairs = [(low_g, high_g) for low_g, low_q in points for high_g, high_q in points
             if low_q < target < high_q and low_g+1 < high_g]
    if pairs:
        low, high = min(pairs, key=lambda pair: pair[1]-pair[0])
        candidate = max(low+1, min(high-1, candidate))
    return candidate if candidate > 0 and candidate != gross else proportional
