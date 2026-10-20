"""Fast display estimates, separate from fresh route qualification and execution.

Heuristics consume Backend observations only. A budget range reuses a selected
complete quote's economics; it carries no executable plan and makes no claim
that pool/capacity state is still current. Ordinary providers keep validating
state and choosing the actual execution independently.
"""
from collections import OrderedDict
from copy import deepcopy
from fractions import Fraction

from .basket_arithmetic import BasketArithmetic
from .execution_tolerance import floor, ceil
from .quote_models import LegModel, PoolBaseline


def model_estimate(packet, request):
    """Existing factorized Core/Helpers display arithmetic, without chain reads."""
    if not packet.get('protocol'):
        return None
    try:
        source = packet['protocol']['state']
        state = {name: [int(v) for v in value] if name in ('weights', 'conversions', 'available', 'recoveryShares', 'recoveryValues')
                 else int(value) if name in ('issueFee', 'helperFee', 'redeemFee', 'supply', 'maxSupply', 'effectiveCap') else value
                 for name, value in source.items()}
        basket = BasketArithmetic(state)
        counter = request['counterToken'].lower()
        def predict(asset, amount, *, inverse=False, buy=False):
            if asset.lower() == counter:
                return amount
            values = []
            for row in packet['routes']:
                pair = (counter, asset.lower()) if buy else (asset.lower(), counter)
                if (row['tokens'][0].lower(), row['tokens'][-1].lower()) != pair:
                    continue
                def f(value):
                    return Fraction(int(value['numerator']), int(value['denominator']))
                baseline = PoolBaseline(f(row['exchangeRate']), f(row['feeRetention']),
                    f(row['localImpact']) if row.get('localImpact') else None) if row.get('exchangeRate') else None
                model = LegModel([(int(p['input']), int(p['output'])) for p in row['points']], baseline)
                value = model.predict(amount, 'anchored' if model.points and baseline else 'local' if baseline else 'larger', inverse)
                if value is not None:
                    values.append(value)
            if not values:
                raise ValueError('Indicative route unavailable')
            return min(values) if inverse else max(values)
        amount = int(request['amount'])
        if request['side'] == 'buy':
            if request['mode'] == 'exact-out':
                result = basket.issue(amount, includes_helper=True)
                return str(sum(predict(asset, int(value), inverse=True, buy=True)
                    for asset, value in zip(state['assets'], result['amountsInExact'], strict=True) if value))
            budgets = {row['outputAsset'].lower(): int(row['amount']) for row in packet['intent']['targets']}
            # Direct input was omitted from swap targets by the seed builder.
            used = sum(budgets.values())
            reserve = [amount-used if asset.lower() == counter else predict(asset, budgets.get(asset.lower(), 0), buy=True)
                       if budgets.get(asset.lower(), 0) else 0 for asset in state['assets']]
            return str(basket.issue_in(reserve)['netCygldOut'])
        def output(gross, *, protected=False):
            projected = basket.redeem_in(gross)['projectedCoreOutputs']
            values = []
            for row in projected:
                if row['kind'] != 0 or not int(row['amount']):
                    continue
                value = predict(row['token'], int(row['amount']))
                if protected and row['token'].lower() != counter:
                    value = floor(value, request['slippageBps'])
                values.append(value)
            return sum(values)
        if request['mode'] == 'exact-in':
            return str(output(amount))
        seed = basket.redeem_out([int(next((t['amount'] for t in packet['intent']['targets']
                         if t['inputAsset'].lower() == asset.lower()), '0')) for asset in state['assets']]
            + [0]*len(state['recoveryShares']))['grossCygldIn']
        for _ in range(11):
            received = output(seed, protected=True)
            if amount <= received <= ceil(amount, request['slippageBps']):
                return str(seed)
            if received <= 0:
                return None
            next_seed = seed*amount//received
            seed = next_seed if next_seed != seed else seed+(1 if received < amount else -1)
    except (ValueError, KeyError, ZeroDivisionError):
        pass
    return None


def model_family(request):
    """Amount-independent identity of the already resolved trading intent."""
    return (request['side'], request['mode'], request['counterToken'].lower(),
            bool(request['native']), request['slippageBps'],
            (request.get('adapter') or '').lower())


class FastTradeEstimates:
    """Own display heuristics and the selection between their indicative results."""
    def __init__(self, limit=256):
        self.limit, self.ranges = limit, OrderedDict()
        self.scope = None

    def observe_scope(self, scope):
        # Reuse the service's existing deployment/fork boundaries, without
        # adding any age or liveness requirement to advisory observations.
        if self.scope != scope:
            self.ranges.clear()
            self.scope = scope

    def remember_selected(self, request, selected, *, scope):
        """Observe only the coordinator's selected, complete qualified tuple."""
        self.observe_scope(scope)
        family = model_family(request)
        budget, maximum = int(request['amount']), int(selected['inputMaximum'])
        # Core can spend less after basket rounding or a better execution
        # route without reaching the issuance limit. Its existing unclipped
        # request/capacity observations distinguish that from a true plateau.
        core = selected.get('providerQuote', {})
        core_capacity_reached = (core.get('requestedGrossCygldOut') is not None
            and core.get('remainingGrossCapacity') is not None
            and int(core['requestedGrossCygldOut']) >= int(core['remainingGrossCapacity']))
        if (request['mode'] != 'exact-in' or maximum >= budget
                or (request['side'] == 'buy' and selected['strategy'] == 'core' and not core_capacity_reached)):
            self.ranges.pop(family, None)
            return
        # An already capacity-limited purchase reaches the same observed
        # output with any sufficient larger budget. This is a display hint,
        # not a promise that liquidity/capacity remains current. Preserve the
        # previously bounded heuristic for other partial exact-in operations.
        upper_bound = {} if request['side'] == 'buy' else {'maximumBudget': str(budget)}
        self.ranges[family] = {
            'strategy': selected['strategy'],
            'range': {'minimumBudget': str(maximum), **upper_bound,
                      'quotedInput': selected['quotedInput'], 'quotedOutput': selected['quotedOutput']}}
        self.ranges.move_to_end(family)
        while len(self.ranges) > self.limit:
            self.ranges.popitem(last=False)

    def invalidate(self, request, *, scope):
        self.observe_scope(scope)
        self.ranges.pop(model_family(request), None)

    def packet(self, request, provider_estimates, *, scope):
        """Return the current family snapshot and a Backend-selected estimate.

        The range is useful to clients even outside this request's amount.
        Its bounds only govern display reuse, never permission to execute.
        """
        self.observe_scope(scope)
        result = {}
        selected = self.ranges.get(model_family(request))
        if selected is not None:
            self.ranges.move_to_end(model_family(request))
            value = selected['range']
            result['budgetRange'] = deepcopy(value)
            if (int(value['minimumBudget']) <= int(request['amount'])
                    and ('maximumBudget' not in value or int(request['amount']) <= int(value['maximumBudget']))):
                result['estimate'] = {'strategy': selected['strategy'], 'amount': value['quotedOutput']}
                return result
        if provider_estimates:
            strategy, amount = max(provider_estimates,
                key=lambda row: (int(row[1]) if request['mode'] == 'exact-in' else -int(row[1]), row[0] == 'core'))
            result['estimate'] = {'strategy': strategy, 'amount': amount}
        return result
