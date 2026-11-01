"""Published UniRoute finder and split search over canonical quote callbacks."""
from .alpha_routes import AlphaRoutes


class UnirouteLocal(AlphaRoutes):
    name = 'uniroute-local'

    def __init__(self, engine, command=None):
        # Reuse the session-owned child framing, cancellation and reaping.
        # Finder batches arrive before the deeper percentage quote callbacks.
        super().__init__(engine, command=command or ['node', 'src/uniswap-sdk/uniroute-worker.ts'])
