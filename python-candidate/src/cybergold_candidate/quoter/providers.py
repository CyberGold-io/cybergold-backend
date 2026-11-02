"""Available suppliers for one producer-owned parallel route search."""
from .hosted_routes import UniRouteApiProvider, UniswapApiProvider
from .custom_routes import CustomRoutes
from .route_tools import PendingRouteTool


def route_providers(settings, engine):
    # Keep the optimizer's process owned by this search. No process/key is
    # needed to construct the API runtime or to replay a selected transaction.
    from .alpha_routes import AlphaRoutes
    from .uniroute_routes import UnirouteLocal
    return [CustomRoutes(engine.registry), PendingRouteTool(AlphaRoutes(engine)),
            PendingRouteTool(UnirouteLocal(engine)), PendingRouteTool(UniRouteApiProvider(engine, settings)),
            PendingRouteTool(UniswapApiProvider(engine, settings, guidestar=True))]
