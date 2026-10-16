"""Process-local sharing of identical reads; no retry, lease or age extension."""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass


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


class SharedReads:
    def __init__(self, max_completed=4096):
        self.pending = {}
        self.completed = OrderedDict()
        self.max_completed = max_completed

    async def _produce(self, entries, produce, retain):
        try:
            values = await produce([key for key, _ in entries])
            for (key, entry), value in zip(entries, values, strict=True):
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
        except Exception as error:
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
                entry = PendingRead(asyncio.get_running_loop().create_future())
                self.pending[key] = entry
                new.append((key, entry))
                counts['issued'] += 1
            else:
                counts['coalesced'] += 1
            entry.users += 1
            selected.append((key, entry, None))
        if new:
            task = asyncio.create_task(self._produce(new, produce, retain))
            for _, entry in new:
                entry.task = task
        try:
            values = await asyncio.gather(*(asyncio.shield(entry.future)
                if entry else asyncio.sleep(0, result=value) for _, entry, value in selected))
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
                if not task.done() and not any(entry.users for entry in self.pending.values()
                                              if entry.task is task):
                    # New callers must not join work already being cancelled.
                    # The old producer's identity check preserves replacements.
                    for key, entry in list(self.pending.items()):
                        if entry.task is task:
                            del self.pending[key]
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def one(self, key, produce):
        async def batch(_keys):
            return [await produce()]
        values, _ = await self.many([key], batch)
        return values[0]

    async def close(self):
        tasks = {entry.task for entry in self.pending.values() if entry.task}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.completed.clear()
