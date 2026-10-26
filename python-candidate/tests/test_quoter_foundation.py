"""Quoter migration and the normal zero-return routing regression.

The injected path outcomes isolate selection, not AMM arithmetic. Existing
Universal tests separately exercise the real SDK and ordered candidate state.
"""
import asyncio
from copy import deepcopy
import unittest

from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.ranking import prefer_completed
from cybergold_candidate.universal_quote import UniversalQuotes
from test_universal_quote import BLOCK, OTHER, PAXG, Engine, Quotes, pool, request


class QuoterFoundationTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_import_names_the_same_quoter(self):
        self.assertIs(UniversalQuotes, Quoter)
        self.assertEqual(Quoter.__module__, 'cybergold_candidate.quoter.search')

    async def test_zero_return_does_not_hide_productive_existing_alternative(self):
        service = Quotes(Engine())
        empty = pool(OTHER, PAXG, '0x' + '11' * 20)
        empty['protocol'] = 'v3'
        productive = pool(OTHER, PAXG, '0x' + '22' * 20)
        service.engine.registry.inventory = {p['id']: p for p in (empty, productive)}
        attempts = []

        async def price(route, amount, block, bank, canonical):
            identity = route[0]['pool']['id']
            attempts.append(identity)
            bank['last-swap'] = {'id': identity}
            return (0, 0) if identity == empty['id'] else (amount, amount * 2)

        service.price_path = price
        bank = {'prior-swap': {'value': 7}}
        _, output, retained = await service.conversion(
            OTHER, PAXG, 1000, deepcopy(BLOCK), bank, {}, first=True)
        self.assertEqual(output, 2000)
        self.assertEqual(retained, [])
        self.assertEqual(attempts, [empty['id'], productive['id']])
        self.assertEqual(bank['prior-swap'], {'value': 7})
        self.assertEqual(bank['last-swap']['id'], productive['id'])

    async def test_all_zero_preserves_normal_conversion_result_and_retention(self):
        service = Quotes(Engine())
        candidates = [pool(OTHER, PAXG, '0x' + part * 20) for part in ('11', '22')]
        candidates[0]['protocol'] = 'v3'
        service.engine.registry.inventory = {p['id']: p for p in candidates}
        attempts = set()

        async def price(route, amount, *_):
            attempts.add(route[0]['pool']['id'])
            return 0, 0

        service.price_path = price
        _, output, retained = await service.conversion(
            OTHER, PAXG, 1000, deepcopy(BLOCK), {}, {}, first=True)
        self.assertEqual(attempts, {p['id'] for p in candidates})
        self.assertEqual(output, 0)
        self.assertEqual(sum(int(row['amount']) for row in retained), 1000)

    async def test_completed_json_quote_contains_actual_producer_clock(self):
        value = await Quotes(Engine()).get(request())
        times = value['metrics']
        self.assertGreaterEqual(times['timeToFirstWholePlanMs'], 0)
        self.assertLessEqual(times['timeToFirstWholePlanMs'], times['searchMs'])
        self.assertLessEqual(times['searchMs'], times['totalMs'])
        self.assertLessEqual(times['canonicalCompletedMs'], times['totalMs'])
        self.assertIn(times['selectionReason'], ('complete', 'best-initial', 'first-extension'))
        self.assertEqual(times['timeToFirstWholePlanMs'], times['firstQualifiedMs'])
        self.assertLessEqual(times['searchMs'], times['selectionMs'])

    async def test_natural_completion_excludes_canonical_read_from_search_time(self):
        service = Quotes(Engine())
        async def canonical(block):
            await asyncio.sleep(.03)
        service.engine.assert_canonical = canonical
        value = await service.get(request())
        times = value['metrics']
        self.assertEqual(times['selectionReason'], 'complete')
        self.assertEqual(times['searchMs'], times['cleanupCompletedMs'])
        self.assertGreaterEqual(times['canonicalCompletedMs'] - times['searchMs'], 20)
        self.assertAlmostEqual(times['finalizationMs'], times['totalMs'] - times['searchMs'], delta=.002)

    def test_output_wins_then_true_scalar_funding_not_retention(self):
        def value(output, funding):
            return {'quotedOutput': str(output), 'inputs': [{'currency': OTHER, 'amount': str(funding)}],
                'estimatedRetainedInputCharges': [{'currency': OTHER, 'amount': '60000'}]}
        old = value(249, 100000)
        self.assertTrue(prefer_completed(value(754, 100000), old, scalar=True))
        self.assertFalse(prefer_completed(value(248, 40000), old, scalar=True))
        self.assertTrue(prefer_completed(value(249, 40000), old, scalar=True))
        self.assertFalse(prefer_completed(value(249, 100000), old, scalar=True))
        self.assertFalse(prefer_completed(value(249, 40000), old, scalar=False))
        different_currency = value(249, 1)
        different_currency['inputs'][0]['currency'] = PAXG
        self.assertFalse(prefer_completed(different_currency, old, scalar=True))


if __name__ == '__main__':
    unittest.main()
