"""Inactive R2 upper-quote component prototype; every proposal is exact-checked.

Runtime does not construct this object. No midpoint or tolerance change. Model
calibration uses paid per-leg minimums, with pool fees and execution margin
kept explicit; missing state/path information uses the shipped local step.
"""
from fractions import Fraction

from cybergold_candidate.basket_arithmetic import BasketArithmetic
from cybergold_candidate.quote_correction import delayed_local_step
from cybergold_candidate.quote_models import LegModel, PoolBaseline


class ComponentCorrection:
    def __init__(self, state, quote_token, decode_path, baselines=None, *, use_upper_rate=False):
        self.basket = BasketArithmetic(state)
        self.quote_token = quote_token.lower()
        self.decode_path = decode_path
        self.baselines = baselines or {}
        self.models, self.selected = {}, {}
        self.proposals, self.fallbacks = [], 0
        self.use_upper_rate = use_upper_rate

    def observe_result(self, result):
        for leg in result['quotes']:
            path = self.decode_path(leg['data'])
            model = self.models.get(path)
            if model is None:
                base = self.baselines.get(path)
                # Model output is the adapter minimum, so execution margin is
                # distinct from the actual pool fee in the source baseline.
                minimum_base = PoolBaseline(base.exchange, base.fee_retention*Fraction(99,100)) if base else None
                model = self.models[path] = LegModel(baseline=minimum_base)
            model.observe(int(leg['inputAmount']), int(leg['minimumAmountOut']))
            self.selected[leg['inputAsset'].lower()] = path

    def predict(self, gross):
        try:
            outputs = self.basket.redeem_in(gross)['projectedCoreOutputs']
        except ValueError:
            return None
        total = 0
        for item in outputs:
            raw = item['amount']
            if item['kind'] != 0 or raw == 0:
                continue
            if item['token'].lower() == self.quote_token:
                total += raw
                continue
            path = self.selected.get(item['token'].lower())
            model = self.models.get(path)
            if model is None:
                return None
            method = 'larger' if self.use_upper_rate else 'anchored' if model.baseline else 'nearest'
            value = model.predict(raw, method)
            if value is None:
                return None
            total += value
        return total

    def __call__(self, points, target, proportional):
        if len(points) < 3:
            return proportional
        upper = min((gross for gross, output in points if output >= target), default=None)
        # A larger observed leg's effective minimum/input rate is used only as
        # a local size-impact assumption. One raw output unit per swapped leg
        # accounts for nested Quoter/adapter floor rounding in the controlled
        # model; this is not a percentage premium or an execution guarantee.
        # The next ordinary exact preview still checks the original interval.
        desired = target + len(self.selected) if self.use_upper_rate else target
        if upper is not None:
            predicted = self.predict(upper)
            if predicted is not None and predicted >= desired:
                low, high = 1, upper
                while low < high:
                    middle = (low+high)//2
                    value = self.predict(middle)
                    if value is None:
                        break
                    if value >= desired: high = middle
                    else: low = middle+1
                else:
                    if low != points[-1][0]:
                        self.proposals.append({'gross':str(low),'predictedMinimum':str(self.predict(low))})
                        return low
        self.fallbacks += 1
        return delayed_local_step(points,target,proportional)
