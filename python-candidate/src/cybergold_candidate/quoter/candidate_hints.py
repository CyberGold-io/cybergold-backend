"""Interleave available topology hints with ordinary candidates; never wait."""
from itertools import product

from .discovery import current_topology, path_steps, route_candidate_steps, route_identity, route_available
from .cooperative import CHECKPOINT, close, values
from .pool_directions import branch_directions, conflicting_pool
from ..routing_encoding import weighted_shares, split_runtime


def normalize_hints(hints, source, target):
    return values(normalize_steps(hints, source, target))


def _union_patterns(routes, amount):
    positions = {id(route): index for index, route in enumerate(routes)}
    # Memoize structural integer patterns, independently of observations that
    # can change while this lazy expansion is consumed. Emission checks them.
    for branches in route_candidate_steps(routes, amount, observed=False):
        if branches is CHECKPOINT:
            yield CHECKPOINT
            continue
        if conflicting_pool(branch_directions(branches)) is None:
            yield tuple((positions[id(row['hops'])], row['amountIn']) for row in branches)


def _directions(alternatives):
    return tuple(tuple(tuple(branch_directions([{'hops': route}])) for route in routes)
                 for routes in alternatives)


def _direction_patterns(directions, amounts):
    total = sum(map(int, amounts))
    funded = (split_runtime(total, [{'sharePpm': share} for share in weighted_shares(
        [{'amountIn': amount} for amount in amounts])]) if total else [0]*len(amounts))
    for indices in product(*(range(len(routes)) for routes in directions)):
        yield CHECKPOINT
        projected = (pair for routes, index, amount in zip(directions, indices, funded, strict=True)
                     if amount for pair in routes[index])
        yield indices, conflicting_pool(projected) is not None


def _structural_routes(routes):
    """Freeze only connectivity for a suspended union-pattern producer."""
    def hop_recipe(hop):
        if 'pool' not in hop:
            return {'kind': hop['kind'], 'currencyOut': hop['currencyOut']}
        pool = hop['pool']
        recipe = {key: pool[key] for key in ('protocol', 'feePips', 'tickSpacing', 'hooks') if key in pool}
        recipe.update({key: {'address': pool[key]['address']} for key in ('token0', 'token1')})
        return {'pool': recipe, 'zeroForOne': hop['zeroForOne']}
    return [[hop_recipe(hop) for hop in route] for route in routes]


def normalize_steps(hints, source, target):
    """The existing path producer owns connectivity and native transitions.

    A hint offers a pool graph and split weights, never authority to relabel
    unrelated hop output as the requested currency. Reconstruct directions
    rather than introducing a second route-validation policy.
    """
    previous_key, previous_patterns = None, ()
    topology = current_topology()
    try:
        for offer in hints:
            yield CHECKPOINT
            if offer is CHECKPOINT:
                continue
            try:
                candidate = offer['branches']
                alternatives = []
                opposed = any(not route_available(row['hops']) for row in candidate)
                if not opposed:
                    for row in candidate:
                        alternatives.append((yield from path_steps(
                            [hop['pool'] for hop in row['hops'] if 'pool' in hop], source, target)))
                # Cooperative walks may have learned a zero-price leg while
                # building alternatives, including an empty later path set.
                opposed = opposed or any(not route_available(row['hops']) for row in candidate)
                amounts = tuple(row['amountIn'] for row in candidate)
                directions = _directions(alternatives)
                patterns = (_direction_patterns(directions, amounts) if alternatives else ())
                if topology is not None and alternatives:
                    key = 'normalized', amounts, directions
                    patterns = topology.shared_patterns(key,
                        lambda: _direction_patterns(directions, amounts))
                for pattern in patterns:
                    yield CHECKPOINT
                    if pattern is CHECKPOINT:
                        continue
                    indices, crossed = pattern
                    routes = [rows[index] for rows, index in zip(alternatives, indices, strict=True)]
                    if any(not route_available(route) for route in routes):
                        opposed = True
                        continue
                    branches = [{'amountIn': row['amountIn'], 'hops': route}
                                for row, route in zip(candidate, routes, strict=True)]
                    if crossed:
                        opposed = True
                        continue
                    yield branches, list(offer.get('origins', []))
                if opposed:
                    # A crossed or disproved split can still expose compatible
                    # paths in its remaining graph. Reuse lazy singles/splits.
                    routes = yield from path_steps([hop['pool'] for row in candidate
                        for hop in row['hops'] if 'pool' in hop], source, target)
                    amount = sum(int(row['amountIn']) for row in candidate)
                    key = amount, tuple(route_identity(route) for route in routes)
                    if topology is not None:
                        previous_key, previous_patterns = topology.hint_union
                    steps = (topology.shared_patterns(('hint-union', key),
                                 lambda: _union_patterns(_structural_routes(routes), amount)) if topology is not None else
                             ((value for pattern in previous_patterns for value in (CHECKPOINT, pattern))
                              if key == previous_key else _union_patterns(routes, amount)))
                    patterns = []
                    for pattern in steps:
                        if pattern is CHECKPOINT:
                            yield CHECKPOINT
                            continue
                        patterns.append(pattern)
                        if any(not route_available(routes[index]) for index, _ in pattern):
                            continue
                        # Reuse only integer allocations. Current pools,
                        # metadata and supplier origins remain live, and each
                        # consumer receives its own branch/hop containers.
                        yield [{'amountIn': funded, 'hops': [dict(hop) for hop in routes[index]]}
                               for index, funded in pattern], list(offer.get('origins', []))
                    previous_key, previous_patterns = key, tuple(patterns)
                    if topology is not None:
                        # Keep the synchronous iterator's completed memo as
                        # well as the session's shared incremental recipes.
                        topology.hint_union = previous_key, previous_patterns
            except Exception:
                # Ordinary malformed topology does not discard a sibling.
                continue
    finally:
        close(hints)
