"""One computation stream, with synchronous and cooperative consumers.

Private checkpoints describe work, never route offers. They do not change
candidate eligibility or the owner's quote clock. Closing either consumer
closes its suspended computation; no work is sent to an unowned thread.
"""
import asyncio
from contextvars import ContextVar
from heapq import merge


CHECKPOINT = object()
QUANTUM = 64
_driver = ContextVar('cooperative_async_driver', default=None)


def asynchronous():
    return _driver.get() is not None


def await_steps(task):
    """A private checkpoint can suspend the async driver on owned CPU work."""
    while not task.done():
        _driver.get()[0] = task
        yield CHECKPOINT
    return task.result()


def advance(steps, *, asynchronous=False):
    """Scope driver state to next(), never across a public yield or Task."""
    if not asynchronous and _driver.get() is None:
        return next(steps), None
    driver = [None] if asynchronous else None
    token = _driver.set(driver)
    try:
        value = next(steps)
        return value, driver[0] if driver is not None else None
    finally:
        _driver.reset(token)


async def ready(task):
    try:
        await asyncio.shield(task)
    except Exception:
        # Resume next() so the producer raises inside its existing feed error
        # handler. A failed optional source must not bypass a valid sibling.
        pass


def close(iterator):
    method = getattr(iterator, 'close', None)
    if method is not None:
        method()


def finish(steps):
    token = _driver.set(None)
    try:
        while True:
            next(steps)
    except StopIteration as done:
        return done.value
    finally:
        try:
            close(steps)
        finally:
            _driver.reset(token)


def values(steps):
    try:
        while True:
            try:
                value, _ = advance(steps)
            except StopIteration:
                return
            if value is not CHECKPOINT:
                yield value
    finally:
        close(steps)


async def async_values(steps):
    count = 0
    try:
        while True:
            try:
                value, pending = advance(steps, asynchronous=True)
            except StopIteration:
                return
            if pending is not None:
                await ready(pending)
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
                _, pending = advance(steps, asynchronous=True)
            except StopIteration as done:
                return done.value
            if pending is not None:
                await ready(pending)
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
