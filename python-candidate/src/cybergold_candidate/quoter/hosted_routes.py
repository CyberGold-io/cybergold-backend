"""Hosted Uniswap routing supplies pool hints, never executable prices or calldata.

The response contracts are the official Trading API OpenAPI specification and
Guidestar integration guide, reviewed 2026-11-01. ``routeCandidates`` strings,
remote output prices, router-balance sentinels and settlement instructions are
ignored. Structured paths and relative input proportions nominate whole plans;
the local Helpers simulation prices them against the execution chain.
"""
import asyncio
from copy import deepcopy

from web3 import Web3

import httpx

from ..pool_producer import PoolIdentifier, PoolProducer
from ..protocol_config import configured_address
from ..route_observations import api_exchange, origin_scope
from ..uniswap_routes import pool_identity, v3_branches, v4_pool_id
from ..uniswap_state import POOL_MANAGER
from ..route_search import WETH
from ..routing_encoding import ZERO
from .bootstrap import ProviderUnavailable
from .discovery import paths, route_candidates


QUOTE_URL = 'https://trade-api.gateway.uniswap.org/v1/quote'


class HostedRouteError(RuntimeError):
    """Supplier failure with no response body, credential or URL in its text."""


class HostedCandidates(list):
    """Candidate list plus optional response-scoped engine observations.

    The integration source and the API's actual backend engine are separate.
    This metadata never admits, rejects or ranks a candidate.
    """
    def __init__(self, candidates, engine_attribution):
        super().__init__(candidates)
        self.engine_attribution = engine_attribution


def observed_engine(document):
    """Use only documented response evidence; missing metadata stays unknown.

    Official OpenAPI: nonempty routeCandidates is UniRoute-backed; swapSteps
    is emitted when Guidestar serves the quote. There is no documented UniRoute
    request selector. An empty/absent field is not an engine eligibility rule.
    """
    quote = document['quote']
    uniroute = isinstance(quote.get('routeCandidates'), list) and bool(quote['routeCandidates'])
    guidestar = isinstance(quote.get('swapSteps'), list) and bool(quote['swapSteps'])
    if uniroute and guidestar:
        return {'engine': 'unverified', 'evidence': 'ambiguous'}
    if uniroute:
        return {'engine': 'uniroute', 'evidence': 'route-candidates'}
    if guidestar:
        return {'engine': 'guidestar', 'evidence': 'swap-steps'}
    return {'engine': 'unverified', 'evidence': 'not-disclosed'}


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
            yield _pair('v3', pool['token0' if hop['zeroForOne'] else 'token1']['address'],
                        pool['token1' if hop['zeroForOne'] else 'token0']['address'], fee=pool['feePips'])


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
    if guidestar or (isinstance(quote.get('swapSteps'), list) and quote['swapSteps']):
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


def semantic_pool(identifier, registry):
    """Publish executable identity now; optional SDK metadata is acquired on use."""
    a, b = sorted((identifier['tokenA'].lower(), identifier['tokenB'].lower()))
    protocol, fee = identifier['protocol'], int(identifier.get('fee', 3000))
    pool = {'id': f'{protocol}:{a}:{b}:{fee}', 'protocol': protocol,
        'token0': {'address': Web3.to_checksum_address(a), 'chainId': registry.chain},
        'token1': {'address': Web3.to_checksum_address(b), 'chainId': registry.chain}, 'feePips': fee}
    if protocol == 'v4':
        pool.update(tickSpacing=identifier['tickSpacing'], hooks=identifier['hooks'],
            poolManager=getattr(registry.get_rpc(), 'pool_manager', POOL_MANAGER))
        pool['id'] = v4_pool_id((a, b, fee, pool['tickSpacing'], pool['hooks']))
    known = next((row for row in registry.inventory.values() if pool_identity(row) == pool_identity(pool)), None)
    if known is not None:
        # Bind current local identity metadata, never remote scalar observations.
        for field in ('id', 'address', 'tickSpacing', 'hooks', 'poolManager', 'token0', 'token1'):
            if field in known:
                pool[field] = deepcopy(known[field])
    return pool


def market_segment(registry, source, target):
    """A Mainnet-backed fork imports only the shared AMM part of its Core path."""
    core, seed = getattr(registry, 'core', None), getattr(registry, 'seed', None)
    prefix, suffix = [], []
    if registry.chain == 31338 and core is not None and seed is not None:
        a, b = seed['token0']['address'], seed['token1']['address']
        anchor = b if a.lower() == core.lower() else a
        if source.lower() == core.lower():
            prefix = [{'pool': deepcopy(seed), 'zeroForOne': source.lower() == a.lower()}]
            source = anchor
        if target.lower() == core.lower():
            suffix = [{'pool': deepcopy(seed), 'zeroForOne': anchor.lower() == a.lower()}]
            target = anchor
    return source, target, prefix, suffix


def _ordered_candidate(identifiers, source, target, amount, registry, max_hops=3):
    # Preserve the proposed order, rather than treating a reversed swap step as
    # another forward-funded branch. Graph alternatives remain separate below.
    current, hops = source.lower(), []
    for identifier in identifiers:
        a, b = identifier['tokenA'].lower(), identifier['tokenB'].lower()
        if current == ZERO and a == WETH.lower():
            hops.append({'kind': 'wrap', 'currencyOut': a})
            current = a
        elif current == WETH.lower() and a == ZERO:
            hops.append({'kind': 'unwrap', 'currencyOut': ZERO})
            current = ZERO
        if current != a:
            return []
        pool = semantic_pool(identifier, registry)
        hops.append({'pool': pool, 'zeroForOne': current == pool['token0']['address'].lower()})
        current = b
    if current == WETH.lower() and target.lower() == ZERO:
        hops.append({'kind': 'unwrap', 'currencyOut': ZERO})
        current = ZERO
    elif current == ZERO and target.lower() == WETH.lower():
        hops.append({'kind': 'wrap', 'currencyOut': WETH.lower()})
        current = WETH.lower()
    if current != target.lower() or len(identifiers) > max_hops:
        return []
    return [{'amountIn': str(amount), 'hops': hops}]


def proposed_splits(document, source, target, registry, max_hops=3):
    """Remote input proportions nominate weights, never funding or output prices."""
    branches = []
    quote = document['quote']
    routes = quote.get('route') or []
    if routes:
        for route in routes:
            identifiers = topology_identifiers({'quote': {'route': [route]}})
            choices = _ordered_candidate(identifiers, source, target, route[0]['amountIn'], registry, max_hops)
            # This exact proposed branch is independent of reconstructed graph alternatives.
            if choices:
                branches.append(choices[0])
    else:
        for step in quote.get('swapSteps', []):
            rows = []
            if step['type'] in ('V2_SWAP_EXACT_IN', 'V3_SWAP_EXACT_IN'):
                rows.append((topology_identifiers({'quote': {'swapSteps': [step]}}, guidestar=True), step['amountIn']))
            elif step['type'] == 'V4_SWAP':
                for action in step['v4Actions']:
                    if action['action'] == 'SWAP_EXACT_IN_SINGLE':
                        key = action['poolKey']
                        a, b = ((key['currency0'], key['currency1']) if action['zeroForOne'] else
                                (key['currency1'], key['currency0']))
                        rows.append(([_pair('v4', a, b, fee=key['fee'], tick_spacing=key['tickSpacing'],
                                            hooks=key['hooks'])], action['amountIn']))
                    elif action['action'] == 'SWAP_EXACT_IN':
                        rows.append((list(_v4_actions([action])), action['amountIn']))
            for identifiers, weight in rows:
                if int(weight) == 1 << 255:
                    continue  # Universal Router's balance sentinel is not a split proportion.
                choices = _ordered_candidate(identifiers, source, target, weight, registry, max_hops)
                if choices:
                    branches.append(choices[0])
    if len(branches) < 2:
        return []
    amounts = [int(branch['amountIn']) for branch in branches]
    total = sum(amounts)
    # The ordinary integer/ABI parser owns malformed nomination errors. Ratios
    # are rebased to ppm; remote raw amounts and balance sentinels are not funded.
    allocated = 0
    for index, (branch, amount) in enumerate(zip(branches, amounts, strict=True)):
        share = 1_000_000 - allocated if index == len(branches)-1 else amount*1_000_000//total
        branch['amountIn'] = str(share)
        allocated += share
    return [branches]


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
        self.client = None

    @property
    def diagnostics(self):
        execution = self.engine.registry.chain
        return {'nominationChainId': 1 if execution == 31338 else execution,
                'executionChainId': execution}

    async def discover(self, source, target, amount, block):
        if not self.api_key:
            raise ProviderUnavailable('Uniswap API key is not configured')
        registry = self.engine.registry
        source, target, prefix, suffix = market_segment(registry, source, target)
        if source.lower() == target.lower():
            return HostedCandidates([[{'amountIn': str(amount), 'hops': prefix + suffix}]],
                {'engine': 'unverified', 'evidence': 'not-disclosed'})
        # The existing Sandbox is a Mainnet fork. Only topology acquisition uses
        # its parent; local pool identities and execution always retain 31338.
        chain = 1 if registry.chain == 31338 else registry.chain
        headers = {'x-api-key': self.api_key, 'Accept': 'application/json',
                   'x-universal-router-version': '2.2.0'}
        if self.guidestar:
            headers.update({'x-api-experimental': 'true', 'x-universal-router-swapsteps': 'true'})
        payload = {'type': 'EXACT_INPUT', 'amount': str(amount), 'tokenIn': source,
                   'tokenOut': target, 'tokenInChainId': chain, 'tokenOutChainId': chain,
                   'swapper': self.swapper, 'autoSlippage': 'DEFAULT',
                   'routingPreference': 'BEST_PRICE', 'protocols': ['V2', 'V3', 'V4'],
                   'hooksOptions': 'V4_NO_HOOKS', 'includeRouteCandidates': True}
        if self.client is None:
            self.client = self.client_factory()
            self.clients.add(self.client)
        with origin_scope(self.name), api_exchange():
            response = await self.client.post(QUOTE_URL, headers=headers, json=payload)
            if response.status_code >= 400:
                raise HostedRouteError(f'Uniswap route provider returned HTTP {response.status_code}')
        document = response.json()
        identifiers = topology_identifiers(document, guidestar=self.guidestar)
        pools = {pool_identity(pool): pool for pool in (semantic_pool(identifier, registry) for identifier in identifiers)}
        try:
            nominees = proposed_splits(document, source, target, registry, 3-len(prefix)-len(suffix))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            # Optional split proportions cannot retract ordinary structured paths.
            nominees = []
        nominees.extend(route_candidates(paths(list(pools.values()), source, target,
            max_hops=3-len(prefix)-len(suffix)), int(amount)))
        candidates = [[{**branch, 'hops': deepcopy(prefix) + branch['hops'] + deepcopy(suffix)}
                       for branch in nominee] for nominee in nominees]
        return HostedCandidates(candidates, observed_engine(document))

    async def close(self):
        await asyncio.gather(*(client.aclose() for client in tuple(self.clients)))
        self.clients.clear()
        self.client = None


class UniRouteApiProvider(UniswapApiProvider):
    """UniRoute API integration through standard Uniswap Trading API routing.

    ``includeRouteCandidates`` requests UniRoute's optional diagnostics, not a
    dedicated engine selector. Structured served topology remains useful when
    the API does not disclose its backend engine. Runtime configuration replaces
    the standard API provider with this adapter; it does not send both requests.
    """
    def __init__(self, engine, settings, *, client_factory=None, resolver=None):
        super().__init__(engine, settings, client_factory=client_factory, resolver=resolver)
        self.name = 'uniroute-api'
