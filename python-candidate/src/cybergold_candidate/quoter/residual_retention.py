"""One complete Core-issuance alternative retaining actual residual input."""
from copy import deepcopy


def _groups(request, plan):
    if request['intent'] == 0:
        for branch, row in enumerate(plan['body']['branches']):
            if row['kind'] == 0:
                yield branch, row['data']['basketAssets'], row['data']['continuations']
    elif request['intent'] == 2:
        yield 0, [row['currency'] for row in request['inputs']], plan['body']['continuations']


def residual_retention_proposal(request, plan):
    core = request['outputCurrency']
    # Only a different execution body is another proposal. An already-empty
    # continuation must not recursively retry its own contract failure.
    if not any(asset.lower() != core.lower() and (
            row['route']['routes'] or row['route']['inputCurrency'].lower() != asset.lower()
            or row['route']['outputCurrency'].lower() != core.lower())
            for _, assets, rows in _groups(request, plan)
            for asset, row in zip(assets, rows, strict=True)):
        return None
    selected = deepcopy(plan)
    for branch, assets, rows in _groups(request, selected):
        for index, (asset, row) in enumerate(zip(assets, rows, strict=True)):
            if asset.lower() == core.lower():
                continue
            route = {'inputCurrency': asset, 'outputCurrency': core, 'routes': []}
            row.update(route=route, feeCygld='0')
            selected.setdefault('conversions', {})[f'{branch}:residual:{index}'] = {
                'inputCurrency': asset, 'outputCurrency': core, 'branches': [], 'template': deepcopy(route)}
    return {'inputs': deepcopy(request['inputs']), 'plan': selected}
