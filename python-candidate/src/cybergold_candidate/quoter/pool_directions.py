"""One trade may reuse a physical pool only in the same direction.

These pure projections use executable funding and pool keys. Native wrappers
are not pools, and an unknown Core-produced amount is never treated as zero.
"""
from ..routing_encoding import ZERO, split_runtime, weighted_routes
from ..uniswap_routes import pool_identity


def conflicting_pool(directions):
    """Return the first opposed canonical pool key, without mutating callers."""
    seen = {}
    for identity, source in directions:
        source = source.lower()
        if identity in seen and seen[identity] != source:
            return identity
        seen[identity] = source
    return None


def branch_directions(branches, *, amount=None):
    """Project funded branch hops; encoded integer remainder owns its real lot."""
    if not branches or amount == 0:
        return
    if all('amountIn' in branch for branch in branches):
        total = sum(int(branch['amountIn']) for branch in branches)
        if not total:
            return
        amounts = split_runtime(total if amount is None else amount, weighted_routes(branches))
    else:
        amounts = [int(branch['amountIn']) if 'amountIn' in branch else None for branch in branches]
    for branch, amount in zip(branches, amounts, strict=True):
        if amount == 0:
            continue
        for hop in branch['hops']:
            if 'pool' in hop:
                pool = hop['pool']
                yield pool_identity(pool), pool['token0' if hop['zeroForOne'] else 'token1']['address'].lower()


def _route_directions(route, amount):
    if amount == 0:
        return
    routes = route.get('routes', ())
    previous = [int(row['sharePpm']) for row in routes[:-1]]
    zero_remainder = previous.count(1_000_000) == 1 and sum(previous) == 1_000_000
    amounts = (split_runtime(amount, routes) if amount is not None else
               [None if (index == len(routes)-1 and not zero_remainder) or
                         (index < len(routes)-1 and int(row['sharePpm'])) else 0
                for index, row in enumerate(routes)])
    for row, funded in zip(routes, amounts, strict=True):
        if funded == 0:
            continue
        source = route['inputCurrency'].lower()
        for step in row['steps']:
            output = step['currencyOut'].lower()
            if int(step['kind']) < 3:
                pool = {'protocol': {0: 'v2', 1: 'v3', 2: 'v4'}[int(step['kind'])],
                        'token0': {'address': source}, 'token1': {'address': output},
                        'feePips': int(step['fee']), 'tickSpacing': int(step['tickSpacing']), 'hooks': ZERO}
                yield pool_identity(pool), source
            source = output


def body_directions(request, body, observations=(), *, known_funding=None):
    """Project executable templates, independently of conversion metadata.

    Explicit lots and fresh observations can prove zero funding. Missing Core
    observations remain unknown; all routes able to receive a lot then count.
    """
    funding = dict(known_funding or {})
    funding.update((row['operation'], int(row['fundedInput'])) for row in observations)
    intent = request['intent']
    if intent == 2:
        for index, row in enumerate(body.get('continuations', ())):
            asset = request['inputs'][index] if index < len(request['inputs']) else None
            amount = 0 if asset is not None and not int(asset['amount']) else funding.get(f'0:residual:{index}')
            yield from _route_directions(row['route'], amount)
        return
    if intent == 3:
        return
    for branch, row in enumerate(body.get('branches', ())):
        amount, data = int(row['amountIn']), row['data']
        if not amount:
            continue
        if row['kind'] == 1:
            routed = amount - int(data['feeCygld']) if intent == 1 else amount
            yield from _route_directions(data['route'], routed)
        elif intent == 0:
            for acquisition in data['acquisitions']:
                yield from _route_directions(acquisition.get('route', {}), int(acquisition['amountIn']))
            for index, row in enumerate(data['continuations']):
                yield from _route_directions(row['route'], funding.get(f'{branch}:residual:{index}'))
        else:
            for index, (asset, route) in enumerate(zip(data['expectedOutputs'], data['conversions'], strict=True)):
                if int(asset['kind']) == 0:
                    yield from _route_directions(route, funding.get(f'{branch}:redeem:{index}'))


def quote_directions(value, chain=None):
    """Reuse existing measured Core projections for omitted zero conversions."""
    body = value.get('plan', {}).get('body', {})
    if not body:
        return
    known = {}
    if value['request']['intent'] in (0, 2):
        # A local import avoids a dependency cycle with compilation/simulation.
        from .plan_simulation import project_core_inputs
        for row in project_core_inputs(value, chain if chain is not None else (value.get('context') or {}).get('chainId')):
            known[f"{row['branch']}:residual:{row['index']}"] = row['residual']
    elif value['request']['intent'] == 1:
        for row in (value.get('pricingEvidence') or {}).get('coreOutputAmounts', ()):
            if int(row['kind']) == 0:
                known[f"{row['branch']}:redeem:{row['index']}"] = int(row['amount'])
    yield from body_directions(value['request'], body,
                              value.get('conversionObservations', ()), known_funding=known)
