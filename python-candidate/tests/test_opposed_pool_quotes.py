"""The accepted direction rule covers stored quotes and fresh preparation alike."""
from copy import deepcopy
import unittest

from cybergold_candidate.preview_errors import KnownPreviewError
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.quoter.quote_book import QuoteBook
from cybergold_candidate.tx_preparation import TransactionPreparation
from cybergold_candidate.economic_quotes import EconomicQuotes
from test_economic_quote_api import SharedStore
from test_progressive_economic_quotes import ScriptedQuoter
from test_quoter_plan_simulation import (
    CORE, HELPERS, PAXG, OTHER, USER, WETH, encoded, fixture, measured, route, stage)


def path(source, *outputs):
    value = route(source, outputs[-1])
    value['routes'][0]['steps'] = [
        {'kind': 1, 'currencyOut': output, 'fee': 500, 'tickSpacing': 10}
        for output in outputs]
    return value


def split_market(*, opposed=True):
    request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
    paths = [path(WETH, PAXG, OTHER, CORE),
             path(WETH, OTHER, PAXG, CORE) if opposed else path(WETH, PAXG, CORE)]
    plan = {'allocations': [{'kind': 1, 'amountIn': '5000'} for _ in paths],
            'conversions': {}, 'body': {'branches': [
                {'kind': 1, 'amountIn': '5000', 'data': {'route': row, 'feeCygld': '0'}}
                for row in paths]}}
    return request, plan


def raw_market(*, paid=False):
    return encoded(measured(1998 if paid else 2000, fees=(0, 0, 2 if paid else 0), stages=[
        stage(0, WETH, CORE, 5000, 1000), stage(1, WETH, CORE, 5000, 1000, branch=1)]))


def core_with_dormant_reverse():
    request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '10000'}], 'outputCurrency': CORE}
    plan = {'allocations': [{'kind': 0, 'amountIn': '10000'}], 'conversions': {},
            'body': {'branches': [{'kind': 0, 'amountIn': '10000', 'data': {
                'basketAssets': [PAXG],
                'acquisitions': [{'amountIn': '10000', 'route': route(WETH, PAXG)}],
                'continuations': [{'route': path(PAXG, WETH, CORE), 'feeCygld': '0'}]}}]}}
    return request, plan


def raw_core(residual=0):
    stages = [stage(0, WETH, PAXG, 10000, 100),
              stage(1, PAXG, CORE, 100, 900, returned=residual)]
    if residual:
        stages.append(stage(2, PAXG, CORE, residual, 100))
    return encoded(measured(900+(100 if residual else 0), stages=stages))


class OpposedPoolQuoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_same_direction_shared_pools_remain_quotable_and_preparable(self):
        request, plan = split_market(opposed=False)
        saved = deepcopy(plan)
        simulation, q, _, provider = fixture(raw_market(), raw_market(paid=True))
        quote = await simulation(request, plan)
        prepared = await TransactionPreparation(q).prepare({'quote': quote, 'sender': USER, 'recipient': USER})
        self.assertEqual(prepared['economicQuote']['quotedOutput'], quote['quotedOutput'])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(plan, saved)

    async def test_fresh_opposed_execution_identifies_the_exact_pool(self):
        request, plan = split_market()
        simulation, _, _, provider = fixture(raw_market())
        with self.assertRaisesRegex(KnownPreviewError, 'opposite directions') as raised:
            await simulation(request, plan)
        failure = public_quote_error(raised.exception)
        self.assertEqual(failure['code'], 'opposed-pool-directions')
        self.assertIn(PAXG.lower(), repr(failure['constraint']['pool']))
        self.assertIn(OTHER.lower(), repr(failure['constraint']['pool']))
        self.assertEqual(len(provider.calls), 1)

    async def test_stored_crossed_body_cannot_win_without_conversion_metadata(self):
        request, crossed = split_market()
        simulation, _, _, _ = fixture(raw_market())
        _, compatible = split_market(opposed=False)
        incumbent = await simulation(request, compatible)
        bad = {**deepcopy(incumbent), 'plan': crossed, 'quotedOutput': '999999999'}
        book = QuoteBook(request)
        self.assertTrue(book.observe(incumbent, identity='good', current=False))
        self.assertFalse(book.observe(bad, identity='bad', current=False))
        self.assertEqual(book.winner()['quotedOutput'], incumbent['quotedOutput'])
        # A newly measured disproof also removes the previous historical row.
        self.assertTrue(book.observe(bad, identity='good'))
        self.assertIsNone(book.winner())

    async def test_zero_dormant_residual_is_allowed_but_fresh_positive_reverse_is_not(self):
        request, plan = core_with_dormant_reverse()
        simulation, q, _, provider = fixture(raw_core(), raw_core(), raw_core(5))
        quote = await simulation(request, plan)
        self.assertNotIn('0:residual:0', [row['operation'] for row in quote['conversionObservations']])
        book = QuoteBook(request)
        self.assertTrue(book.observe(quote, identity='zero', current=False))
        self.assertIsNotNone(book.winner())
        preparation = TransactionPreparation(q)
        prepared = await preparation.prepare({'quote': quote, 'sender': USER, 'recipient': USER})
        self.assertEqual(prepared['economicQuote']['quotedOutput'], quote['quotedOutput'])
        with self.assertRaisesRegex(KnownPreviewError, 'opposite directions'):
            await preparation.prepare({'quote': quote, 'sender': USER, 'recipient': USER})
        self.assertEqual(len(provider.calls), 3)

    async def test_cached_basket_opposition_falls_through_to_ordinary_search(self):
        # Cache/control-flow fixture; these amounts are not contract economics.
        request = {'intent': 2, 'inputs': [{'currency': PAXG, 'amount': '100'},
                    {'currency': OTHER, 'amount': '100'}], 'outputCurrency': CORE}
        body = {'continuations': [
            {'route': path(PAXG, OTHER, CORE), 'feeCygld': '0'},
            {'route': path(OTHER, PAXG, CORE), 'feeCygld': '0'}]}
        bad = {'request': deepcopy(request), 'inputs': deepcopy(request['inputs']),
               'quotedOutput': '99999', 'plan': {'allocations': [], 'conversions': {}, 'body': body},
               'context': {'chainId': 31338}, 'conversionObservations': [
                   {'operation': f'0:residual:{index}', 'fundedInput': '5'} for index in range(2)]}
        good = deepcopy(bad)
        good['quotedOutput'] = '900'
        for index, currency in enumerate((PAXG, OTHER)):
            good['plan']['body']['continuations'][index]['route'] = route(currency, currency)
        searched, frames = [], []
        async def search(current, callback, **_):
            searched.append(deepcopy(current))
            await callback({'type': 'qualified', 'value': good})
            return good
        store = SharedStore()
        store.rows[store.capture_scope(request)] = deepcopy(bad)
        service = EconomicQuotes(ScriptedQuoter(search), store)
        self.addAsyncCleanup(service.close)
        async def publish(frame):
            frames.append(deepcopy(frame))
        self.assertIsNone(await service.cached_offer(request, bad, store.capture_scope(request)))
        value = await service.progressive(request, publish)
        self.assertEqual(searched, [request])
        self.assertEqual(value['quotedOutput'], '900')
        self.assertTrue(frames)
        self.assertTrue(all(frame['value']['quotedOutput'] == '900' for frame in frames))


if __name__ == '__main__':
    unittest.main()
