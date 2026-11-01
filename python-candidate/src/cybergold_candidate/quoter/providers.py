"""Available suppliers for one producer-owned parallel route search."""
from .hosted_routes import UniswapApiProvider


def route_providers(settings, engine):
    # Keep the optimizer's process owned by this search. No process/key is
    # needed to construct the API runtime or to replay a selected transaction.
    from .alpha_routes import AlphaRoutes
    return [AlphaRoutes(engine), UniswapApiProvider(engine, settings),
            UniswapApiProvider(engine, settings, guidestar=True)]
