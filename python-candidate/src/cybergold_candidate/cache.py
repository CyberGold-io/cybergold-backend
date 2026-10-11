"""Preserve the existing one-entry market cache and in-flight sharing policy."""
import asyncio
from time import monotonic
from datetime import datetime

from cachetools import TLRUCache


class MarketFeed:
    def __init__(self, resolve, ttl, timer=monotonic, metrics=None, feed=None):
        self.resolve = resolve
        # A shared hit carries its remaining acquisition lifetime; local reuse
        # must not restart the full freshness period in a second API process.
        self.cache = TLRUCache(maxsize=1, timer=timer,
            ttu=lambda _key, value, now: now + getattr(value, 'remaining_ttl', ttl))
        self.last_known = None
        self.pending = None
        self.metrics,self.feed=metrics,feed

    async def _refresh(self):
        started=monotonic();outcome='error'
        try:
            result = await self.resolve(self.last_known)
            outcome='fresh' if result['isFresh'] else 'fallback'
            if result['isFresh']:
                self.last_known = result['payload']
                self.cache['feed'] = result
                if self.metrics:
                    from .telemetry import observe
                    observe(lambda:self.metrics.market_last_fresh.labels(self.feed).set(
                        datetime.fromisoformat(result['payload']['fetchedAt']).timestamp()))
            # Fallback is returned to concurrent callers, but a later caller
            # must retry the supplier. Never renew the last observation age.
            return result
        finally:
            self.pending = None
            if self.metrics:
                from .telemetry import observe
                observe(lambda:self.metrics.market_refreshes.labels(self.feed,outcome).inc())
                observe(lambda:self.metrics.market_duration.labels(self.feed).observe(monotonic()-started))

    async def get(self):
        cached = self.cache.get('feed')
        if self.metrics:
            from .telemetry import observe
            outcome='hit' if cached is not None else 'coalesced' if self.pending is not None else 'miss'
            observe(lambda:self.metrics.cache_requests.labels(self.feed,outcome).inc())
        if cached is not None:
            return cached
        if self.pending is None:
            self.pending = asyncio.create_task(self._refresh())
        # A disconnected caller does not cancel the shared supplier operation.
        return await asyncio.shield(self.pending)

    async def close(self):
        if self.pending is not None:
            self.pending.cancel()
            await asyncio.gather(self.pending, return_exceptions=True)
