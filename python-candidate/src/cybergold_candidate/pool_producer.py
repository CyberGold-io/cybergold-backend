"""Configured Uniswap pool identifiers -> canonical server-owned observations."""
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from copy import deepcopy
from typing import Literal
from pathlib import Path
import uuid

from eth_utils.abi import collapse_if_tuple
from fastapi.responses import JSONResponse, Response
from pydantic import Field, ValidationError, field_validator, model_validator
from web3 import AsyncWeb3, Web3

from .pool_cache import Pair
from .recovery_rpc import RecoveryRpc, abi_value, ZERO
from .rpc_transport import rpc_provider
from .supplier_dispatch import dispatch
from .quote_errors import public_quote_error

ABI = json.loads(Path(__file__).with_name('pool-producer-abi.json').read_text())
DEFAULT_FACTORY = '0x1F98431c8aD98523631AE4a59f267346ea31F984'


class PoolIdentifier(Pair):
    # An omitted discriminator retains the historical V3 request/wire shape.
    protocol: Literal['v2', 'v3', 'v4'] | None = None
    fee: int = Field(default=3000, ge=0, le=2**24-1)
    id: str | None = None
    poolId: str | None = None
    poolManager: str | None = None
    tickSpacing: int | None = Field(default=None, ge=-(2**23), le=2**23-1)
    hooks: str | None = None

    @field_validator('poolManager', 'hooks')
    @classmethod
    def pool_address(cls, value):
        return cls.address(value) if value is not None else value

    @field_validator('poolId')
    @classmethod
    def pool_id(cls, value):
        import re
        if value is not None and not re.fullmatch(r'0x[a-fA-F0-9]{64}', value):
            raise ValueError('Invalid PoolId')
        return value

    @model_validator(mode='after')
    def key_fields(self):
        if self.protocol == 'v4' and (self.tickSpacing is None or self.hooks is None):
            raise ValueError('V4 PoolKey requires tickSpacing and hooks')
        if 'fee' not in self.model_fields_set and self.protocol != 'v2':
            raise ValueError('Pool fee is required')
        return self


def identifier_from_pool(pool):
    value = {'protocol': pool['protocol'], 'id': pool['id'],
             'tokenA': pool['token0']['address'], 'tokenB': pool['token1']['address'],
             'fee': int(pool['feePips'])}
    if pool['protocol'] == 'v4':
        value.update(poolId=pool['id'], poolManager=pool['poolManager'],
                     tickSpacing=pool['tickSpacing'], hooks=pool.get('hooks') or ZERO)
    return value


def public_pool(pool):
    """Only canonical identity/metadata, without internal discovery checkpoints."""
    from .uniswap_routes import PoolRef
    return PoolRef.model_validate(pool).model_dump(exclude_none=True)


def serialize_snapshot(state, context):
    pool = public_pool(state)
    protocol = state['protocol']
    value = {'context': context, 'protocol': protocol, 'dex': 'uniswap_'+protocol,
             'id': state['id'], 'pool': pool,
             'token0': pool['token0']['address'].lower(), 'token1': pool['token1']['address'].lower(),
             'fee': int(state['feePips']), 'exists': True}
    if state.get('address'):
        value['poolAddress'] = state['address']
    if protocol == 'v2':
        r0, r1 = int(state['reserve0']), int(state['reserve1'])
        value.update(reserve0Raw=str(r0), reserve1Raw=str(r1))
        if r0:
            value['marginalPrice'] = {'numerator': str(r1), 'denominator': str(r0)}
    else:
        price = int(state['sqrtRatioX96'])
        value.update(activeLiquidityRaw=state['liquidity'], sqrtPriceX96Raw=str(price), tick=state['tick'],
                     tickSpacing=state['tickSpacing'], ticks=deepcopy(state.get('ticks', [])),
                     bitmapWords=deepcopy(state.get('bitmapWords', [])),
                     marginalPrice={'numerator': str(price*price), 'denominator': str(2**192)})
        for name in ('lpFee', 'protocolFee'):
            if name in state:
                value[name] = state[name]
        if protocol == 'v4':
            from .uniswap_routes import pool_key
            value.update(poolId=state['id'], poolManager=state['poolManager'], hooks=state.get('hooks') or ZERO,
                poolKey=dict(zip(('currency0', 'currency1', 'fee', 'tickSpacing', 'hooks'), pool_key(state), strict=True)),
                lpFee=state['lpFee'], protocolFee=state['protocolFee'], exists=price != 0)
            # ERC20 balanceOf(PoolManager) is shared across pools, never reserves.
    return value


class PoolRpc(RecoveryRpc):
    def __init__(self, settings, w3=None):
        # Share the proven block/canonicality/provider operations, without
        # requiring Recovery's unrelated Core/Governance configuration.
        self.chain_id = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.w3 = w3 or AsyncWeb3(rpc_provider(settings.RPC_URL, settings.RPC_AUTHORIZATION))
        self.factory = Web3.to_checksum_address(getattr(settings, 'NEXT_PUBLIC_UNISWAP_V3_FACTORY_ADDRESS', None)
            or os.environ.get('NEXT_PUBLIC_UNISWAP_V3_FACTORY_ADDRESS') or DEFAULT_FACTORY)
        self.pool_contracts = {group: self.w3.eth.contract(abi=abi) for group, abi in ABI.items()}

    async def read(self, group, address, name, block, args=()):
        function = next(entry for entry in ABI[group] if entry['name'] == name)
        data = self.pool_contracts[group].encode_abi(name, args=[abi_value(value, parameter)
            for value, parameter in zip(args, function['inputs'], strict=True)])
        response = await self.w3.provider.make_request('eth_call', [
            {'to': address, 'data': data}, {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Pool contract read failed')
        values = self.w3.codec.decode([collapse_if_tuple(output) for output in function['outputs']],
                                     bytes.fromhex(response['result'][2:]))
        return values[0] if len(values) == 1 else values


class PoolProducer:
    def __init__(self, settings, rpc=None, now=None, registry=None):
        self.settings, self.rpc = settings, rpc
        self.registry = registry
        self.chain_id = int(settings.NEXT_PUBLIC_CHAIN_ID)
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    async def get(self, identifier):
        if self.registry is not None:
            return await self.get_registered(identifier)
        if self.rpc is None:
            self.rpc = PoolRpc(self.settings)
        async with asyncio.timeout(15):
            block = await self.rpc.block(None)
            token0, token1 = sorted((identifier['tokenA'].lower(), identifier['tokenB'].lower()))
            fee = identifier['fee']
            pool = Web3.to_checksum_address(await self.rpc.read('factory', self.rpc.factory,
                'getPool', block, (token0, token1, fee)))
            result = {'context': {'chainId': self.chain_id, 'blockNumber': str(block['number']),
                'blockHash': block['hash'], 'observedAt': self.now()},
                'dex': 'uniswap_v3', 'token0': token0, 'token1': token1, 'fee': fee,
                'exists': pool != ZERO}
            if pool != ZERO:
                slot, liquidity, balance0, balance1 = await dispatch([
                    ('pool', pool, 'slot0', block),
                    ('pool', pool, 'liquidity', block),
                    ('token', token0, 'balanceOf', block, (pool,)),
                    ('token', token1, 'balanceOf', block, (pool,))],
                    lambda arguments: self.rpc.read(*arguments))
                result.update(poolAddress=pool, activeLiquidityRaw=str(liquidity),
                    sqrtPriceX96Raw=str(slot[0]), tick=slot[1], token0BalanceRaw=str(balance0),
                    token1BalanceRaw=str(balance1))
            # Neither a caller observation nor a mixed/reorged read can be
            # published as canonical pool data. No DB or shared-cache fallback.
            await self.rpc.assert_canonical(block)
            result['context']['observedAt'] = self.now()
            return result

    async def resolve(self, identifier, block, staged=None):
        """Resolve identity once; share the quote registry's static lookup cache."""
        from .uniswap_routes import v4_pool_id
        registry, rpc = self.registry, self.registry.get_rpc()
        staged = staged if staged is not None else {}
        protocol = identifier.get('protocol') or 'v3'
        token0, token1 = sorted((identifier['tokenA'].lower(), identifier['tokenB'].lower()))
        fee = identifier.get('fee', 3000)
        requested_id = identifier.get('id') or identifier.get('poolId')
        known = registry.inventory.get(requested_id) if requested_id else None
        if known and known['protocol'] == protocol:
            return deepcopy(known)
        if protocol == 'v4':
            manager = identifier.get('poolManager') or rpc.pool_manager
            key = (token0, token1, fee, identifier['tickSpacing'], identifier['hooks'])
            identity = v4_pool_id(key)
            known = registry.inventory.get(identity)
            if known and known.get('poolManager', rpc.pool_manager).lower() == manager.lower():
                return deepcopy(known)
            if manager.lower() != rpc.pool_manager.lower():
                raise ValueError('No StateView is configured for this PoolManager')
            address = None
        else:
            from datetime import datetime, timezone
            month = datetime.now(timezone.utc).strftime('%Y-%m')
            if registry.lookup_month != month:
                registry.lookups = {key: pool for key, pool in registry.lookups.items() if pool is not None}
                registry.lookup_month = month
            lookup = (protocol, (token0, token1), fee if protocol == 'v3' else 3000)
            known = next((pool for pool in registry.inventory.values() if pool['protocol'] == protocol
                and pool.get('address') and sorted((pool['token0']['address'].lower(), pool['token1']['address'].lower())) == [token0, token1]
                and (protocol == 'v2' or int(pool['feePips']) == fee)), None)
            if known:
                staged[lookup] = {'pool': known, 'acquired': False}
                return deepcopy(known)
            async def acquire_address():
                if lookup in registry.lookups:
                    cached = registry.lookups[lookup]
                    anchor = registry.lookup_anchors.get(lookup)
                    if cached is not None or anchor and anchor['blockHash'].lower() == block['hash'].lower():
                        return {'pool': cached, 'acquired': False}
                if protocol == 'v2':
                    values = await rpc.read_function(rpc.v2_factory, 'getPair(address,address)',
                        ['address', 'address'], [token0, token1], ['address'], block)
                else:
                    values = await rpc.read_function(rpc.factory, 'getPool(address,address,uint24)',
                        ['address', 'address', 'uint24'], [token0, token1, fee], ['address'], block)
                address = values[0]
                if address.lower() == ZERO:
                    return {'pool': None, 'acquired': True}
                a, b = await asyncio.gather(self.token_ref(token0, block), self.token_ref(token1, block))
                value = {'id': address.lower(), 'protocol': protocol, 'address': Web3.to_checksum_address(address),
                         'token0': a, 'token1': b, 'feePips': fee if protocol == 'v3' else 3000}
                if protocol == 'v3':
                    spacing, = await rpc.read_function(address, 'tickSpacing()', [], [], ['int24'], block)
                    value['tickSpacing'] = spacing
                return {'pool': value, 'acquired': True}
            resolved = deepcopy(await registry.pending.one(('pool-identity', registry.generation, block['hash'], lookup), acquire_address))
            staged[lookup] = resolved
            return resolved['pool']
        a, b = await asyncio.gather(self.token_ref(token0, block), self.token_ref(token1, block))
        return {'id': identity, 'protocol': protocol, 'token0': a, 'token1': b,
                'feePips': fee, 'tickSpacing': identifier['tickSpacing'],
                'hooks': identifier['hooks'], 'poolManager': manager}

    async def token_ref(self, address, block):
        try:
            return await self.registry.token_metadata(address, block, publish=False)
        except Exception:
            # Optional display decimals cannot make a previously supported V3
            # slot/balance observation depend on a new metadata prerequisite.
            return {**self.registry.token(address, 0), 'decimalsKnown': False}

    async def head(self):
        registry = self.registry
        return await registry.pending.one(('pool-api-head', registry.generation), lambda: registry.get_rpc().block(None))

    async def get_registered(self, identifier):
        registry = self.registry
        async with asyncio.timeout(15):
            await registry.ensure_loaded()
            generation = registry.generation
            block = await self.head()
            context = {'chainId': self.chain_id, 'blockNumber': str(block['number']),
                       'blockHash': block['hash'], 'observedAt': self.now()}
            staged = {}
            pool = await self.resolve(identifier, block, staged)
            state = None
            if pool is None:
                token0, token1 = sorted((identifier['tokenA'].lower(), identifier['tokenB'].lower()))
                value = {'context': context, 'dex': 'uniswap_'+(identifier.get('protocol') or 'v3'),
                         'token0': token0, 'token1': token1, 'fee': identifier.get('fee', 3000), 'exists': False}
                if identifier.get('protocol'):
                    value['protocol'] = identifier['protocol']
            else:
                state = await registry.snapshot(pool, block, publish=False)
                value = serialize_snapshot(state, context)
                if pool['protocol'] == 'v3':
                    balance0, balance1 = await asyncio.gather(*(registry.get_rpc().read_function(
                        token['address'], 'balanceOf(address)', ['address'], [pool['address']], ['uint256'], block)
                        for token in (pool['token0'], pool['token1'])))
                    value.update(token0BalanceRaw=str(balance0[0]), token1BalanceRaw=str(balance1[0]))
            await registry.pending.one(('pool-api-canonical', block['hash']), lambda: registry.get_rpc().assert_canonical(block))
            if generation == registry.generation:
                anchor = {'blockNumber': str(block['number']), 'blockHash': block['hash']}
                if pool and value['exists']:
                    if pool['id'] not in registry.inventory:
                        pool = registry.acquire_pool(pool, block)
                    for token in (pool['token0'], pool['token1']):
                        if token.get('decimalsKnown') is not False:
                            registry.metadata[token['address'].lower()] = deepcopy(token)
                for lookup, resolved in staged.items():
                    if resolved['acquired'] or lookup not in registry.lookups:
                        registry.lookup_anchors[lookup] = deepcopy(pool.get('acquisition', anchor) if pool else anchor)
                    registry.lookups[lookup] = deepcopy(pool if resolved['pool'] is not None else None)
                if state is not None:
                    if pool and pool.get('acquisition'):
                        state['acquisition'] = deepcopy(pool['acquisition'])
                    registry.publish_observation(state)
            value['context']['observedAt'] = self.now()
            if not identifier.get('protocol'):
                # Keep old JSON byte shape, while using the same observed source.
                old_fields = ('context', 'dex', 'token0', 'token1', 'fee', 'exists', 'poolAddress',
                              'activeLiquidityRaw', 'sqrtPriceX96Raw', 'tick', 'token0BalanceRaw', 'token1BalanceRaw')
                value = {key: value[key] for key in old_fields if key in value}
            return value

    async def catalog(self, token_a=None, token_b=None):
        registry = self.registry
        await registry.ensure_loaded(wait=True)
        block = await self.head()
        filters = {token.lower() for token in (token_a, token_b) if token}
        entries = [public_pool(pool) for pool in registry.inventory.values()
                   if (pool['protocol'] == 'v4' or pool.get('address')) and
                   (filters <= {pool['token0']['address'].lower(), pool['token1']['address'].lower()} if filters else
                    registry.core.lower() in {pool['token0']['address'].lower(), pool['token1']['address'].lower()})]
        return {'context': {'chainId': self.chain_id, 'blockNumber': str(block['number']),
                           'blockHash': block['hash'], 'observedAt': self.now()},
                'entries': sorted(entries, key=lambda row: (row['protocol'], row['id'])),
                'catalogMonth': registry.discovery_month}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_pool_snapshot(request, producer):
    try:
        identifier = PoolIdentifier.model_validate(await request.json()).model_dump(exclude_unset=True, exclude_none=True)
    except (ValueError, ValidationError):
        return JSONResponse({'error': 'Invalid pool identifier.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    return await pool_response(request, lambda: producer.get(identifier))


async def handle_pool_catalog(request, producer):
    token_a, token_b = request.query_params.get('tokenA'), request.query_params.get('tokenB')
    try:
        for token in (token_a, token_b):
            if token is not None:
                Pair.address(token)
    except ValueError:
        return JSONResponse({'error': 'Invalid pool catalog filter.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    return await pool_response(request, lambda: producer.catalog(token_a, token_b))


async def pool_response(request, produce):
    async def result():
        try:
            async with asyncio.timeout(15):
                return JSONResponse(await produce(), headers={'Cache-Control': 'no-store'})
        except Exception as error:
            correlation = str(uuid.uuid4())
            failure = public_quote_error(error)
            payload = {'error': 'Pool observations are temporarily unavailable.', 'correlationId': correlation,
                       **({'code': failure['code']} if failure['code'].startswith('rpc-') else {}),
                       **({'diagnostics': failure['diagnostics']} if 'diagnostics' in failure else {})}
            logging.getLogger('cybergold.candidate').error(json.dumps({'context': 'pool-snapshot',
                'correlationId': correlation, 'errorClassification': payload.get('code', 'pool-snapshot-unavailable'),
                'exceptionType': type(error).__name__,
                **({'diagnostics': payload['diagnostics']} if 'diagnostics' in payload else {})}))
            return JSONResponse(payload, status_code=503, headers={'Cache-Control': 'no-store'})
    async def disconnected():
        while (await request.receive())['type'] != 'http.disconnect':
            pass
    operation, caller = asyncio.create_task(result()), asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((operation, caller), return_when=asyncio.FIRST_COMPLETED)
        return await operation if operation in done else Response(status_code=499)
    finally:
        operation.cancel()
        caller.cancel()
        await asyncio.gather(operation, caller, return_exceptions=True)
