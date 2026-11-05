"""Physical route enumeration; no pricing, deadlines, or mutable pool state."""
from itertools import combinations
from collections import defaultdict
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar

from ..routing_encoding import ZERO, weighted_routes
from ..route_search import WETH
from ..uniswap_routes import pool_identity, opposite
from .cooperative import CHECKPOINT, finish, sort_steps


def _enumerate_paths(pools, source, target, weth=WETH, max_hops=3):
    return finish(_enumerate_path_steps(pools, source, target, weth, max_hops))


def _enumerate_path_steps(pools, source, target, weth=WETH, max_hops=3):
    """Selected pool graph plus explicit lossless native/WETH transitions."""
    graph = {}
    unique = {}
    for pool in pools:
        yield CHECKPOINT
        identity = pool_identity(pool)
        if identity not in unique or pool.get('address'):
            unique[identity] = pool
    for pool in unique.values():
        yield CHECKPOINT
        if pool.get('hooks', ZERO).lower() != ZERO:
            continue
        for token in (pool['token0'], pool['token1']):
            graph.setdefault(token['address'].lower(), []).append(pool)
    found = []
    def walk(current, route, visited, hops):
        yield CHECKPOINT
        if current == target.lower():
            if route:
                found.append(route)
            return
        if hops < max_hops:
            edges = yield from sort_steps(graph.get(current, []), key=lambda row: (row['protocol'], row['id']))
            for pool in edges:
                yield CHECKPOINT
                following = opposite(pool, current)
                if following not in visited:
                    yield from walk(following, route + [{'pool': pool, 'zeroForOne': current == pool['token0']['address'].lower()}],
                         visited | {following}, hops + 1)
        if current in (ZERO, weth.lower()):
            following = weth.lower() if current == ZERO else ZERO
            if following not in visited:
                yield from walk(following, route + [{'kind': 'wrap' if current == ZERO else 'unwrap',
                    'currencyOut': following}], visited | {following}, hops)
    yield from walk(source.lower(), [], {source.lower()}, 0)
    return (yield from sort_steps(found, key=lambda route: (len(route), repr(route)))) if len(found) > 1 else found



_topology = ContextVar('quote_topology_reuse', default=None)


@contextmanager
def topology_scope(cache):
    token = _topology.set(cache)
    try:
        yield cache
    finally:
        _topology.reset(token)


def current_topology():
    return _topology.get()


class TopologyCache:
    """One discovery owner's immutable walks and rendered-route identities.

    Pool dictionaries, observations, amounts and origins are never cached.
    Current representatives are bound on every read; metadata still owns the
    existing repr-based ordering. Split combinations remain lazy and fresh.
    """
    def __init__(self):
        self.walks, self.validated = {}, {}
        self.graph_builds = self.path_hits = self.route_validations = self.validation_hits = 0
        self._catalog_objects, self._catalog_unique, self._catalog_graph = (), {}, ()

    def catalog_changed(self, pools):
        """Reuse the catalog owner's graph key between its existing changes."""
        pools = list(pools)
        self._catalog_objects = frozenset(map(id, pools))
        self._catalog_unique = self._unique(pools)
        self._catalog_graph = self._graph(self._catalog_unique)

    @staticmethod
    def _unique(pools):
        unique = {}
        for pool in pools:
            identity = pool_identity(pool)
            if identity not in unique or pool.get('address'):
                unique[identity] = pool
        return unique

    @staticmethod
    def _graph(unique):
        return tuple(sorted(((identity, pool['token0']['address'].lower(),
            pool['token1']['address'].lower(), pool.get('hooks', ZERO).lower())
            for identity, pool in unique.items()), key=repr))

    def clear(self):
        self.walks.clear()
        self.validated.clear()
        self._catalog_objects, self._catalog_unique, self._catalog_graph = (), {}, ()

    def paths(self, pools, source, target, weth, max_hops):
        return finish(self.path_steps(pools, source, target, weth, max_hops))

    def path_steps(self, pools, source, target, weth, max_hops):
        pools = list(pools)
        if len(pools) == len(self._catalog_objects) and self._catalog_objects == frozenset(map(id, pools)):
            unique, graph = self._catalog_unique, self._catalog_graph
        else:
            unique = self._unique(pools)
            graph = self._graph(unique)
        key = source.lower(), target.lower(), weth.lower(), max_hops, graph
        if key not in self.walks:
            routes = yield from _enumerate_path_steps(list(unique.values()), source, target, weth, max_hops)
            walks = []
            for route in routes:
                walks.append(tuple((pool_identity(hop['pool']), hop['zeroForOne'])
                    if 'pool' in hop else (hop['kind'], hop['currencyOut']) for hop in route))
                yield CHECKPOINT
            self.walks[key] = tuple(walks)
            self.graph_builds += 1
            return routes
        self.path_hits += 1
        routes = []
        for route in self.walks[key]:
            routes.append([{'pool': unique[step[0]], 'zeroForOne': step[1]}
                if isinstance(step[0], tuple) else {'kind': step[0], 'currencyOut': step[1]} for step in route])
            yield CHECKPOINT
        return (yield from sort_steps(routes, key=lambda route: (len(route), repr(route)))) if len(routes) > 1 else routes

    def nomination_identity(self, candidate):
        amounts = [int(row['amountIn']) for row in candidate]
        total = sum(amounts)
        shares = [0 if index == len(candidate)-1 else amount*1_000_000//total
                  for index, amount in enumerate(amounts)]
        result = []
        for row, share in zip(candidate, shares, strict=True):
            route = row['hops']
            key = tuple(((hop['pool']['protocol'], hop['pool']['token0']['address'],
                hop['pool']['token1']['address'], hop['pool']['feePips'],
                hop['pool'].get('tickSpacing'), hop['pool'].get('hooks', ZERO), hop['zeroForOne'])
                if 'pool' in hop else None,
                (hop['kind'], hop['currencyOut']) if 'kind' in hop else None) for hop in route)
            if key not in self.validated:
                # Retain encoding validation before identity construction, as
                # in the uncached nomination path. Current primitive fields
                # invalidate both together; optional pool metadata stays live.
                weighted_routes([{'amountIn': '1', 'hops': route}])
                self.validated[key] = route_identity(route)
                self.route_validations += 1
            else:
                self.validation_hits += 1
            result.append((share, self.validated[key]))
        return tuple(result)


def paths(pools, source, target, weth=WETH, max_hops=3):
    return finish(path_steps(pools, source, target, weth, max_hops))


def path_steps(pools, source, target, weth=WETH, max_hops=3):
    cache = current_topology()
    return (yield from cache.path_steps(pools, source, target, weth, max_hops) if cache is not None else
            _enumerate_path_steps(pools, source, target, weth, max_hops))


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


def seeded_path_steps(pools, seed, source, target, weth=WETH):
    """Direct pools and one connector beside the seed, before the full walk.

    These are a subset of ordinary discovery. No pool state or price is read,
    and the consuming adapter still validates/filters each nomination.
    """
    unique = {}
    for pool in pools:
        yield CHECKPOINT
        identity = pool_identity(pool)
        if identity not in unique or pool.get('address'):
            unique[identity] = pool
    source, target, weth = source.lower(), target.lower(), weth.lower()
    start, end = weth if source == ZERO else source, weth if target == ZERO else target
    prefix = [{'kind': 'wrap', 'currencyOut': weth}] if source == ZERO else []
    suffix = [{'kind': 'unwrap', 'currencyOut': ZERO}] if target == ZERO else []
    anchor = unique.get(pool_identity(seed))
    def hop(pool, currency):
        return {'pool': pool, 'zeroForOne': currency == pool['token0']['address'].lower()}
    for pool in unique.values():
        yield CHECKPOINT
        if pool.get('hooks', ZERO).lower() != ZERO:
            continue
        tokens = {pool['token0']['address'].lower(), pool['token1']['address'].lower()}
        if start in tokens and opposite(pool, start) == end:
            yield prefix + [hop(pool, start)] + suffix
        if anchor is None or pool is anchor or anchor.get('hooks', ZERO).lower() != ZERO:
            continue
        anchored = {anchor['token0']['address'].lower(), anchor['token1']['address'].lower()}
        if end in anchored and start in tokens:
            middle = opposite(pool, start)
            if middle != start and middle != end and middle in anchored and opposite(anchor, middle) == end:
                yield prefix + [hop(pool, start), hop(anchor, middle)] + suffix
        if start in anchored and end in tokens:
            middle = opposite(anchor, start)
            if middle != start and middle != end and middle in tokens and opposite(pool, middle) == end:
                yield prefix + [hop(anchor, start), hop(pool, middle)] + suffix


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


def market_plan(source, target, route, amount, *, origins=None):
    hops = deepcopy(route)
    physical_source = source
    if hops and hops[0].get('kind') in ('wrap', 'unwrap'):
        physical_source = hops.pop(0)['currencyOut']
    template = {'inputCurrency': physical_source, 'outputCurrency': target,
                'routes': weighted_routes([{'amountIn': str(amount), 'hops': hops}])}
    return {'allocations': [{'kind': 1, 'amountIn': str(amount)}],
            'conversions': {'0:market': {'inputCurrency': source, 'outputCurrency': target,
                'branches': [{'hops': hops}], 'template': deepcopy(template),
                **({'discoveryOrigins': sorted(set(origins))} if origins is not None else {})}},
            'body': {'branches': [{'kind': 1, 'amountIn': str(amount),
                'data': {'route': template, 'feeCygld': '0'}}]}}
