"""Completion-driven, fair route work; the owning quote keeps its clock."""
import asyncio
from inspect import isawaitable

from .rpc_diagnostics import freeze_quote_work
from .recovery_rpc import SnapshotChanged
from .route_work_slots import CandidateWork, run_candidate


def raise_snapshot_disproof(outcomes):
    """An owned read disproving the context outranks ordinary stopped work."""
    for outcome in outcomes:
        if isinstance(outcome, SnapshotChanged):
            raise outcome


async def schedule_routes(make_feeds, evaluate, *, discover=None, on_completed=None, limit=8):
    """Interleave leg feeds without waiting for one discovery/quote tail.

    One prefetched candidate per leg keeps slow graph enumeration separate from
    completed quote delivery. The limit bounds held pricing-work permits;
    additional parked candidate tasks remain owned and drained. Cancellation
    drains only tasks created here, leaving shared read ownership
    to the engine's ordinary subscription contract. A feed factory may prepare
    its groups cooperatively before returning the ordinary per-leg iterators.
    """
    feeds, pending_next, ready, active = [], {}, {}, set()
    slots, changed = asyncio.Semaphore(limit), asyncio.Event()
    notifications = set()

    def completed(task):
        notifications.add(task)
        changed.set()

    def watch(task):
        task.add_done_callback(completed)
        return task

    discovery = watch(asyncio.create_task(discover())) if discover is not None else None
    expanded = discovery is None
    cursor = 0

    async def advance(feed):
        # Iterator exhaustion is a normal feed result, including when discovery
        # replaces a feed in the same turn that its final anext completes.
        try:
            return True, await anext(feed)
        except StopAsyncIteration:
            return False, None

    def next_candidate(index):
        if feeds[index] is not None and index not in pending_next and index not in ready:
            pending_next[index] = watch(asyncio.create_task(advance(feeds[index])))

    async def close_feeds():
        for task in pending_next.values():
            task.cancel()
        outcomes = await asyncio.gather(*pending_next.values(), return_exceptions=True)
        pending_next.clear()
        outcomes.extend(await asyncio.gather(*(feed.aclose() for feed in feeds if feed is not None),
                                            return_exceptions=True))
        ready.clear()
        raise_snapshot_disproof(outcomes)

    async def start_feeds():
        nonlocal feeds
        offered = make_feeds(expanded)
        feeds = list(await offered if isawaitable(offered) else offered)
        for index in range(len(feeds)):
            next_candidate(index)

    try:
        await start_feeds()
        while active or pending_next or ready or (discovery is not None and not expanded):
            # Each leg gets one turn before another candidate from that leg.
            while ready and not slots.locked():
                for offset in range(len(feeds)):
                    index = (cursor + offset) % len(feeds)
                    if index in ready:
                        candidate = ready.pop(index)
                        await slots.acquire()
                        lease = CandidateWork(slots, changed)
                        task = asyncio.create_task(run_candidate(lease, evaluate, index, candidate))
                        task.add_done_callback(lambda _task, owned=lease: owned.close())
                        active.add(watch(task))
                        next_candidate(index)
                        cursor = (index + 1) % len(feeds)
                        break
            if not active and not pending_next and (discovery is None or expanded):
                break
            # Completion callbacks are registered once. A released pricing lease
            # uses the same wakeup, without rescanning every parked candidate.
            if changed.is_set():
                await asyncio.sleep(0)
            await changed.wait()
            changed.clear()
            done, notifications = notifications, set()
            finished = active & done
            if finished:
                outcomes = await asyncio.gather(*finished, return_exceptions=True)
                raise_snapshot_disproof(outcomes)
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        raise outcome
                active.difference_update(finished)
                if on_completed:
                    await on_completed()
            if discovery is not None and not expanded and discovery in done:
                await discovery
                await close_feeds()
                expanded = True
                await start_feeds()
                continue
            for index, task in list(pending_next.items()):
                if task not in done:
                    continue
                del pending_next[index]
                available, candidate = task.result()
                if available:
                    ready[index] = candidate
                else:
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
