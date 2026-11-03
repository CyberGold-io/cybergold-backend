"""CyberGold's existing generic graph search through the shared route API.

Core anchoring, seed preference, private-state replay and funding compilation
belong to the consuming CyberGold adapter, not this AMM path provider.
"""
from .discovery import path_steps, early_path_steps, route_candidates, route_identity
from .cooperative import CHECKPOINT, close, values
from .route_tools import CandidateFeed, RouteTool


class _AvailableRoutes:
    # Consumers preserve this producer's early order instead of buffering all
    # linear paths a second time before allowing its first nomination through.
    progressive_nominations = True

    def __init__(self, registry, query, projection=None, early_paths=None):
        self.registry, self.query, self.projection = registry, query, projection
        self.early_paths = early_paths

    def with_path_projection(self, projection):
        return _AvailableRoutes(self.registry, self.query, projection, self.early_paths)

    def with_early_paths(self, early_paths):
        return _AvailableRoutes(self.registry, self.query, self.projection, early_paths)

    def __iter__(self):
        # A query can precede ordinary catalog acquisition. Each consumption
        # sees today's request-owned inventory instead of buffering its old
        # paths or materializing the combinatorial split proposals.
        return values(self.cooperative_steps())

    def cooperative_steps(self, projection_steps=None):
        def project(routes):
            if projection_steps is not None:
                return (yield from projection_steps(routes))
            return list(self.projection(routes)) if self.projection is not None else routes
        pools = list(self.registry.inventory.values())
        early = yield from (self.early_paths(pools) if self.early_paths is not None else
            early_path_steps(pools, self.query.source, self.query.target))
        early = yield from project(early)
        emitted = set()
        for route in early:
            emitted.add(route_identity(route))
            yield CHECKPOINT
            yield [{'amountIn': str(self.query.amount), 'hops': route}]
        routes = yield from path_steps(pools, self.query.source, self.query.target)
        routes = yield from project(routes)
        for route in routes:
            yield CHECKPOINT
            if route_identity(route) not in emitted:
                yield [{'amountIn': str(self.query.amount), 'hops': route}]
        # Splits retain the full original route list and allocation order,
        # including paths whose single nomination was emitted early.
        candidates = route_candidates(routes, self.query.amount)
        try:
            for candidate in candidates:
                yield CHECKPOINT
                if len(candidate) > 1:
                    yield candidate
        finally:
            close(candidates)


class CustomRoutes(RouteTool):
    name = 'cybergold-custom'

    def __init__(self, registry):
        self.registry = registry

    def discover(self, query):
        return CandidateFeed(available=_AvailableRoutes(self.registry, query))
