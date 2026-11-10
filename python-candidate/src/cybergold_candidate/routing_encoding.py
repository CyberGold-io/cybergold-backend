"""Lower economic routes into the no-hook UniswapRoutingAdapter payload.

The deployed legacy encoders remain separate: an address change never relabels
an old payload. Native/WETH transitions are explicit, lossless route steps.
"""
from web3 import Web3

ZERO = '0x' + '00' * 20
ROUTING_ENCODING = 'uniswap-routing-v1'
ROUTING_TYPE = '(bool,uint256,uint256,(uint256,(uint8,address,uint24,int24)[])[])'
STEP_KIND = {'v2': 0, 'v3': 1, 'v4': 2, 'wrap': 3, 'unwrap': 4}


def route_steps(hops):
    steps = []
    for hop in hops:
        if 'kind' in hop:
            kind = hop['kind']
            steps.append((STEP_KIND[kind], Web3.to_checksum_address(hop['currencyOut']), 0, 0))
            continue
        pool = hop['pool']
        if pool.get('hooks', ZERO).lower() != ZERO:
            raise ValueError('A no-hook route cannot encode a hooked PoolKey.')
        output = pool['token1' if hop['zeroForOne'] else 'token0']['address']
        steps.append((STEP_KIND[pool['protocol']], Web3.to_checksum_address(output),
                      int(pool['feePips']), int(pool.get('tickSpacing') or 0)))
    return steps


def encode_routing(plan):
    exact_in = plan['mode'] == 'exactIn'
    branches = [(int(branch['amountIn']) if exact_in else 0, route_steps(branch['hops']))
                for branch in plan['branches']]
    return Web3.to_hex(Web3().codec.encode([ROUTING_TYPE], [
        (exact_in, int(plan['limit']), int(plan['deadline']), branches)]))


def weighted_shares(branches):
    """Compute only the encoded ppm weights; the final route owns remainder."""
    total = sum(int(branch['amountIn']) for branch in branches)
    return [0 if index == len(branches)-1 else int(branch['amountIn']) * 1_000_000 // total
            for index, branch in enumerate(branches)]


def weighted_routes(branches):
    """The final route owns integer remainder, exactly as the Solidity template."""
    routes = []
    for branch, share in zip(branches, weighted_shares(branches), strict=True):
        routes.append({'sharePpm': share, 'steps': [
            {'kind': kind, 'currencyOut': output, 'fee': fee, 'tickSpacing': spacing}
            for kind, output, fee, spacing in route_steps(branch['hops'])]})
    return routes


def exact_output_routes(branches):
    """Round funding up so encoded path lots cover their exact-output inputs."""
    amounts = [int(branch['amountIn']) for branch in branches]
    total = sum(amounts)
    routes = weighted_routes(branches)
    # Reserve one ppm for every positive path, including sub-ppm inputs.
    remaining = 1_000_000 - sum(amount > 0 for amount in amounts)
    for amount, route in zip(amounts[:-1], routes[:-1], strict=True):
        route['sharePpm'] = 1 + amount * remaining // total if amount else 0
    shares = [route['sharePpm'] for route in routes[:-1]]
    shares.append(1_000_000 - sum(shares))
    funding = max((amount * 1_000_000 + share - 1) // share
                  for amount, share in zip(amounts, shares, strict=True) if amount)
    return funding, routes


def split_runtime(amount, routes):
    allocated, result = 0, []
    for index, route in enumerate(routes):
        value = amount - allocated if index == len(routes) - 1 else amount * int(route['sharePpm']) // 1_000_000
        if value < 0 or value > amount - allocated:
            raise ValueError('Runtime route allocation exceeds its source lot.')
        result.append(value)
        allocated += value
    return result
