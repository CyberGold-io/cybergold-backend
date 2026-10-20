"""An exhausted Core cap ends discovery without suppressing Market quotes."""
import asyncio
import unittest

from cybergold_candidate.preview_errors import KnownPreviewError
from cybergold_candidate.quote_errors import QuoteFailure, public_quote_error
from cybergold_candidate.recovery_rpc import SnapshotChanged
from test_quote_intent import service, request, retained_plan
from test_trade_quote import Engines, request as trade_request


class ExhaustedIssuanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_caps_stop_token_and_native_search_before_any_route_or_preview(self):
        for mode in ('issue-exact-in', 'issue-exact-out'):
            for native in (False, True):
                for maximum, effective, kind in ((100, 200, 'maximum-total-supply'),
                                                  (200, 100, 'effective-supply-cap')):
                    with self.subTest(mode=mode, native=native, limitKind=kind):
                        intent, provider, route, wire = service(31338)
                        self.addAsyncCleanup(route.close)
                        wire.capacity_values = {'totalSupply': 100, 'maxTotalSupply': maximum,
                                                'effectiveCygldSupplyCap': effective}
                        frames = []
                        async with asyncio.timeout(2):
                            with self.assertRaises(KnownPreviewError) as raised:
                                await intent.get(request(mode, native),
                                                 lambda f: asyncio.sleep(0, result=frames.append(f)))
                        payload = public_quote_error(raised.exception)
                        self.assertEqual(payload['code'], 'issuance-cap-exceeded')
                        self.assertEqual(payload['constraint'], {
                            'kind': 'issuance-cap', 'quantity': 'gross-cygld-mint', 'limitKind': kind,
                            'availableRaw': '0', 'currentSupplyRaw': '100', 'limitRaw': '100'})
                        self.assertEqual(sum(map(len, wire.capacity_batches)), 3)
                        self.assertEqual(wire.batches, [])
                        self.assertEqual(provider.contract_calls, [])
                        self.assertFalse(any(f['type'] == 'qualified' for f in frames))

    async def test_retained_issue_plan_does_not_restart_search_at_full_cap(self):
        intent, provider, route, wire = service(31338)
        self.addAsyncCleanup(route.close)
        intent.retain_plans = True
        first = await intent.get(request('issue-exact-in'), lambda f: asyncio.sleep(0))
        wire.capacity_values = {'totalSupply': 100, 'maxTotalSupply': 100, 'effectiveCygldSupplyCap': 200}
        wire.batches.clear()
        provider.contract_calls.clear()
        with self.assertRaises(KnownPreviewError):
            await intent.get({**request('issue-exact-in'), 'retainedPlan': retained_plan(first)},
                             lambda f: asyncio.sleep(0))
        self.assertEqual(wire.batches, [])
        self.assertEqual(provider.contract_calls, [])

    async def test_exhaustion_rechecks_canonicality_before_rejecting(self):
        intent, provider, route, wire = service(31338)
        self.addAsyncCleanup(route.close)
        wire.capacity_values = {'totalSupply': 100, 'maxTotalSupply': 100}
        provider.reorg = True
        with self.assertRaises(SnapshotChanged):
            await intent.get(request('issue-exact-in'), lambda f: asyncio.sleep(0))
        self.assertEqual(wire.batches, [])

    async def test_redemption_is_not_blocked_by_full_issuance_cap(self):
        intent, provider, route, wire = service(31338)
        self.addAsyncCleanup(route.close)
        wire.capacity_values = {'totalSupply': 100, 'maxTotalSupply': 100}
        quote = await intent.get(request('redeem-exact-in'), lambda f: asyncio.sleep(0))
        self.assertEqual(quote['mode'], 'redeem-exact-in')
        self.assertEqual(wire.capacity_batches, [])

    async def test_market_still_wins_when_core_cap_is_full(self):
        intent, provider, route, wire = service(31338)
        self.addAsyncCleanup(route.close)
        wire.capacity_values = {'totalSupply': 100, 'maxTotalSupply': 100}
        engines = Engines()
        self.addAsyncCleanup(engines.close)
        engines.core.get = intent.get
        result = await engines.quotes.get(trade_request(), lambda f: asyncio.sleep(0))
        self.assertEqual(result['strategy'], 'market')
        self.assertEqual(result['providerAssessments']['core']['code'], 'issuance-cap-exceeded')
        self.assertEqual(result['providerAssessments']['core']['constraint']['availableRaw'], '0')
        self.assertEqual(result['providerAssessments']['core']['searchOutcome'], 'complete')
        self.assertEqual(wire.batches, [])

    async def test_market_failure_is_not_hidden_behind_core_cap(self):
        for market_code in ('quote-no-route', 'rpc-rate-limit', 'quote-timeout', 'quote-insufficient-liquidity'):
            for first in ('core', 'market'):
                with self.subTest(market_code=market_code, first=first):
                    engines = Engines()
                    self.addAsyncCleanup(engines.close)
                    engines.core_error = KnownPreviewError('issuance-cap-exceeded', 'No issuance capacity remains.',
                                                           constraint={'kind': 'issuance-cap', 'availableRaw': '0'})
                    engines.market_error = QuoteFailure(market_code)
                    held = asyncio.Event()
                    setattr(engines, 'hold_market' if first == 'core' else 'hold_core', held)
                    async def publish(frame):
                        if frame['type'] == 'provider-error' and frame['strategy'] == first:
                            held.set()
                    with self.assertRaises(QuoteFailure) as raised:
                        await engines.quotes.get(trade_request(), publish)
                    self.assertEqual(raised.exception.code, market_code)

    async def test_native_quote_exposes_cap_without_running_market(self):
        intent, provider, route, wire = service(31338)
        self.addAsyncCleanup(route.close)
        wire.capacity_values = {'totalSupply': 100, 'maxTotalSupply': 100}
        engines = Engines()
        self.addAsyncCleanup(engines.close)
        engines.core.get = intent.get
        with self.assertRaises(KnownPreviewError) as raised:
            async with asyncio.timeout(2):
                await engines.quotes.get(trade_request(native=True), lambda f: asyncio.sleep(0))
        self.assertEqual(raised.exception.code, 'issuance-cap-exceeded')
        self.assertEqual(engines.market_calls, [])
        self.assertEqual(wire.batches, [])

    async def test_partially_available_cap_keeps_existing_terminal_error_precedence(self):
        engines = Engines()
        self.addAsyncCleanup(engines.close)
        engines.core_error = KnownPreviewError('issuance-cap-exceeded', 'Amount exceeds remaining capacity.',
                                               constraint={'kind': 'issuance-cap', 'availableRaw': '10'})
        engines.market_error = QuoteFailure('quote-no-route')
        # Core finishes first; the new exhausted-cap preference must not alter
        # ordinary failures while issuance is still possible.
        engines.hold_market = asyncio.Event()
        async def publish(frame):
            if frame['type'] == 'provider-error' and frame['strategy'] == 'core':
                engines.hold_market.set()
        with self.assertRaises(KnownPreviewError) as raised:
            await engines.quotes.get(trade_request(), publish)
        self.assertIs(raised.exception, engines.core_error)


if __name__ == '__main__':
    unittest.main()
