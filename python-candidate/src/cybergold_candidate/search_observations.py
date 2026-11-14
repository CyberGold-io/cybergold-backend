"""One search's successful advisory observations, never canonical storage."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
import asyncio

from .shared_reads import SharedReads


_current = ContextVar('search_observations', default=None)


class SearchObservations:
    def __init__(self):
        self.reads = SharedReads()
        self.pool_states = {}
        self.pool_initializations = {}
        self.bitmap_prefetches = {}
        self.bitmap_full_pools = set()

    async def read(self, key, produce):
        """Share pending work and own successful decoded values for this search."""
        async def fetch(_keys):
            return [{'value': await produce()}]
        values, _ = await self.reads.many([('decoded', key)], fetch, retain=True)
        return deepcopy(values[0]['value'])

    async def close(self):
        for task in self.bitmap_prefetches.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.bitmap_prefetches.values(), return_exceptions=True)
        self.bitmap_prefetches.clear()
        self.bitmap_full_pools.clear()
        await self.reads.close()
        self.pool_states.clear()
        self.pool_initializations.clear()


def current_search_observations():
    return _current.get()


@asynccontextmanager
async def search_observation_scope():
    """Each producer owns its memo; children/callbacks share it by context."""
    observations = SearchObservations()
    token = _current.set(observations)
    try:
        yield observations
    finally:
        await observations.close()
        _current.reset(token)
