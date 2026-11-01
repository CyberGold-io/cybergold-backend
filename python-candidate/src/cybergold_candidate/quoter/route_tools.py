"""One generic AMM query/candidate/feed contract for every route tool."""
from collections import deque
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, TypeAlias


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
    their next iteration. Pending work belongs to the request/session owner.
    Neither part supplies trusted prices, Core economics or execution calldata.
    """
    available: Iterable[RouteCandidate] = ()
    pending: Awaitable[Iterable[RouteCandidate]] | None = None

    def available_projected(self, projection=None):
        """Apply a consumer's opaque path projection where supported.

        This is a fresh immediate-feed view, never shared query state. Pending
        nominations retain their own shapes and the adapter's ordinary replay.
        """
        project = getattr(self.available, 'with_path_projection', None)
        return project(projection) if projection is not None and project is not None else self.available


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
        return CandidateFeed(pending=self._pending(query))

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
            pending.append(feed)
            yield value
    finally:
        for feed in pending:
            close = getattr(feed, 'close', None)
            if close is not None:
                close()
