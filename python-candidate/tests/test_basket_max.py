"""Executable proportional MAX: integer boundaries and real pinned RPC layout."""
import asyncio
import random
from types import SimpleNamespace
import unittest

from eth_utils.abi import collapse_if_tuple
import httpx
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncBaseProvider

from cybergold_candidate.app import create_app
from cybergold_candidate.basket_arithmetic import BasketArithmetic, FP, PPM
from cybergold_candidate.basket_max import BasketMax, BasketMaxRpc, proportional_maximum
from cybergold_candidate.basket_preview import ABI as PREVIEW_ABI
from cybergold_candidate.protocol_facts import ABI as FACTS_ABI

HASH = '0x' + 'a' * 64
CORE, HELPERS = '0x' + '1' * 40, '0x' + '2' * 40
ASSETS = ['0x' + '3' * 40, '0x' + '4' * 40, '0x' + '5' * 40]


class ArithmeticTests(unittest.TestCase):
    def test_core_fee_plateau_is_canonicalized_before_gross_cap(self):
        self.assertEqual(proportional_maximum([100], [PPM], [0], [FP], 900000, 2, 0), (10, [10]))
        # Gross budgets 1..10 all issue one net unit and canonical gross one.
        # The next driver, 11, needs canonical gross 11 and exceeds cap two.
        self.assertEqual(proportional_maximum([100], [PPM], [0], [FP], 0, 2, 0), (2, [2]))

    def test_largest_driver_matches_exhaustive_independent_fee_rounding(self):
        rng = random.Random(461)
        for _ in range(500):
            weights = [rng.choice([0, 100000, 250000, 500000, 750000]), 0]
            weights[1] = PPM - weights[0]
            decimals = [rng.choice([0, 1, 2]), rng.choice([0, 1, 2])]
            conversions = [FP * rng.randint(1, 4), FP * rng.randint(1, 4)]
            fee, capacity = rng.choice([0, 1000, 100000, 500000, 900000]), rng.randint(0, 40)
            driver = rng.choice([i for i, weight in enumerate(weights) if weight])
            budgets = [rng.randint(0, 35), rng.randint(0, 35)]
            scales = [weight * 10**precision for weight, precision in zip(weights, decimals)]
            valid = []
            for amount in range(budgets[driver] + 1):
                vector = [amount * scale // scales[driver] for scale in scales]
                if any(value > budget for value, budget in zip(vector, budgets)):
                    continue
                gross = min((vector[i] * conversions[i] // FP) * PPM // weight
                            for i, weight in enumerate(weights) if weight)
                net = gross - gross * fee // PPM
                # Enumerate the first gross representing this net, rather than
                # using the solver's inverse formula or capacity threshold.
                canonical = next((g for g in range(gross + 1) if g - g * fee // PPM == net), 0)
                if net and canonical <= capacity and capacity:
                    valid.append((amount, vector))
            expected = valid[-1] if valid else (0, [0, 0])
            self.assertEqual(proportional_maximum(budgets, weights, decimals, conversions,
                                                 fee, capacity, driver), expected)

    def test_full_wallet_vector_mixed_precision_zero_weight_and_wide_uint(self):
        self.assertEqual(proportional_maximum([80, 13, 0], [500000, 500000, 0], [0, 1, 18],
                                             [FP, FP, 0], 0, 10**30, 0), (1, [1, 10, 0]))
        maximum = 2**200 + 123456789
        self.assertEqual(proportional_maximum([maximum, maximum], [500000, 500000], [18, 18],
                                             [FP, FP], 0, 2**255, 0), (maximum, [maximum, maximum]))
        self.assertEqual(proportional_maximum([10**30, 10**30], [500000, 500000], [6, 18],
                                             [FP, FP], 0, 0, 0), (0, [0, 0]))


class Provider(AsyncBaseProvider):
    def __init__(self, *, capacity=17, failure=None, reorg=False, blocked=False, zero_preview=False):
        super().__init__()
        self.calls, self.failure, self.reorg, self.blocked = [], failure, reorg, blocked
        self.started, self.cancelled = asyncio.Event(), 0
        self.zero_preview = zero_preview
        self.state = {'assets': ASSETS, 'weights': [500000, 500000, 0], 'conversions': [FP, FP, FP],
                      'issueFee': 100000, 'helperFee': 100000, 'supply': 20,
                      'maxSupply': 20 + capacity, 'effectiveCap': 20 + capacity,
                      'available': [0, 0, 0], 'recoveryValues': []}
        self.w3 = Web3()
        self.contracts = {group: self.w3.eth.contract(abi=abi) for group, abi in FACTS_ABI.items()}
        self.preview = self.w3.eth.contract(abi=PREVIEW_ABI)
        names = {'basketAssets': 'assets', 'basketTargetsPpm': 'weights',
                 'basketCygldPerUnitFp18': 'conversions', 'issuanceFeePpm': 'issueFee',
                 'totalSupply': 'supply', 'maxTotalSupply': 'maxSupply', 'effectiveCygldSupplyCap': 'effectiveCap'}
        self.rows = {self.contracts['core'].encode_abi(name): (name, key) for name, key in names.items()}

    def encoded(self, abi, value):
        return '0x' + self.w3.codec.encode([collapse_if_tuple(abi['outputs'][0])], [value]).hex()

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if method == 'eth_chainId':
            result = hex(31338)
        elif method == 'eth_getBlockByNumber':
            result = {'number': '0x65', 'timestamp': '0x6a000001',
                      'hash': '0x' + 'b' * 64 if self.reorg and params[0] != 'latest' else HASH}
        elif method == 'eth_call':
            self.started.set()
            if self.blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            address, data = params[0]['to'], params[0]['data']
            if data in self.rows:
                name, key = self.rows[data]
                abi = next(row for row in FACTS_ABI['core'] if row['name'] == name)
                value = self.state[key]
            elif address.lower() in [asset.lower() for asset in ASSETS]:
                name = 'decimals'
                self.assert_positive_asset(address)
                abi = next(row for row in FACTS_ABI['token'] if row['name'] == name)
                value = 6 if address.lower() == ASSETS[0].lower() else 18
            else:
                name = 'preview'
                _, args = self.preview.decode_function_input(data)
                result = BasketArithmetic(self.state).issue_in(list(args['maximumAmountsIn']))
                abi = PREVIEW_ABI[0]
                value = (0 if self.zero_preview else result['netCygldOut'],
                         (result['fees']['protocolFeeCygld'], result['fees']['helperFeeCygld']),
                         result['amountsInExact'], result['orderedCoreAssets'])
            if name == self.failure:
                return {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000,
                        'message': 'https://secret:password@private.invalid'}}
            result = self.encoded(abi, value)
        else:
            raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}

    def assert_positive_asset(self, address):
        if address.lower() == ASSETS[2].lower():
            raise AssertionError('Zero-weight token metadata is not needed for MAX')

    async def disconnect(self):
        pass


def service(provider):
    settings = SimpleNamespace(RPC_URL='http://synthetic.invalid', RPC_AUTHORIZATION='Bearer test-only',
        NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE, NEXT_PUBLIC_CHAIN_ID='31338',
        NEXT_PUBLIC_GOVERNANCE_DIAMOND_ADDRESS=None, NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=HELPERS)
    return BasketMax(settings, BasketMaxRpc(settings, AsyncWeb3(provider)), lambda: '2026-10-19T00:00:00.000Z')


REQUEST = {'driverToken': ASSETS[0], 'maximumAmountsIn': ['100', str(100 * 10**12), '0']}


class MaxTests(unittest.IsolatedAsyncioTestCase):
    async def test_positive_max_uses_one_hash_and_real_preview_with_current_capacity_and_helper_fee(self):
        provider = Provider()
        maximum = service(provider)
        self.addAsyncCleanup(maximum.close)
        result = await maximum.get(REQUEST)
        expected_driver, expected_amounts = proportional_maximum([100, 100 * 10**12, 0],
            provider.state['weights'], [6, 18, 0], provider.state['conversions'], 100000, 17, 0)
        self.assertEqual(result['driverAmount'], str(expected_driver))
        self.assertEqual(result['maximumAmountsIn'], [str(value) for value in expected_amounts])
        preview = BasketArithmetic(provider.state).issue_in(expected_amounts)
        self.assertEqual(result['netCygldOut'], str(preview['netCygldOut']))
        self.assertEqual(result['context'], {'chainId': 31338, 'blockNumber': '101', 'blockHash': HASH,
                                             'observedAt': '2026-10-19T00:00:00.000Z'})
        calls = [params for method, params in provider.calls if method == 'eth_call']
        self.assertEqual(len(calls), 10)  # Seven Core values, two positive-weight decimals, one preview.
        self.assertTrue(all(params[1] == {'blockHash': HASH, 'requireCanonical': True} for params in calls))
        self.assertEqual(sum(params[0]['to'].lower() == HELPERS.lower() for params in calls), 1)
        provider.state['supply'] = provider.state['maxSupply']
        self.assertEqual((await maximum.get(REQUEST))['driverAmount'], '0')

    async def test_zero_helper_fee_preserves_actual_preview_net(self):
        provider = Provider()
        provider.state['helperFee'] = 0
        maximum = service(provider)
        self.addAsyncCleanup(maximum.close)
        result = await maximum.get(REQUEST)
        preview = BasketArithmetic(provider.state).issue_in([int(value) for value in result['maximumAmountsIn']])
        self.assertEqual(result['netCygldOut'], str(preview['netCygldOut']))

    async def test_capacity_zero_and_wallet_dust_return_zero_without_preview(self):
        for provider, request in [(Provider(capacity=0), REQUEST),
                                  (Provider(), {**REQUEST, 'maximumAmountsIn': ['0', '100', '0']})]:
            maximum = service(provider)
            self.addAsyncCleanup(maximum.close)
            result = await maximum.get(request)
            self.assertEqual((result['driverAmount'], result['maximumAmountsIn'], result['netCygldOut']),
                             ('0', ['0', '0', '0'], '0'))
            self.assertFalse(any(method == 'eth_call' and params[0]['to'].lower() == HELPERS.lower()
                                 for method, params in provider.calls))
            self.assertEqual(sum(method == 'eth_call' for method, _ in provider.calls), 7)

    async def test_actual_zero_net_preview_clears_all_raw_budgets(self):
        maximum = service(Provider(zero_preview=True))
        self.addAsyncCleanup(maximum.close)
        result = await maximum.get(REQUEST)
        self.assertEqual((result['driverAmount'], result['maximumAmountsIn'], result['netCygldOut']),
                         ('0', ['0', '0', '0'], '0'))

    async def test_http_invalid_uint_without_rpc_and_invalid_canonical_vector(self):
        provider = Provider()
        app = create_app(basket_max=service(provider))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for budgets in [['-1'], [str(2**256)], ['1.5']]:
                response = await client.post('/api/quotes/basket-max', json={**REQUEST, 'maximumAmountsIn': budgets})
                self.assertEqual(response.status_code, 400)
            self.assertEqual(provider.calls, [])
            for request in [{**REQUEST, 'maximumAmountsIn': ['1']}, {**REQUEST, 'driverToken': ASSETS[2]}]:
                response = await client.post('/api/quotes/basket-max', json=request)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.headers['cache-control'], 'no-store')

    async def test_ordinary_read_preview_and_reorg_failures_are_not_published_as_zero(self):
        for provider in [Provider(failure='effectiveCygldSupplyCap'), Provider(failure='preview'), Provider(reorg=True)]:
            app = create_app(basket_max=service(provider))
            async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.post('/api/quotes/basket-max', json=REQUEST)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertIn('correlationId', response.json())
                self.assertNotIn('password', response.text)

    async def test_cancellation_reaches_existing_shared_reads(self):
        provider = Provider(blocked=True)
        maximum = service(provider)
        task = asyncio.create_task(maximum.get(REQUEST))
        await provider.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await maximum.close()
        self.assertGreater(provider.cancelled, 0)


if __name__ == '__main__':
    unittest.main()
