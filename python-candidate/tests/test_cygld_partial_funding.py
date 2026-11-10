"""Recorded real Helpers redemption, supply funding and paid preparation.

The fixed Sandbox source calls are reproduced offline with exact calldata and
funding overrides. Contract return bytes, not a Core/AMM arithmetic oracle,
supply the expected economic results. Invalid oversized roots have no output
to preserve; only the successful smaller observation binds preparation.
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
from cybergold_candidate.preview_errors import KnownPreviewError
from cybergold_candidate.quote_errors import public_quote_error
from cybergold_candidate.quoter import Quoter
from cybergold_candidate.quoter.funding import cached_core_funding, direct_basket_funding, supply_funding
from cybergold_candidate.quoter.pool_directions import conflicting_pool, quote_directions
from cybergold_candidate.quoter.simulation_funding import SIMULATION_SENDER
from cybergold_candidate.tx_preparation import TransactionPreparation, compile_execution


FIXTURE = Path(__file__).parent / 'fixtures/cygld-redemption-supply-20261110.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class CygldPartialFundingTests(unittest.IsolatedAsyncioTestCase):
    async def replay_case(self, name):
        fixture = json.loads(FIXTURE.read_text())
        case = next(row for row in fixture['cases'] if row['case'] == name)
        original = deepcopy(case)
        self.assertTrue(fixture['sourceIdentityUnchanged'])
        self.assertTrue(fixture['generationUnchanged'])
        config = fixture['protocolConfiguration']
        settings = SimpleNamespace(NEXT_PUBLIC_CHAIN_ID='31338',
            NEXT_PUBLIC_CORE_DIAMOND_ADDRESS=config['contracts']['core'],
            NEXT_PUBLIC_HELPERS_DIAMOND_ADDRESS=config['contracts']['helpers'],
            CYBERGOLD_UNISWAP_ROUTING_ADAPTER_ADDRESS=config['contracts']['uniswapAdapter'])
        calls, pending = [], deepcopy(case['exchanges'])

        async def recorded_request(method, params):
            self.assertEqual(method, 'eth_call')
            self.assertTrue(pending, 'Unrecorded network/state request')
            observed = pending.pop(0)
            self.assertEqual(digest(observed['params']), observed['paramsSha256'])
            self.assertEqual(params, observed['params'], observed['phase'])
            calls.append(deepcopy(params))
            return deepcopy(observed['response'])

        rpc = SimpleNamespace(w3=SimpleNamespace(codec=Web3().codec,
            provider=SimpleNamespace(make_request=recorded_request)))
        registry = SimpleNamespace(chain=31338, core=settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS,
                                   seed=None, get_rpc=lambda: rpc)
        engine = SimpleNamespace(registry=registry, semaphore=asyncio.Semaphore(8),
            quote_sdk_branches=AsyncMock(side_effect=AssertionError('A complete Helpers body needs no SDK repricing')))
        q = Quoter(settings, engine, now=lambda: case['observedAt'])
        self.addAsyncCleanup(q.close)
        request, selected = deepcopy(case['request']), deepcopy(case['originalPlan'])
        if case['oversized']:
            self.assertGreater(int(request['inputs'][0]['amount']), int(fixture['facts']['supply']))
            with self.assertRaises(KnownPreviewError) as raised:
                await q.plan_simulator(request, selected, block=fixture['anchor'])
            self.assertEqual(public_quote_error(raised.exception), case['rootFailure'])
            self.assertEqual(case['rootFailure']['code'], 'redemption-supply-exceeded')
            state = {'supply': int(fixture['facts']['supply'])}
            funding = supply_funding(request, state)
            if request['intent'] == 1:
                request, selected = cached_core_funding(request, state, selected)
            else:
                self.assertEqual(direct_basket_funding(request, state), funding)
                request['inputs'] = funding
        self.assertEqual(request, case['fundedRequest'])
        self.assertEqual(selected, case['selectedPlan'])
        neutral = await q.plan_simulator(request, selected, block=fixture['anchor'])
        for key, expected in case['neutralExpected'].items():
            self.assertEqual(neutral[key], expected, key)
        self.assertIsNone(conflicting_pool(quote_directions(neutral, 31338)))
        preparation = TransactionPreparation(q, now=lambda: case['preparationNow'])
        payload = {'quote': deepcopy(neutral), 'sender': SIMULATION_SENDER,
            'recipient': SIMULATION_SENDER, 'slippageBps': 0,
            'acceptedBounds': deepcopy(case['acceptedBounds'])}
        prepared = await preparation.prepare(payload)
        paid = prepared['economicQuote']
        for key, expected in case['paidExpected'].items():
            self.assertEqual(paid[key], expected, key)
        self.assertEqual(digest(prepared['plan']), case['preparedPlanSha256'])
        self.assertEqual(prepared['outputMinimum'], case['acceptedBounds']['minimumOutput'])
        self.assertEqual(paid['inputs'], neutral['inputs'])
        self.assertEqual(paid['estimatedRecipientOutputs'], neutral['estimatedRecipientOutputs'])
        self.assertEqual(paid['fees'], neutral['fees'])
        self.assertEqual(paid['estimatedRetainedInputCharges'], [])
        # Tightening the accepted input maximum fails before another RPC. The
        # successful recorded preparation used the exact original maxima.
        payload['acceptedBounds']['inputs'][0]['amount'] = str(int(paid['inputs'][0]['amount'])-1)
        before = len(calls)
        with self.assertRaisesRegex(InvalidPreview, 'Accepted input maximum'):
            await preparation.prepare(payload)
        self.assertEqual(len(calls), before)
        if request['intent'] == 1:
            self.assertGreater(int(paid['quotedOutput']), 0)
            with self.assertRaisesRegex(InvalidPreview, 'Accepted scalar output minimum'):
                compile_execution(neutral, recipient=SIMULATION_SENDER,
                    deadline=case['preparationNow']+600, minimum=int(neutral['quotedOutput'])+1)
        else:
            self.assertEqual(paid['quotedOutput'], '0')
            self.assertTrue(all(int(row['amount']) > 0 for row in paid['estimatedRecipientOutputs']))
            self.assertEqual(paid['plan']['body']['expectedOutputs'], neutral['plan']['body']['expectedOutputs'])
        self.assertFalse(pending)
        engine.quote_sdk_branches.assert_not_awaited()
        self.assertEqual(case, original)

    async def test_actual_positive_cygld_core_to_native_eth_and_paid_minima(self):
        await self.replay_case('cygld-eth-positive')

    async def test_actual_cygld_supply_rejection_then_smaller_eth_preparation(self):
        await self.replay_case('cygld-eth-supply')

    async def test_actual_cygld_supply_rejection_then_basket_outputs_and_minima(self):
        await self.replay_case('cygld-basket-supply')


if __name__ == '__main__':
    unittest.main()
