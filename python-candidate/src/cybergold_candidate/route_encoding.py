"""The sole lowering boundary from economic routes to deployed adapter ABIs."""
from web3 import Web3

from .uniswap_routes import LEGACY_V3_ADAPTERS, standalone_v3, v3_path
from .routing_encoding import encode_routing


ZERO = '0x'+'00'*20
ADAPTER_TYPE = '(bool,uint256,uint256,(uint256,(uint8,address,uint24,int24,address,bytes)[])[])'
PROTOCOL = {'v2': 0, 'v3': 1, 'v4': 2}
ROUTING_ADAPTERS = set()


def register_routing_adapter(address):
    """Bind a release-configured deployed identity; never redirect captured data."""
    ROUTING_ADAPTERS.add(address.lower())


def encode_adapter(plan):
    """Existing typed Helpers ABI, shared by Market and non-V3/split Core."""
    branches = []
    for branch in plan['branches']:
        hops = []
        for hop in branch['hops']:
            pool = hop['pool']
            output = pool['token1' if hop['zeroForOne'] else 'token0']['address']
            hops.append((PROTOCOL[pool['protocol']], output, int(pool['feePips']),
                int(pool.get('tickSpacing') or 0), pool.get('hooks') or ZERO, b''))
        branches.append((int(branch['amountIn']) if plan['mode'] == 'exactIn' else 0, hops))
    return Web3.to_hex(Web3().codec.encode([ADAPTER_TYPE], [(
        plan['mode'] == 'exactIn', int(plan['limit']), int(plan['deadline']), branches)]))


def encode_route(plan, adapter=None):
    """Keep execution shape while choosing only the concrete adapter's wire ABI.

    Core's single V3 path has historically executed as one whole-path command,
    including on the multi-protocol adapter. Its typed per-hop counterpart has
    different custody/gas behavior, so format normalization must not change it.
    """
    if adapter and adapter.lower() in ROUTING_ADAPTERS:
        return encode_routing(plan)
    legacy = bool(adapter) and adapter.lower() in LEGACY_V3_ADAPTERS
    whole_v3 = standalone_v3(plan)
    if legacy or (plan['executionContext'] == 'helpers-core' and whole_v3):
        if not whole_v3:
            raise ValueError('Historical V3 adapter cannot encode this route.')
        exact_in = plan['mode'] == 'exactIn'
        path = v3_path(plan['branches'][0]['hops'], not exact_in)
        return Web3.to_hex(Web3().codec.encode(['bytes', 'uint256', 'uint256', 'bool'], [
            bytes.fromhex(path[2:]), int(plan['limit']), int(plan['deadline']), exact_in]))
    return encode_adapter(plan)
