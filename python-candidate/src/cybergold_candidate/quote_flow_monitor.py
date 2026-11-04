"""Independent event-loop readiness observations, without request CPU attribution."""
import asyncio
import json
import logging

from .telemetry import observe


class LoopMonitor:
    def __init__(self, metrics, *, interval=0.1, clock=None, sleep=None):
        self.metrics, self.interval = metrics, interval
        self.clock, self.sleep = clock, sleep or asyncio.sleep
        self.task = None

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run())

    async def run(self):
        clock = self.clock or asyncio.get_running_loop().time
        ready = clock()+self.interval
        while True:
            await self.sleep(max(0,ready-clock()))
            resumed = clock()
            lag = max(0,resumed-ready)
            observe(lambda:self.metrics.event_loop_lag.observe(lag))
            if lag >= 0.1:
                observe(lambda:logging.getLogger('cybergold.candidate').info(json.dumps({
                    'event':'quote_event_loop_lag','component':'api',
                    'lagMs':round(lag*1000,3),'intervalMs':round(self.interval*1000,3)})))
            # Resume normal sampling rather than burst through missed ticks.
            ready = resumed+self.interval

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
            self.task = None
