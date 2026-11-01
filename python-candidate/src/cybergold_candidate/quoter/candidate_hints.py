"""Interleave available topology hints with ordinary candidates; never wait."""
from itertools import product

from .discovery import paths, route_identity


def normalize_hints(hints, source, target):
    """The existing path producer owns connectivity and native transitions.

    A hint offers a pool graph and split weights, never authority to relabel
    unrelated hop output as the requested currency. Reconstruct directions
    rather than introducing a second route-validation policy.
    """
    for offer in hints:
        try:
            candidate = offer['branches']
            alternatives = [paths([hop['pool'] for hop in row['hops'] if 'pool' in hop],
                                  source, target) for row in candidate]
            for routes in product(*alternatives) if alternatives else ():
                yield ([{'amountIn': row['amountIn'], 'hops': route}
                        for row, route in zip(candidate, routes, strict=True)], list(offer.get('origins', [])))
        except Exception:
            # Pure topology parsing has no asynchronous context/cancellation
            # work. An ordinary supplier shape error cannot discard a local
            # route that has already completed.
            continue
