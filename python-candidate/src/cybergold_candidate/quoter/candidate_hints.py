"""Interleave available topology hints with ordinary candidates; never wait."""
from itertools import product

from .discovery import path_steps
from .cooperative import CHECKPOINT, close, values


def normalize_hints(hints, source, target):
    return values(normalize_steps(hints, source, target))


def normalize_steps(hints, source, target):
    """The existing path producer owns connectivity and native transitions.

    A hint offers a pool graph and split weights, never authority to relabel
    unrelated hop output as the requested currency. Reconstruct directions
    rather than introducing a second route-validation policy.
    """
    try:
        for offer in hints:
            yield CHECKPOINT
            if offer is CHECKPOINT:
                continue
            try:
                candidate = offer['branches']
                alternatives = []
                for row in candidate:
                    alternatives.append((yield from path_steps(
                        [hop['pool'] for hop in row['hops'] if 'pool' in hop], source, target)))
                for routes in product(*alternatives) if alternatives else ():
                    yield CHECKPOINT
                    yield ([{'amountIn': row['amountIn'], 'hops': route}
                            for row, route in zip(candidate, routes, strict=True)], list(offer.get('origins', [])))
            except Exception:
                # Ordinary malformed topology does not discard a sibling.
                continue
    finally:
        close(hints)
