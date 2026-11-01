"""CyberGold's existing generic graph search through the shared route API.

Core anchoring, seed preference, private-state replay and funding compilation
belong to the consuming CyberGold adapter, not this AMM path provider.
"""
from .discovery import paths, route_candidates
from .route_tools import CandidateFeed, RouteTool


class _AvailableRoutes:
    def __init__(self, registry, query, projection=None):
        self.registry, self.query, self.projection = registry, query, projection

    def with_path_projection(self, projection):
        return _AvailableRoutes(self.registry, self.query, projection)

    def __iter__(self):
        # A query can precede ordinary catalog acquisition. Each consumption
        # sees today's request-owned inventory instead of buffering its old
        # paths or materializing the combinatorial split proposals.
        routes = paths(list(self.registry.inventory.values()), self.query.source, self.query.target)
        if self.projection is not None:
            routes = list(self.projection(routes))
        yield from route_candidates(routes, self.query.amount)


class CustomRoutes(RouteTool):
    name = 'cybergold-custom'

    def __init__(self, registry):
        self.registry = registry

    def discover(self, query):
        return CandidateFeed(available=_AvailableRoutes(self.registry, query))
