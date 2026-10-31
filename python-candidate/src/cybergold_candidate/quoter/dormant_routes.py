"""Select unpriced zero-residual topology before an economic quote is offered.

Only already-selected pool identities and the existing Core market seed are
used. No snapshot, search, simulated output or execution guard is added.
"""
from copy import deepcopy

from .discovery import paths
from .reuse_routes import _conversion
from ..routing_encoding import weighted_routes
from ..uniswap_routes import pool_identity


def with_dormant_routes(value, seed=None):
    if value['request']['intent'] not in (0, 2) or seed is None:
        return value
    value = deepcopy(value)
    plan = value['plan']
    core = value['request']['outputCurrency']
    pools = [hop['pool'] for chosen in plan['conversions'].values()
             for branch in chosen['branches'] for hop in branch['hops'] if 'pool' in hop]
    pools.append(seed)
    anchor = pool_identity(seed)
    groups = ([(index, branch['data']['basketAssets'], branch['data']['continuations'])
               for index, branch in enumerate(plan['body']['branches']) if branch['kind'] == 0]
              if value['request']['intent'] == 0 else
              [(0, [row['currency'] for row in value['inputs']], plan['body']['continuations'])])
    for branch, assets, continuations in groups:
        for index, (asset, continuation) in enumerate(zip(assets, continuations, strict=True)):
            operation = f'{branch}:residual:{index}'
            route = continuation['route']
            # Identity placeholders describe a zero historical residual. A
            # priced continuation or an already-selected dormant path stays as is.
            if (operation in plan['conversions'] or asset.lower() == core.lower()
                    or route['routes'] or route['outputCurrency'].lower() != asset.lower()):
                continue
            selected = next((hops for hops in paths(pools, asset, core)
                if pool_identity(next(hop['pool'] for hop in reversed(hops) if 'pool' in hop)) == anchor), None)
            if selected is None:
                continue  # No new quote eligibility requirement or discovery.
            hops = deepcopy(selected)
            physical_source = asset
            if hops[0].get('kind') in ('wrap', 'unwrap'):
                physical_source = hops.pop(0)['currencyOut']
            template = {'inputCurrency': physical_source, 'outputCurrency': core,
                        'routes': weighted_routes([{'amountIn': '1', 'hops': hops}])}
            plan['conversions'][operation] = _conversion({'inputCurrency': asset, 'outputCurrency': core,
                'branches': [{'hops': hops}], 'template': template})
            continuation['route'] = deepcopy(template)
    return value
