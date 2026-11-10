"""Available suppliers for one producer-owned parallel route search."""
from .hosted_routes import UniRouteApiProvider, UniswapApiProvider
from .custom_routes import CustomRoutes
from .route_tools import PendingRouteTool


def route_providers(settings, engine):
    # Each search owns its framed calculations; healthy local children remain
    # with the engine. Construction starts neither a process nor an API call.
    from .alpha_routes import AlphaRoutes
    from .uniroute_routes import UnirouteLocal
    return [CustomRoutes(engine.registry), PendingRouteTool(engine.route_optimizer(AlphaRoutes).session()),
            PendingRouteTool(engine.route_optimizer(UnirouteLocal).session()),
            PendingRouteTool(UniRouteApiProvider(engine, settings, fastest=True)),
            PendingRouteTool(UniRouteApiProvider(engine, settings)),
            PendingRouteTool(UniswapApiProvider(engine, settings, guidestar=True))]
