"""Exact discovery identities computed once for captured immutable routes."""
import pickle

from ..prepared_values import FrozenDict, FrozenList, freeze
from ..routing_encoding import ZERO, weighted_shares
from ..uniswap_routes import pool_identity


def pool_parts(pool):
    def calculate():
        return (pool_identity(pool), ((pool.get('address') or '').lower(),
            (pool.get('poolManager') or '').lower(), int(pool.get('tickSpacing') or 0),
            (pool.get('hooks') or ZERO).lower(),
            tuple((pool[name]['address'].lower(), pool[name].get('chainId'),
                   pool[name].get('decimals')) for name in ('token0', 'token1'))))
    if not isinstance(pool, FrozenDict):
        return calculate()
    if 'nomination-pool' not in pool.derived:
        pool.derived['nomination-pool'] = calculate()
    return pool.derived['nomination-pool']


def nomination_identity(branches, *, lots=True, shares=None):
    def calculate():
        leading = [row['hops'][0].get('kind') for row in branches if row['hops']]
        strip = (not lots and len(leading) == len(branches) and leading
                 and leading[0] in ('wrap', 'unwrap') and all(kind == leading[0] for kind in leading))
        paths = []
        for row in branches:
            hops = row['hops'][1:] if strip else row['hops']
            route, extras = [], []
            for hop in hops:
                if 'pool' in hop:
                    identity, extra = pool_parts(hop['pool'])
                    route.append((identity, hop['zeroForOne']))
                    extras.append(extra)
                else:
                    route.append((hop['kind'], hop['currencyOut'].lower()))
            paths.append((tuple(route), tuple(extras)))
        weights = (tuple(int(row['amountIn']) for row in branches) if lots else
                   weighted_shares(branches) if shares is None else shares)
        return tuple(zip(weights, paths, strict=True))
    if not isinstance(branches, FrozenList):
        return calculate()
    key = lots, None if shares is None else tuple(shares)
    if key not in branches.derived:
        branches.derived[key] = calculate()
    return branches.derived[key]


def _prepared_pool(pool, memo, values):
    identity = id(pool)
    if identity in memo:
        return memo[identity]
    try:
        # The existing job capture/pipe already owns this exact representation.
        # Equal copies can share immutable observations; amounts, paths and
        # mutable row/hop containers are not interned. Keep ordering and scalar
        # types in the key, without a digest or a new nomination predicate.
        key = pickle.dumps(pool, protocol=5)
    except Exception:
        return freeze(pool, memo)  # Optional reuse cannot introduce an error.
    if key not in values:
        values[key] = freeze(pool, memo)
    memo[identity] = values[key]
    return values[key]


def prepare_rows(rows):
    """Private job: share both aliased and exactly equal captured pool values."""
    memo, values = {}, {}
    for row in rows:
        try:
            for branch in row:
                for hop in branch['hops']:
                    if 'pool' in hop:
                        hop['pool'] = _prepared_pool(hop['pool'], memo, values)
            identities = nomination_identity(row), nomination_identity(row, lots=False)
        except Exception:
            identities = None  # Ordinary malformed-nomination consumer path.
        yield row, identities
