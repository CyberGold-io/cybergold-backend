"""Independent event-loop readiness observations, without request CPU attribution."""
import asyncio
import gc
import json
import logging
import time

from .telemetry import observe


class LoopMonitor:
    def __init__(self, metrics, *, interval=0.1, clock=None, sleep=None):
        self.metrics, self.interval = metrics, interval
        self.clock, self.sleep = clock, sleep or asyncio.sleep
        self.task = None
        self._gc_callback = self._observe_gc
        self._gc_registered = False
        self._gc_started = (None, None, None)
        # Immutable rows: completed spans, wall ns, process CPU ns. Never reset
        # while sampling: a collection during log allocation belongs to a later
        # snapshot rather than being erased by an interval-counter reset.
        self._gc_totals = ((0, 0, 0),) * 3

    def _register_gc(self):
        if not self._gc_registered:
            gc.callbacks.append(self._gc_callback)
            self._gc_registered = True

    def _remove_gc(self):
        for index, callback in enumerate(gc.callbacks):
            if callback is self._gc_callback:
                del gc.callbacks[index]
                break
        self._gc_registered = False
        self._gc_started = (None, None, None)

    def _observe_gc(self, phase, info):
        try:
            generation = info.get('generation')
            if type(generation) is not int or not 0 <= generation <= 2:
                return
            if phase == 'start':
                self._gc_started = (self._gc_started[:generation] +
                                    (None,) + self._gc_started[generation+1:])
                started = (time.monotonic_ns(), time.process_time_ns())
                self._gc_started = (self._gc_started[:generation] +
                                    (started,) + self._gc_started[generation+1:])
            elif phase == 'stop':
                started = self._gc_started[generation]
                self._gc_started = (self._gc_started[:generation] +
                                    (None,) + self._gc_started[generation+1:])
                if started is None:
                    return
                wall = max(0, time.monotonic_ns()-started[0])
                cpu = max(0, time.process_time_ns()-started[1])
                count, total_wall, total_cpu = self._gc_totals[generation]
                updated = (count+1, total_wall+wall, total_cpu+cpu)
                self._gc_totals = (self._gc_totals[:generation] +
                                   (updated,) + self._gc_totals[generation+1:])
        except Exception:
            pass  # Optional observation cannot escape into ordinary GC work.

    def _gc_snapshot(self):
        return self._gc_totals if self._gc_registered else None

    def _log_lag(self, lag, elapsed, previous_gc, current_gc):
        event = {'event':'quote_event_loop_lag','component':'api',
                 'lagMs':round(lag*1000,3),'intervalMs':round(self.interval*1000,3)}
        if previous_gc is not None and current_gc is not None:
            event['gcSincePreviousLoopMeasurement'] = {
                'scope':'process-gc-callback-spans',
                'measurementIntervalMs':round(elapsed*1000,3),
                'spanAccounting':'whole-span-at-stop',
                'generations':[
                    {'generation':generation,
                     'completedCollections':after[0]-before[0],
                     'summedCollectionSpanWallMs':round((after[1]-before[1])/1e6,3),
                     'summedProcessCpuDuringCollectionSpansMs':round((after[2]-before[2])/1e6,3)}
                    for generation, (before, after) in
                    enumerate(zip(previous_gc, current_gc))]}
        logging.getLogger('cybergold.candidate').info(json.dumps(event))

    def start(self):
        if self.task is None or self.task.done():
            observe(self._register_gc)
            try:
                self.task = asyncio.create_task(self.run())
            except BaseException:
                observe(self._remove_gc)
                raise

    async def run(self):
        clock = self.clock or asyncio.get_running_loop().time
        measured = clock()
        previous_gc = self._gc_snapshot()
        ready = measured+self.interval
        while True:
            await self.sleep(max(0,ready-clock()))
            resumed = clock()
            current_gc = self._gc_snapshot()
            lag = max(0,resumed-ready)
            observe(lambda:self.metrics.event_loop_lag.observe(lag))
            if lag >= 0.1:
                observe(lambda:self._log_lag(lag, resumed-measured,
                                            previous_gc, current_gc))
            # Advance on every measurement, not only emitted lag rows. The
            # pointer-coherent tuples also retain GC during later formatting.
            measured, previous_gc = resumed, current_gc
            # Resume normal sampling rather than burst through missed ticks.
            ready = resumed+self.interval

    async def close(self):
        try:
            if self.task is not None:
                self.task.cancel()
                await asyncio.gather(self.task,return_exceptions=True)
                self.task = None
        finally:
            observe(self._remove_gc)
