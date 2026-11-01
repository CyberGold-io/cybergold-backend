"""Published UniRoute RouteFinder wired to current AMM topology nominations.

This is the public finder component, not the unavailable private full quote
optimizer. Existing canonical Quoter evaluation prices every nominated shape.
"""
from .alpha_routes import AlphaRoutes


class UnirouteLocal(AlphaRoutes):
    name = 'uniroute-local'

    def __init__(self, engine, command=None):
        # Reuse the session-owned child framing, cancellation and reaping.
        # This worker never requests a quote callback or needs pool state.
        super().__init__(engine, command=command or ['node', 'src/uniswap-sdk/uniroute-worker.ts'])
