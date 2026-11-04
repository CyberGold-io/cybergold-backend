"""A slow factory member does not hold unrelated connector discovery work."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from cybergold_candidate.recovery_rpc import SnapshotChanged
from cybergold_candidate.route_quote_engine import RouteQuoteEngine
from cybergold_candidate.rpc_block_context import LATEST_BLOCK
from cybergold_candidate.uniswap_state import ZERO
from quoter_fixture import synthetic_pool
from test_universal_quote import CORE, WETH, PAXG


class Factory:
    factory, v2_factory = 'v3-factory', 'v2-factory'
    def __init__(self, *, held=False, error=None):
        self.calls = []
        self.slots = asyncio.Semaphore(8)
        self.held, self.release, self.later = held, asyncio.Event(), asyncio.Event()
        self.active = self.peak = self.pending = self.pending_peak = 0
        self.error, self.failed = error, False

    async def read_function(self, address, signature, _inputs, args, _outputs, _block):
        self.pending += 1
        self.pending_peak = max(self.pending_peak, self.pending)
        try:
            async with self.slots:
                self.calls.append((signature, tuple(args)))
                index = len(self.calls)
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    if index == 36:
                        self.later.set()
                    if self.held and index == 1:
                        await self.release.wait()
                    else:
                        await asyncio.sleep(0)
                    if self.error is not None and not self.failed and signature.startswith('getPool'):
                        self.failed = True
                        raise self.error
                    return (ZERO,)
                finally:
                    self.active -= 1
        finally:
            self.pending -= 1


class Registry:
    chain, core = 31338, CORE
    def __init__(self, rpc):
        self.rpc = rpc
        self.lookups = {}
        self.lookup_month = datetime.now(timezone.utc).strftime('%Y-%m')
        self.metadata = {}
        pools = [synthetic_pool(CORE, '0x'+format(900+i, '040x'), 10000+i, 'v2') for i in range(10)]
        self.inventory = {pool['id']: pool for pool in pools}
    def get_rpc(self): return self.rpc
    def token(self, address, decimals): return {'address': address, 'chainId': self.chain, 'decimals': decimals}
    def persist(self, *_): pass


class ConnectorRefillTests(unittest.IsolatedAsyncioTestCase):
    async def discover(self, registry):
        return await RouteQuoteEngine.connector_inventory(SimpleNamespace(registry=registry), WETH, PAXG, LATEST_BLOCK)

    async def test_later_work_and_required_read_progress_while_first_factory_is_held(self):
        rpc = Factory(held=True)
        registry = Registry(rpc)
        task = asyncio.create_task(self.discover(registry))
        try:
            await asyncio.wait_for(rpc.later.wait(), 1)
            self.assertFalse(task.done())
            await rpc.read_function('required', 'required()', [], [], ['address'], LATEST_BLOCK)
            required = next(i for i, call in enumerate(rpc.calls) if call[0] == 'required()')
            self.assertLess(required, 115)
            # Preserve the existing source scheduling boundary and RPC slots;
            # one independent getter may temporarily join the connector cohort.
            self.assertLessEqual(rpc.pending_peak, 36)
            self.assertLessEqual(rpc.peak, 8)
            rpc.release.set()
            await asyncio.wait_for(task, 1)
            self.assertEqual(len(rpc.calls), 116)
            self.assertEqual(len(registry.lookups), 115)
            await self.discover(registry)
            self.assertEqual(len(rpc.calls), 116)
            added = synthetic_pool(CORE, '0x'+format(9999, '040x'), 19999, 'v2')
            registry.inventory[added['id']] = added
            await self.discover(registry)
            self.assertEqual(len(rpc.calls), 126)
        finally:
            rpc.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual((rpc.active, rpc.pending), (0, 0))

    async def test_ordinary_failure_remains_retryable_and_canonical_disproof_drains(self):
        rpc = Factory(error=OSError('unknown factory observation'))
        registry = Registry(rpc)
        await self.discover(registry)
        self.assertEqual(len(rpc.calls), 115)
        self.assertEqual(len(registry.lookups), 114)
        await self.discover(registry)
        self.assertEqual(len(rpc.calls), 116)
        self.assertEqual(len(registry.lookups), 115)
        rpc = Factory(error=SnapshotChanged('controlled disproof'))
        with self.assertRaises(SnapshotChanged):
            await self.discover(Registry(rpc))
        self.assertEqual((rpc.active, rpc.pending), (0, 0))

    async def test_cancelled_owner_drains_held_and_queued_members(self):
        rpc = Factory(held=True)
        task = asyncio.create_task(self.discover(Registry(rpc)))
        await asyncio.wait_for(rpc.later.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((rpc.active, rpc.pending), (0, 0))


if __name__ == '__main__':
    unittest.main()
