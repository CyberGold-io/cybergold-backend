"""Real common engine over the retained inert RouteSearchRpc wire fixtures.

Only optional metadata/discovery I/O is unavailable here. Native contract
pricing, known-empty pool observations, ABI encoding and the candidate scheduler
are the ordinary product implementations.
"""
from web3 import Web3

from cybergold_candidate.quote_errors import rpc_failure
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.uniswap_state import PoolRegistry


class FixturePoolRpc:
    def __init__(self, rpc):
        self.rpc = rpc
        self.chain_id = rpc.chain_id
        self.w3 = rpc.w3
        self.factory = rpc.pools.factory

    async def block(self, block_hash):
        return await self.rpc.block(block_hash)

    async def assert_canonical(self, block):
        await self.rpc.assert_canonical(block)

    async def read_function(self, address, signature, inputs, args, outputs, block):
        data = Web3.to_hex(Web3.keccak(text=signature)[:4] + self.w3.codec.encode(inputs, args))
        calls = [(address, data)]
        if signature.startswith('quoteExact'):
            rows = await self.rpc.call_batch(calls, block)
        else:
            rows, _ = await self.rpc.pool_batch(calls, block, {})
        row = rows[0]
        if 'error' in row:
            raise rpc_failure(row['error'])
        return self.w3.codec.decode(outputs, bytes.fromhex(row['result'][2:]))

    async def close(self):
        # The facade owns the retained wire transport.
        pass


class FixtureRouteEngine(RouteQuoteEngine):
    def __init__(self, settings, rpc):
        registry = PoolRegistry(settings, rpc=FixturePoolRpc(rpc))
        registry.inventory = {}
        super().__init__(settings, registry)
        async def unavailable(*_args, **_kwargs):
            raise ValueError('Optional fixture pool metadata is unavailable')
        registry.snapshot = unavailable

    async def connector_inventory(self, *_args):
        # Original fixtures describe the original V3 Quoter candidate universe.
        pass

    async def close(self):
        await super().close()
        await self.registry.close()


def install_fixture_engine(routes):
    """Attach and close a test-owned engine alongside its existing facade."""
    engine = FixtureRouteEngine(routes.settings, routes.rpc)
    routes.engine = engine
    close = routes.close
    async def close_fixture():
        await engine.close()
        await close()
    routes.close = close_fixture
    return engine
