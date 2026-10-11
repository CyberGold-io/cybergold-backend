"""Protocol-aware identities and route order; no AMM arithmetic."""
from copy import deepcopy
import asyncio
from typing import Literal

from pydantic import BaseModel, Field
from .uniswap_v4 import v4_pool_id

# Canonical historical deployment (Ops mainnet-app-contracts / Helpers release).
# This is encoder dispatch, not an adapter approval or transaction admission check.
LEGACY_V3_ADAPTERS = {'0x4edb8190232a47e45d861003672938eb7ee84a15'}


def uses_typed_adapter(address):
    return bool(address) and address.lower() not in LEGACY_V3_ADAPTERS


class TokenRef(BaseModel):
    address: str
    decimals: int
    chainId: int
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
    """Complete standalone paths then lazy splits, bounded by the caller's budget."""
    async def routes():
        async for hops in discover_routes_async(pools, token_in, token_out):
            if supported_route(hops, mode):
                yield hops
    async for hops in routes():
        yield [{'amountIn': str(amount) if mode == 'exactIn' else '0', 'hops': hops}]
    if mode == 'exactIn':
        left_index = 0
        async for left in routes():
            right_index = 0
            async for right in routes():
                if right_index > left_index:
                    for percent in (25, 50, 75):
                        first = amount*percent//100
                        if first and amount-first:
                            yield [{'amountIn': str(first), 'hops': left},
                                {'amountIn': str(amount-first), 'hops': right}]
                right_index += 1
            left_index += 1


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
