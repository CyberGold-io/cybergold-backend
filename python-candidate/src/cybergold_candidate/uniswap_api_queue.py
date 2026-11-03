"""Process-local Uniswap API pacing, independent of chain RPC transport.

One quote engine owns the queue for its configured API key. Start times are
spaced, not HTTP responses: slow requests can remain in flight concurrently.
The existing quote task owns cancellation; each provider query attempts HTTP
once, and a server cooldown applies to subsequent independent queries.
"""
import asyncio
from email.utils import parsedate_to_datetime
import math
import time

from .route_observations import api_queue_wait


def retry_after_seconds(value, now=time.time):
    """Respect either Retry-After form; use a one-second pause when absent."""
    try:
        try:
            delay = float(value)
        except ValueError:
            delay = parsedate_to_datetime(value).timestamp() - now()
        return max(0.0, delay) if math.isfinite(delay) else 1.0
    except (TypeError, ValueError, OverflowError):
        return 1.0


class UniswapApiQueue:
    def __init__(self, rps=6, *, now=time.monotonic, sleep=asyncio.sleep):
        self.interval = 1 / rps
        self.now = now
        self.sleep = sleep
        self.next_start = 0.0
        self.paused_until = 0.0
        self.lock = asyncio.Lock()
        self.pending = set()

    async def wait(self):
        task = asyncio.current_task()
        self.pending.add(task)
        try:
            with api_queue_wait():
                # asyncio.Lock preserves FIFO acquisition. Hold it only while
                # waiting for admission; release before any HTTP work. Updating
                # at the resumed caller avoids a backlog of granted permits
                # bunching actual requests after an event-loop stall.
                async with self.lock:
                    while True:
                        delay = max(self.next_start, self.paused_until) - self.now()
                        if delay <= 0:
                            self.next_start = self.now() + self.interval
                            return
                        await self.sleep(delay)
        finally:
            self.pending.discard(task)

    def pause(self, seconds):
        self.paused_until = max(self.paused_until, self.now() + seconds)

    def close(self):
        for task in tuple(self.pending):
            task.cancel()
