"""Interleave available topology hints with ordinary candidates; never wait."""
from itertools import product

from .discovery import current_topology, path_steps, route_candidates, route_identity, route_available
from .cooperative import CHECKPOINT, close, values
from .pool_directions import branch_directions, conflicting_pool


def normalize_hints(hints, source, target):
    return values(normalize_steps(hints, source, target))


def _union_patterns(routes, amount):
    positions = {id(route): index for index, route in enumerate(routes)}
    # Memoize structural integer patterns, independently of observations that
    # can change while this lazy expansion is consumed. Emission checks them.
    for branches in route_candidates(routes, amount, observed=False):
        yield CHECKPOINT
        if conflicting_pool(branch_directions(branches)) is None:
            yield tuple((positions[id(row['hops'])], row['amountIn']) for row in branches)


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
                for routes in product(*alternatives) if alternatives else ():
                    yield CHECKPOINT
                    if any(not route_available(route) for route in routes):
                        opposed = True
                        continue
                    branches = [{'amountIn': row['amountIn'], 'hops': route}
                                for row, route in zip(candidate, routes, strict=True)]
                    if conflicting_pool(branch_directions(branches)) is not None:
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
                    steps = ((value for pattern in previous_patterns for value in (CHECKPOINT, pattern))
                             if key == previous_key else _union_patterns(routes, amount))
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
                        # Sibling feeds share only the last fully consumed
                        # integer pattern set. Bind current paths/origins above;
                        # no pool state, mutable body or price is retained.
                        topology.hint_union = previous_key, previous_patterns
            except Exception:
                # Ordinary malformed topology does not discard a sibling.
                continue
    finally:
        close(hints)
