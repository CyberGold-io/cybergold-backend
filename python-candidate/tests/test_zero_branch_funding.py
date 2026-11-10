"""Actual Helpers controls for zero Market slots beside productive Core.

Ten recorded source eth_calls cover two fresh bases, four neutral zero-slot
bodies, and four fee-paid preparations. These offline byte replays verify
execution representation; they do not claim to run route discovery.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from web3 import Web3

from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.pool_directions import conflicting_pool, quote_directions
from cybergold_candidate.quoter.simulation_funding import SIMULATION_SENDER
from cybergold_candidate.tx_preparation import TransactionPreparation, core_bounds


FIXTURE = Path(__file__).parent / 'fixtures/helpers-zero-branches-20261110.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ZeroBranchFundingTests(unittest.IsolatedAsyncioTestCase):
    async def replay_family(self, name):
        fixture = json.loads(FIXTURE.read_text())
        family = next(row for row in fixture['families'] if row['family'] == name)
        original = deepcopy(family)
        contracts = fixture['protocolConfiguration']['contracts']
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=contracts['core'],
            NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=contracts['helpers'],
            CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS=contracts['uniswapAdapter'])
        pending = [deepcopy(family['exchange'])]
        for case in family['cases']:
            pending.extend(deepcopy(case['exchanges']))
        calls = []

        async def recorded_request(method, params):
            self.assertEqual(method, 'eth_call')
            self.assertTrue(pending, 'Unrecorded state request')
            exchange = pending.pop(0)
            self.assertEqual(digest(exchange['params']), exchange['paramsSha256'])
            self.assertEqual(params, exchange['params'], exchange['case'] + ':' + exchange['phase'])
            if exchange['phase'] == 'paid-preparation':
                self.assertEqual(params[1], 'latest')
            else:
                self.assertEqual(params[1], {'blockHash': fixture['anchor']['hash'], 'requireCanonical': True})
            calls.append(deepcopy(params))
            return deepcopy(exchange['response'])

        rpc = SimpleNamespace(w3=SimpleNamespace(codec=Web3().codec,
            provider=SimpleNamespace(make_request=recorded_request)))
        engine = SimpleNamespace(registry=SimpleNamespace(chain=31338, seed=None, get_rpc=lambda: rpc),
            semaphore=asyncio.Semaphore(8),
            quote_sdk_branches=AsyncMock(side_effect=AssertionError('Complete wire controls need no SDK repricing')))
        q = Quoter(settings, engine, now=lambda: fixture['finishedAt'])
        self.addAsyncCleanup(q.close)
        base = await q.plan_simulator(family['request'], family['selectedPlan'], block=fixture['anchor'])
        for key, expected in family['expected'].items():
            self.assertEqual(base[key], expected, key)
        self.assertGreater(int(base['fees']['coreProtocolFeeCygld']), 0)
        self.assertEqual(base['estimatedRetainedInputCharges'], [])
        for case in family['cases']:
            with self.subTest(case=case['case']):
                request, plan = deepcopy(case['request']), deepcopy(case['selectedPlan'])
                core_index, zero_index = case['coreIndex'], case['zeroIndex']
                self.assertEqual(plan['body']['branches'][core_index], base['plan']['body']['branches'][0])
                self.assertEqual(plan['body']['branches'][zero_index]['amountIn'], '0')
                self.assertEqual(plan['body']['branches'][zero_index]['kind'], 1)
                for operation, chosen in base['plan']['conversions'].items():
                    self.assertEqual(plan['conversions'][f'{core_index}:{operation.split(":", 1)[1]}'], chosen)
                neutral = await q.plan_simulator(request, plan, block=fixture['anchor'])
                self.assertEqual(core_bounds(neutral, 0), case['acceptedBounds']['expectedCoreOutputs'])
                self.assertIsNone(conflicting_pool(quote_directions(neutral, 31338)))
                payload = {'quote': deepcopy(neutral), 'sender': SIMULATION_SENDER,
                    'recipient': SIMULATION_SENDER, 'slippageBps': 0,
                    'acceptedBounds': deepcopy(case['acceptedBounds'])}
                preparation = TransactionPreparation(q, now=lambda: case['preparationNow'])
                prepared = await preparation.prepare(payload)
                paid = prepared['economicQuote']
                self.assertEqual(digest(prepared['plan']), case['preparedPlanSha256'])
                self.assertEqual(prepared['outputMinimum'], base['quotedOutput'])
                for value, expected in ((neutral, case['neutralExpected']), (paid, case['paidExpected'])):
                    for key, amount in expected.items():
                        self.assertEqual(value[key], amount, key)
                    for key in ('inputs', 'quotedOutput', 'fees', 'estimatedRecipientOutputs', 'estimatedRetainedInputCharges'):
                        self.assertEqual(value[key], base[key], key)
                    self.assertEqual(value['plan']['body'], plan['body'])
                    self.assertEqual(value['plan']['conversions'], plan['conversions'])
                    self.assertTrue(all(row['operation'].startswith(f'{core_index}:')
                                        for row in value['conversionObservations']))
                    self.assertTrue(all(int(row['branch']) == core_index
                                        for row in value['pricingEvidence']['stages']))
                # The accepted input maximum is checked before any extra call.
                payload['acceptedBounds']['inputs'][0]['amount'] = str(int(paid['inputs'][0]['amount']) - 1)
                before = len(calls)
                with self.assertRaisesRegex(InvalidPreview, 'Accepted input maximum'):
                    await preparation.prepare(payload)
                self.assertEqual(len(calls), before)
        self.assertFalse(pending)
        self.assertEqual(len(calls), 5)
        engine.quote_sdk_branches.assert_not_awaited()
        self.assertEqual(family, original)

    async def test_actual_gold_core_with_leading_and_trailing_zero_market(self):
        await self.replay_family('gold')

    async def test_actual_cygld_core_sale_with_leading_and_trailing_zero_market(self):
        await self.replay_family('cygld')


if __name__ == '__main__':
    unittest.main()
