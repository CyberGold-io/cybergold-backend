"""Paid local observations improve stalled minimum-output inversion."""


def delayed_local_step(points, target, proportional):
    """Preserve the first three ordinary checks; every proposal is checked again.

    No midpoint premium, calibration reads or extra solver evaluations. Integer
    basket steps can defeat average output/input rates. A paid marginal slope
    accounts for locally constant contributions, without certifying a bound.
    """
    if len(points) < 3:
        return proportional
    gross, quoted = points[-1]
    if quoted <= 0:
        return proportional
    candidate = -(-(gross * target) // quoted)
    previous = next(((g, q) for g, q in reversed(points[:-1])
                     if g != gross and q != quoted and (g-gross)*(q-quoted) > 0), None)
    if previous:
        previous_g, previous_q = previous
        dg, dq = gross-previous_g, quoted-previous_q
        if dq < 0:
            dg, dq = -dg, -dq
        candidate = gross - (-((target-quoted)*dg) // dq)
    pairs = [(low_g, high_g) for low_g, low_q in points for high_g, high_q in points
             if low_q < target < high_q and low_g+1 < high_g]
    if pairs:
        low, high = min(pairs, key=lambda pair: pair[1]-pair[0])
        candidate = max(low+1, min(high-1, candidate))
    # Retain the ordinary ABI domain; extrapolation can exceed a realizable gross.
    return candidate if 0 < candidate < 2**256 and candidate != gross else proportional
