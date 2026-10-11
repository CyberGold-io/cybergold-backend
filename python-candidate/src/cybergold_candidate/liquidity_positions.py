"""Wallet-owned Uniswap v4 CYGLD/PAXG positions at one canonical block."""
import asyncio
import re
from types import SimpleNamespace

from eth_utils.abi import collapse_if_tuple
from web3 import AsyncWeb3, Web3

from .protocol_facts import handle_protocol_facts
from .rpc_transport import rpc_provider
from .wallet_balances import WalletRequest
from .uniswap_v4 import (POOL_ID, POSITION_MANAGER, STATE_VIEW, INITIALIZATION_BLOCK,
    POOL_KEY_COMPONENTS, STATE_ABI, read_pool_slot0, v4_pool_id)
from fastapi.responses import JSONResponse
from pydantic import ValidationError

TRANSFER_TOPIC = Web3.to_hex(Web3.keccak(text='Transfer(address,address,uint256)'))
Q96 = 1 << 96
Q128 = 1 << 128
LOG_BLOCK_RANGE = 10000

POSITION_ABI = [
    {'type': 'function', 'name': 'balanceOf', 'stateMutability': 'view',
     'inputs': [{'name': 'holder', 'type': 'address'}],
     'outputs': [{'name': 'balance', 'type': 'uint256'}]},
    {'type': 'function', 'name': 'getPoolAndPositionInfo', 'stateMutability': 'view',
     'inputs': [{'name': 'tokenId', 'type': 'uint256'}],
     'outputs': [{'name': 'poolKey', 'type': 'tuple', 'components': POOL_KEY_COMPONENTS},
                 {'name': 'info', 'type': 'uint256'}]},
]

# Exact Q128.128 factors from Uniswap v4 TickMath.getSqrtPriceAtTick.
# https://github.com/Uniswap/v4-core/blob/main/src/libraries/TickMath.sol
TICK_FACTORS = (
    0xfffcb933bd6fad37aa2d162d1a594001, 0xfff97272373d413259a46990580e213a,
    0xfff2e50f5f656932ef12357cf3c7fdcc, 0xffe5caca7e10e4e61c3624eaa0941cd0,
    0xffcb9843d60f6159c9db58835c926644, 0xff973b41fa98c081472e6896dfb254c0,
    0xff2ea16466c96a3843ec78b326b52861, 0xfe5dee046a99a2a811c461f1969c3053,
    0xfcbe86c7900a88aedcffc83b479aa3a4, 0xf987a7253ac413176f2b074cf7815e54,
    0xf3392b0822b70005940c7a398e4b70f3, 0xe7159475a2c29b7443b29c7fa6e889d9,
    0xd097f3bdfd2022b8845ad8f792aa5825, 0xa9f746462d870fdf8a65dc1f90e061e5,
    0x70d869a156d2a1b890bb3df62baf32f7, 0x31be135f97d08fd981231505542fcfa6,
    0x9aa508b5b7a84e1c677de54f3e99bc9, 0x5d6af8dedb81196699c329225ee604,
    0x2216e584f5fa1ea926041bedfe98, 0x48a170391f7dc42444e8fa2,
)


def sqrt_price_at_tick(tick):
    absolute = abs(tick)
    if absolute > 887272:
        raise ValueError('Tick is outside the Uniswap price range')
    ratio = 1 << 128
    for bit, factor in enumerate(TICK_FACTORS):
        if absolute & (1 << bit):
            ratio = ratio * factor >> 128
    if tick > 0:
        ratio = ((1 << 256) - 1) // ratio
    return (ratio >> 32) + bool(ratio % (1 << 32))


def liquidity_token_amounts(sqrt_price, lower_tick, upper_tick, liquidity):
    """Principal amounts in token wei, rounded down as an LP withdrawal."""
    lower, upper = sqrt_price_at_tick(lower_tick), sqrt_price_at_tick(upper_tick)
    price = min(max(sqrt_price, lower), upper)
    # SqrtPriceMath.getAmount0Delta/getAmount1Delta, roundUp=false.
    return ((liquidity << 96) * (upper - price) // upper // price,
            liquidity * (price - lower) // Q96)


def unclaimed_fee_amount(liquidity, current_growth, last_growth):
    """Position.update's exact uint256 growth subtraction and floor division."""
    # Growth overflow is intentional in Uniswap; fee changes credit the caller
    # immediately, so Position.State has no additional cached tokens-owed field.
    # https://github.com/Uniswap/v4-core/blob/main/src/libraries/Position.sol
    return liquidity * ((current_growth - last_growth) % (1 << 256)) // Q128


def token_decimal(amount):
    whole, fractional = divmod(amount, 10**18)
    return str(whole) + ('.' + str(fractional).zfill(18).rstrip('0') if fractional else '')


def signed_tick(info, shift):
    raw = (info >> shift) & 0xffffff
    return raw - 0x1000000 if raw >= 0x800000 else raw


async def gather_read_tasks(*operations):
    """Keep the observation's deadline and cancellation over every sibling."""
    tasks = [asyncio.create_task(operation) for operation in operations]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class LiquidityPositionsRpc:
    def __init__(self, settings, w3=None):
        self.w3 = w3 or AsyncWeb3(rpc_provider(settings.RPC_URL, settings.RPC_AUTHORIZATION))
        self.position_contract = self.w3.eth.contract(abi=POSITION_ABI)
        self.state_contract = self.w3.eth.contract(abi=STATE_ABI)

    async def block(self):
        block = await self.w3.eth.get_block('latest')
        return {'hash': Web3.to_hex(block['hash']), 'number': block['number']}

    async def assert_canonical(self, block):
        # Reuse the existing readers' snapshot relationship for range logs.
        current = await self.w3.eth.get_block(block['number'])
        if Web3.to_hex(current['hash']).lower() != block['hash'].lower():
            raise ValueError('Liquidity positions snapshot changed')

    async def call(self, name, block, args):
        is_state = name in {function['name'] for function in STATE_ABI}
        abi = STATE_ABI if is_state else POSITION_ABI
        contract = self.state_contract if is_state else self.position_contract
        address = STATE_VIEW if is_state else POSITION_MANAGER
        function = next(item for item in abi if item['name'] == name)
        response = await self.w3.provider.make_request('eth_call', [
            {'to': address, 'data': contract.encode_abi(name, args=args)},
            {'blockHash': block['hash'], 'requireCanonical': True}])
        if 'error' in response:
            raise ValueError('Liquidity position contract read failed')
        return self.w3.codec.decode([collapse_if_tuple(output) for output in function['outputs']],
                                   bytes.fromhex(response['result'][2:]))

    async def transfers(self, holder, incoming, start, end):
        topic = '0x' + holder[2:].lower().zfill(64)
        response = await self.w3.provider.make_request('eth_getLogs', [{
            'address': POSITION_MANAGER, 'fromBlock': hex(start), 'toBlock': hex(end),
            'topics': [TRANSFER_TOPIC, None, topic] if incoming else [TRANSFER_TOPIC, topic],
        }])
        if 'error' in response:
            message = response['error'].get('message', '')
            # Only split ordinary supplier range/result-size errors; an outage
            # stays unavailable instead of being retried across many ranges.
            range_error = re.search(
                r'block range|range.*(?:limit|large|exceed)|query.*(?:limit|large|exceed)|'
                r'more than [\d,]+.*(?:results|blocks)|(?:response|result).*too (?:large|many)|'
                r'(?:logs?|response|result).*(?:size|count|limit).*exceed|'
                r'(?:logs?|response|result).*exceed.*(?:maximum|limit)', message, re.IGNORECASE)
            if start == end or not range_error:
                raise ValueError('Liquidity position transfer discovery failed')
            midpoint = (start + end) // 2
            first = await self.transfers(holder, incoming, start, midpoint)
            second = await self.transfers(holder, incoming, midpoint + 1, end)
            return first + second
        return response['result']

    async def close(self):
        await self.w3.provider.disconnect()


class LiquidityPositions:
    def __init__(self, settings, rpc=None):
        self.settings, self.rpc = settings, rpc

    async def get(self, holder):
        if self.rpc is None:
            self.rpc = LiquidityPositionsRpc(self.settings)
        holder = Web3.to_checksum_address(holder)
        async with asyncio.timeout(60):
            block = await self.rpc.block()
            balance, = await self.rpc.call('balanceOf', block, [holder])
            if balance == 0:
                await self.rpc.assert_canonical(block)
                return {'positions': [], 'paxgAmount': '0', 'cygldAmount': '0',
                        'blockNumber': str(block['number'])}
            # The latest wallet Transfer for a token establishes its current
            # ownership. When the owned IDs cover balanceOf, all current NFTs
            # have been found; otherwise scan back to this pool's creation.
            # An earlier NFT cannot belong to this pool. Never truncate history
            # by an arbitrary recent lookback or publish a partial observation.
            token_ids, seen = set(), set()
            end = block['number']
            while end >= INITIALIZATION_BLOCK and len(token_ids) < balance:
                start = max(INITIALIZATION_BLOCK, end - LOG_BLOCK_RANGE + 1)
                incoming, outgoing = await gather_read_tasks(
                    self.rpc.transfers(holder, True, start, end),
                    self.rpc.transfers(holder, False, start, end))
                transfers = sorted(incoming + outgoing, reverse=True,
                    key=lambda log: (int(log['blockNumber'], 16), int(log['logIndex'], 16)))
                for log in transfers:
                    token_id = int(log['topics'][3], 16)
                    if token_id in seen:
                        continue
                    seen.add(token_id)
                    if log['topics'][2][-40:].lower() == holder[2:].lower():
                        token_ids.add(token_id)  # Includes self-transfers, deduplicated above.
                end = start - 1

            async def position(token_id):
                key, info = await self.rpc.call('getPoolAndPositionInfo', block, [token_id])
                pool_id = v4_pool_id(key, self.rpc.w3.codec)
                if pool_id != POOL_ID:
                    return None
                lower, upper = signed_tick(info, 8), signed_tick(info, 32)
                pool = bytes.fromhex(POOL_ID[2:])
                # PoolManager records the position for PositionManager, with
                # the NFT's tokenId as salt. This read also supplies liquidity.
                liquidity, last0, last1 = await self.rpc.call('getPositionInfo', block,
                    [pool, POSITION_MANAGER, lower, upper, token_id.to_bytes(32, 'big')])
                fee0, fee1 = 0, 0
                if liquidity:
                    inside0, inside1 = await self.rpc.call('getFeeGrowthInside', block, [pool, lower, upper])
                    fee0 = unclaimed_fee_amount(liquidity, inside0, last0)
                    fee1 = unclaimed_fee_amount(liquidity, inside1, last1)
                # Removing all liquidity already credits its accrued fees;
                # a zero-liquidity NFT cannot retain unclaimed position fees.
                return token_id, lower, upper, liquidity, fee0, fee1

            owned = await gather_read_tasks(*(position(token_id) for token_id in sorted(token_ids)))
            owned = [position for position in owned if position is not None]
            positions, paxg_total, cygld_total = [], 0, 0
            if owned:
                sqrt_price, *_ = await read_pool_slot0(self.rpc.call, POOL_ID, block)
                for token_id, lower, upper, liquidity, fee0, fee1 in owned:
                    paxg, cygld = liquidity_token_amounts(sqrt_price, lower, upper, liquidity)
                    paxg += fee0
                    cygld += fee1
                    paxg_total += paxg
                    cygld_total += cygld
                    positions.append({'tokenId': str(token_id), 'paxgAmount': token_decimal(paxg),
                                      'cygldAmount': token_decimal(cygld)})
            await self.rpc.assert_canonical(block)
            return {'positions': positions, 'paxgAmount': token_decimal(paxg_total),
                    'cygldAmount': token_decimal(cygld_total), 'blockNumber': str(block['number'])}

    async def close(self):
        if self.rpc:
            await self.rpc.close()


async def handle_liquidity_positions(request, service):
    try:
        holder = WalletRequest.model_validate(dict(request.query_params)).holder
    except ValidationError:
        return JSONResponse({'error': 'A valid holder address is required.'}, status_code=400,
                            headers={'Cache-Control': 'no-store'})
    bound = SimpleNamespace(get=lambda: service.get(holder)) if service else None
    return await handle_protocol_facts(request, bound, 'liquidity-positions',
                                       'Liquidity positions are temporarily unavailable.')
