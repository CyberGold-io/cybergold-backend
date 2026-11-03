"""Failed candidate banks retire while the owning search remains active."""
import asyncio
from contextlib import contextmanager
import gc
import unittest
from unittest.mock import patch
import weakref

from cybergold_candidate.basket_preview import InvalidPreview
from cybergold_candidate.preview_errors import KnownPreviewError
from cybergold_candidate.quote_errors import QuoteFailure, public_quote_error
from cybergold_candidate.quoter.amm import PartialPath
from cybergold_candidate.quoter.bootstrap import RouteBootstrap, current_bootstrap
from cybergold_candidate.quoter.contracts import HopTrace, PathTrace
from cybergold_candidate.quoter.route_tools import CandidateFeed, RouteTool
from test_universal_quote import BLOCK, CORE, WETH, Engine, Quotes, request


class PrivateBank:
    def __init__(self):
        self.words = bytearray(1024)


class HeldTool(RouteTool):
    name = 'held-fixture-supplier'

    def __init__(self):
        self.entered, self.finish = asyncio.Event(), asyncio.Event()
        self.closed = False

    def discover(self, query):
        async def hold():
            self.entered.set()
            await self.finish.wait()
            return []
        return CandidateFeed(pending=hold())

    async def close(self):
        self.closed = True


class QuoterFailureHistoryTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def ordinary_completion(self):
        done = asyncio.Event()
        original = RouteBootstrap.run
        async def observed(session, ordinary, reevaluate, **options):
            async def owned():
                try:
                    return await ordinary
                finally:
                    done.set()
            return await original(session, owned(), reevaluate, **options)
        with patch.object(RouteBootstrap, 'run', observed):
            yield done

    async def held_search(self, failure):
        q, supplier, banks = Quotes(Engine()), HeldTool(), []
        q.route_provider_factory = lambda: [supplier]
        async def candidate(*args, **options):
            current_bootstrap().offers(WETH, CORE, 10000, BLOCK)
            bank = PrivateBank()
            index = len(banks)
            banks.append(weakref.ref(bank))
            raise failure(index, bank)
        q.candidate = candidate
        value = request()
        value['inputs'][0]['currency'] = WETH
        operation = asyncio.create_task(q.get(value))
        await asyncio.wait_for(supplier.entered.wait(), 2)
        return q, supplier, banks, operation

    async def test_ignored_no_route_tracebacks_release_private_banks_during_search(self):
        with self.ordinary_completion() as ordinary_done:
            q, supplier, banks, operation = await self.held_search(
                lambda index, bank: QuoteFailure('quote-no-route'))
            try:
                await asyncio.wait_for(ordinary_done.wait(), 2)
                gc.collect()
                self.assertGreater(len(banks), 8)
                self.assertTrue(all(ref() is None for ref in banks))
                self.assertFalse(operation.done(), 'independent supplier still owns pending work')
                supplier.finish.set()
                with self.assertRaises(QuoteFailure) as caught:
                    await operation
                self.assertEqual(caught.exception.code, 'quote-no-route')
                self.assertTrue(supplier.closed)
                self.assertEqual(q.engine.semaphore._value, 8)
            finally:
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def test_ignored_partial_traces_release_pre_states_without_stopping_other_work(self):
        def partial(index, bank):
            return PartialPath(PathTrace([], 10000, '0:market', 0, 0,
                hops=[HopTrace({}, 10000, 5000, 4000, {'privateBank': bank})]))
        with self.ordinary_completion() as ordinary_done:
            q, supplier, banks, operation = await self.held_search(partial)
            try:
                await asyncio.wait_for(ordinary_done.wait(), 2)
                gc.collect()
                self.assertGreater(len(banks), 8)
                self.assertTrue(all(ref() is None for ref in banks), 'unused PartialPath.trace must retire too')
                self.assertFalse(operation.done())
                operation.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await operation
                self.assertTrue(supplier.closed)
                self.assertEqual(q.engine.semaphore._value, 8)
            finally:
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def test_first_informative_original_error_keeps_priority_identity_and_diagnostics(self):
        first = KnownPreviewError('issuance-cap-exceeded', 'fixture capacity',
            constraint={'kind': 'issuance-cap', 'availableRaw': '7'})
        first.rpc_diagnostics = {'failureType': 'rpc-error', 'method': 'eth_call', 'upstreamErrorCode': 3}
        first.quote_diagnostics = {'phase': 'initial-preview', 'qualified': False}
        def failure(index, bank):
            if index == 0:
                return InvalidPreview('unusable fixture path')
            if index == 1:
                return QuoteFailure('quote-no-route')
            if index == 2:
                return first
            return QuoteFailure('rpc-timeout')
        with self.ordinary_completion() as ordinary_done:
            q, supplier, banks, operation = await self.held_search(failure)
            try:
                await asyncio.wait_for(ordinary_done.wait(), 2)
                gc.collect()
                self.assertGreater(len(banks), 8)
                self.assertEqual([index for index, ref in enumerate(banks) if ref() is not None], [2])
                self.assertFalse(operation.done())
                supplier.finish.set()
                with self.assertRaises(KnownPreviewError) as caught:
                    await operation
                self.assertIs(caught.exception, first)
                public = public_quote_error(first)
                self.assertEqual(public['code'], 'issuance-cap-exceeded')
                self.assertEqual(public['constraint'], first.constraint)
                self.assertEqual(public['diagnostics'], first.rpc_diagnostics)
                self.assertEqual(public['quoteDiagnostics'], first.quote_diagnostics)
                self.assertIn('routeDiscovery', first.quoter_metrics)
                self.assertTrue(supplier.closed)
                self.assertEqual(q.engine.semaphore._value, 8)
            finally:
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
