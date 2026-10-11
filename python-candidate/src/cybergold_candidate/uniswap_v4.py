"""Shared V4 singleton identities and block-bound StateView reads.

The caller retains its RPC transport, caching, errors and cancellation. These
helpers provide ABI/identity data and observations, never swap or LP arithmetic.
"""
import asyncio

from eth_utils.abi import collapse_if_tuple
from web3 import Web3

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
