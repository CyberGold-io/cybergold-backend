"""One producer's selection clock, distinct from caller cancellation.

The selection window includes context acquisition and executable qualification.
Existing terminal canonical checks and owned-task drain follow selection; their
elapsed time is measured rather than hidden in a new discovery allowance.
"""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from inspect import iscoroutine

from .rpc_diagnostics import bind_quote_error, quote_error_diagnostics, quote_owned_task


_budget = ContextVar('quote_selection_budget', default=None)


class SearchStopped(BaseException):
    """The producer ended discovery; its existing finalizer must still run."""


def current_budget():
    return _budget.get()


@contextmanager
def budget_context(budget):
    token = _budget.set(budget)
    try:
        yield budget
    finally:
        _budget.reset(token)


def budget_entry(function):
    @wraps(function)
    async def entered(*args, **kwargs):
        if current_budget() is not None:
            return await function(*args, **kwargs)
        with budget_context(QuoteBudget()):
            return await function(*args, **kwargs)
    return entered


class QuoteBudget:
    def __init__(self, initial=5, extension=10):
        self.loop = asyncio.get_running_loop()
        self.started = self.loop.time()
        self.initial = self.started + initial
        self.deadline = self.initial + extension
        self.stop = asyncio.Event()
        self.ready = False
        self.first_qualified = None
        self.selected = None
        self.reason = None
        self.finished = None
        self.canonical = None
        self.drained = None

    def elapsed(self):
        return (self.loop.time() - self.started) * 1000

    def finish_selection(self, reason):
        if not self.stop.is_set():
            self.selected, self.reason = self.loop.time(), reason
            self.stop.set()

    def qualified(self):
        """Admit a checked candidate while its producer's window is open."""
        now = self.loop.time()
        if self.stop.is_set():
            return False
        if now >= self.deadline:
            self.finish_selection('timeout')
            return False
        if now >= self.initial and self.ready:
            self.finish_selection('best-initial')
            return False
        self.ready = True
        if self.first_qualified is None:
            self.first_qualified = now
        if now >= self.initial:
            self.finish_selection('first-extension')
        return True

    def invalidated(self):
        self.ready = False

    def canonical_done(self):
        self.canonical = self.loop.time()

    def cleanup_done(self):
        self.drained = self.loop.time()

    async def prepare(self, operation):
        """Context work consumes the original fifteen seconds as well."""
        async with asyncio.timeout_at(self.deadline):
            return await self.discovery(operation)

    async def discovery(self, operation):
        if self.stop.is_set():
            if iscoroutine(operation):
                operation.close()
            raise SearchStopped()
        async def owned():
            with quote_owned_task():
                return await operation
        task = asyncio.create_task(owned())
        stopped = asyncio.create_task(self.stop.wait())
        try:
            done, _ = await asyncio.wait((task, stopped), return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return await task
            task.cancel()
            outcome, = await asyncio.gather(task, return_exceptions=True)
            if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                raise outcome
            raise SearchStopped()
        finally:
            stopped.cancel()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, stopped, return_exceptions=True)

    async def produce(self, operation):
        async def clock():
            await asyncio.sleep(max(0, self.initial - self.loop.time()))
            if self.ready:
                self.finish_selection('best-initial')
                return
            await asyncio.sleep(max(0, self.deadline - self.loop.time()))
            self.finish_selection('timeout')
        timer = asyncio.create_task(clock())
        try:
            result = await operation
            if self.selected is None:
                self.finish_selection('complete')
            return result
        except SearchStopped as stopped:
            error = TimeoutError('Quote selection budget exhausted')
            bind_quote_error(error, quote_error_diagnostics(stopped))
            raise error from None
        finally:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
            self.finished = self.loop.time()

    def timings(self):
        def offset(value):
            return None if value is None else round((value - self.started) * 1000, 3)
        return {'firstQualifiedMs': offset(self.first_qualified),
                'selectionMs': offset(self.selected), 'canonicalMs': offset(self.canonical),
                'drainedMs': offset(self.drained), 'terminalMs': offset(self.finished),
                'selectionReason': self.reason}

    def metrics(self):
        times = self.timings()
        values = {'firstQualifiedMs': times['firstQualifiedMs'],
                  'selectionMs': times['selectionMs'],
                  'canonicalCompletedMs': times['canonicalMs'],
                  'cleanupCompletedMs': times['drainedMs']}
        if self.finished is not None and self.selected is not None:
            values['finalizationMs'] = round((self.finished - self.selected) * 1000, 3)
        return {name: value for name, value in values.items() if value is not None}
