"""Request-owned route hints alongside ordinary whole-plan discovery.

Suppliers nominate semantic candidates only. Conversions read completed hints
without waiting; arrivals ask the owner to reevaluate its ordinary whole plans.
No supplier quote, private pool bank, selection clock or ranking lives here.
"""
import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from inspect import isawaitable

from ..quote_budget import SearchStopped, current_budget
from ..recovery_rpc import SnapshotChanged
from ..route_observations import origin_scope


_bootstrap = ContextVar('route_discovery_bootstrap', default=None)


def current_bootstrap():
    return _bootstrap.get()


@contextmanager
def bootstrap_scope(session):
    token = _bootstrap.set(session)
    try:
        yield session
    finally:
        _bootstrap.reset(token)


class ProviderUnavailable(RuntimeError):
    """A supplier has no configured/runnable discovery capability."""


class RouteBootstrap:
    def __init__(self, providers):
        self._loop = asyncio.get_running_loop()
        self._budget = current_budget()
        self._started_mono = self._loop.time()
        self._started_ms = self._elapsed_ms()
        self._finished_ms = None
        self._owners = [] if isinstance(providers, Mapping) else list(providers)
        self.providers = (list(providers.items()) if isinstance(providers, Mapping)
                          else [(provider.name, provider.discover) for provider in self._owners])
        self._queries, self._attempts, self._tasks = {}, [], set()
        self._close_errors = []
        self._changed = asyncio.Event()
        self._closed, self._close_task = False, None
        self.revision, self.reevaluations = 0, 0

    def _elapsed_ms(self):
        value = self._budget.elapsed() if self._budget is not None else (
            self._loop.time() - self._started_mono) * 1000
        return round(value, 3)

    @property
    def timings(self):
        """Per-provider wall timings, in the producer's existing clock.

        First-candidate is the earliest nomination. Completed/cancelled are the
        last completed/cancelled attempts; pending counts remain independent.
        Duration spans the first attempt to its latest finish (or now while a
        query is pending), not the sum of overlapping supplier query durations.
        Without a producer budget these coordinates start at session creation.
        """
        result = {}
        for name, _ in self.providers:
            attempts = [row for row in self._attempts if row['provider'] == name]
            started = min((row['startedMs'] for row in attempts), default=None)
            completed = max((row['completedMs'] for row in attempts if row['completedMs'] is not None), default=None)
            cancelled = max((row['cancelledMs'] for row in attempts if row['cancelledMs'] is not None), default=None)
            pending = sum(row['status'] == 'pending' for row in attempts)
            end = self._elapsed_ms() if pending else max(
                (value for value in (completed, cancelled) if value is not None), default=started)
            result[name] = {'started': len(attempts), 'pending': pending, 'startedMs': started,
                'firstCandidateMs': min((row['firstCandidateMs'] for row in attempts
                                         if row['firstCandidateMs'] is not None), default=None),
                'completedMs': completed, 'cancelledMs': cancelled,
                'durationMs': round(end - started, 3) if started is not None else None}
        return result

    @property
    def metrics(self):
        statuses = ('pending', 'completed', 'empty', 'unavailable', 'error',
                    'cancelled', 'stopped', 'invalidated')
        result = {}
        timings = self.timings
        for name, _ in self.providers:
            attempts = [row for row in self._attempts if row['provider'] == name]
            result[name] = {'started': len(attempts),
                **{status: sum(row['status'] == status for row in attempts) for status in statuses},
                'candidates': sum(row['candidates'] for row in attempts),
                **{key: value for key, value in timings[name].items() if key.endswith('Ms')}}
        finished = self._finished_ms if self._finished_ms is not None else self._elapsed_ms()
        return {'queries': len(self._queries), 'revision': self.revision,
                'reevaluations': self.reevaluations, 'providers': result,
                'closeErrors': len(self._close_errors),
                'clock': 'producer' if self._budget is not None else 'session',
                'startedMs': self._started_ms, 'completedMs': self._finished_ms,
                'elapsedMs': round(finished - self._started_ms, 3)}

    def _raise_failure(self):
        # Preserve the existing priority of a canonical-context disproof over
        # cancellation or an otherwise completed sibling operation.
        failures = []
        for task in self._tasks:
            if task.done():
                if task.cancelled():
                    if not self._closed:
                        failures.append(asyncio.CancelledError())
                elif task.exception() is not None:
                    failures.append(task.exception())
        disproof = next((error for error in failures if isinstance(error, SnapshotChanged)), None)
        if disproof is not None:
            raise disproof
        if failures:
            raise failures[0]

    def candidates(self, source, target, amount, block):
        """Backward-compatible branch-only view of completed nominations."""
        return [offer['branches'] for offer in self.offers(source, target, amount, block)]

    def offers(self, source, target, amount, block):
        """Start suppliers; return completed branches with diagnostic origins.

        Origins neither authorize a candidate nor change query sharing/ranking.
        Duplicate nominations retain each supplier for the consumer to combine.
        """
        self._raise_failure()
        if self._closed:
            return []
        key = source.lower(), target.lower(), int(amount)
        if key not in self._queries:
            self._queries[key] = []
            for name, discover in self.providers:
                attempt = {'provider': name, 'status': 'pending', 'candidates': 0,
                    'startedMs': self._elapsed_ms(), 'firstCandidateMs': None,
                    'completedMs': None, 'cancelledMs': None}
                self._attempts.append(attempt)
                task = asyncio.create_task(self._discover(discover, key, block, attempt))
                self._tasks.add(task)
                task.add_done_callback(lambda done, row=attempt: self._completed(done, row))
        return deepcopy(self._queries[key])

    async def _discover(self, discover, key, block, attempt):
        try:
            with origin_scope(attempt['provider']):
                rows = deepcopy(list(await discover(key[0], key[1], key[2], block)))
            attempt['status'] = 'completed' if rows else 'empty'
            attempt['candidates'] = len(rows)
            if rows:
                attempt['firstCandidateMs'] = self._elapsed_ms()
                self._queries[key].extend({'branches': row, 'origins': [attempt['provider']]} for row in rows)
                self.revision += 1
        except ProviderUnavailable:
            attempt['status'] = 'unavailable'
        except SnapshotChanged:
            attempt['status'] = 'invalidated'
            raise
        except asyncio.CancelledError:
            attempt['status'] = 'cancelled'
            attempt['cancelledMs'] = self._elapsed_ms()
            raise
        except SearchStopped:
            attempt['status'] = 'stopped'
            raise
        except Exception:
            # Supplier text may contain an HTTP URL/key or subprocess stderr.
            # Only its ordinary outcome belongs in the shared quote metrics.
            attempt['status'] = 'error'
        finally:
            if attempt['status'] != 'cancelled':
                attempt['completedMs'] = self._elapsed_ms()

    def _completed(self, task, attempt):
        if task.cancelled():
            attempt['status'] = 'cancelled'
            if attempt['cancelledMs'] is None:
                attempt['cancelledMs'] = self._elapsed_ms()
        else:
            task.exception()  # Retrieve failures even if the owner is already draining.
        self._changed.set()

    async def run(self, ordinary, reevaluate):
        """Keep ordinary completion independent and consume late arrivals."""
        ordinary_task = asyncio.create_task(ordinary)
        round_task, changed_task = None, None
        completed_revision, round_revision = 0, 0
        budget = current_budget()
        stopped = asyncio.create_task(budget.stop.wait()) if budget is not None else None
        result = None
        try:
            while True:
                self._raise_failure()
                if ordinary_task.done():
                    result = await ordinary_task
                if round_task is not None and round_task.done():
                    await round_task
                    completed_revision = round_revision
                    round_task = None
                if stopped is not None and stopped.done():
                    raise SearchStopped()
                if round_task is None and self.revision > completed_revision:
                    round_revision = self.revision
                    self.reevaluations += 1
                    round_task = asyncio.create_task(reevaluate())
                providers_pending = any(not task.done() for task in self._tasks)
                if ordinary_task.done() and round_task is None and not providers_pending:
                    self._raise_failure()
                    return result
                self._changed.clear()
                changed_task = asyncio.create_task(self._changed.wait())
                waiters = {changed_task}
                if not ordinary_task.done():
                    waiters.add(ordinary_task)
                if round_task is not None:
                    waiters.add(round_task)
                if stopped is not None:
                    waiters.add(stopped)
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                changed_task.cancel()
                await asyncio.gather(changed_task, return_exceptions=True)
                changed_task = None
        finally:
            owned = [task for task in (ordinary_task, round_task, changed_task, stopped) if task is not None]
            for task in owned:
                if not task.done():
                    task.cancel()
            outcomes = await asyncio.gather(*owned, return_exceptions=True)
            try:
                await self.close()
            except SnapshotChanged as error:
                outcomes.append(error)
            disproof = next((error for error in outcomes if isinstance(error, SnapshotChanged)), None)
            if disproof is not None:
                raise disproof

    async def _close(self):
        for task in self._tasks:
            if not task.done():
                task.cancel()
        outcomes = await asyncio.gather(*self._tasks, return_exceptions=True)
        async def close_provider(provider):
            close = getattr(provider, 'close', None)
            if close is not None:
                value = close()
                if isawaitable(value):
                    await value
        outcomes.extend(await asyncio.gather(*(close_provider(provider) for provider in self._owners),
                                            return_exceptions=True))
        self._close_errors = [error for error in outcomes if isinstance(error, Exception)
                              and not isinstance(error, SnapshotChanged)]
        self._finished_ms = self._elapsed_ms()
        disproof = next((error for error in outcomes if isinstance(error, SnapshotChanged)), None)
        if disproof is not None:
            raise disproof

    async def close(self):
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await self._close_task
            raise
