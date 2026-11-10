"""Interleave available topology hints with ordinary candidates; never wait."""
from itertools import product

from .discovery import path_steps, route_candidates, route_identity
from .cooperative import CHECKPOINT, close, values
from .pool_directions import branch_directions, conflicting_pool


def normalize_hints(hints, source, target):
    return values(normalize_steps(hints, source, target))


def _union_patterns(routes, amount):
    positions = {id(route): index for index, route in enumerate(routes)}
    for branches in route_candidates(routes, amount):
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
    try:
        for offer in hints:
            yield CHECKPOINT
            if offer is CHECKPOINT:
                continue
            try:
                candidate = offer['branches']
                alternatives = []
                opposed = False
                for row in candidate:
                    alternatives.append((yield from path_steps(
                        [hop['pool'] for hop in row['hops'] if 'pool' in hop], source, target)))
                for routes in product(*alternatives) if alternatives else ():
                    yield CHECKPOINT
                    branches = [{'amountIn': row['amountIn'], 'hops': route}
                                for row, route in zip(candidate, routes, strict=True)]
                    if conflicting_pool(branch_directions(branches)) is not None:
                        opposed = True
                        continue
                    yield branches, list(offer.get('origins', []))
                if opposed:
                    # A crossed split can expose shorter compatible paths in
                    # its union graph. Reuse ordinary lazy singles/splits.
                    routes = yield from path_steps([hop['pool'] for row in candidate
                        for hop in row['hops'] if 'pool' in hop], source, target)
                    amount = sum(int(row['amountIn']) for row in candidate)
                    key = amount, tuple(route_identity(route) for route in routes)
                    steps = ((value for pattern in previous_patterns for value in (CHECKPOINT, pattern))
                             if key == previous_key else _union_patterns(routes, amount))
                    patterns = []
                    for pattern in steps:
                        if pattern is CHECKPOINT:
                            yield CHECKPOINT
                            continue
                        patterns.append(pattern)
                        # Reuse only integer allocations. Current pools,
                        # metadata and supplier origins remain live, and each
                        # consumer receives its own branch/hop containers.
                        yield [{'amountIn': funded, 'hops': [dict(hop) for hop in routes[index]]}
                               for index, funded in pattern], list(offer.get('origins', []))
                    previous_key, previous_patterns = key, tuple(patterns)
            except Exception:
                # Ordinary malformed topology does not discard a sibling.
                continue
    finally:
        close(hints)
