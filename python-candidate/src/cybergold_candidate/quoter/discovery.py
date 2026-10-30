"""Physical route enumeration; no pricing, deadlines, or mutable pool state."""
from itertools import combinations
from collections import defaultdict
from copy import deepcopy

from ..routing_encoding import ZERO, weighted_routes
from ..route_search import WETH
from ..uniswap_routes import pool_identity, opposite


def paths(pools, source, target, weth=WETH, max_hops=3):
    """Selected pool graph plus explicit lossless native/WETH transitions."""
    graph = {}
    unique = {}
    for pool in pools:
        identity = pool_identity(pool)
        if identity not in unique or pool.get('address'):
            unique[identity] = pool
    for pool in unique.values():
        if pool.get('hooks', ZERO).lower() != ZERO:
            continue
        for token in (pool['token0'], pool['token1']):
            graph.setdefault(token['address'].lower(), []).append(pool)
    found = []
    def walk(current, route, visited, hops):
        if current == target.lower():
            if route:
                found.append(route)
            return
        if hops < max_hops:
            for pool in sorted(graph.get(current, []), key=lambda row: (row['protocol'], row['id'])):
                following = opposite(pool, current)
                if following not in visited:
                    walk(following, route + [{'pool': pool, 'zeroForOne': current == pool['token0']['address'].lower()}],
                         visited | {following}, hops + 1)
        if current in (ZERO, weth.lower()):
            following = weth.lower() if current == ZERO else ZERO
            if following not in visited:
                walk(following, route + [{'kind': 'wrap' if current == ZERO else 'unwrap',
                    'currencyOut': following}], visited | {following}, hops)
    walk(source.lower(), [], {source.lower()}, 0)
    return sorted(found, key=lambda route: (len(route), repr(route)))


def route_candidates(routes, amount):
    for route in routes:
        yield [{'amountIn': str(amount), 'hops': route}]
    for left, right in combinations(routes, 2):
        for share in (25, 50, 75):
            first = amount * share // 100
            if first and amount - first:
                yield [{'amountIn': str(first), 'hops': left}, {'amountIn': str(amount - first), 'hops': right}]


def route_identity(route):
    return tuple((pool_identity(hop['pool']), hop['zeroForOne']) if 'pool' in hop
                 else (hop['kind'], hop['currencyOut'].lower()) for hop in route)


def families(registry, source, target, core):
    anchor = pool_identity(registry.seed)
    groups = defaultdict(list)
    for route in paths(list(registry.inventory.values()), source, target):
        physical = [hop for hop in route if 'pool' in hop]
        if not physical:
            continue
        edge = physical[0] if source.lower() == core.lower() else physical[-1]
        if pool_identity(edge['pool']) != anchor:
            continue
        currencies, protocols = [source.lower()], []
        for hop in route:
            if 'pool' in hop:
                pool = hop['pool']
                protocols.append(pool['protocol'])
                currencies.append(pool['token1' if hop['zeroForOne'] else 'token0']['address'].lower())
            else:
                protocols.append(hop['kind'])
                currencies.append(hop['currencyOut'].lower())
        groups[(tuple(currencies), tuple(protocols))].append(route)
    result = []
    for key, routes in sorted(groups.items(), key=lambda row: (len(row[0][1]), repr(row[0]))):
        routes.sort(key=lambda route: tuple((hop['pool']['feePips'], repr(pool_identity(hop['pool'])))
                    if 'pool' in hop else (-1, hop['kind']) for hop in route))
        result.append((key, routes))
    return result


def market_plan(source, target, route, amount):
    hops = deepcopy(route)
    physical_source = source
    if hops and hops[0].get('kind') in ('wrap', 'unwrap'):
        physical_source = hops.pop(0)['currencyOut']
    template = {'inputCurrency': physical_source, 'outputCurrency': target,
                'routes': weighted_routes([{'amountIn': str(amount), 'hops': hops}])}
    return {'allocations': [{'kind': 1, 'amountIn': str(amount)}],
            'conversions': {'0:market': {'inputCurrency': source, 'outputCurrency': target,
                'branches': [{'hops': hops}], 'template': deepcopy(template)}},
            'body': {'branches': [{'kind': 1, 'amountIn': str(amount),
                'data': {'route': template, 'feeCygld': '0'}}]}}
