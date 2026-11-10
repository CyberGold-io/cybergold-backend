"""Shared complete funding proposals; Helpers measures their economic result."""
from copy import deepcopy

from ..basket_arithmetic import ceil_div
from ..market_fee import get_market_fee_rate, quoted_fee
from .reuse_routes import _amounts, extract_blueprint, resize_blueprint


def funding_proposal(request, selected, amounts=None, conversions=None, inputs=None):
    """Apply operation funding and route edits to one privately owned whole plan.

    Acquisition amounts are payment units. Market amounts include any input-side
    sale fee; callers use the shared fee arithmetic when nominating those lots.
    Basket vectors can be replaced directly without introducing scalar sums.
    """
    plan = deepcopy(selected)
    amounts, conversions = amounts or {}, conversions or {}
    for operation, chosen in conversions.items():
        chosen = deepcopy(chosen)
        plan['conversions'][operation] = chosen
        branch, role, *position = operation.split(':')
        if request['intent'] == 2:
            plan['body']['continuations'][int(position[0])]['route'] = deepcopy(chosen['template'])
        else:
            data = plan['body']['branches'][int(branch)]['data']
            if role == 'market':
                data['route'] = deepcopy(chosen['template'])
            elif role == 'acquire':
                data['acquisitions'][int(position[0])]['route'] = deepcopy(chosen['template'])
            elif role == 'residual':
                data['continuations'][int(position[0])]['route'] = deepcopy(chosen['template'])
            elif role == 'redeem':
                data['conversions'][int(position[0])] = deepcopy(chosen['template'])
                aliases = plan.get('assetConversions', {}).get(branch)
                if aliases is not None:
                    asset = data['expectedOutputs'][int(position[0])]['token'].lower()
                    aliases[asset] = deepcopy(chosen)
    if request['intent'] in (0, 1):
        for index, (allocation, branch) in enumerate(zip(plan['allocations'], plan['body']['branches'], strict=True)):
            if branch['kind'] == 0 and request['intent'] == 0:
                for position, row in enumerate(branch['data']['acquisitions']):
                    row['amountIn'] = str(amounts.get(f'{index}:acquire:{position}', row['amountIn']))
                amount = sum(int(row['amountIn']) for row in branch['data']['acquisitions'])
            else:
                role = 'market' if branch['kind'] == 1 else 'core'
                amount = int(amounts.get(f'{index}:{role}', branch['amountIn']))
            branch['amountIn'] = allocation['amountIn'] = str(amount)
        funded = [{**request['inputs'][0],
                   'amount': str(sum(int(row['amountIn']) for row in plan['allocations']))}]
    else:
        funded = deepcopy(request['inputs'])
    return {'inputs': deepcopy(inputs) if inputs is not None else funded, 'plan': plan}


def supply_funding(request, state):
    """Nominate available CYGLD funding without a fresh read or an exclusion."""
    if request['intent'] not in (1, 3) or 'supply' not in state:
        return None
    original = int(request['inputs'][0]['amount'])
    amount = min(original, int(state['supply']))
    return ([{**request['inputs'][0], 'amount': str(amount)}]
            if amount and amount < original else None)


def cached_core_funding(request, state, selected=None):
    """Keep selected scalar topology/proportions when proposing lower supply."""
    funding = supply_funding(request, state)
    if funding is None:
        return request, selected
    original, amount = int(request['inputs'][0]['amount']), int(funding[0]['amount'])
    if selected is not None and request['intent'] == 1:
        blueprint = extract_blueprint({'request': request, 'inputs': request['inputs'], 'plan': selected})
        weights = [branch['weight'] for branch in blueprint['branches']]
        unallocated = max(0, original-sum(weights))
        allocated = sum(_amounts(amount, [*weights, unallocated])[:-1]) if unallocated else amount
        selected = resize_blueprint(blueprint, allocated, [])
    return {**request, 'inputs': funding}, selected


def direct_basket_funding(request, state):
    """Propose basket/capacity amounts from existing construction observations."""
    if request['intent'] == 3:
        return supply_funding(request, state)
    if request['intent'] != 2:
        return None
    units, weights = state.get('conversions'), state.get('weights')
    if not units or not weights:
        return None
    budgets = [int(row['amount']) for row in request['inputs']]
    try:
        gross = min((budget * int(unit) // 10**18) * 1_000_000 // int(weight)
                    for budget, unit, weight in zip(budgets, units, weights, strict=True) if int(weight))
        if all(name in state for name in ('supply', 'maxSupply', 'effectiveCap')):
            gross = min(gross, max(0, min(int(state['maxSupply']), int(state['effectiveCap']))-int(state['supply'])))
        amounts = [ceil_div(ceil_div(gross * int(weight), 1_000_000) * 10**18, int(unit)) if int(weight) else 0
                   for unit, weight in zip(units, weights, strict=True)]
    except (ValueError, ZeroDivisionError):
        return None
    if not any(amounts) or amounts == budgets:
        return None
    return [{**row, 'amount': str(amount)} for row, amount in zip(request['inputs'], amounts, strict=True)]


def measured_funding_proposal(value, chain):
    """Return (funded request, complete body) from measured input consumption."""
    request, plan = value['request'], value['plan']
    if request['intent'] not in (0, 1):
        return None
    payment = request['inputs'][0]['currency'].lower()
    measured = {row['operation']: row for row in value.get('conversionObservations', [])}

    def consumed(operation, amount):
        chosen, row = plan['conversions'].get(operation), measured.get(operation)
        # Native wrapping belongs to Helpers: chosen names the logical payment,
        # while its template and measured row can name the physical wrapped unit.
        if not chosen or not row or chosen['inputCurrency'].lower() != payment:
            return amount
        return min(amount, int(row['consumedInput']))

    amounts, total = {}, 0
    for index, branch in enumerate(plan['body']['branches']):
        if branch['kind'] == 0 and request['intent'] == 0:
            acquisitions = [consumed(f'{index}:acquire:{position}', int(row['amountIn']))
                            for position, row in enumerate(branch['data']['acquisitions'])]
            amounts.update({f'{index}:acquire:{position}': amount for position, amount in enumerate(acquisitions)})
            amount = sum(acquisitions)
        elif branch['kind'] == 0:
            # Core redemption keeps its nominal CYGLD lot; only market input
            # consumption can nominate a reduction here.
            amount = int(branch['amountIn'])
        elif request['intent'] == 1:
            original = int(branch['amountIn'])
            routed = consumed(f'{index}:market', original - int(branch['data']['feeCygld']))
            rate = get_market_fee_rate(chain, payment, request['outputCurrency'], 'exact-in')
            amount = min(original, routed + quoted_fee(routed, rate))
            amounts[f'{index}:market'] = amount
        else:
            amount = consumed(f'{index}:market', int(branch['amountIn']))
            amounts[f'{index}:market'] = amount
        total += amount
    if total <= 0 or total >= int(value['inputs'][0]['amount']):
        return None
    proposal = funding_proposal(request, plan, amounts)
    return {**request, 'inputs': proposal['inputs']}, proposal['plan']
