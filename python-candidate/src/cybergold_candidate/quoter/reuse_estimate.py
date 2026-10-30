"""Approximate nearby-amount hints from completed observations only.

Nothing in this module reads a chain, simulates a swap or qualifies execution.
The exact Quoter independently replays the saved physical routes.
"""
from copy import deepcopy

from ..market_fee import get_market_fee_rate, quoted_fee
from ..routing_encoding import ZERO
from ..route_search import WETH


FEE_NAMES = ('coreProtocolFeeCygld', 'coreHelpersFeeCygld', 'marketFeeCygld')


def scalar_request(request):
    return int(request['intent']) in (0, 1) and len(request['inputs']) == 1


def sample_for_quote(quote):
    """Normalize cached accounting without requiring exact legacy precision."""
    try:
        request = quote['request']
        if not scalar_request(request):
            return None
        source = request['inputs'][0]['currency'].lower()
        funding = quote['inputs'][0]
        if funding['currency'].lower() != source:
            return None
        funded, output = int(funding['amount']), int(quote['quotedOutput'])
        fees = {name: int(quote.get('fees', {}).get(name, '0')) for name in FEE_NAMES}
        reference, basis = funded, 'funded-input-approximation'
        retained = quote.get('estimatedRetainedInputCharges')
        # WETH is a source unit only when this selected conversion explicitly
        # wraps native input. Never convert an intermediate remainder by price.
        conversions = quote.get('plan', {}).get('conversions', {}) or {}
        wrapped_source = source == ZERO and any(
            isinstance(row, dict) and row.get('inputCurrency', '').lower() == ZERO
            and row.get('template', {}).get('inputCurrency', '').lower() == WETH.lower()
            for row in conversions.values())
        source_units = {source, WETH.lower()} if wrapped_source else {source}
        if retained is not None:
            # The evaluator already aggregates each conversion's retained lot.
            # Branch/stage rows refer to distinct external source lots; do not
            # sum all conversion consumption across the plan's other currencies.
            try:
                remainder = sum(int(row['amount']) for row in retained
                                if row['currency'].lower() in source_units)
                observed = funded - remainder
                if observed >= 0:
                    reference, basis = observed, 'observed-nonretained'
            except (KeyError, TypeError, ValueError, AttributeError):
                # Partial legacy accounting leaves the positive funded-input
                # approximation useful; precision is not an eligibility rule.
                pass
        if int(request['intent']) == 1 and quote.get('routeFamily') == 'market':
            observation = next((row for row in quote.get('conversionObservations', [])
                if isinstance(row, dict) and row.get('operation') == '0:market'
                and row.get('inputCurrency', '').lower() in source_units), None)
            if observation is not None:
                try:
                    consumed = int(observation['consumedInput'])
                    rate = get_market_fee_rate(quote['context']['chainId'], source,
                                              request['outputCurrency'], 'exact-in')
                    fee = quoted_fee(consumed, rate)
                    reference, basis = consumed + fee, 'market-sale-consumed'
                    fees['marketFeeCygld'] = fee
                except (KeyError, TypeError, ValueError):
                    # Retain the cached observed/funding approximation when a
                    # legacy observation lacks the optional sale fee detail.
                    pass
        if reference <= 0 or output < 0 or any(value < 0 for value in fees.values()):
            return None
        return {'referenceInput': str(reference), 'netOutput': str(output),
                'fees': {name: str(value) for name, value in fees.items()}, 'basis': basis}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def attach_reuse_sample(quote):
    """Own response metadata; never change the saved plan or economic terms."""
    value = deepcopy(quote)
    sample = sample_for_quote(value)
    if sample is not None:
        value['reuseSample'] = sample
    else:
        value.pop('reuseSample', None)
    return value


def arithmetic_estimate(sample, budget):
    """Clamp this candidate at its observed reference; fees are a breakdown."""
    try:
        reference, amount = int(sample['referenceInput']), int(budget)
        if reference <= 0 or amount < 0:
            return None
        used = min(amount, reference)
        return {'strategy': 'universal', 'source': 'cached-upper',
            'amount': str(int(sample['netOutput']) * used // reference),
            'referenceInput': str(used), 'basis': sample['basis'],
            'fees': {name: str(int(sample['fees'][name]) * used // reference) for name in FEE_NAMES}}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


class CachedEconomicEstimates:
    """DB-only scope/neighbor lookup followed by simple integer arithmetic."""
    def __init__(self, store, core, *, observe_scope=None):
        self.store, self.core, self.observe_scope = store, core, observe_scope

    async def get_model(self, request):
        packet = {'namespace': 'trade', 'intent': deepcopy(request), 'models': []}
        try:
            if self.observe_scope is not None:
                await self.observe_scope()
            counter = ZERO if request.get('native') else request['counterToken']
            buy = request['side'] == 'buy'
            economic = {'intent': 0 if buy else 1,
                'inputs': [{'currency': counter if buy else self.core, 'amount': request['amount']}],
                'outputCurrency': self.core if buy else counter}
            scope = self.store.capture_scope(economic)
            neighbors = await self.store.neighbors(economic, scope=scope)
            upper = neighbors.get('upper')
            if upper is not None:
                quote = upper['quote']
                sample = sample_for_quote(quote)
                estimate = arithmetic_estimate(sample, request['amount']) if sample else None
                if estimate is not None:
                    packet['estimate'] = {**estimate, 'context': deepcopy(quote['context'])}
                    if upper.get('identity') is not None:
                        packet['estimate']['sourceIdentity'] = upper['identity']
                    if quote.get('request', {}).get('inputs'):
                        packet['estimate']['sourceRequestedInput'] = quote['request']['inputs'][0]['amount']
        except Exception:
            # Optional SQL/accounting failure is an empty hint, not permission
            # to hydrate inventory/models, read a head or call RPC/SDK.
            pass
        return packet
