"""Coordinator unit fixtures with a programmable SDK boundary.

The opaque price oracle retains existing inert wire/timing/error controls. It
does not model AMM mathematics or call product native pricing. Real SDK tests
separately exercise arithmetic, pool acquisition and execution-state replay.
"""
from copy import deepcopy
from web3 import Web3

from cybergold_candidate.quote_errors import QuoteFailure, rpc_failure
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.rpc_diagnostics import quote_sdk_request
from cybergold_candidate.uniswap_routes import v3_path
from cybergold_candidate.uniswap_state import PoolRegistry, ZERO


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
        super().__init__(settings, registry, ProgrammableSdk(rpc))
        async def snapshot(pool, block, **_kwargs):
            read = registry.get_rpc().read_function
            address, = await read(rpc.pools.factory, 'getPool(address,address,uint24)',
                ['address', 'address', 'uint24'], [pool['token0']['address'], pool['token1']['address'],
                    pool['feePips']], ['address'], block)
            if address.lower() == ZERO:
                raise QuoteFailure('quote-no-route')
            liquidity, = await read(address, 'liquidity()', [], [], ['uint128'], block)
            return {**deepcopy(pool), 'liquidity': str(liquidity), '_fixtureBlock': deepcopy(block)}
        registry.snapshot = snapshot

    async def connector_inventory(self, *_args):
        # These controller tests retain the canonical initial V3 skeletons.
        pass

    async def close(self):
        await super().close()
        await self.registry.close()


class ProgrammableSdk:
    """Opaque SDK replies supplied by the existing in-memory price oracle."""
    def __init__(self, rpc):
        self.rpc = rpc

    async def close(self):
        pass

    async def request(self, payload):
        pools = {pool['id']: pool for pool in payload['pools']}
        if any(int(pool['liquidity']) == 0 for pool in pools.values()):
            raise QuoteFailure('quote-no-route')
        block = next(iter(pools.values()))['_fixtureBlock']
        mode = payload['mode']
        total_in = total_out = 0
        with quote_sdk_request() as acquired:
            acquired()
            for branch in payload['route']['branches']:
                hops = [{'pool': pools[hop['poolId']], 'zeroForOne': hop['zeroForOne']}
                    for hop in branch['hops']]
                path = v3_path(hops, mode == 'exactOut')
                amount = int(branch['amountIn']) if mode == 'exactIn' else int(payload['amount'])
                signature = 'quoteExactInput(bytes,uint256)' if mode == 'exactIn' else 'quoteExactOutput(bytes,uint256)'
                data = Web3.to_hex(Web3.keccak(text=signature)[:4] +
                    self.rpc.w3.codec.encode(['bytes', 'uint256'], [bytes.fromhex(path[2:]), amount]))
                # This is the test's programmable in-memory oracle transport;
                # production RouteQuoteEngine contains no contract price call.
                row, = await self.rpc.call_batch([(self.rpc.quoter, data)], block)
                if 'error' in row:
                    raise rpc_failure(row['error'])
                quoted, *_ = self.rpc.w3.codec.decode(['uint256', 'uint160[]', 'uint32[]', 'uint256'],
                    bytes.fromhex(row['result'][2:]))
                total_in += amount if mode == 'exactIn' else quoted
                total_out += quoted if mode == 'exactIn' else amount
        return {'amountIn': str(total_in), 'amountOut': str(total_out), 'fullyFilled': True,
            'settled': True, 'postState': deepcopy(payload['pools'])}


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
