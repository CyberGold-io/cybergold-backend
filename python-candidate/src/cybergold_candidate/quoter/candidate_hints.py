"""Interleave available topology hints with ordinary candidates; never wait."""
from itertools import product, zip_longest

from ..uniswap_routes import pool_identity
from ..routing_encoding import weighted_routes
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


def interleave(ordinary, hints, *, market=False, core=None, source=None, anchor=None):
    """Current Market anchor applies to every nominated split branch too."""
    seen = {}
    for pair in zip_longest(ordinary, hints):
        for index, item in enumerate(pair):
            if item is None:
                continue
            try:
                candidate, origins = (item, ['cybergold-custom']) if index == 0 else item
                weights = weighted_routes(candidate)
                identity = tuple((weight['sharePpm'], route_identity(row['hops']))
                                 for row, weight in zip(candidate, weights, strict=True))
                if identity in seen:
                    seen[identity].extend(name for name in origins if name not in seen[identity])
                    continue
                if market:
                    for row in candidate:
                        hops = row['hops'] if source.lower() == core.lower() else reversed(row['hops'])
                        edge = next(hop for hop in hops if 'pool' in hop)
                        if pool_identity(edge['pool']) != anchor:
                            break
                    else:
                        seen[identity] = list(dict.fromkeys(origins))
                        yield candidate, seen[identity]
                    continue
                seen[identity] = list(dict.fromkeys(origins))
                yield candidate, seen[identity]
            except (KeyError, TypeError, ValueError, StopIteration):
                # An unsupported provider shape is one unavailable candidate,
                # never a prerequisite for the ordinary candidates beside it.
                continue
