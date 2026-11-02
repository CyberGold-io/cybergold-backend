"""Construct changed-funding proposals from already measured consumption."""
from copy import deepcopy

from ..market_fee import M, get_market_fee_rate, quoted_fee
from ..routing_encoding import split_runtime
from .contracts import capture_paths
from .ranking import prefer_completed
from .reuse_routes import _amounts, extract_blueprint, resize_blueprint


def cached_core_funding(request, state, selected=None):
    """Construct known-supply funding without a fresh read or an exclusion.

    This is another funded proposal under the original requested maximum. A
    missing/zero observation leaves ordinary execution to report its result.
    Selected scalar bodies retain their topology and allocation proportions;
    the ordinary Helpers price recompiles their current SELL fee.
    """
    if request['intent'] not in (1, 3) or 'supply' not in state:
        return request, selected
    original = int(request['inputs'][0]['amount'])
    amount = min(original, int(state['supply']))
    if not amount or amount == original:
        return request, selected
    funded = {**request, 'inputs': [{**request['inputs'][0], 'amount': str(amount)}]}
    if selected is not None and request['intent'] == 1:
        blueprint = extract_blueprint({'request': request, 'inputs': request['inputs'], 'plan': selected})
        weights = [branch['weight'] for branch in blueprint['branches']]
        unallocated = max(0, original-sum(weights))
        allocated = sum(_amounts(amount, [*weights, unallocated])[:-1]) if unallocated else amount
        selected = resize_blueprint(blueprint, allocated, [])
    return funded, selected


def exact_ppm_routes(routes, desired):
    total = sum(desired)
    result = deepcopy(routes)
    if not total:
        return None
    for index, target in enumerate(desired[:-1]):
        low = (target * M + total - 1) // total
        high = min(M, ((target + 1) * M + total - 1) // total - 1)
        if low > high:
            return None
        result[index]['sharePpm'] = low
    result[-1]['sharePpm'] = 0
    return result if split_runtime(total, result) == desired else None


async def reconstruct(quoter, value, block, assets, weights, observations):
    request = value['request']
    if request['intent'] not in (0, 1):
        return value
    payment = request['inputs'][0]['currency'].lower()
    if not any(row['currency'].lower() == payment and int(row['amount'])
               for row in value['estimatedRetainedInputCharges']):
        return value
    if request['intent'] == 1 and any(row['kind'] != 1 for row in value['plan']['allocations']):
        return value
    if value.get('pricingEvidence', {}).get('engine') == 'helpers-execution':
        return await reconstruct_measured(quoter, value, block, assets, weights, observations)
    funded = {**request, 'inputs': deepcopy(value['inputs'])}
    with capture_paths() as traces:
        replay = await quoter.candidate(funded, 100, 'core-first', block, assets, weights,
            selected=value['plan'], observations=observations, selection=False)
    groups = {}
    for trace in traces:
        groups.setdefault(trace.operation, []).append(trace)
    plan = deepcopy(replay['plan'])

    def shrink(operation, amount):
        chosen = plan['conversions'].get(operation)
        rows = groups.get(operation)
        if not chosen or not rows or chosen['template']['inputCurrency'].lower() != payment:
            return amount
        desired = [row.consumed for row in rows]
        if sum(desired) >= amount:
            return amount
        routes = exact_ppm_routes(chosen['template']['routes'], desired)
        if routes is None:
            return amount
        chosen['template']['routes'] = routes
        return sum(desired)

    for index, (allocation, branch) in enumerate(zip(plan['allocations'], plan['body']['branches'], strict=True)):
        if branch['kind'] == 0:
            acquisitions = branch['data']['acquisitions']
            for asset_index, row in enumerate(acquisitions):
                row['amountIn'] = str(shrink(f'{index}:acquire:{asset_index}', int(row['amountIn'])))
            amount = sum(int(row['amountIn']) for row in acquisitions)
        elif request['intent'] == 1:
            rows = groups.get(f'{index}:market', [])
            routed = sum(row.consumed for row in rows)
            rate = get_market_fee_rate(quoter.engine.registry.chain, payment, request['outputCurrency'], 'exact-in')
            amount = routed + quoted_fee(routed, rate)
            chosen = plan['conversions'][f'{index}:market']
            routes = exact_ppm_routes(chosen['template']['routes'], [row.consumed for row in rows])
            if routes is None:
                return value
            chosen['template']['routes'] = routes
        else:
            amount = shrink(f'{index}:market', int(branch['amountIn']))
        if amount <= 0:
            return value  # Removing any branch would require a different index map.
        allocation['amountIn'] = branch['amountIn'] = str(amount)
    total = sum(int(row['amountIn']) for row in plan['allocations'])
    if total >= int(value['inputs'][0]['amount']):
        return value
    funded['inputs'] = [{**value['inputs'][0], 'amount': str(total)}]
    proposal = await quoter.candidate(funded, 100, 'core-first', block, assets, weights,
        selected=plan, observations=observations, selection=False)
    proposal['request'] = deepcopy(request)
    proposal['searchCoverage'] = deepcopy(value['searchCoverage'])
    return proposal if prefer_completed(proposal, value, scalar=True) else value


async def reconstruct_measured(quoter, value, block, assets, weights, observations):
    """Reuse completed execution measurements; only changed funding is repriced."""
    proposal = measured_funding_proposal(value, quoter.engine.registry.chain)
    if proposal is None:
        return value
    funded, plan = proposal
    proposal = await quoter.candidate(funded, 100, 'core-first', block, assets, weights,
        selected=plan, observations=observations, selection=False)
    proposal['request'] = deepcopy(value['request'])
    return proposal if prefer_completed(proposal, value, scalar=True) else value


def measured_funding_proposal(value, chain):
    """Return (funded request, complete body), without a replay or network tail."""
    request, plan = value['request'], deepcopy(value['plan'])
    if request['intent'] not in (0, 1):
        return None
    if request['intent'] == 1 and any(row['kind'] != 1 for row in plan['allocations']):
        return None
    payment = request['inputs'][0]['currency'].lower()
    measured = {row['operation']: row for row in value.get('conversionObservations', [])}
    def consumed(operation, amount):
        chosen, row = plan['conversions'].get(operation), measured.get(operation)
        # This nominates new funding, not unchanged output. Keep split weights
        # and native wrapping, then let the complete Helpers call measure it.
        if not chosen or not row or chosen['inputCurrency'].lower() != payment:
            return amount
        return min(amount, int(row['consumedInput']))
    for index, (allocation, branch) in enumerate(zip(plan['allocations'], plan['body']['branches'], strict=True)):
        if branch['kind'] == 0:
            acquisitions = branch['data']['acquisitions']
            for asset_index, row in enumerate(acquisitions):
                row['amountIn'] = str(consumed(f'{index}:acquire:{asset_index}', int(row['amountIn'])))
            amount = sum(int(row['amountIn']) for row in acquisitions)
        elif request['intent'] == 1:
            original = int(branch['amountIn'])
            routed = consumed(f'{index}:market', original - int(branch['data']['feeCygld']))
            rate = get_market_fee_rate(chain, payment, request['outputCurrency'], 'exact-in')
            amount = min(original, routed + quoted_fee(routed, rate))
        else:
            amount = consumed(f'{index}:market', int(branch['amountIn']))
        if amount <= 0:
            return None
        allocation['amountIn'] = branch['amountIn'] = str(amount)
    total = sum(int(row['amountIn']) for row in plan['allocations'])
    if total >= int(value['inputs'][0]['amount']):
        return None
    funded = {**request, 'inputs': [{**value['inputs'][0], 'amount': str(total)}]}
    return funded, plan
