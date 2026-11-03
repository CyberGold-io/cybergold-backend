"""One generic AMM query/candidate/feed contract for every route tool."""
import asyncio
from collections import deque
from collections.abc import AsyncIterable, Awaitable, Iterable
from dataclasses import dataclass
from inspect import isawaitable, iscoroutine
from typing import Any, TypeAlias
from .cooperative import CHECKPOINT, close


class FeedSteps:
    """Private ordering capability; every underlying offer remains eligible."""
    def __init__(self, steps, *, progressive=False):
        self.steps, self.progressive = steps, progressive

    def __iter__(self):
        return iter(self.steps)

    def close(self):
        close(self.steps)


RouteCandidate: TypeAlias = list[dict[str, Any]]


@dataclass(frozen=True)
class RouteQuery:
    source: str
    target: str
    amount: int
    block: dict


@dataclass(frozen=True)
class CandidateFeed:
    """Repeatable immediate nominations plus optional asynchronous work.

    Available iterables are lazy and may observe a newly expanded catalog on
    their next iteration. Pending work and incremental batches belong to the
    request/session owner. Nominations supply no trusted prices, Core economics
    or execution calldata.
    """
    available: Iterable[RouteCandidate] = ()
    pending: Awaitable[Iterable[RouteCandidate]] | None = None
    updates: AsyncIterable[Iterable[RouteCandidate]] | None = None

    def available_projected(self, projection=None):
        """Apply a consumer's opaque path projection where supported.

        This is a fresh immediate-feed view, never shared query state. Pending
        nominations retain their own shapes and the adapter's ordinary replay.
        """
        project = getattr(self.available, 'with_path_projection', None)
        return project(projection) if projection is not None and project is not None else self.available

    def available_steps(self, projection=None, projection_steps=None, early_paths=None):
        available = self.available_projected(projection)
        early = getattr(available, 'with_early_paths', None)
        if early_paths is not None and early is not None:
            available = early(early_paths)
        steps = getattr(available, 'cooperative_steps', None)
        return steps(projection_steps) if steps is not None else available


class RouteTool:
    """Public tool facade; source-specific clients stay behind this boundary."""
    name: str
    # Cache dependency only; every tool runs regardless of this optional flag.
    catalog_dependent = False

    def discover(self, query: RouteQuery) -> CandidateFeed:
        raise NotImplementedError

    async def close(self):
        pass


class PendingRouteTool(RouteTool):
    """Adapt an existing asynchronous client without changing its wire code."""
    def __init__(self, provider, name=None):
        self.provider = provider
        self.name = name if name is not None else provider.name
        self.catalog_dependent = getattr(provider, 'catalog_dependent', False)
        self._discover = getattr(provider, 'discover', provider)

    def discover(self, query):
        if getattr(self.provider, 'discover_batches', None) is not None:
            return CandidateFeed(updates=self._updates(query))
        return CandidateFeed(pending=self._pending(query))

    @property
    def diagnostics(self):
        return getattr(self.provider, 'diagnostics', {})

    async def _updates(self, query):
        iterator = aiter(self.provider.discover_batches(query.source, query.target, query.amount, query.block))
        try:
            async for batch in iterator:
                yield batch
        finally:
            close = getattr(iterator, 'aclose', None)
            if close is not None:
                await close()

    async def _pending(self, query):
        # Even a raw client that starts a Task when called is invoked only
        # after the session has bound this supplier's ownership/origin scope.
        return await self._discover(query.source, query.target, query.amount, query.block)

    async def close(self):
        close = getattr(self.provider, 'close', None)
        if close is not None:
            value = close()
            if isawaitable(value):
                await value


async def async_batches(feed):
    """Consume owned incremental/one-shot results without a second clock.

    Immediate feeds remain separately repeatable and lazy. An incremental
    batch is available to its consumer before later source work completes.
    Known producers use either updates or pending; both are consumed if given.
    """
    try:
        updates = getattr(feed, 'updates', None)
        if updates is not None:
            iterator = aiter(updates)
            try:
                async for batch in iterator:
                    yield batch
            finally:
                close = getattr(iterator, 'aclose', None)
                if close is not None:
                    await close()
        if feed.pending is not None:
            yield await feed.pending
    finally:
        # A stream failure/cancellation can occur before a separately supplied
        # one-shot result is awaited. Both parts belong to this feed's owner.
        if iscoroutine(feed.pending):
            feed.pending.close()
        elif isinstance(feed.pending, asyncio.Future):
            if not feed.pending.done():
                feed.pending.cancel()
            outcomes = await asyncio.gather(feed.pending, return_exceptions=True)
            from ..recovery_rpc import SnapshotChanged
            disproof = next((value for value in outcomes if isinstance(value, SnapshotChanged)), None)
            if disproof is not None:
                raise disproof


def round_robin(feeds):
    """Read one nomination per feed/round without materializing a source."""
    pending = deque(iter(feed) for feed in feeds)
    try:
        while pending:
            feed = pending.popleft()
            try:
                value = next(feed)
            except StopIteration:
                continue
            # A checkpoint is work within this feed's current turn, not an
            # offered candidate that rotates the source ordering.
            if value is CHECKPOINT:
                pending.appendleft(feed)
            else:
                pending.append(feed)
            yield value
    finally:
        for feed in pending:
            close = getattr(feed, 'close', None)
            if close is not None:
                close()
