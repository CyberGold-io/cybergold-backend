"""One optional post-selection payer-funding construction, then exact replay."""
from copy import deepcopy

from ..market_fee import M, get_market_fee_rate, quoted_fee
from ..routing_encoding import split_runtime
from .contracts import capture_paths
from .ranking import prefer_completed


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
