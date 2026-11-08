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


def input_limit_observed(quote):
    """Historical limitation of this route/funding, never a capacity bound."""
    coverage = quote.get('searchCoverage')
    return isinstance(coverage, dict) and (coverage.get('inputLimitObserved') is True
        or coverage.get('selectedPhase') in ('backward-prefix', 'measured-funding', 'capacity-limited'))


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
                'fees': {name: str(value) for name, value in fees.items()}, 'basis': basis,
                **({'inputLimitObserved': True} if input_limit_observed(quote) else {})}
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


def arithmetic_estimate(sample, budget, *, expand=False):
    """Indicative arithmetic only; paid route limits retain their observation."""
    try:
        reference, amount = int(sample['referenceInput']), int(budget)
        if reference <= 0 or amount < 0:
            return None
        used = amount if expand else min(amount, reference)
        return {'strategy': 'universal', 'source': 'cached-lower' if expand else 'cached-upper',
            'amount': str(int(sample['netOutput']) * used // reference),
            'referenceInput': str(used), 'basis': sample['basis'],
            'fees': {name: str(int(sample['fees'][name]) * used // reference) for name in FEE_NAMES}}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def populate_estimate_packet(packet, request, neighbors):
    """Rank cached arithmetic into the caller-owned packet, with no IO."""
    for neighbor in neighbors:
        quote = neighbor['quote']
        sample = sample_for_quote(quote)
        if neighbor['side'] not in ('lower', 'upper') or sample is None:
            continue
        # A known path can provide a full-budget advisory estimate.
        # Paid limitation/source-retention evidence clamps it; merely
        # retargeting an original-funded replay to a larger request is
        # not evidence that the route's capacity was exhausted.
        limited = sample.get('inputLimitObserved') or (
            int(sample['referenceInput']) < int(quote['inputs'][0]['amount']))
        estimate = arithmetic_estimate(sample, request['amount'],
            expand=neighbor['side'] == 'lower' and not limited)
        if estimate is None:
            continue
        if int(estimate['referenceInput']) == int(request['amount']):
            estimate['fullBudget'] = True
        previous = packet.get('estimate')
        rank = (int(estimate['amount']), -int(estimate['referenceInput']))
        if previous is not None and rank <= (int(previous['amount']), -int(previous['referenceInput'])):
            continue
        packet['estimate'] = {**estimate, 'context': deepcopy(quote['context']),
            **({'routeOrigins': deepcopy(quote['routeOrigins'])} if quote.get('routeOrigins') else {})}
        if neighbor.get('identity') is not None:
            packet['estimate']['sourceIdentity'] = neighbor['identity']
        if quote.get('request', {}).get('inputs'):
            packet['estimate']['sourceRequestedInput'] = quote['request']['inputs'][0]['amount']
