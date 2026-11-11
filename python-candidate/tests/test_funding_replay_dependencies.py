"""Sizing advances private state only when a later Core operation consumes it.

These are def-use controls over complete plan structures, not price oracles;
existing real-SDK and captured Helpers tests validate the nominees' economics.
"""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cybergold_candidate.quoter import core_funding
from cybergold_candidate.quoter.evaluate import encode_nomination
from cybergold_candidate.quoter.funding import funding_proposal
from test_universal_quote import WETH, PAXG, OTHER, CORE
from quoter_fixture import synthetic_pool


class FundingReplayDependencyTests(unittest.IsolatedAsyncioTestCase):
    def value(self, core_first=True):
        acquire, residual = {}, {}
        acquisitions, continuations = [], []
        for index, asset in enumerate((PAXG, OTHER)):
            pool = synthetic_pool(WETH, asset, 9761+index, 'v2')
            route, chosen = encode_nomination(WETH, asset, ([{'amountIn': '10000', 'hops': [
                {'pool': pool, 'zeroForOne': pool['token0']['address'].lower() == WETH.lower()}]}], []))
            acquisitions.append({'amountIn': '10000', 'route': route})
            acquire[index] = chosen
            pool = synthetic_pool(asset, CORE, 9771+index, 'v2')
            template, chosen = encode_nomination(asset, CORE, ([{'amountIn': '100', 'hops': [
                {'pool': pool, 'zeroForOne': pool['token0']['address'].lower() == asset.lower()}]}], []))
            residual[index] = chosen
            continuations.append({'route': template, 'feeCygld': '11'})
        core = {'kind': 0, 'amountIn': '20000', 'data': {'basketAssets': [PAXG, OTHER],
                'acquisitions': acquisitions, 'continuations': continuations}}
        pool = synthetic_pool(WETH, CORE, 9781, 'v2')
        market_template, market_chosen = encode_nomination(WETH, CORE, ([{'amountIn': '1000', 'hops': [
            {'pool': pool, 'zeroForOne': pool['token0']['address'].lower() == WETH.lower()}]}], []))
        market = {'kind': 1, 'amountIn': '1000',
                  'data': {'route': market_template, 'feeCygld': '17'}}
        branches = [core, market] if core_first else [market, core]
        core_index, market_index = (0, 1) if core_first else (1, 0)
        conversions = {f'{core_index}:acquire:{i}': chosen for i, chosen in acquire.items()}
        conversions.update({f'{core_index}:residual:{i}': chosen for i, chosen in residual.items()})
        conversions[f'{market_index}:market'] = market_chosen
        request = {'intent': 0, 'inputs': [{'currency': WETH, 'amount': '21000'}], 'outputCurrency': CORE}
        plan = {'body': {'branches': branches}, 'allocations': [
            {'kind': row['kind'], 'amountIn': row['amountIn']} for row in branches],
            'conversions': conversions}
        measured = [{'branch': core_index, 'index': index, 'currency': asset,
                     'consumed': 4000, 'acquired': 9969, 'residual': 5969}
                    for index, asset in enumerate((PAXG, OTHER))]
        return {'request': request, 'plan': plan}, measured

    async def test_terminal_market_and_residual_bank_advances_are_not_dependencies(self):
        value, measured = self.value()
        original = deepcopy(value)
        selected = deepcopy(value['plan']['conversions']['0:residual:0'])
        for useful in (0, 100):
            with self.subTest(useful=useful):
                residuals = {(0, 0): (useful, selected)} if useful else {}
                targets = []
                async def inverse(q, chosen, source, target, funded, desired, block, bank, canonical):
                    targets.append(desired)
                    return desired, deepcopy(chosen)
                async def unused(q, chosen, source, target, amount, block, bank, canonical):
                    if amount:
                        raise AssertionError('A terminal state advance has no bank consumer')
                    return 0
                with patch.object(core_funding, 'inverse_conversion', inverse), patch.object(core_funding, '_replay', unused):
                    result = await core_funding._sized(SimpleNamespace(), value, measured, residuals, {}, {})
                expected = funding_proposal(value['request'], value['plan'], amounts={
                    '0:acquire:0': 4000+useful, '0:acquire:1': 4000}, conversions={
                        '0:residual:0': selected if useful else core_funding._retaining(PAXG, CORE),
                        '0:residual:1': core_funding._retaining(OTHER, CORE)})
                self.assertEqual(result, expected)
                self.assertEqual(targets, [4000+useful, 4000])
        self.assertEqual(value, original)

    async def test_market_before_core_still_advances_the_bank_used_by_each_inverse(self):
        value, measured = self.value(core_first=False)
        replayed, inverses = [], []
        async def replay(q, chosen, source, target, amount, block, bank, canonical):
            if not amount:
                return 0
            replayed.append(amount)
            bank['preceding-market-state'] = amount
            return 17
        async def inverse(q, chosen, source, target, funded, desired, block, bank, canonical):
            self.assertEqual(bank['preceding-market-state'], 1000)
            inverses.append(desired)
            return desired, deepcopy(chosen)
        with patch.object(core_funding, 'inverse_conversion', inverse), patch.object(core_funding, '_replay', replay):
            result = await core_funding._sized(SimpleNamespace(), value, measured, {}, {}, {})
        self.assertEqual(replayed, [1000])
        self.assertEqual(inverses, [4000, 4000])
        self.assertEqual(result['inputs'][0]['amount'], '9000')
        self.assertNotIn('preceding-market-state', result)

    async def test_useful_residual_advances_bank_for_later_core_but_not_after_last_core(self):
        value, measured = self.value()
        first = deepcopy(value['plan']['body']['branches'][0])
        value['plan']['body']['branches'] = [first, deepcopy(first)]
        value['plan']['allocations'] = [{'kind': 0, 'amountIn': '20000'} for _ in range(2)]
        value['request']['inputs'][0]['amount'] = '40000'
        conversions = {key: chosen for key, chosen in value['plan']['conversions'].items()
                       if key.startswith('0:')}
        conversions.update({f'1:{key[2:]}': deepcopy(chosen)
                            for key, chosen in list(conversions.items())})
        value['plan']['conversions'] = conversions
        measured += [{**row, 'branch': 1} for row in list(measured)]
        residuals = {(0, 0): (100, conversions['0:residual:0']),
                     (1, 0): (75, conversions['1:residual:0'])}
        original = deepcopy(value)
        replayed, targets = [], []
        async def replay(q, chosen, source, target, amount, block, bank, canonical):
            if amount:
                replayed.append((source, amount))
                bank['useful-residual-state'] = (source, amount)
            return 0
        async def inverse(q, chosen, source, target, funded, desired, block, bank, canonical):
            if len(targets) < 2:
                self.assertNotIn('useful-residual-state', bank)
            else:
                self.assertEqual(bank['useful-residual-state'], (PAXG, 100))
            targets.append(desired)
            return desired, deepcopy(chosen)
        with patch.object(core_funding, 'inverse_conversion', inverse), patch.object(core_funding, '_replay', replay):
            result = await core_funding._sized(SimpleNamespace(), value, measured, residuals, {}, {})
        self.assertEqual(replayed, [(PAXG, 100)])
        self.assertEqual(targets, [4100, 4000, 4075, 4000])
        self.assertEqual([row['amountIn'] for row in result['plan']['body']['branches']], ['8100', '8075'])
        self.assertEqual(result['inputs'][0]['amount'], '16175')
        self.assertEqual(value, original)


if __name__ == '__main__':
    unittest.main()
