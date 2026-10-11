"""Exact LP principal/fees, wallet Transfer ownership and ordinary outages."""
import asyncio
from decimal import Decimal, localcontext
import json
from types import SimpleNamespace
import unittest

import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.liquidity_positions import (
    INITIALIZATION_BLOCK, POOL_ID, POSITION_MANAGER, STATE_VIEW, TRANSFER_TOPIC,
    LiquidityPositions, LiquidityPositionsRpc, Q96, Q128, liquidity_token_amounts,
    sqrt_price_at_tick, token_decimal, unclaimed_fee_amount,
)

WALLET = '0x' + '1' * 40
OTHER = '0x' + '2' * 40
ZERO = '0x' + '0' * 40
HASH = '0x' + 'a' * 64
KEY = ('0x45804880De22913dAFE09f4980848ECE6EcbAf78',
       '0x601da021cAF3DB5AA63e700D239b5935C370601d', 100, 1, ZERO)


def transfer(token_id, sender, recipient, index):
    return {'blockNumber': hex(INITIALIZATION_BLOCK + 1), 'logIndex': hex(index),
            'topics': [TRANSFER_TOPIC, '0x' + sender[2:].zfill(64),
                       '0x' + recipient[2:].zfill(64), '0x' + f'{token_id:064x}']}


class Provider(AsyncBaseProvider):
    def __init__(self, range_limit=None, failure=None, reorg=False, pre_pool=False, blocked=False,
                 fee_growth=None, last_growth=None):
        super().__init__()
        self.calls = []
        self.range_limit, self.failure, self.reorg = range_limit, failure, reorg
        self.pre_pool, self.blocked = pre_pool, blocked
        self.started, self.cancelled = asyncio.Event(), 0
        self.codec = Web3().codec
        self.fee_growth, self.last_growth = fee_growth or {}, last_growth or {}
        self.events = [
            transfer(1, ZERO, WALLET, 0),
            transfer(2, ZERO, WALLET, 1), transfer(2, WALLET, OTHER, 2),
            transfer(3, ZERO, WALLET, 3), transfer(3, WALLET, ZERO, 4),
            transfer(4, ZERO, WALLET, 5), transfer(4, WALLET, WALLET, 6),
            transfer(5, ZERO, OTHER, 7), transfer(5, OTHER, WALLET, 8),
            transfer(6, ZERO, WALLET, 9), transfer(7, ZERO, WALLET, 10),
            transfer(8, ZERO, OTHER, 11),
        ]

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_getBlockByNumber':
            number = INITIALIZATION_BLOCK - 1 if self.pre_pool else INITIALIZATION_BLOCK + 10
            result = {'number': hex(number), 'timestamp': '0x6a000001',
                      'hash': '0x' + 'b' * 64 if self.reorg and params[0] != 'latest' else HASH}
        elif method == 'eth_getLogs':
            self.started.set()
            query = params[0]
            if self.blocked or (self.failure == 'incoming' and len(query['topics']) == 2):
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            if self.failure == 'incoming':
                await asyncio.sleep(0.01)  # Let the outgoing sibling enter its read.
                return self.error('ordinary discovery failure')
            if self.failure == 'logs':
                return self.error('https://password@private.invalid unavailable')
            if self.failure == 'rate':
                return self.error('RPC request rate limit exceeded')
            start, end = int(query['fromBlock'], 16), int(query['toBlock'], 16)
            if self.range_limit and end - start + 1 > self.range_limit:
                return self.error('requested block range exceeds maximum range')
            topics = query['topics']
            result = [row for row in self.events if start <= int(row['blockNumber'], 16) <= end
                      and all(topic is None or row['topics'][index] == topic
                              for index, topic in enumerate(topics))]
        elif method == 'eth_call':
            data = params[0]['data']
            selectors = {name: Web3.to_hex(Web3.keccak(text=signature))[:10]
                         for name, signature in (
                             ('info', 'getPoolAndPositionInfo(uint256)'),
                             ('balance', 'balanceOf(address)'),
                             ('position', 'getPositionInfo(bytes32,address,int24,int24,bytes32)'),
                             ('growth', 'getFeeGrowthInside(bytes32,int24,int24)'),
                             ('slot0', 'getSlot0(bytes32)'))}
            name = next(name for name, selector in selectors.items() if data.startswith(selector))
            if self.failure == name:
                return self.error('private provider password')
            token_id = int(data[10:], 16)
            if name == 'balance':
                holder = '0x' + data[-40:]
                owned = set()
                for event in self.events:
                    token = int(event['topics'][3], 16)
                    if event['topics'][2][-40:] == holder[2:]:
                        owned.add(token)
                    elif event['topics'][1][-40:] == holder[2:]:
                        owned.discard(token)
                result = '0x' + self.codec.encode(['uint256'], [len(owned)]).hex()
            elif name == 'info':
                key = (*KEY[:2], 500, *KEY[3:]) if token_id == 6 else KEY
                lower, upper = self.ticks(token_id)
                info = ((int(POOL_ID[2:52], 16) << 56) |
                        ((upper & 0xffffff) << 32) | ((lower & 0xffffff) << 8))
                result = '0x' + self.codec.encode(['(address,address,uint24,int24,address)', 'uint256'],
                                                 [key, info]).hex()
            elif name == 'position':
                _, _, _, _, salt = self.codec.decode(
                    ['bytes32', 'address', 'int24', 'int24', 'bytes32'], bytes.fromhex(data[10:]))
                token_id = int.from_bytes(salt, 'big')
                last0, last1 = self.last_growth.get(token_id, (0, 0))
                result = '0x' + self.codec.encode(['uint128', 'uint256', 'uint256'],
                    [0 if token_id == 7 else 10**18, last0, last1]).hex()
            elif name == 'growth':
                _, lower, upper = self.codec.decode(['bytes32', 'int24', 'int24'], bytes.fromhex(data[10:]))
                result = '0x' + self.codec.encode(['uint256', 'uint256'],
                    self.fee_growth.get((lower, upper), (0, 0))).hex()
            else:
                result = '0x' + self.codec.encode(['uint160', 'int24', 'uint24', 'uint24'],
                                                 [Q96, 0, 0, 100]).hex()
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    @staticmethod
    def ticks(token_id):
        return (-200, -100) if token_id == 4 else (100, 200) if token_id == 5 else (-100, 100)

    @staticmethod
    def error(message):
        return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': message}}

    async def disconnect(self):
        pass


def service(provider):
    # LP observation does not depend on unrelated Core, Helpers or database configuration.
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION=None)
    return LiquidityPositions(settings, LiquidityPositionsRpc(settings, AsyncWeb3(provider)))


class LiquidityMathTests(unittest.TestCase):
    def test_uniswap_tickmath_vectors_include_negative_ticks_and_extremes(self):
        for tick, expected in ((-887272, 4295128739), (0, Q96),
            (-1, 79224201403219477170569942574), (1, 79232123823359799118286999568),
            (887272, 1461446703485210103287273052203988822378723970342)):
            self.assertEqual(sqrt_price_at_tick(tick), expected)

    def test_principal_matches_independent_high_precision_price_equations(self):
        # Independent Decimal price equations exercise this pool's narrow range,
        # signed ranges and large liquidity without reproducing TickMath factors.
        for lower, upper, current, liquidity in (
            (34375, 34381, 34378, 10**24), (-100, 100, 0, 10**18),
            (100, 200, 0, 10**18), (-200, -100, 0, 10**18)):
            with localcontext() as context:
                context.prec = 120
                base = Decimal('1.0001')
                lower_price = base ** (Decimal(lower) / 2)
                upper_price = base ** (Decimal(upper) / 2)
                price = min(max(base ** (Decimal(current) / 2), lower_price), upper_price)
                expected0 = int(Decimal(liquidity) * (1 / price - 1 / upper_price))
                expected1 = int(Decimal(liquidity) * (price - lower_price))
            actual0, actual1 = liquidity_token_amounts(sqrt_price_at_tick(current), lower, upper, liquidity)
            self.assertLessEqual(abs(actual0 - expected0), 1)
            self.assertLessEqual(abs(actual1 - expected1), 1)

    def test_tick_boundaries_clamp_and_zero_liquidity_is_empty(self):
        lower, upper = sqrt_price_at_tick(-100), sqrt_price_at_tick(100)
        self.assertEqual(liquidity_token_amounts(lower, -100, 100, 10**18), (9999541693800299, 0))
        self.assertEqual(liquidity_token_amounts(upper, -100, 100, 10**18), (0, 9999541693800299))
        self.assertEqual(liquidity_token_amounts(lower - 1, -100, 100, 10**18),
                         liquidity_token_amounts(lower, -100, 100, 10**18))
        self.assertEqual(liquidity_token_amounts(upper + 1, -100, 100, 10**18),
                         liquidity_token_amounts(upper, -100, 100, 10**18))
        self.assertEqual(liquidity_token_amounts(Q96, -100, 100, 0), (0, 0))
        self.assertEqual(token_decimal(1), '0.000000000000000001')
        self.assertEqual(token_decimal(10**36 + 10**17), '1000000000000000000.1')

    def test_unclaimed_fees_use_prior_growth_round_down_and_uint256_wraparound(self):
        self.assertEqual(unclaimed_fee_amount(9, 7 * Q128, 5 * Q128), 18)
        self.assertEqual(unclaimed_fee_amount(3, Q128 // 2, 0), 1)
        self.assertEqual(unclaimed_fee_amount(7, Q128 // 2, (1 << 256) - Q128), 10)
        self.assertEqual(unclaimed_fee_amount(Q128 - 1, Q128 - 1, 0), Q128 - 2)
        self.assertEqual(unclaimed_fee_amount(0, Q128, (1 << 256) - Q128), 0)


class LiquidityPositionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_transfers_burns_self_transfers_unrelated_pool_and_zero_nft(self):
        provider = Provider()
        value = await service(provider).get(WALLET)
        self.assertEqual([row['tokenId'] for row in value['positions']], ['1', '4', '5', '7'])
        self.assertEqual(value['positions'][-1], {'tokenId': '7', 'paxgAmount': '0', 'cygldAmount': '0'})
        self.assertEqual(value['paxgAmount'], '0.009949671258790518')
        self.assertEqual(value['cygldAmount'], '0.009949671258790518')
        self.assertEqual(value['blockNumber'], str(INITIALIZATION_BLOCK + 10))
        calls = [params for method, params in provider.calls if method == 'eth_call']
        for params in calls:
            self.assertEqual(params[1], {'blockHash': HASH, 'requireCanonical': True})
            self.assertIn(params[0]['to'], (POSITION_MANAGER, STATE_VIEW))
        slot_selector = Web3.to_hex(Web3.keccak(text='getSlot0(bytes32)'))[:10]
        self.assertEqual(sum(params[0]['data'].startswith(slot_selector) for params in calls), 1)
        active_liquidity_selector = Web3.to_hex(Web3.keccak(text='getLiquidity(bytes32)'))[:10]
        self.assertFalse(any(params[0]['data'].startswith(active_liquidity_selector) for params in calls))
        # IDs 2 and 3 are gone, and another pool (6) receives only its metadata read.
        position_selector = Web3.to_hex(Web3.keccak(text='getPositionInfo(bytes32,address,int24,int24,bytes32)'))[:10]
        position_calls = [params for params in calls if params[0]['data'].startswith(position_selector)]
        queried = [int(params[0]['data'][-64:], 16) for params in position_calls]
        self.assertEqual(sorted(queried), [1, 4, 5, 7])
        for params in position_calls:
            pool, owner, lower, upper, salt = provider.codec.decode(
                ['bytes32', 'address', 'int24', 'int24', 'bytes32'], bytes.fromhex(params[0]['data'][10:]))
            self.assertEqual(pool, bytes.fromhex(POOL_ID[2:]))
            self.assertEqual(owner.lower(), POSITION_MANAGER.lower())
            self.assertEqual((lower, upper), provider.ticks(int.from_bytes(salt, 'big')))
        liquidity_selector = Web3.to_hex(Web3.keccak(text='getPositionLiquidity(uint256)'))[:10]
        self.assertFalse(any(params[0]['data'].startswith(liquidity_selector) for params in calls))

    async def test_total_quantities_add_unclaimed_fees_for_both_in_and_out_of_range_positions(self):
        provider = Provider(fee_growth={
            (-100, 100): (3 * Q128, 5 * Q128),
            (-200, -100): (Q128 // 2, 7 * Q128),
            (100, 200): (Q128, 2 * Q128),
        }, last_growth={1: (2 * Q128, 4 * Q128), 4: (0, 5 * Q128), 5: (Q128, 0)})
        value = await service(provider).get(WALLET)
        self.assertEqual(value['paxgAmount'], '1.509949671258790518')
        self.assertEqual(value['cygldAmount'], '5.009949671258790518')
        self.assertEqual(value['positions'], [
            {'tokenId': '1', 'paxgAmount': '1.004987272070749096', 'cygldAmount': '1.004987272070749096'},
            {'tokenId': '4', 'paxgAmount': '0.5', 'cygldAmount': '2.004962399188041422'},
            {'tokenId': '5', 'paxgAmount': '0.004962399188041422', 'cygldAmount': '2'},
            {'tokenId': '7', 'paxgAmount': '0', 'cygldAmount': '0'},
        ])

    async def test_provider_range_splitting_keeps_complete_transfer_history(self):
        value = await service(Provider(range_limit=3)).get(WALLET)
        self.assertEqual([row['tokenId'] for row in value['positions']], ['1', '4', '5', '7'])

    async def test_latest_global_transfer_order_handles_reacquisition_and_later_loss(self):
        provider = Provider()
        provider.events.extend([
            transfer(9, ZERO, WALLET, 12), transfer(9, WALLET, OTHER, 13),
            transfer(9, OTHER, WALLET, 14), transfer(9, WALLET, OTHER, 15),
            transfer(10, ZERO, WALLET, 16), transfer(10, WALLET, OTHER, 17),
            transfer(10, OTHER, WALLET, 18),
        ])
        value = await service(provider).get(WALLET)
        self.assertEqual([row['tokenId'] for row in value['positions']], ['1', '4', '5', '7', '10'])

    async def test_recent_transfers_covering_snapshot_balance_avoid_older_history(self):
        provider = Provider()
        reader = service(provider)
        latest = INITIALIZATION_BLOCK + 500000
        async def recent_block():
            return {'number': latest, 'hash': HASH}
        async def canonical(_block):
            pass
        reader.rpc.block = recent_block
        reader.rpc.assert_canonical = canonical
        for event in provider.events:
            event['blockNumber'] = hex(latest - 100)
        value = await reader.get(WALLET)
        self.assertEqual([row['tokenId'] for row in value['positions']], ['1', '4', '5', '7'])
        queries = [params[0] for method, params in provider.calls if method == 'eth_getLogs']
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(int(query['fromBlock'], 16) == latest - 9999 for query in queries))

    async def test_multiple_windows_preserve_latest_loss_before_older_mint(self):
        provider = Provider()
        latest = INITIALIZATION_BLOCK + 20000
        provider.events = [transfer(1, ZERO, WALLET, 0), transfer(2, ZERO, WALLET, 1),
                           transfer(2, WALLET, OTHER, 0)]
        provider.events[-1]['blockNumber'] = hex(latest - 1)
        reader = service(provider)
        async def block():
            return {'number': latest, 'hash': HASH}
        async def canonical(_block):
            pass
        reader.rpc.block, reader.rpc.assert_canonical = block, canonical
        value = await reader.get(WALLET)
        self.assertEqual([row['tokenId'] for row in value['positions']], ['1'])
        self.assertEqual(len([method for method, _ in provider.calls if method == 'eth_getLogs']), 4)

    async def test_older_unrelated_nft_does_not_require_history_before_this_pool(self):
        provider = Provider()
        next(event for event in provider.events if int(event['topics'][3], 16) == 6)['blockNumber'] = hex(INITIALIZATION_BLOCK - 100)
        value = await service(provider).get(WALLET)
        self.assertEqual([row['tokenId'] for row in value['positions']], ['1', '4', '5', '7'])
        queries = [params[0] for method, params in provider.calls if method == 'eth_getLogs']
        self.assertTrue(all(int(query['fromBlock'], 16) == INITIALIZATION_BLOCK for query in queries))

    async def test_rate_limit_is_unavailable_and_does_not_split_into_more_requests(self):
        provider = Provider(failure='rate')
        with self.assertRaises(ValueError):
            await service(provider).rpc.transfers(WALLET, True, INITIALIZATION_BLOCK, INITIALIZATION_BLOCK + 10)
        self.assertEqual(len([method for method, _ in provider.calls if method == 'eth_getLogs']), 1)

    async def test_concurrent_wallets_remain_independent(self):
        reader = service(Provider())
        first, second = await asyncio.gather(reader.get(WALLET), reader.get(OTHER))
        self.assertEqual([row['tokenId'] for row in first['positions']], ['1', '4', '5', '7'])
        self.assertEqual([row['tokenId'] for row in second['positions']], ['2', '8'])

    async def test_empty_wallet_and_pre_pool_snapshot_have_zero_but_outages_fail(self):
        empty = await service(Provider()).get('0x' + '9' * 40)
        self.assertEqual(empty['positions'], [])
        self.assertEqual(empty['paxgAmount'], '0')
        pre_pool = await service(Provider(pre_pool=True)).get(WALLET)
        self.assertEqual(pre_pool['positions'], [])
        self.assertEqual(pre_pool['paxgAmount'], '0')
        for provider in (Provider(failure='balance'), Provider(failure='logs'), Provider(failure='info'),
                         Provider(failure='position'), Provider(failure='growth'), Provider(failure='slot0'), Provider(reorg=True)):
            with self.assertRaises(ValueError):
                await service(provider).get(WALLET)

    async def test_fee_growth_failure_is_unavailable_without_principal_only_http_total(self):
        app = create_app(liquidity_positions=service(Provider(failure='growth')))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            response = await client.get('/api/account/liquidity-positions', params={'holder': WALLET})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('paxgAmount', response.json())
        self.assertNotIn('positions', response.json())
        self.assertNotIn('password', response.text)

    async def test_zero_position_manager_balance_skips_history_without_fabricating_errors(self):
        provider = Provider(failure='logs')
        value = await service(provider).get('0x' + '9' * 40)
        self.assertEqual(value['positions'], [])
        self.assertFalse(any(method == 'eth_getLogs' for method, _ in provider.calls))

    async def test_cancellation_stops_both_wallet_log_queries(self):
        provider = Provider(blocked=True)
        task = asyncio.create_task(service(provider).get(WALLET))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(provider.cancelled, 2)

    async def test_failed_incoming_query_cancels_and_awaits_blocked_outgoing_sibling(self):
        provider = Provider(failure='incoming')
        with self.assertRaises(ValueError):
            await service(provider).get(WALLET)
        self.assertEqual(provider.cancelled, 1)

    async def test_fixed_http_route_invalid_holder_redacted_outage_and_no_store(self):
        for failure, expected in ((None, 200), ('logs', 503)):
            provider = Provider(failure=failure)
            app = create_app(liquidity_positions=service(provider))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                invalid = await client.get('/api/account/liquidity-positions?holder=private-password')
                self.assertEqual(invalid.status_code, 400)
                response = await client.get('/api/account/liquidity-positions', params={
                    'holder': WALLET, 'pool': 'ignored', 'provider': 'http://untrusted.invalid'})
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertNotIn('password', response.text)
                self.assertNotIn('untrusted', json.dumps(provider.calls))
                if failure:
                    self.assertNotIn('positions', response.json())
                else:
                    self.assertEqual(len(response.json()['positions']), 4)
                self.assertIn('operation="/api/account/liquidity-positions"', (await client.get('/metrics')).text)


if __name__ == '__main__':
    unittest.main()
