"""Shared V4 singleton identities and block-bound StateView reads.

The caller retains its RPC transport, caching, errors and cancellation. These
helpers provide ABI/identity data and observations, never swap or LP arithmetic.
"""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar

from eth_utils.abi import collapse_if_tuple
from web3 import Web3

_tick_prefetch_attempts = ContextVar('tick_prefetch_attempts', default=None)


@asynccontextmanager
async def tick_prefetch_scope():
    """Share advisory acquisition attempts only within the owning request."""
    if _tick_prefetch_attempts.get() is not None:
        yield
        return
    token = _tick_prefetch_attempts.set(set())
    try:
        yield
    finally:
        _tick_prefetch_attempts.reset(token)


def begin_tick_prefetch(pool, block, *, window=None):
    attempts = _tick_prefetch_attempts.get()
    if attempts is None:
        return True
    identity = (pool.get('poolManager', '').lower(), pool['id'].lower(), block['hash'].lower(), window)
    if identity in attempts:
        return False
    attempts.add(identity)
    return True

POOL_ID = '0x33fd4629a4e190b9a98a8a3758afb7a2639eb740088a04bd4d3016e3ac9d55a4'
POOL_MANAGER = '0x000000000004444c5dc75cB358380D2e3dE08A90'
POSITION_MANAGER = Web3.to_checksum_address('0xbd216513d74c8cf14cf4747e6aaa6420ff64ee9e')
STATE_VIEW = Web3.to_checksum_address('0x7ffe42c4a5deea5b0fec41c94c136cf115597227')
INITIALIZATION_BLOCK = 25638581
POOL_KEY_COMPONENTS = [
    {'name': 'currency0', 'type': 'address'}, {'name': 'currency1', 'type': 'address'},
    {'name': 'fee', 'type': 'uint24'}, {'name': 'tickSpacing', 'type': 'int24'},
    {'name': 'hooks', 'type': 'address'},
]
STATE_ABI = [
    {'type': 'function', 'name': 'getSlot0', 'stateMutability': 'view',
     'inputs': [{'name': 'poolId', 'type': 'bytes32'}],
     'outputs': [{'name': 'sqrtPriceX96', 'type': 'uint160'}, {'name': 'tick', 'type': 'int24'},
                 {'name': 'protocolFee', 'type': 'uint24'}, {'name': 'lpFee', 'type': 'uint24'}]},
    {'type': 'function', 'name': 'getPositionInfo', 'stateMutability': 'view',
     'inputs': [{'name': 'poolId', 'type': 'bytes32'}, {'name': 'owner', 'type': 'address'},
                {'name': 'tickLower', 'type': 'int24'}, {'name': 'tickUpper', 'type': 'int24'},
                {'name': 'salt', 'type': 'bytes32'}],
     'outputs': [{'name': 'liquidity', 'type': 'uint128'},
                 {'name': 'feeGrowthInside0LastX128', 'type': 'uint256'},
                 {'name': 'feeGrowthInside1LastX128', 'type': 'uint256'}]},
    {'type': 'function', 'name': 'getFeeGrowthInside', 'stateMutability': 'view',
     'inputs': [{'name': 'poolId', 'type': 'bytes32'}, {'name': 'tickLower', 'type': 'int24'},
                {'name': 'tickUpper', 'type': 'int24'}],
     'outputs': [{'name': 'feeGrowthInside0X128', 'type': 'uint256'},
                 {'name': 'feeGrowthInside1X128', 'type': 'uint256'}]},
    {'type': 'function', 'name': 'getLiquidity', 'stateMutability': 'view',
     'inputs': [{'name': 'poolId', 'type': 'bytes32'}],
     'outputs': [{'name': 'liquidity', 'type': 'uint128'}]},
    {'type': 'function', 'name': 'getTickBitmap', 'stateMutability': 'view',
     'inputs': [{'name': 'poolId', 'type': 'bytes32'}, {'name': 'wordPosition', 'type': 'int16'}],
     'outputs': [{'name': 'bitmap', 'type': 'uint256'}]},
    {'type': 'function', 'name': 'getTickLiquidity', 'stateMutability': 'view',
     'inputs': [{'name': 'poolId', 'type': 'bytes32'}, {'name': 'tick', 'type': 'int24'}],
     'outputs': [{'name': 'liquidityGross', 'type': 'uint128'}, {'name': 'liquidityNet', 'type': 'int128'}]},
]
STATE_FUNCTIONS = {function['name']: function for function in STATE_ABI}


def v4_pool_id(key, codec=None):
    codec = codec or Web3().codec
    return Web3.to_hex(Web3.keccak(codec.encode(
        [component['type'] for component in POOL_KEY_COMPONENTS], key)))


async def read_state_view(read_function, state_view, name, block, args):
    function = STATE_FUNCTIONS[name]
    inputs = [collapse_if_tuple(item) for item in function['inputs']]
    outputs = [collapse_if_tuple(item) for item in function['outputs']]
    return await read_function(state_view, name+'('+','.join(inputs)+')', inputs, args, outputs, block)


async def read_pool_slot0(call, pool_id, block):
    return await call('getSlot0', block, [bytes.fromhex(pool_id[2:])])


async def read_pool_state(read_function, state_view, pool_id, block):
    async def call(name, context, args):
        return await read_state_view(read_function, state_view, name, context, args)
    slot, liquidity = await asyncio.gather(read_pool_slot0(call, pool_id, block),
        call('getLiquidity', block, [bytes.fromhex(pool_id[2:])]))
    return {'sqrtRatioX96': str(slot[0]), 'tick': slot[1], 'protocolFee': slot[2],
            'lpFee': slot[3], 'liquidity': str(liquidity[0])}


async def read_tick_bitmap_words(read_function, manager, pool_id, positions, block):
    """Read the same StateLibrary bitmap slots in bounded transport batches.

    V4 StateLibrary uses pools slot 6 and tickBitmap offset 5. This is storage
    acquisition only: the SDK still traverses and prices every initialized tick.
    https://github.com/Uniswap/v4-core/blob/main/src/libraries/StateLibrary.sol
    """
    codec = Web3().codec
    state_slot = int.from_bytes(Web3.keccak(codec.encode(
        ['bytes32', 'uint256'], [bytes.fromhex(pool_id[2:]), 6])), 'big')
    async def read_batch(batch):
        slots = [Web3.keccak(codec.encode(['int256', 'uint256'], [position, state_slot+5]))
                 for position in batch]
        values, = await read_function(manager, 'extsload(bytes32[])', ['bytes32[]'], [slots], ['bytes32[]'], block)
        return [(position, int.from_bytes(value, 'big')) for position, value in zip(batch, values, strict=True)]
    # Batches only bound calldata, not coverage: every requested word is read.
    # Keep optional bulk work from queuing every batch ahead of required reads.
    result = []
    for index in range(0, len(positions), 128):
        result.extend(await read_batch(positions[index:index+128]))
    return result
