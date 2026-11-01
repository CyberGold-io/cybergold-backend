"""Hosted Uniswap routing supplies pool hints, never executable prices or calldata.

The response contracts are the official Trading API OpenAPI specification and
Guidestar integration guide, reviewed 2026-11-01. ``routeCandidates`` strings,
remote amounts, router-balance sentinels and settlement instructions are ignored.
Current discovery builds supported paths; current SDK replay prices them.
"""
import asyncio

import httpx

from ..pool_producer import PoolIdentifier, PoolProducer
from ..protocol_config import configured_address
from ..route_observations import api_exchange, origin_scope
from ..uniswap_routes import pool_identity, v3_branches
from ..uniswap_state import owned_reads
from .bootstrap import ProviderUnavailable
from .discovery import paths, route_candidates


QUOTE_URL = 'https://trade-api.gateway.uniswap.org/v1/quote'


class HostedRouteError(RuntimeError):
    """Supplier failure with no response body, credential or URL in its text."""


def _pair(protocol, source, target, *, fee=3000, tick_spacing=None, hooks=None):
    value = {'protocol': protocol, 'tokenA': source, 'tokenB': target, 'fee': int(fee)}
    if protocol == 'v4':
        value.update(tickSpacing=int(tick_spacing), hooks=hooks)
    # Reuse the existing pool identifier parser. Remote addresses, observations
    # and token display metadata do not enter the authoritative producer.
    return PoolIdentifier.model_validate(value).model_dump(exclude_none=True)


def _v3_path(packed):
    for branch in v3_branches(packed, 'exactIn', '1'):
        for hop in branch['hops']:
            pool = hop['pool']
            yield _pair('v3', pool['token0']['address'], pool['token1']['address'],
                        fee=pool['feePips'])


def _v4_key(key):
    return _pair('v4', key['currency0'], key['currency1'], fee=key['fee'],
                 tick_spacing=key['tickSpacing'], hooks=key['hooks'])


def _v4_actions(actions):
    for action in actions:
        kind = action['action']
        if kind in ('SWAP_EXACT_IN_SINGLE', 'SWAP_EXACT_OUT_SINGLE'):
            yield _v4_key(action['poolKey'])
        elif kind == 'SWAP_EXACT_IN':
            currency = action['currencyIn']
            for hop in action['path']:
                following = hop['intermediateCurrency']
                yield _pair('v4', currency, following, fee=hop['fee'],
                            tick_spacing=hop['tickSpacing'], hooks=hop['hooks'])
                currency = following
        elif kind == 'SWAP_EXACT_OUT':
            currency = action['currencyOut']
            for hop in action['path']:
                following = hop['intermediateCurrency']
                yield _pair('v4', currency, following, fee=hop['fee'],
                            tick_spacing=hop['tickSpacing'], hooks=hop['hooks'])
                currency = following
        # Settle/take operations are deliberately not reconstructed. They do
        # not nominate a pool and cannot grant funding to our new quote.


def topology_identifiers(document, *, guidestar=False):
    """Extract only structured pool keys from the served CLASSIC quote.

    An empty Guidestar ``route`` is normal. V2/V3 paths and V4 action keys
    provide graph edges, not independently funded translations of swap steps.
    """
    quote = document['quote']
    identifiers = []
    if guidestar:
        for step in quote['swapSteps']:
            kind = step['type']
            if kind in ('V2_SWAP_EXACT_IN', 'V2_SWAP_EXACT_OUT'):
                identifiers.extend(_pair('v2', a, b)
                    for a, b in zip(step['path'], step['path'][1:]))
            elif kind in ('V3_SWAP_EXACT_IN', 'V3_SWAP_EXACT_OUT'):
                identifiers.extend(_v3_path(step['path']))
            elif kind == 'V4_SWAP':
                identifiers.extend(_v4_actions(step['v4Actions']))
            # Wrap/unwrap and other non-pool commands are not execution input.
            # Existing discovery owns lossless native/WETH graph transitions.
    else:
        for route in quote['route']:
            for pool in route:
                protocol = {'v2-pool': 'v2', 'v3-pool': 'v3', 'v4-pool': 'v4'}[pool['type']]
                identifiers.append(_pair(protocol, pool['tokenIn']['address'],
                    pool['tokenOut']['address'], fee=3000 if protocol == 'v2' else pool['fee'],
                    tick_spacing=pool.get('tickSpacing'), hooks=pool.get('hooks')))
    unique = {}
    for identifier in identifiers:
        pair = tuple(sorted((identifier['tokenA'].lower(), identifier['tokenB'].lower())))
        identity = (identifier['protocol'], pair, identifier['fee'],
                    identifier.get('tickSpacing'), (identifier.get('hooks') or '').lower())
        unique.setdefault(identity, identifier)
    return list(unique.values())


class UniswapApiProvider:
    def __init__(self, engine, settings, *, guidestar=False, client_factory=None, resolver=None):
        self.engine, self.settings, self.guidestar = engine, settings, guidestar
        self.name = 'uniswap-guidestar' if guidestar else 'uniswap-standard-api'
        self.api_key = getattr(settings, 'CYBERGOLD_UNISWAP_API_KEY', None)
        self.swapper = (configured_address(settings, 'CYBERGOLD_UNISWAP_API_SWAPPER')
                        or configured_address(settings, 'NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS'))
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=None))
        self.resolver = resolver or PoolProducer(settings, registry=engine.registry)
        self.clients = set()

    async def discover(self, source, target, amount, block):
        if not self.api_key:
            raise ProviderUnavailable('Uniswap API key is not configured')
        chain = self.engine.registry.chain
        headers = {'x-api-key': self.api_key, 'Accept': 'application/json',
                   'x-universal-router-version': '2.2.0'}
        if self.guidestar:
            headers.update({'x-api-experimental': 'true', 'x-universal-router-swapsteps': 'true'})
        payload = {'type': 'EXACT_INPUT', 'amount': str(amount), 'tokenIn': source,
                   'tokenOut': target, 'tokenInChainId': chain, 'tokenOutChainId': chain,
                   'swapper': self.swapper, 'autoSlippage': 'DEFAULT',
                   'routingPreference': 'BEST_PRICE', 'protocols': ['V2', 'V3', 'V4'],
                   'hooksOptions': 'V4_NO_HOOKS', 'includeRouteCandidates': True}
        client = self.client_factory()
        self.clients.add(client)
        try:
            async with client:
                with origin_scope(self.name), api_exchange():
                    response = await client.post(QUOTE_URL, headers=headers, json=payload)
                    if response.status_code >= 400:
                        raise HostedRouteError(f'Uniswap route provider returned HTTP {response.status_code}')
                document = response.json()
        finally:
            self.clients.discard(client)
        identifiers = topology_identifiers(document, guidestar=self.guidestar)
        resolved = await owned_reads(*(self.resolver.resolve(identifier, block) for identifier in identifiers))
        pools = {pool_identity(pool): pool for pool in resolved if pool is not None}
        return list(route_candidates(paths(list(pools.values()), source, target), int(amount)))

    async def close(self):
        await asyncio.gather(*(client.aclose() for client in tuple(self.clients)))
