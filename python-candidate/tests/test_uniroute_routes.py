"""Actual public UniRoute finder through the existing owned child lifecycle."""
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest

from cybergold_candidate.quoter.uniroute_routes import UnirouteLocal
from cybergold_candidate.quoter.alpha_routes import AlphaRouteError
from cybergold_candidate.quoter.bootstrap import ProviderUnavailable


A, B, C = ('0x'+value*40 for value in ('1', '2', '3'))
ROOT = Path(__file__).resolve().parents[2]
BLOCK = {'number': 101, 'hash': '0x'+'ab'*32}


def engine(chain=1):
    def pool(a, b, protocol):
        return {'id': f'{protocol}:{a}:{b}', 'protocol': protocol, 'token0': {'address': a, 'chainId': chain},
                'token1': {'address': b, 'chainId': chain}, 'feePips': 3000, 'tickSpacing': 60}
    rows = [pool(A, B, 'v2'), pool(B, C, 'v3')]
    async def unexpected(*_args, **_kwargs):
        raise AssertionError('Enumeration must not price or acquire state')
    return SimpleNamespace(registry=SimpleNamespace(chain=chain, inventory={row['id']: row for row in rows}),
                           quote_sdk_branches=unexpected)


class LocalUniRouteTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, value):
        return UnirouteLocal(value, command=['node', str(ROOT/'src/uniswap-sdk/uniroute-worker.ts'), '--finder-only'])

    async def test_actual_public_finder_returns_mixed_forward_hops_without_pricing(self):
        value = engine()
        original = deepcopy(value.registry.inventory)
        provider = self.provider(value)
        try:
            candidates = await provider.discover(A, C, 12345678901234567890, BLOCK)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0][0]['amountIn'], '12345678901234567890')
            self.assertEqual([hop['pool']['protocol'] for hop in candidates[0][0]['hops']], ['v2', 'v3'])
            child = provider.process
            reverse = await provider.discover(C, A, 999, BLOCK)
            self.assertEqual(len(reverse), 1)
            self.assertIs(provider.process, child)
            self.assertEqual(value.registry.inventory, original)
            self.assertEqual(provider.diagnostics['quoteCallbacks'], 0)
        finally:
            await provider.close()
        self.assertIsNotNone(child.returncode)
        with self.assertRaises(ProviderUnavailable):
            await provider.discover(A, C, 100, BLOCK)

    async def test_true_sandbox_chain_metadata_is_preserved(self):
        provider = self.provider(engine(chain=31338))
        try:
            candidates = await provider.discover(A, C, 100, BLOCK)
            self.assertEqual(candidates[0][0]['hops'][0]['pool']['token0']['chainId'], 31338)
        finally:
            await provider.close()

    async def test_ordinary_calculation_error_reuses_worker_for_next_request(self):
        value = engine()
        original = deepcopy(value.registry.inventory)
        next(iter(value.registry.inventory.values()))['token0']['address'] = None
        provider = self.provider(value)
        try:
            with self.assertRaises(AlphaRouteError):
                await provider.discover(A, C, 100, BLOCK)
            child = provider.process
            self.assertIsNone(child.returncode)
            value.registry.inventory = original
            candidates = await provider.discover(A, C, 100, BLOCK)
            self.assertEqual(len(candidates), 1)
            self.assertIs(provider.process, child)
        finally:
            await provider.close()
        self.assertIsNotNone(child.returncode)


class ConcurrentLocalFinderTests(unittest.IsolatedAsyncioTestCase):
    async def test_later_query_publishes_raw_hints_while_first_deep_callback_is_held(self):
        value = engine(chain=31338)
        value.semaphore = asyncio.Semaphore(8)
        entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def pricing(*_args, **_kwargs):
            entered.set()
            try:
                await release.wait()
                return {'amountIn': '1', 'amountOut': '1', 'fullyFilled': True, 'settled': True}
            except asyncio.CancelledError:
                cancelled.set()
                raise
        value.quote_sdk_branches = pricing
        provider = UnirouteLocal(value, command=['node', str(ROOT/'src/uniswap-sdk/uniroute-worker.ts')])
        one = provider.discover_batches(A, C, 1000, BLOCK)
        two = provider.discover_batches(C, A, 2000, BLOCK)
        pending = None
        try:
            self.assertTrue(await asyncio.wait_for(anext(one), 3))
            pending = asyncio.create_task(anext(one))
            await asyncio.wait_for(entered.wait(), 1)
            # No additional clock or worker: another calculation's finder can run.
            self.assertTrue(await asyncio.wait_for(anext(two), 1))
            self.assertEqual(provider.sequence, 2)
            self.assertFalse(release.is_set())
            self.assertFalse(pending.done())
            child = provider.process
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            self.assertTrue(cancelled.is_set())
            self.assertIs(provider.process, child)
            self.assertIsNone(child.returncode)
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await one.aclose()
            await two.aclose()
            release.set()
            await provider.close()
        self.assertFalse(provider.requests)
        self.assertEqual(value.semaphore._value, 8)


if __name__ == '__main__':
    unittest.main()
