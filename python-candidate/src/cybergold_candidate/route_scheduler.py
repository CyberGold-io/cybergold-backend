"""Completion-driven, fair route work; the owning quote keeps its clock."""
import asyncio

from .rpc_diagnostics import freeze_quote_work
from .recovery_rpc import SnapshotChanged


def raise_snapshot_disproof(outcomes):
    """An owned read disproving the context outranks ordinary stopped work."""
    for outcome in outcomes:
        if isinstance(outcome, SnapshotChanged):
            raise outcome


async def schedule_routes(make_feeds, evaluate, *, discover=None, on_completed=None, limit=8):
    """Interleave leg feeds without waiting for one discovery/quote tail.

    One prefetched candidate per leg keeps slow graph enumeration separate from
    completed quote delivery. The existing eight-job allowance bounds pricing;
    cancellation drains only tasks created here, leaving shared read ownership
    to the engine's ordinary subscription contract.
    """
    feeds, pending_next, ready, active = [], {}, {}, set()
    discovery = asyncio.create_task(discover()) if discover is not None else None
    expanded = discovery is None
    cursor = 0

    def next_candidate(index):
        if feeds[index] is not None and index not in pending_next and index not in ready:
            pending_next[index] = asyncio.create_task(anext(feeds[index]))

    async def close_feeds():
        for task in pending_next.values():
            task.cancel()
        outcomes = await asyncio.gather(*pending_next.values(), return_exceptions=True)
        pending_next.clear()
        outcomes.extend(await asyncio.gather(*(feed.aclose() for feed in feeds if feed is not None),
                                            return_exceptions=True))
        ready.clear()
        raise_snapshot_disproof(outcomes)

    def start_feeds():
        nonlocal feeds
        feeds = list(make_feeds(expanded))
        for index in range(len(feeds)):
            next_candidate(index)

    try:
        start_feeds()
        while active or pending_next or ready or (discovery is not None and not expanded):
            # Each leg gets one turn before another candidate from that leg.
            while ready and len(active) < limit:
                for offset in range(len(feeds)):
                    index = (cursor + offset) % len(feeds)
                    if index in ready:
                        candidate = ready.pop(index)
                        active.add(asyncio.create_task(evaluate(index, candidate)))
                        next_candidate(index)
                        cursor = (index + 1) % len(feeds)
                        break
            waiters = active | set(pending_next.values())
            if discovery is not None and not expanded:
                waiters.add(discovery)
            if not waiters:
                break
            done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            completed = active & done
            if completed:
                outcomes = await asyncio.gather(*completed, return_exceptions=True)
                raise_snapshot_disproof(outcomes)
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        raise outcome
                active.difference_update(completed)
                if on_completed:
                    await on_completed()
            if discovery is not None and not expanded and discovery in done:
                await discovery
                await close_feeds()
                expanded = True
                start_feeds()
                continue
            for index, task in list(pending_next.items()):
                if task not in done:
                    continue
                del pending_next[index]
                try:
                    ready[index] = task.result()
                except StopAsyncIteration:
                    feeds[index] = None
    except BaseException as error:
        freeze_quote_work(error)
        raise
    finally:
        for task in active:
            task.cancel()
        if discovery is not None:
            discovery.cancel()
        outcomes = await asyncio.gather(*active, *([discovery] if discovery is not None else []),
                                        return_exceptions=True)
        try:
            await close_feeds()
        except SnapshotChanged as error:
            outcomes.append(error)
        raise_snapshot_disproof(outcomes)
