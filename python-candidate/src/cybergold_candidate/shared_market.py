"""Optional standard Valkey reuse of validated gold/FX observations.

Local coalescing and supplier fallback remain in MarketFeed/resolve_market.
There is deliberately no distributed producer lease or cached fallback.
"""
import json
import math
import time

from valkey.asyncio import Valkey
from valkey.asyncio.retry import Retry
from valkey.backoff import NoBackoff

from .market import parse_gold_payload, parse_fx_payload
from .alias_dates import date_milliseconds
from .telemetry import observe


class SharedObservation(dict):
    """Wire-compatible resolution with its remaining acquisition lifetime."""
    def __init__(self, payload, remaining_ttl):
        super().__init__(payload=payload, isFresh=True)
        self.remaining_ttl = remaining_ttl


class SharedMarketCache:
    def __init__(self, url, chain, client=None, clock=time.time, metrics=None):
        self.url, self.chain, self.client = url, chain, client
        self.clock, self.metrics = clock, metrics

    def connection(self):
        if self.client is None:
            # Lazy: an invalid/unreachable optional cache does not gate startup.
            self.client = Valkey.from_url(self.url, decode_responses=True,
                socket_connect_timeout=.2, socket_timeout=.2, max_connections=8,
                retry=Retry(NoBackoff(), 0))
        return self.client

    def keys(self, feed):
        prefix = f'cybergold:market:v1:chain:{self.chain}:{feed}'
        return prefix + ':fresh', prefix + ':last'

    def metric(self, feed, operation, result):
        if self.metrics:
            observe(lambda: self.metrics.shared_market_requests.labels(feed, operation, result).inc())

    async def resolve(self, feed, previous, supplier, ttl):
        parser = parse_gold_payload if feed == 'gold' else parse_fx_payload
        keys = self.keys(feed)
        last = None
        try:
            raw_fresh, raw_last = await self.connection().mget(keys)
            if raw_last:
                last = parser(json.loads(raw_last))
                if last and last['stale']:
                    last = None
            if raw_fresh:
                record = json.loads(raw_fresh)
                payload = parser(record.get('payload'))
                remaining = float(record['expiresAt']) - self.clock()
                if payload:
                    # A record written with an older refresh policy cannot extend
                    # the current lifetime of its actual acquisition.
                    age = max(0, self.clock() - date_milliseconds(payload['fetchedAt']) / 1000)
                    remaining = min(remaining, ttl - age)
                if payload and not payload['stale'] and math.isfinite(remaining) and remaining > 0:
                    self.metric(feed, 'read', 'hit')
                    return SharedObservation(payload, min(ttl, remaining))
            self.metric(feed, 'read', 'miss')
        except Exception:
            # Ordinary cache errors never expose credentials or bypass local
            # one-producer coalescing / the existing ten-second supplier bound.
            self.metric(feed, 'read', 'error')

        result = await supplier(previous if previous is not None else last)
        if result['isFresh']:
            try:
                payload = result['payload']
                record = {'payload': payload, 'expiresAt': self.clock() + ttl}
                async with self.connection().pipeline(transaction=False) as pipeline:
                    pipeline.set(keys[0], json.dumps(record), px=ttl * 1000)
                    # Reconstructible last-known observations have no time
                    # expiry, but the instance's allkeys-LRU memory bound applies.
                    pipeline.set(keys[1], json.dumps(payload))
                    await pipeline.execute()
                self.metric(feed, 'write', 'success')
            except Exception:
                self.metric(feed, 'write', 'error')
        return result

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
