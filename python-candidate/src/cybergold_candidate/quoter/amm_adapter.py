"""CyberGold execution adaptation over the shared AMM discovery API.

Tools nominate only AMM branches. Core previews, whole-plan fees and final
selection stay in the Quoter; both Market and Market+Core conversions use this
adapter for anchor/native/split semantics and candidate-private replay.
"""
import asyncio
from copy import deepcopy
from collections import defaultdict

from ..quote_errors import QuoteFailure, public_quote_error
from ..recovery_rpc import SnapshotChanged
from ..routing_encoding import weighted_routes, split_runtime
from ..uniswap_routes import pool_identity
from ..pool_snapshot import copy_pool_bank
from .bootstrap import current_bootstrap
from .candidate_hints import normalize_steps
from .custom_routes import CustomRoutes
from .contracts import path_nomination, capture_paths
from .discovery import current_topology, route_identity, seeded_path_steps
from .route_tools import RouteQuery, round_robin
from .cooperative import CHECKPOINT, close, values, async_values, async_finish, finish, sort_steps
from .amm import PartialPath
from .prefix import backward_input


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
    return values(prioritize_steps(candidates, registry))


def prioritize_steps(candidates, registry):
    # Buffer only the immediate prefix of single paths for the existing quick
    # V3 seed preference. Split combinations remain lazy for every provider.
    singles, iterator, tail = [], iter(candidates), ()
    try:
        for value in iterator:
            yield CHECKPOINT
            if value is CHECKPOINT:
                continue
            candidate, origins = value
            if len(candidate) != 1:
                tail = ((candidate, origins),)
                break
            singles.append((candidate, origins))
        edge = pool_identity(registry.seed)
        singles = yield from sort_steps(singles, key=lambda item: route_priority(item[0][0]['hops'], edge))
        yield from singles
        yield from tail
        yield from iterator
    finally:
        close(iterator)


def adapt_candidates(candidates, source, core, *, market=False, anchor=None):
    return values(adapt_steps(candidates, source, core, market=market, anchor=anchor))


def adapt_steps(candidates, source, core, *, market=False, anchor=None):
    seen = {}
    try:
        for value in candidates:
            yield CHECKPOINT
            if value is CHECKPOINT:
                continue
            candidate, origins = value
            try:
                topology = current_topology()
                if topology is not None:
                    identity = topology.nomination_identity(candidate)
                else:
                    weights = weighted_routes(candidate)
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
    finally:
        close(candidates)


def linear_prefix(feed):
    # The existing optional family/prefix-repair jobs consume single paths.
    # Built-in tools emit those before split alternatives; ordinary conversion
    # still consumes every split nomination through the same API.
    try:
        for value in feed:
            if value is CHECKPOINT:
                yield value
                continue
            candidate, origins = value
            if len(candidate) != 1:
                break
            yield candidate, origins
    finally:
        close(feed)


class CyberGoldAmmAdapter:
    def __init__(self, engine, core):
        self.engine, self.core = engine, core

    def nominations(self, source, target, amount, block, *, market=False, first=False, linear_only=False):
        return values(self.nomination_steps(source, target, amount, block,
            market=market, first=first, linear_only=linear_only))

    def async_nominations(self, source, target, amount, block, **options):
        return async_values(self.nomination_steps(source, target, amount, block, **options))

    def nomination_steps(self, source, target, amount, block, *, market=False, first=False, linear_only=False):
        registry = self.engine.registry
        bootstrap = current_bootstrap()
        # A registered query may have no ready hint for this consumer yet.
        # Reuse the short prefix until actual supplier/completed offers exist.
        initial_custom = first and (bootstrap is None or not bootstrap.has_ready_offers(source, target, amount))
        query = RouteQuery(source, target, int(amount), block)
        anchor = pool_identity(registry.seed) if market else None
        def project_paths(routes):
            return finish(project_steps(routes))
        def project_steps(routes):
            if market:
                selected = []
                for route in routes:
                    yield CHECKPOINT
                    if pool_identity(next(hop for hop in
                            (route if source.lower() == self.core.lower() else reversed(route))
                            if 'pool' in hop)['pool']) == anchor:
                        selected.append(route)
                routes = selected
            if first:
                routes = yield from sort_steps(routes,
                    key=lambda route: route_priority(route, pool_identity(registry.seed)))
            return routes
        if bootstrap is not None:
            feeds = bootstrap.offer_feeds(source, target, amount, block, path_projection=project_paths,
                cooperative=True, projection_steps=project_steps)
        else:
            feed = CustomRoutes(registry).discover(query)
            def offers():
                candidates = iter(feed.available_steps(project_paths, project_steps))
                try:
                    for candidate in candidates:
                        yield CHECKPOINT if candidate is CHECKPOINT else {
                            'branches': candidate, 'origins': ['cybergold-custom']}
                finally:
                    close(candidates)
            feeds = [offers()]
        feeds = [normalize_steps(offers, source, target) for offers in feeds]
        if first:
            feeds = [prioritize_steps(feed, registry) for feed in feeds]
        if linear_only:
            feeds = [linear_prefix(feed) for feed in feeds]
        ordinary = round_robin(feeds)
        initial_provider = (next((provider for _, provider in bootstrap.providers
                                  if isinstance(provider, CustomRoutes)), None)
                            if initial_custom and bootstrap is not None else None)
        if initial_custom and (bootstrap is None or initial_provider is not None):
            def initial_then(remaining):
                try:
                    routes = []
                    for route in seeded_path_steps(list(registry.inventory.values()), registry.seed, source, target):
                        if route is CHECKPOINT:
                            yield route
                        else:
                            routes.append(route)
                    routes = yield from sort_steps(routes,
                        key=lambda route: route_priority(route, pool_identity(registry.seed)))
                    for route in routes:
                        if bootstrap is not None:
                            bootstrap.observe_initial_candidate(query, initial_provider)
                        yield [{'amountIn': str(amount), 'hops': route}], ['cybergold-custom']
                    yield from remaining
                finally:
                    close(remaining)
            ordinary = initial_then(ordinary)
        return adapt_steps(ordinary, source, self.core, market=market, anchor=anchor)

    def family_offers(self, source, target, amount, block):
        return finish(self.family_steps(source, target, amount, block))

    async def async_family_offers(self, source, target, amount, block):
        return await async_finish(self.family_steps(source, target, amount, block))

    def family_steps(self, source, target, amount, block):
        groups = defaultdict(list)
        candidates = self.nomination_steps(source, target, amount, block, market=True, linear_only=True)
        try:
            yield from self._group_families(candidates, groups, source)
        finally:
            close(candidates)
        result = []
        ordered = yield from sort_steps(groups.items(), key=lambda row: (len(row[0][1]), repr(row[0])))
        for key, rows in ordered:
            rows = yield from sort_steps(rows, key=lambda row: tuple((hop['pool']['feePips'], repr(pool_identity(hop['pool'])))
                if 'pool' in hop else (-1, hop['kind']) for hop in row[0]))
            result.append((key, rows))
        return result

    def _group_families(self, candidates, groups, source):
        for value in candidates:
            yield CHECKPOINT
            if value is CHECKPOINT:
                continue
            branches, origins = value
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

    async def convert(self, source, target, amount, block, bank, canonical, *, market=False,
                         first=False, branch=0, stage=0, capture=None, price_path=None):
        if not amount or source.lower() == target.lower():
            if capture is not None:
                capture.update(inputCurrency=source, outputCurrency=target, branches=[],
                               _observation={'inputCurrency': source, 'fundedInput': str(amount),
                                             'consumedInput': str(amount), 'outputCurrency': target, 'output': str(amount)})
            return identity_template(source), amount, []
        candidates = self.async_nominations(source, target, amount, block, market=market, first=first)
        best, rpc_error = None, None
        try:
            async for branches, origins in candidates:
                # A common leading wrap belongs to Helpers funding, not to the
                # adapter's whole-conversion intermediate set.
                try:
                    leading = [row['hops'][0].get('kind') for row in branches]
                    normalized = deepcopy(branches)
                    physical_source = source
                    if leading and leading[0] in ('wrap', 'unwrap') and all(value == leading[0] for value in leading):
                        physical_source = normalized[0]['hops'][0]['currencyOut']
                        for row in normalized:
                            row['hops'] = row['hops'][1:]
                    routes = weighted_routes(normalized)
                    async def replay(funding):
                        trial = copy_pool_bank(bank)
                        output, consumed, retained = 0, 0, []
                        for row, funded in zip(normalized, split_runtime(funding, routes), strict=True):
                            row['amountIn'] = str(funded)
                            with path_nomination(source, origins), capture_paths(reuse=True):
                                used, received = await price_path(row['hops'], funded, block, trial, canonical)
                            output += received
                            consumed += used
                            if used < funded:
                                retained.append({'branch': branch,
                                    'stage': stage + (physical_source.lower() != source.lower()),
                                    'currency': physical_source, 'amount': str(funded-used)})
                        return output, consumed, retained, trial
                    funding = amount
                    try:
                        output, consumed, retained, trial = await replay(funding)
                    except PartialPath as error:
                        from .capacity_recovery import scaled_funding
                        repaired = await backward_input(self, error.trace)
                        if repaired is None:
                            continue
                        funding = scaled_funding(amount, error.trace.funded, repaired)
                        if not 0 < funding < amount:
                            continue
                        # The failed trial advanced its prefix. Reconstruct the
                        # whole conversion from the preceding operation's bank,
                        # retaining route weights and actual split order.
                        output, consumed, retained, trial = await replay(funding)
                except SnapshotChanged:
                    raise
                except Exception as error:
                    if public_quote_error(error).get('code', '').startswith('rpc-'):
                        rpc_error = error
                    continue
                if retained:
                    retained = [{**retained[0], 'amount': str(sum(int(row['amount']) for row in retained))}]
                if best is None or output > best[0] or (output == best[0] and funding < best[7]):
                    template = {'inputCurrency': physical_source, 'outputCurrency': target,
                                'routes': routes}
                    best = output, template, retained, trial, deepcopy(normalized), consumed, origins, funding
                    if first and output > 0:
                        break
                await asyncio.sleep(0)
        finally:
            await candidates.aclose()
        if best is None:
            raise rpc_error or QuoteFailure('quote-no-route')
        if capture is not None:
            capture.update(inputCurrency=source, outputCurrency=target, branches=[{'hops': row['hops']} for row in best[4]], template=deepcopy(best[1]),
                           discoveryOrigins=sorted(best[6]),
                           _observation={'inputCurrency': best[1]['inputCurrency'], 'fundedInput': str(best[7]),
                                         'consumedInput': str(best[5]), 'outputCurrency': target, 'output': str(best[0])})
            if best[7] != amount:
                capture['_funding'] = best[7]
        bank.clear()
        bank.update(best[3])
        return best[1], best[0], best[2]
