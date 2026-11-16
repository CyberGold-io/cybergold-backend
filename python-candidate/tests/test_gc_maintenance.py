"""Query cleanup ownership, native-cadence fallback and optional observation."""
import asyncio
import gc
from types import SimpleNamespace
import unittest
import weakref

from cybergold_candidate.gc_maintenance import GcMaintenance
from cybergold_candidate.quote_flow import Flow, flow_scope, producer_flow
from cybergold_candidate.telemetry import Metrics, TelemetryMiddleware


class Collector:
    def __init__(self, thresholds=(2000, 10, 10), enabled=True):
        self.thresholds, self.enabled = thresholds, enabled
        self.count = (0, 0, 0)
        self.callbacks, self.collections = [], []
    def isenabled(self): return self.enabled
    def get_threshold(self): return self.thresholds
    def set_threshold(self, *values): self.thresholds = values
    def get_count(self): return self.count
    def stop(self, generation, count=0):
        self.count = (0, 0, count)
        for callback in list(self.callbacks):
            callback('stop', {'generation': generation})
    def collect(self, generation):
        self.collections.append(generation)
        self.stop(generation)
        return 7


class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.collector, self.records = Collector(), []
        self.maintenance = GcMaintenance(collector=self.collector, sink=self.records.append)
        self.maintenance.start()
        self.addCleanup(self.maintenance.close)

    async def test_small_http_work_restores_cadence_without_full_sweep(self):
        for _ in range(30):
            self.maintenance.acquire().release()
            await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [])
        self.assertEqual(self.collector.thresholds, (2000, 10, 10))

    async def test_query_completion_waits_for_last_foreground_owner_and_coalesces(self):
        first = self.maintenance.acquire(quote=True)
        second = self.maintenance.acquire(quote=True)
        api = self.maintenance.acquire()
        first.release(); second.release(); second.release()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [])
        api.release()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [2])
        self.assertEqual(self.maintenance.active, 0)
        self.assertEqual(self.records[0]['action'], 'quote-completed')
        self.assertEqual(self.records[0]['collected'], 7)

    async def test_new_query_before_idle_callback_postpones_cleanup(self):
        self.maintenance.acquire(quote=True).release()
        owner = self.maintenance.acquire(quote=True)
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [])
        owner.release()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [2])

    async def test_sustained_work_restores_native_selection_after_existing_cadence(self):
        owner = self.maintenance.acquire(quote=True)
        self.collector.stop(1, 10)
        self.assertEqual(self.collector.thresholds[:2], (2000, 10))
        self.assertGreater(self.collector.thresholds[2], 10)
        self.collector.stop(1, 11)
        self.assertGreater(self.collector.thresholds[2], 10)
        self.collector.stop(1, 21)
        self.assertGreater(self.collector.thresholds[2], 10)
        self.collector.stop(1, 22)
        self.assertEqual(self.collector.thresholds, (2000, 10, 10))
        self.assertEqual(self.records, [{'event':'quote_gc_maintenance', 'component':'api',
                                        'action':'automatic-resumed'}])
        self.assertEqual(self.collector.collections, [])
        self.collector.stop(2)
        self.assertGreater(self.collector.thresholds[2], 10)
        owner.release()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [2])

    async def test_new_work_before_idle_does_not_restart_accumulated_deferral(self):
        owner = self.maintenance.acquire(quote=True)
        self.collector.stop(1, 11)
        owner.release()
        owner = self.maintenance.acquire()
        self.collector.stop(1, 22)
        self.assertEqual(self.collector.thresholds, (2000, 10, 10))
        owner.release()
        owner = self.maintenance.acquire()
        self.assertEqual(self.collector.thresholds, (2000, 10, 10))
        owner.release()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [2])

    async def test_due_cadence_on_acquisition_is_not_reset(self):
        self.collector.count = (0, 0, 15)
        owner = self.maintenance.acquire()
        self.collector.stop(1, 26)
        self.assertEqual(self.collector.thresholds, (2000, 10, 10))
        owner.release()

    async def test_initially_disabled_and_zero_threshold_policies_are_preserved(self):
        for disabled, threshold in ((True, (2000, 10, 10)), (False, (0, 7, 9))):
            self.maintenance.close()
            self.collector.enabled, self.collector.thresholds = not disabled, threshold
            self.maintenance.start()
            owner = self.maintenance.acquire(quote=True)
            self.assertEqual(self.collector.thresholds, threshold)
            owner.release(); await asyncio.sleep(0)
            self.assertEqual(self.collector.thresholds, threshold)
            self.assertEqual(self.collector.collections, [])
            self.assertEqual(self.collector.enabled, not disabled)

    async def test_failed_collection_and_diagnostics_restore_config_without_loop_error(self):
        def fail(_): raise ValueError('ordinary collection error')
        self.collector.collect = fail
        self.maintenance.acquire(quote=True).release()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.thresholds, (2000, 10, 10))
        self.assertEqual(self.records[-1]['action'], 'cleanup-failed')
        self.maintenance.sink = fail
        self.collector.collect = lambda _: 0
        self.maintenance.acquire(quote=True).release()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.thresholds, (2000, 10, 10))

    async def test_shutdown_cancels_pending_cleanup_and_removes_only_own_callback(self):
        other = lambda *_: None
        self.collector.callbacks.append(other)
        self.maintenance.acquire(quote=True).release()
        self.maintenance.close()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [])
        self.assertEqual(self.collector.callbacks, [other])
        self.assertEqual(self.collector.thresholds, (2000, 10, 10))

    async def test_owned_shared_tail_defers_query_cleanup_after_http_finishes(self):
        metrics = Metrics(); metrics.gc_maintenance = self.maintenance
        search = None
        async def app(scope, receive, send):
            nonlocal search
            with producer_flow('search') as search:
                search.retain_producer()
            await send({'type':'http.response.start', 'status':200, 'headers':[]})
            await send({'type':'http.response.body', 'body':b'ok'})
        async def nothing(*_): pass
        await TelemetryMiddleware(app, metrics=metrics, component="api")(
            {'type':'http', 'path':'/api/economic-quotes', 'method':'GET', 'headers':[]}, nothing, nothing)
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [])
        self.assertEqual(self.maintenance.active, 1)
        search.release_producer()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [2])

    async def test_cancelled_search_finishes_cleanup_before_releasing_ownership(self):
        metrics = SimpleNamespace(gc_maintenance=self.maintenance)
        parent = Flow('/api/economic-quotes/stream', metrics=metrics, sink=lambda _: None)
        entered, draining, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def run():
            with flow_scope(parent), producer_flow('search'):
                try:
                    entered.set(); await asyncio.Event().wait()
                finally:
                    draining.set(); await release.wait()
        task = asyncio.create_task(run()); await entered.wait(); task.cancel(); await draining.wait()
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [])
        release.set()
        with self.assertRaises(asyncio.CancelledError): await task
        await asyncio.sleep(0)
        self.assertEqual(self.collector.collections, [2])


class NativeCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_young_gc_and_refcounting_continue_and_old_gc_eventually_resumes(self):
        original, enabled = gc.get_threshold(), gc.isenabled()
        seen = []
        def observe(phase, info):
            if phase == 'stop': seen.append(info['generation'])
        policy = GcMaintenance(sink=lambda _: None)
        try:
            gc.enable(); gc.set_threshold(40, 1, 1); gc.collect()
            policy.start(); owner = policy.acquire(quote=True); gc.callbacks.append(observe)
            class Cycle: pass
            value = Cycle(); reference = weakref.ref(value); del value
            self.assertIsNone(reference())
            # Sustained foreground allocation; retained graphs exceed CPython's
            # existing long-lived-object heuristic so ordinary oldest GC runs.
            held = []
            for _ in range(80):
                held.extend([[object(), {'v': 1}] for _ in range(200)])
                if 2 in seen: break
                await asyncio.sleep(0)
            self.assertIn(0, seen); self.assertIn(1, seen); self.assertIn(2, seen)
            owner.release(); await asyncio.sleep(0)
            self.assertEqual(gc.get_threshold(), (40, 1, 1))
        finally:
            policy.close()
            if observe in gc.callbacks: gc.callbacks.remove(observe)
            gc.set_threshold(*original)
            if not enabled: gc.disable()
            gc.collect()


if __name__ == '__main__': unittest.main()
