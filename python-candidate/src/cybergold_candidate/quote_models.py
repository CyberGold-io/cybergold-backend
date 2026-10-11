"""Display-only factorized route models; rational raw units, no RPC probes.

The marginal pool rate and fee remain independent observations. The free fit
is explicitly an effective-rate fallback, never a measured exchange rate.
"""
from dataclasses import dataclass
from fractions import Fraction as F


def rounded(value, inverse=False):
    if value <= 0:
        return None
    return ((value.numerator + value.denominator - 1) // value.denominator
            if inverse else value.numerator // value.denominator)


@dataclass(frozen=True)
class PoolBaseline:
    exchange: F
    fee_retention: F
    local_impact: F | None = None

    @classmethod
    def v3(cls, sqrt_price, liquidity, fee, zero_for_one):
        root = F(sqrt_price, 2**96)
        rate = root**2 if zero_for_one else 1/root**2
        impact = (root/F(liquidity) if zero_for_one else 1/(F(liquidity)*root)) if liquidity else None
        return cls(rate, F(1_000_000-fee, 1_000_000), impact)


class LegModel:
    def __init__(self, points=(), baseline=None):
        self.points = sorted(dict(points).items())
        self.baseline = baseline
        self.residuals = []
        self.retired = 0

    def predict(self, amount, method='larger', inverse=False):
        x = int(amount)
        if x <= 0:
            return None
        points = [(b, a) for a, b in self.points] if inverse else self.points
        if method in ('larger', 'nearest'):
            eligible = [p for p in points if p[0] >= x] if method == 'larger' else points
            if not eligible:
                return None
            a, b = min(eligible, key=lambda p: p[0] if method == 'larger' else abs(p[0]-x))
            return rounded(F(x*b, a), inverse)
        if method == 'linear':
            below = max((p for p in points if p[0] <= x), default=None)
            above = min((p for p in points if p[0] >= x), default=None)
            if not below or not above:
                return self.predict(x, 'larger', inverse)
            value = F(below[1]) if below[0] == above[0] else below[1] + F((x-below[0])*(above[1]-below[1]), above[0]-below[0])
            return rounded(value, inverse)
        if method == 'free':
            if len(self.points) < 2:
                return self.predict(x, 'larger', inverse)
            axis = 1 if inverse else 0
            a, b = min(zip(self.points, self.points[1:]), key=lambda pair: abs(pair[0][axis]-x) + abs(pair[1][axis]-x))
            beta = (F(b[0], b[1])-F(a[0], a[1]))/(b[0]-a[0])
            alpha = F(a[0], a[1])-beta*a[0]
            if beta < 0 or alpha <= 0:
                return self.predict(x, 'linear', inverse)
            denominator = 1-beta*x if inverse else alpha+beta*x
            return rounded(F(alpha*x if inverse else x, denominator), inverse) if denominator > 0 else None
        if not self.baseline:
            return None
        baseline = self.baseline
        if method == 'local':
            impact = baseline.local_impact
        else:
            candidates = [(abs((b if inverse else a)-x), (baseline.exchange*baseline.fee_retention*a/b-1)/(baseline.fee_retention*a))
                          for a, b in self.points if a > 0 and b > 0]
            impact = min(candidates)[1] if candidates else None
        if impact is None or impact < 0:
            return None
        # Q(x) = R*f*x/(1+k*f*x), with explicit rate, fee and size effect.
        denominator = baseline.fee_retention*(baseline.exchange-impact*x) if inverse else 1+impact*baseline.fee_retention*x
        if denominator <= 0:
            return None
        value = F(x, denominator) if inverse else baseline.exchange*baseline.fee_retention*x/denominator
        return rounded(value, inverse)

    def observe(self, amount_in, amount_out, method='larger'):
        if amount_in <= 0 or amount_out <= 0:
            return
        prediction = self.predict(amount_in, method)
        if prediction is not None:
            self.residuals.append(F(amount_out-prediction, amount_out))
            self.residuals[:] = self.residuals[-64:]
        if not self.baseline:
            # An unanchored combined-rate predictor is also retired when its
            # actually observed lower-size rate contradicts the larger point.
            # This does not relabel the difference as separately measured impact.
            retained = [(a, b) for a, b in self.points
                        if not (a >= amount_in and amount_in*b//a > amount_out)]
            self.retired += len(self.points)-len(retained)
            self.points = retained
        if self.baseline:
            # Owner's contradiction rule concerns impact at an observed size.
            # R/f are held fixed; a disproven point is retired, not a route.
            retained = [(a, b) for a, b in self.points
                        if not (a >= amount_in and amount_in*b//a > amount_out)]
            self.retired += len(self.points)-len(retained)
            self.points = retained
        self.points = sorted({**dict(self.points),amount_in:amount_out}.items())[-32:]

    def residual_range(self, prediction):
        if not self.residuals:
            return None
        return (rounded(prediction/(1-min(self.residuals))), rounded(prediction/(1-max(self.residuals)), True))

    def rebased(self, baseline):
        """N9f: retain historical impact as an assumption, replacing measured R/f.

        This creates provisional points, not new observations. It cannot account
        for changed active liquidity/ticks without subsequent exact results.
        """
        if not self.baseline:
            return LegModel([], baseline)
        old = self.baseline
        points = []
        for x, y in self.points:
            impact = (old.exchange*old.fee_retention*x/y-1)/(old.fee_retention*x)
            if impact < 0:
                continue
            amount = rounded(baseline.exchange*baseline.fee_retention*x/(1+impact*baseline.fee_retention*x))
            if amount:
                points.append((x,amount))
        return LegModel(points,baseline)


def hybrid_legs(amounts, models, actual, method='anchored'):
    """N9g route components only; caller still needs genuine Basket/fee math."""
    return [actual.get(i) if i in actual else model.predict(amount,method)
            for i,(amount,model) in enumerate(zip(amounts,models,strict=True))]
