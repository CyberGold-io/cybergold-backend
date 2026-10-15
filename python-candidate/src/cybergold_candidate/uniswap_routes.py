"""Protocol-aware identities and route order; no AMM arithmetic."""
from copy import deepcopy
import asyncio
from typing import Literal

from pydantic import BaseModel
from .app_tokens import TOKENS
from .uniswap_v4 import v4_pool_id

# Canonical historical deployment (Ops mainnet-app-contracts / Helpers release).
# This is encoder dispatch, not an adapter approval or transaction admission check.
LEGACY_V3_ADAPTERS = {'0x4edb8190232a47e45d861003672938eb7ee84a15'}
V3_DIRECT_FEES = (100, 500, 3000, 10000)
V3_VIA_FEES = (500, 3000, 10000)


def uses_typed_adapter(address):
    return bool(address) and address.lower() not in LEGACY_V3_ADAPTERS


class TokenRef(BaseModel):
    address: str
    # Execution identity does not depend on optional SDK/display observations.
    # A caller-selected V3 path is usable before token metadata is available.
    decimals: int | None = None
    chainId: int | None = None
    decimalsKnown: bool | None = None


class PoolRef(BaseModel):
    id: str
    protocol: Literal['v2', 'v3', 'v4']
    token0: TokenRef
    token1: TokenRef
    address: str | None = None
    feePips: int = 0
    tickSpacing: int | None = None
    poolManager: str | None = None
    hooks: str | None = None


class Hop(BaseModel):
    pool: PoolRef
    zeroForOne: bool


class Branch(BaseModel):
    amountIn: str
    hops: list[Hop]


class RoutePlan(BaseModel):
    version: Literal[1] = 1
    executionContext: Literal['helpers-market', 'helpers-core']
    mode: Literal['exactIn', 'exactOut']
    tokenIn: str
    tokenOut: str
    branches: list[Branch]
    inputAmount: str
    outputAmount: str
    limit: str
    deadline: str


def route_mode(mode):
    return {'exact-in': 'exactIn', 'exact-out': 'exactOut',
            'exactIn': 'exactIn', 'exactOut': 'exactOut'}[mode]


def _v3_hop(source, target, fee, chain_id):
    source, target = source.lower(), target.lower()
    a, b = sorted((source, target))
    token0, token1 = {'address': a}, {'address': b}
    if chain_id is not None:
        token0['chainId'] = token1['chainId'] = int(chain_id)
    return {'pool': {'id': f'v3:{a}:{b}:{fee}', 'protocol': 'v3',
        'token0': token0, 'token1': token1, 'feePips': fee}, 'zeroForOne': source == a}


def initial_v3_branches(target, mode, chain_id=None):
    """Original direct/via-WETH coverage, before optional state observations."""
    mode = route_mode(mode)
    source, output = target['inputAsset'], target['outputAsset']
    if source.lower() == output.lower():
        return
    weth = dict(TOKENS)['weth']
    paths = [([source, output], [fee]) for fee in V3_DIRECT_FEES]
    if source.lower() != weth.lower() and output.lower() != weth.lower():
        paths.extend(([source, weth, output], [a, b]) for a in V3_VIA_FEES for b in V3_VIA_FEES)
    paths.sort(key=lambda row: (sum(row[1]), len(row[1]) > 1, '/'.join(map(str, row[1]))))
    for tokens, fees in paths:
        yield [{'amountIn': str(target['amount']) if mode == 'exactIn' else '0',
            'hops': [_v3_hop(a, b, fee, chain_id)
                for a, b, fee in zip(tokens[:-1], tokens[1:], fees, strict=True)]}]


def v3_branches(path, mode, amount, chain_id=None):
    """Decode packed V3 input once; every internal hop runs input -> output.

    Tokens and fee tiers are the executable pool identity. Optional pool and
    token observations are acquired by the shared quote engine, never needed
    just to retain, quote through a native fallback, or encode this route.
    """
    mode = route_mode(mode)
    raw = bytes.fromhex(path.removeprefix('0x')) if isinstance(path, str) else bytes(path)
    if len(raw) < 43 or (len(raw)-20) % 23:
        raise ValueError('Invalid packed V3 path.')
    tokens = ['0x'+raw[:20].hex()]
    fees = []
    for offset in range(20, len(raw), 23):
        fees.append(int.from_bytes(raw[offset:offset+3]))
        tokens.append('0x'+raw[offset+3:offset+23].hex())
    if mode == 'exactOut':
        tokens.reverse()
        fees.reverse()
    hops = [_v3_hop(a, b, fee, chain_id)
        for a, b, fee in zip(tokens[:-1], tokens[1:], fees, strict=True)]
    return [{'amountIn': str(amount) if mode == 'exactIn' else '0', 'hops': hops}]


def v3_plan(path, mode, amount, *, chain_id=None, execution_context='helpers-core',
            limit='0', deadline='0'):
    """Normalize a selected legacy/API path without retaining a second format."""
    mode = route_mode(mode)
    branches = v3_branches(path, mode, amount, chain_id)
    first, last = branches[0]['hops'][0], branches[0]['hops'][-1]
    return {'version': 1, 'executionContext': execution_context, 'mode': mode,
        'tokenIn': first['pool']['token0' if first['zeroForOne'] else 'token1']['address'],
        'tokenOut': last['pool']['token1' if last['zeroForOne'] else 'token0']['address'],
        'branches': branches, 'inputAmount': str(amount) if mode == 'exactIn' else '0',
        'outputAmount': str(amount) if mode == 'exactOut' else '0',
        'limit': str(limit), 'deadline': str(deadline)}


def standalone_v3(plan):
    branches = plan['branches']
    return len(branches) == 1 and bool(branches[0]['hops']) and all(
        hop['pool']['protocol'] == 'v3' for hop in branches[0]['hops'])


def pool_identity(pool):
    """Execution identity is stable when optional observed metadata arrives.

    Chain, factory and V4 PoolManager come from the configured operation, not
    from a candidate's enrichment. Within it these are the deployed routers'
    pool keys, including the V4 fee/tick-spacing/hooks key.
    """
    protocol = pool['protocol']
    tokens = tuple(sorted((pool['token0']['address'].lower(), pool['token1']['address'].lower())))
    if protocol == 'v2':
        return (protocol, *tokens)
    if protocol == 'v3':
        return (protocol, *tokens, int(pool['feePips']))
    return (protocol, *tokens, int(pool['feePips']), int(pool['tickSpacing']),
            (pool.get('hooks') or '0x'+'00'*20).lower())


def route_identity(branches):
    """Ordered execution/allocation key; optional pool observations are absent."""
    return tuple((str(int(branch['amountIn'])), tuple((pool_identity(hop['pool']), hop['zeroForOne'])
        for hop in branch['hops'])) for branch in branches)


def pool_key(pool):
    return (pool['token0']['address'], pool['token1']['address'], int(pool['feePips']),
            int(pool['tickSpacing']), pool.get('hooks') or '0x'+'00'*20)


def opposite(pool, address):
    a, b = pool['token0']['address'].lower(), pool['token1']['address'].lower()
    return b if address.lower() == a else a if address.lower() == b else None


def discover_routes(pools, token_in, token_out, max_hops=3):
    """Bound hop depth, preserve every path in the selected graph, no top-N."""
    graph = {}
    for pool in pools:
        for token in (pool['token0'], pool['token1']):
            graph.setdefault(token['address'].lower(), []).append(pool)
    result = []

    def visit(token, path, visited):
        if token == token_out.lower():
            if path:
                result.append(path)
            return
        if len(path) == max_hops:
            return
        for pool in sorted(graph.get(token, []), key=lambda row: (row['protocol'], row['id'])):
            following = opposite(pool, token)
            if following in visited:
                continue
            hop = {'pool': deepcopy(pool), 'zeroForOne': token == pool['token0']['address'].lower()}
            visit(following, path+[hop], visited|{following})
    visit(token_in.lower(), [], {token_in.lower()})
    return sorted(result, key=len)


def supported_route(hops, mode):
    return mode == 'exactIn' or len({hop['pool']['protocol'] for hop in hops}) == 1


async def discover_routes_async(pools, token_in, token_out, max_hops=3):
    """Same graph coverage, cooperatively cancellable even on dense graphs."""
    graph = {}
    for index, pool in enumerate(pools):
        for token in (pool['token0'], pool['token1']):
            graph.setdefault(token['address'].lower(), []).append(pool)
        if index % 64 == 0:
            await asyncio.sleep(0)
    for token, rows in graph.items():
        rows.sort(key=lambda row: (row['protocol'], row['id']))
        await asyncio.sleep(0)
    visits = 0
    async def walk(token, path, visited, depth):
        nonlocal visits
        visits += 1
        if visits % 64 == 0:
            await asyncio.sleep(0)
        if token == token_out.lower():
            if len(path) == depth:
                yield path
            return
        if len(path) == depth:
            return
        for pool in graph.get(token, []):
            following = opposite(pool, token)
            if following in visited:
                continue
            hop = {'pool': pool, 'zeroForOne': token == pool['token0']['address'].lower()}
            async for route in walk(following, path+[hop], visited|{following}, depth):
                yield route
    # Complete each hop depth before longer connector paths. Coverage and
    # deterministic ordering are unchanged; cheap candidates arrive sooner.
    for depth in range(1, max_hops+1):
        async for route in walk(token_in.lower(), [], {token_in.lower()}, depth):
            yield route


async def candidate_branches(pools, token_in, token_out, mode, amount):
    """Complete standalone paths, then lazily replay their identities for splits."""
    retained = []
    async for hops in discover_routes_async(pools, token_in, token_out):
        if supported_route(hops, mode):
            if mode == 'exactIn':
                # The original graph yields fresh hop dictionaries on every
                # traversal, with the same underlying selected pool objects.
                retained.append([dict(hop) for hop in hops])
            yield [{'amountIn': str(amount) if mode == 'exactIn' else '0', 'hops': hops}]
    if mode == 'exactIn':
        for left_index, left in enumerate(retained):
            await asyncio.sleep(0)
            for right_index, right in enumerate(retained):
                # Keep cooperative progress even when tiny raw amounts yield
                # no split candidates; this is not a candidate selection rule.
                if right_index % 64 == 0:
                    await asyncio.sleep(0)
                if right_index > left_index:
                    for percent in (25, 50, 75):
                        first = amount*percent//100
                        if first and amount-first:
                            yield [{'amountIn': str(first), 'hops': [dict(hop) for hop in left]},
                                {'amountIn': str(amount-first), 'hops': [dict(hop) for hop in right]}]




def v3_path(hops, exact_out=False):
    entries = []
    for hop in hops:
        pool = hop['pool']
        source, target = (pool['token0']['address'], pool['token1']['address']) if hop['zeroForOne'] else (
            pool['token1']['address'], pool['token0']['address'])
        entries.append((source, int(pool['feePips']), target))
    if exact_out:
        entries = [(target, fee, source) for source, fee, target in reversed(entries)]
    return '0x'+entries[0][0][2:]+''.join(f'{fee:06x}'+target[2:] for _, fee, target in entries)


def resize_branches(branches, amount):
    """Conserve raw units while retaining ordered allocation weights."""
    result = deepcopy(branches)
    total = sum(int(branch['amountIn']) for branch in branches)
    if len(result) == 1:
        result[0]['amountIn'] = str(amount)
        return result
    previous = cumulative = 0
    for branch in result:
        cumulative += int(branch['amountIn'])
        allocation = amount*cumulative//total
        branch['amountIn'] = str(allocation-previous)
        previous = allocation
    return result
