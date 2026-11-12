"""CyberGold's existing generic graph search through the shared route API.

Core anchoring, seed preference, private-state replay and funding compilation
belong to the consuming CyberGold adapter, not this AMM path provider.
"""
from .discovery import path_steps, route_candidate_steps
from .cooperative import values
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
        return values(self.cooperative_steps())

    def cooperative_steps(self, projection_steps=None):
        routes = yield from path_steps(list(self.registry.inventory.values()), self.query.source, self.query.target)
        if projection_steps is not None:
            routes = yield from projection_steps(routes)
        elif self.projection is not None:
            routes = list(self.projection(routes))
        yield from route_candidate_steps(routes, self.query.amount)


class CustomRoutes(RouteTool):
    name = 'cybergold-custom'

    def __init__(self, registry):
        self.registry = registry

    def discover(self, query):
        return CandidateFeed(available=_AvailableRoutes(self.registry, query))
