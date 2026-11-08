"""One computation stream, with synchronous and cooperative consumers.

Private checkpoints describe work, never route offers. They do not change
candidate eligibility or the owner's quote clock. Closing either consumer
closes its suspended computation; no work is sent to an unowned thread.
"""
import asyncio
from heapq import merge


CHECKPOINT = object()
QUANTUM = 64


def close(iterator):
    method = getattr(iterator, 'close', None)
    if method is not None:
        method()


def finish(steps):
    try:
        while True:
            next(steps)
    except StopIteration as done:
        return done.value
    finally:
        close(steps)


def values(steps):
    try:
        for value in steps:
            if value is not CHECKPOINT:
                yield value
    finally:
        close(steps)


async def async_values(steps):
    count = 0
    try:
        for value in steps:
            count += 1
            if count == QUANTUM:
                count = 0
                await asyncio.sleep(0)
            if value is not CHECKPOINT:
                yield value
    finally:
        close(steps)


async def async_finish(steps):
    count = 0
    try:
        while True:
            try:
                next(steps)
            except StopIteration as done:
                return done.value
            count += 1
            if count == QUANTUM:
                count = 0
                await asyncio.sleep(0)
    finally:
        close(steps)


def sort_steps(items, *, key):
    """Stable sorting with bounded key/sort/merge work between checkpoints."""
    chunks, chunk = [], []
    for index, value in enumerate(items):
        chunk.append((key(value), index, value))
        yield CHECKPOINT
        if len(chunk) == QUANTUM:
            chunk.sort()
            chunks.append(chunk)
            chunk = []
    if chunk:
        chunk.sort()
        chunks.append(chunk)
    result = []
    for _, _, value in merge(*chunks):
        result.append(value)
        yield CHECKPOINT
    return result
