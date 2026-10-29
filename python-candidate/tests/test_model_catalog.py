"""First model requests consume stored catalog facts; optional failures fall back."""
import asyncio
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace
import unittest

from cybergold_candidate.market_swap import MarketQuotes
from cybergold_candidate.quote_models import PoolBaseline
from cybergold_candidate.uniswap_state import PoolRegistry, PAXG
from test_trade_quote import Engines, request


CORE = '0x'+'1'*40
USDT = '0x'+'2'*40
ADAPTER = '0x'+'3'*40
BLOCK = {'number': 1, 'hash': '0x'+'4'*64}
SETTINGS = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='1', NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=CORE)
CONNECTOR = {'id': '0x'+'5'*40, 'address': '0x'+'5'*40, 'protocol': 'v2', 'feePips': 3000,
    'token0': {'address': PAXG, 'decimals': 18, 'chainId': 1},
    'token1': {'address': USDT, 'decimals': 6, 'chainId': 1}}


async def nothing():
    pass


class Store:
    def __init__(self, *, fail=False):
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.fail = fail

    async def load(self, namespace):
        if namespace == 'inventory':
            self.started.set()
            await self.release.wait()
            if self.fail:
                raise OSError('Optional fixture store is unavailable')
            return {CONNECTOR['id']: deepcopy(CONNECTOR)}
        return {}


class ModelCatalogTests(unittest.IsolatedAsyncioTestCase):
    def registry(self, store):
        registry = PoolRegistry(SETTINGS, store=store, rpc=SimpleNamespace(close=nothing))
        self.addAsyncCleanup(registry.close)
        return registry

    def market(self, registry):
        market = MarketQuotes(SETTINGS, registry, sdk=SimpleNamespace(close=nothing))
        self.addAsyncCleanup(market.close)
        async def baseline(_plan, _block):
            return PoolBaseline(Fraction(2), Fraction(1), Fraction(0))
        market.route_baseline = baseline
        return market

    async def test_first_market_model_waits_for_catalog_before_enumerating_connector(self):
        store = Store()
        market = self.market(self.registry(store))
        operation = asyncio.create_task(market.get_model({'side': 'buy', 'mode': 'exact-in',
            'counterToken': USDT, 'adapter': ADAPTER}, block=BLOCK))
        try:
            await asyncio.wait_for(store.started.wait(), 1)
            await asyncio.sleep(0)
            self.assertFalse(operation.done())
        finally:
            store.release.set()
        value = await operation
        self.assertEqual(len(value['routes']), 1)
        self.assertEqual(value['routes'][0]['route']['branches'][0]['hops'][0]['pool']['id'], CONNECTOR['id'])

    async def test_market_optional_store_failure_keeps_existing_route_baseline_fallback(self):
        store = Store(fail=True)
        store.release.set()
        registry = self.registry(store)
        market = self.market(registry)
        value = await market.get_model({'side': 'buy', 'mode': 'exact-in',
            'counterToken': PAXG, 'adapter': ADAPTER}, block=BLOCK)
        self.assertTrue(registry.loaded)
        self.assertEqual(len(value['routes']), 1)
        self.assertIsNotNone(market.estimate(value, {'side': 'buy', 'mode': 'exact-in', 'amount': '1000'}))

    def trade(self, store):
        engines = Engines()
        self.addAsyncCleanup(engines.quotes.close)
        self.addAsyncCleanup(engines.pending.close)
        engines.market.registry = self.registry(store)
        baseline = {'routes': []}
        def packet(value):
            return {**engines.packet(value), **deepcopy(baseline)}
        def populated():
            baseline['routes'] = [{'points': [], 'exchangeRate': {'numerator': '2', 'denominator': '1'},
                'feeRetention': {'numerator': '1', 'denominator': '1'},
                'localImpact': {'numerator': '0', 'denominator': '1'}}]
        def market_packet(value):
            if CONNECTOR['id'] in engines.market.registry.inventory:
                populated()
            return packet(value)
        engines.market.packet = market_packet
        engines.market.estimate = lambda value, query: MarketQuotes.estimate(None, value, query)
        async def acquire(value, *, block):
            engines.models += 1
            populated()
            return packet(value)
        engines.market.get_model = acquire
        return engines

    async def test_trade_model_uses_loaded_facts_before_returning_its_first_packet(self):
        store = Store()
        engines = self.trade(store)
        query = {key: value for key, value in request(amount='1000').items() if key not in ('recipient', 'deadline')}
        operation = asyncio.create_task(engines.quotes.get_model(query))
        try:
            await asyncio.wait_for(store.started.wait(), 1)
            await asyncio.sleep(0)
            self.assertFalse(operation.done())
        finally:
            store.release.set()
        value = await operation
        self.assertEqual(value['estimate'], {'strategy': 'market', 'amount': '1998'})
        self.assertEqual((engines.heads, engines.models), (0, 0))

    async def test_trade_optional_store_failure_allows_ordinary_model_acquisition(self):
        store = Store(fail=True)
        store.release.set()
        engines = self.trade(store)
        query = {key: value for key, value in request(amount='1000').items() if key not in ('recipient', 'deadline')}
        value = await engines.quotes.get_model(query)
        self.assertEqual(value['estimate'], {'strategy': 'market', 'amount': '1998'})
        self.assertEqual((engines.heads, engines.models), (1, 1))


if __name__ == '__main__':
    unittest.main()
