"""Candidate-owned pricing permits, released only at required-state suspension."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar


_current = ContextVar('candidate_route_work_lease', default=None)


class _EnginePermit:
    def __init__(self, semaphore):
        self.semaphore, self.owned = semaphore, False

    async def acquire(self):
        await self.semaphore.acquire()
        self.owned = True

    def release(self):
        if self.owned:
            self.owned = False
            self.semaphore.release()


class CandidateWork:
    """One live evaluation; a parked evaluation still belongs to its scheduler."""
    def __init__(self, slots, changed):
        # The scheduler reserves this permit before creating the task. Closing
        # a cancelled-before-first-turn task must release that reservation too.
        self.slots, self.changed = slots, changed
        self.owner, self.owned, self.closed = None, True, False
        self.engines = []

    def release(self):
        for permit in reversed(self.engines):
            permit.release()
        if self.owned:
            self.owned = False
            self.slots.release()
            self.changed.set()

    async def acquire(self):
        try:
            await self.slots.acquire()
            self.owned = True
            for permit in self.engines:
                await permit.acquire()
        except BaseException:
            self.release()
            # Semaphore restores a grant cancelled before acquire returns, even
            # though this lease never owned it. Wake admission for that capacity.
            self.changed.set()
            raise

    def close(self):
        if not self.closed:
            self.closed = True
            self.release()


async def run_candidate(lease, evaluate, index, candidate):
    lease.owner = asyncio.current_task()
    token = _current.set(lease)
    try:
        return await evaluate(index, candidate)
    finally:
        lease.close()
        _current.reset(token)


def _owned():
    lease = _current.get()
    # Snapshot/read tasks inherit ContextVars but own none of these permits.
    return lease if lease and lease.owner is asyncio.current_task() and not lease.closed else None


@asynccontextmanager
async def engine_work(semaphore):
    lease = _owned()
    if lease is None:
        async with semaphore:
            yield
        return
    permit = _EnginePermit(semaphore)
    await permit.acquire()
    lease.engines.append(permit)
    try:
        yield
    finally:
        permit.release()
        lease.engines.remove(permit)


@asynccontextmanager
async def required_state_wait():
    lease = _owned()
    if lease is None or not lease.owned:
        yield
        return
    lease.release()
    try:
        yield
    except BaseException:
        # Cancelled/failed required reads have no SDK resume to fund. Outer
        # contexts release only permits actually held, and still drain normally.
        raise
    else:
        await lease.acquire()
