"""CyberGold execution adaptation over the shared AMM discovery API.

Tools nominate only AMM branches. Core previews, whole-plan fees and final
selection stay in the Quoter; both Market and Market+Core conversions use this
adapter for anchor/native/split semantics and candidate-private replay.
"""
import asyncio
from copy import deepcopy
from collections import defaultdict
from itertools import chain

from ..quote_errors import QuoteFailure, public_quote_error
from ..recovery_rpc import SnapshotChanged
from ..routing_encoding import weighted_routes, split_runtime
from ..uniswap_routes import pool_identity
from .bootstrap import current_bootstrap
from .candidate_hints import normalize_hints
from .custom_routes import CustomRoutes
from .route_tools import RouteQuery, round_robin


def identity_template(currency):
    return {'inputCurrency': currency, 'outputCurrency': currency, 'routes': []}


def route_priority(route, edge):
    return (sum(hop['pool']['protocol'] != 'v3' and pool_identity(hop['pool']) != edge
                for hop in route if 'pool' in hop),
            sum(hop['pool']['protocol'] == 'v3' and not hop['pool'].get('address')
                for hop in route if 'pool' in hop),
            sum(hop['pool']['protocol'] == 'v3' and hop['pool']['feePips'] != 3000
                for hop in route if 'pool' in hop), len(route))


def prioritize_candidates(candidates, registry):
    # Buffer only the immediate prefix of single paths for the existing quick
    # V3 seed preference. Split combinations remain lazy for every provider.
    singles, iterator, tail = [], iter(candidates), ()
    for candidate, origins in iterator:
        if len(candidate) != 1:
            tail = ((candidate, origins),)
            break
        singles.append((candidate, origins))
    edge = pool_identity(registry.seed)
    candidates = chain(sorted(singles, key=lambda item: route_priority(item[0][0]['hops'], edge)), tail, iterator)
    yield from candidates


def adapt_candidates(candidates, source, core, *, market=False, anchor=None):
    seen = {}
    for candidate, origins in candidates:
        try:
            weights = weighted_routes(candidate)
            from .discovery import route_identity
            identity = tuple((weight['sharePpm'], route_identity(row['hops']))
                for row, weight in zip(candidate, weights, strict=True))
            if market and any(pool_identity(next(hop for hop in (row['hops'] if source.lower() == core.lower()
                    else reversed(row['hops'])) if 'pool' in hop)['pool']) != anchor for row in candidate):
                continue
            if identity in seen:
                seen[identity].extend(name for name in origins if name not in seen[identity])
                continue
            seen[identity] = list(dict.fromkeys(origins))
            yield candidate, seen[identity]
        except (KeyError, TypeError, ValueError, StopIteration):
            continue


def linear_prefix(feed):
    # The existing optional family/prefix-repair jobs consume single paths.
    # Built-in tools emit those before split alternatives; ordinary conversion
    # still consumes every split nomination through the same API.
    for candidate, origins in feed:
        if len(candidate) != 1:
            break
        yield candidate, origins


class CyberGoldAmmAdapter:
    def __init__(self, engine, core):
        self.engine, self.core = engine, core

    def nominations(self, source, target, amount, block, *, market=False, first=False, linear_only=False):
        registry = self.engine.registry
        bootstrap = current_bootstrap()
        query = RouteQuery(source, target, int(amount), block)
        anchor = pool_identity(registry.seed) if market else None
        def project_paths(routes):
            if market:
                routes = [route for route in routes if pool_identity(next(hop for hop in
                    (route if source.lower() == self.core.lower() else reversed(route))
                    if 'pool' in hop)['pool']) == anchor]
            if first:
                routes = sorted(routes, key=lambda route: route_priority(route, pool_identity(registry.seed)))
            return routes
        if bootstrap is not None:
            feeds = bootstrap.offer_feeds(source, target, amount, block, path_projection=project_paths)
        else:
            feed = CustomRoutes(registry).discover(query)
            feeds = [({'branches': candidate, 'origins': ['cybergold-custom']}
                      for candidate in feed.available_projected(project_paths))]
        feeds = [normalize_hints(offers, source, target) for offers in feeds]
        if first:
            feeds = [prioritize_candidates(feed, registry) for feed in feeds]
        if linear_only:
            feeds = [linear_prefix(feed) for feed in feeds]
        return adapt_candidates(round_robin(feeds), source, self.core, market=market, anchor=anchor)

    def family_offers(self, source, target, amount, block):
        groups = defaultdict(list)
        for branches, origins in self.nominations(source, target, amount, block, market=True, linear_only=True):
            route = branches[0]['hops']
            currencies, protocols = [source.lower()], []
            for hop in route:
                if 'pool' in hop:
                    pool = hop['pool']
                    protocols.append(pool['protocol'])
                    currencies.append(pool['token1' if hop['zeroForOne'] else 'token0']['address'].lower())
                else:
                    protocols.append(hop['kind'])
                    currencies.append(hop['currencyOut'].lower())
            groups[(tuple(currencies), tuple(protocols))].append((route, origins))
        result = []
        for key, rows in sorted(groups.items(), key=lambda row: (len(row[0][1]), repr(row[0]))):
            rows.sort(key=lambda row: tuple((hop['pool']['feePips'], repr(pool_identity(hop['pool'])))
                if 'pool' in hop else (-1, hop['kind']) for hop in row[0]))
            result.append((key, rows))
        return result

    async def convert(self, source, target, amount, block, bank, canonical, *, market=False,
                         first=False, branch=0, stage=0, capture=None, price_path=None):
        if not amount or source.lower() == target.lower():
            if capture is not None:
                capture.update(inputCurrency=source, outputCurrency=target, branches=[],
                               _observation={'inputCurrency': source, 'fundedInput': str(amount),
                                             'consumedInput': str(amount), 'outputCurrency': target, 'output': str(amount)})
            return identity_template(source), amount, []
        candidates = self.nominations(source, target, amount, block, market=market, first=first)
        best, rpc_error = None, None
        for branches, origins in candidates:
            # A common leading wrap belongs to Helpers funding, not to the
            # adapter's whole-conversion intermediate set.
            trial = deepcopy(bank)
            output, consumed, retained = 0, 0, []
            try:
                leading = [row['hops'][0].get('kind') for row in branches]
                normalized = deepcopy(branches)
                physical_source = source
                if leading and leading[0] in ('wrap', 'unwrap') and all(value == leading[0] for value in leading):
                    physical_source = normalized[0]['hops'][0]['currencyOut']
                    for row in normalized:
                        row['hops'] = row['hops'][1:]
                routes = weighted_routes(normalized)
                for row, funded in zip(normalized, split_runtime(amount, routes), strict=True):
                    row['amountIn'] = str(funded)
                for row in normalized:
                    funded = int(row['amountIn'])
                    used, received = await price_path(row['hops'], funded, block, trial, canonical)
                    output += received
                    consumed += used
                    if used < funded:
                        retained.append({'branch': branch, 'stage': stage + (physical_source.lower() != source.lower()), 'currency': physical_source,
                                         'amount': str(funded - used)})
            except SnapshotChanged:
                raise
            except Exception as error:
                if public_quote_error(error).get('code', '').startswith('rpc-'):
                    rpc_error = error
                continue
            if retained:
                retained = [{**retained[0], 'amount': str(sum(int(row['amount']) for row in retained))}]
            if best is None or output > best[0]:
                template = {'inputCurrency': physical_source, 'outputCurrency': target,
                            'routes': routes}
                best = output, template, retained, trial, deepcopy(normalized), consumed, origins
                if first and output > 0:
                    break
            await asyncio.sleep(0)
        if best is None:
            raise rpc_error or QuoteFailure('quote-no-route')
        if capture is not None:
            capture.update(inputCurrency=source, outputCurrency=target, branches=[{'hops': row['hops']} for row in best[4]], template=deepcopy(best[1]),
                           discoveryOrigins=sorted(best[6]),
                           _observation={'inputCurrency': best[1]['inputCurrency'], 'fundedInput': str(amount),
                                         'consumedInput': str(best[5]), 'outputCurrency': target, 'output': str(best[0])})
        bank.clear()
        bank.update(best[3])
        return best[1], best[0], best[2]
