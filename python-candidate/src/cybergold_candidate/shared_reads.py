"""Process-local sharing of identical reads; no retry, lease or age extension."""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from .quote_flow import current_flow, link_owner, retain_shared_producer, release_shared_producer, stage


def discard_pool_observation(rpc, call, block):
    """A failed typed decode must not retain its raw successful RPC envelope."""
    bank = getattr(rpc, 'pool_reads', None)
    if bank is not None:
        address, data = call
        bank.completed.pop((rpc.chain_id, block['hash'].lower(), address.lower(), data.lower()), None)


@dataclass
class PendingRead:
    future: asyncio.Future
    users: int = 0
    task: asyncio.Task | None = None
    owner_flow: object = None


class SharedReads:
    def __init__(self, max_completed=4096):
        self.pending = {}
        self.groups = {}
        self.completed = OrderedDict()
        self.max_completed = max_completed

    async def _produce(self, entries, produce, retain):
        try:
            values = await produce([key for key, _ in entries])
            for (key, entry), value in zip(entries, values, strict=True):
                if isinstance(value, Exception):
                    if not entry.future.done():
                        entry.future.set_exception(value)
                        entry.future.exception()
                    continue
                if retain and 'error' not in value:
                    self.completed[key] = value
                    self.completed.move_to_end(key)
                    while len(self.completed) > self.max_completed:
                        self.completed.popitem(last=False)
                if not entry.future.done():
                    entry.future.set_result(value)
        except asyncio.CancelledError:
            for _, entry in entries:
                entry.future.cancel()
        except BaseException as error:
            for _, entry in entries:
                if not entry.future.done():
                    entry.future.set_exception(error)
                    # A disconnected last subscriber must not leave an
                    # unhandled-future warning; awaiting still raises normally.
                    entry.future.exception()
        finally:
            for key, entry in entries:
                if self.pending.get(key) is entry:
                    del self.pending[key]

    async def many(self, keys, produce, retain=False, counts=None):
        selected, new = [], []
        counts = counts if counts is not None else {}
        counts.update(requested=len(keys), issued=0, coalesced=0, reused=0)
        for key in keys:
            if retain and key in self.completed:
                self.completed.move_to_end(key)
                selected.append((key, None, self.completed[key]))
                counts['reused'] += 1
                continue
            entry = self.pending.get(key)
            if entry is None:
                entry = PendingRead(asyncio.get_running_loop().create_future(), owner_flow=current_flow())
                self.pending[key] = entry
                new.append((key, entry))
                counts['issued'] += 1
            else:
                counts['coalesced'] += 1
                link_owner(entry.owner_flow, 'shared-read')
            entry.users += 1
            selected.append((key, entry, None))
        if new:
            task = asyncio.create_task(self._produce(new, produce, retain))
            flow = retain_shared_producer()
            for _, entry in new:
                entry.task = task
            self.groups[task] = new
            def finished(done):
                release_shared_producer(flow)
                entries = self.groups.pop(done, ())
                if done.cancelled():
                    # A producer cancelled before its first turn cannot run
                    # _produce's cleanup or wake its waiting subscribers.
                    for key, entry in entries:
                        entry.future.cancel()
                        if self.pending.get(key) is entry:
                            del self.pending[key]
            task.add_done_callback(finished)
        try:
            if len(selected) == 1:
                _, entry, cached = selected[0]
                values = [await asyncio.shield(entry.future) if entry is not None else cached]
            elif selected:
                pending = [asyncio.shield(entry.future) for _, entry, _ in selected if entry is not None]
                if pending:
                    resolved = iter(await asyncio.gather(*pending))
                    values = [next(resolved) if entry is not None else cached for _, entry, cached in selected]
                else:
                    # Preserve multi-key cooperation without one Task per hit.
                    await asyncio.sleep(0)
                    values = [cached for _, _, cached in selected]
            else:
                values = []
            return values, counts
        finally:
            tasks = set()
            for _, entry, _ in selected:
                if entry:
                    entry.users -= 1
                    if entry.task:
                        tasks.add(entry.task)
            # One subscriber can cancel without cancelling another's read.
            # When every member is unused, retain the ordinary cancellation.
            for task in tasks:
                entries = self.groups.get(task, ())
                if not task.done() and not any(entry.users for _, entry in entries):
                    # New callers must not join work already being cancelled.
                    # The old producer's identity check preserves replacements.
                    for key, entry in entries:
                        if self.pending.get(key) is entry:
                            del self.pending[key]
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def one(self, key, produce):
        async def batch(_keys):
            return [await produce()]
        values, _ = await self.many([key], batch)
        return values[0]

    async def close(self):
        tasks = tuple(self.groups)
        for task in tasks:
            task.cancel()
        with stage('sharing.settle'):
            await asyncio.gather(*tasks, return_exceptions=True)
        with stage('sharing.clear', kind='cpu'):
            self.completed.clear()
