"""Owner-selected historical indexing allowance; no burst or extra scheduler."""
import asyncio
import time

# HEG counts individual requests per API key (40,000/hour). Reserve half for
# historical collection, split between the two configured environments even
# when their provider key is shared. These are attempts, not block counts or
# weighted broker costs. Live API reads do not use this pacer.
REQUESTS_PER_HOUR = 40000 // 2 // 2
MAX_BLOCKS_PER_RUN = 50000


class IndexingRpcPacer:
    def __init__(self, *, monotonic=time.monotonic, sleep=asyncio.sleep):
        self.monotonic, self.sleep = monotonic, sleep
        self.interval = 3600 / REQUESTS_PER_HOUR
        self.last_attempt = None
        self.attempts = 0
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = self.monotonic()
            # A new process waits for its first slot too: replacing a worker
            # must not grant a fresh request burst. The existing DB advisory
            # lock already serializes worker passes across both App slots.
            delay = self.interval if self.last_attempt is None else max(
                0, self.last_attempt + self.interval - now)
            if delay:
                await self.sleep(delay)
            self.last_attempt = self.monotonic()
            self.attempts += 1
