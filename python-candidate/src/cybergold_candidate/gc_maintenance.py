"""Process GC scheduling owned by foreground work, without request admission.

Quote completion requests one coalesced cleanup after all foreground/owned work
has drained. Young collections and reference counting remain automatic. Under
continuous work, normal full-GC selection resumes after one additional oldest-generation
counter interval beyond the existing generation-2 threshold; there is
no time/memory cap or indefinite full-GC suppression.
"""
import asyncio
import gc
import json
import logging
import time


class _Owner:
    def __init__(self, maintenance, quote):
        self.maintenance, self.quote = maintenance, quote
        self.released = False

    def release(self):
        if not self.released:
            self.released = True
            self.maintenance._release(self.quote)


class GcMaintenance:
    def __init__(self, *, collector=None, sink=None):
        self.collector, self.sink = collector or gc, sink
        self.active = 0
        self.pending_quote_cleanup = False
        self.original = None
        self.loop = None
        self.idle_handle = None
        self.callback = self._observe_gc
        self.started = False
        self.fallback = False
        self.due_at = None

    def start(self):
        if not self.started:
            self.loop = asyncio.get_running_loop()
            self.original = self.collector.get_threshold()
            self.collector.callbacks.append(self.callback)
            self.started = True

    def _enabled(self):
        return self.collector.isenabled() and self.original[0] != 0

    def acquire(self, *, quote=False):
        if not self.started:
            return None
        continuing = self.idle_handle is not None
        if continuing:
            self.idle_handle.cancel()
            self.idle_handle = None
        if not self.active and self._enabled():
            if not continuing:
                self.fallback = False
                count = self.collector.get_count()[2]
                self.due_at = count if count > self.original[2] else None
            if not self.fallback:
                self.collector.set_threshold(*self.original[:2], 2**31-1)
        self.active += 1
        try:
            return _Owner(self, quote)
        except BaseException:
            self._release(False)
            raise

    def _release(self, quote):
        self.active -= 1
        self.pending_quote_cleanup |= quote
        if not self.active and self.started:
            self.idle_handle = self.loop.call_soon(self._idle)

    def _observe_gc(self, phase, info):
        if phase != 'stop' or not self.started:
            return
        try:
            generation = info.get('generation')
            if generation == 2:
                # A natural full collection already discharged the debt.
                self.pending_quote_cleanup = False
                self.due_at = None
                self.fallback = False
                if self.active and self._enabled():
                    self.collector.set_threshold(*self.original[:2], 2**31-1)
            elif generation == 1 and self.active and not self.fallback and self._enabled():
                count = self.collector.get_count()[2]
                if self.due_at is not None and count >= self.due_at + max(1, self.original[2]+1):
                    # Let CPython retain its own oldest-generation selection,
                    # including its long-lived-object ratio heuristic. No
                    # forced collection or new foreground admission rule.
                    self.fallback = True
                    self.collector.set_threshold(*self.original)
                    self._report({'action': 'automatic-resumed'})
                elif self.due_at is None and count > self.original[2]:
                    self.due_at = count
        except Exception:
            # Optional scheduling cannot escape into an allocating caller.
            self.fallback = True
            self.collector.set_threshold(*self.original)

    def _idle(self):
        self.idle_handle = None
        if self.active or not self.started:
            return
        try:
            if self.pending_quote_cleanup and self._enabled():
                started, cpu = time.perf_counter(), time.process_time()
                collected = self.collector.collect(2)
                self.pending_quote_cleanup = False
                self._report({'action': 'quote-completed', 'collected': collected,
                    'wallMs': round((time.perf_counter()-started)*1000, 3),
                    'processCpuMs': round((time.process_time()-cpu)*1000, 3)})
        except Exception:
            self._report({'action': 'cleanup-failed'})
        finally:
            self.collector.set_threshold(*self.original)
            self.fallback = False
            self.due_at = None

    def _report(self, values):
        try:
            record = {'event': 'quote_gc_maintenance', 'component': 'api', **values}
            if self.sink is not None:
                self.sink(record)
            else:
                logging.getLogger('cybergold.candidate').info(json.dumps(record))
        except Exception:
            pass

    def close(self):
        if self.started:
            self.started = False
            if self.idle_handle is not None:
                self.idle_handle.cancel()
                self.idle_handle = None
            for index, callback in enumerate(self.collector.callbacks):
                if callback is self.callback:
                    del self.collector.callbacks[index]
                    break
            self.collector.set_threshold(*self.original)
