"""Quote stage measurements, independent of admission, ranking and lifetimes.

Await stages measure inclusive wall time, never CPU. CPU stages surround only
synchronous code and measure this thread's CPU. Concurrent stage totals overlap;
they are not a critical path. A recorder holds aggregates rather than one row
per SDK callback, and shared owners retain their own flow identity and clock.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import asyncio
import json
import logging
import time
import uuid


STAGES = frozenset('''http.parse http.operation http.await_result http.cleanup http.encode http.send
    cache.scope cache.capture cache.memory cache.seeds cache.read.wait cache.sql.lookup
    cache.sql.neighbors cache.persist cache.close metadata.load metadata.configuration
    metadata.observe metadata.generation metadata.observers database.acquire
    estimate.scope estimate.read estimate.calculate preparation.scope preparation.bounds
    preparation.replay preparation.compile search.run search.context search.enumerate
    search.cleanup discovery.run optimizer.callback optimizer.decode sdk.queue sdk.exchange
    sdk.start sdk.write sdk.read sdk.cleanup sdk.encode sdk.decode pricing.permit
    state.acquire state.clone topology.clone topology.enrich plan.compile helpers.shared
    helpers.permit helpers.rpc rpc.session rpc.http observation.project publication.queue publication.reconcile
    publication.publish other'''.split())
_current = ContextVar('quotation_flow', default=None)


def current_flow():
    return _current.get()


def _safe(action):
    try:
        return action()
    except Exception:
        return None


class Flow:
    def __init__(self, operation, *, request_id=None, attempt_id=None, parent=None,
                 kind='request', metrics=None, clock=None, cpu_clock=None, sink=None):
        self.clock = clock or time.perf_counter
        self.cpu_clock = cpu_clock or time.thread_time
        self.started = self.clock()
        self.operation, self.kind = operation, kind
        self.request_id = request_id or (parent.request_id if parent else None)
        self.attempt_id = attempt_id or (parent.attempt_id if parent else None)
        self.flow_id = self.request_id if kind == 'request' and self.request_id else str(uuid.uuid4())
        self.parent_id = parent.flow_id if parent else None
        self.metrics = metrics if metrics is not None else parent.metrics if parent else None
        self.sink = sink or (parent.sink if parent else None)
        self.rows, self.links = {}, {}
        self.terminal = False
        self.shared_producers = 0
        self.finished_at = None
        self.outcome = None
        self.emitted = False

    def row(self, name, kind):
        key = name, kind
        if key not in self.rows:
            self.rows[key] = {'stage': name, 'kind': kind, 'started': 0,
                'completed': 0, 'failed': 0, 'cancelled': 0, 'summedWallMs': 0.0,
                'summedCpuMs': 0.0, 'maxWallMs': 0.0,
                'readyMarkers': 0,
                'summedReadyWaitMs': 0.0, 'summedResumeDelayMs': 0.0}
        return self.rows[key]

    def link(self, owner, relation):
        if owner is not None and owner.flow_id != self.flow_id:
            key = owner.flow_id, relation
            self.links[key] = self.links.get(key, 0) + 1

    def snapshot(self):
        now = self.clock()
        rows = []
        for row in self.rows.values():
            value = {key: round(item, 3) if isinstance(item, float) else item
                     for key, item in row.items()}
            value['inFlight'] = row['started'] - row['completed'] - row['failed'] - row['cancelled']
            if value['inFlight']:
                value['activePeriodMs'] = round((now-row['_activeSince'])*1000, 3)
            value.pop('_activeSince', None)
            rows.append(value)
        return {'flowId': self.flow_id, 'parentFlowId': self.parent_id,
                'requestId': self.request_id, 'attemptId': self.attempt_id,
                'operation': self.operation, 'flowKind': self.kind,
                'elapsedMs': round((now-self.started)*1000, 3),
                'stages': sorted(rows, key=lambda row: (row['stage'], row['kind'])),
                'sharedOwners': [{'flowId': owner, 'relation': relation, 'subscriptions': count}
                                 for (owner, relation), count in self.links.items()]}

    def finish(self, outcome):
        if self.terminal:
            return
        self.terminal = True
        self.outcome = outcome
        self.finished_at = _safe(self.clock)
        if not self.shared_producers:
            self._emit()

    def retain_producer(self):
        # Diagnostic retention only: never await or extend the caller's life.
        self.shared_producers += 1

    def release_producer(self):
        self.shared_producers -= 1
        if self.terminal and not self.shared_producers:
            self._emit()

    def _emit(self):
        if self.emitted:
            return
        self.emitted = True
        def emit():
            record = {'event': 'quote_flow', 'component': 'api', 'outcome': self.outcome,
                      **self.snapshot()}
            # Shared work can finish for another subscriber after this caller
            # returns. Keep the caller clock, while exposing the owned tail.
            if self.finished_at is not None:
                record['ownedWorkElapsedMs'] = record['elapsedMs']
                record['elapsedMs'] = round((self.finished_at-self.started)*1000, 3)
            if self.sink:
                self.sink(record)
            else:
                logging.getLogger('cybergold.candidate').info(json.dumps(record))
            if self.metrics is not None:
                self.metrics.observe_quote_flow(record)
        _safe(emit)

    def server_timing(self):
        # Headers describe pre-header work only. Complete stream/cleanup
        # measurements are emitted independently when the flow finishes.
        values = [f'cg_backend_headers;dur={(self.clock()-self.started)*1000:.3f}']
        for row in self.rows.values():
            if row['completed'] or row['failed'] or row['cancelled']:
                name = row['stage'].replace('.', '_')
                values.append(f'cg_sum_{name};dur={row["summedWallMs"]:.3f}')
        return ', '.join(values)


@contextmanager
def flow_scope(flow):
    token = _current.set(flow)
    try:
        yield flow
    finally:
        _current.reset(token)


@contextmanager
def producer_flow(kind):
    parent = current_flow()
    if parent is None:
        yield None
        return
    flow = _safe(lambda: Flow(parent.operation, parent=parent, kind=kind))
    if flow is None:
        yield None
        return
    task = asyncio.current_task()
    if task is not None:
        # An observer can join this owner before or after it completes; the
        # tag has exactly the task's lifetime and never decides eligibility.
        _safe(lambda: setattr(task, 'quote_flow', flow))
    outcome = 'succeeded'
    with flow_scope(flow):
        try:
            yield flow
        except asyncio.CancelledError:
            outcome = 'cancelled'
            raise
        except BaseException:
            outcome = 'failed'
            raise
        finally:
            flow.finish(outcome)


class Span:
    def __init__(self, flow=None, name='other', kind='await'):
        self.flow, self.name, self.kind = flow, name, kind
        self.active, self.started, self.cpu_started, self.granted = False, None, None, None

    def __enter__(self):
        if self.flow is not None:
            def start():
                self.started = self.flow.clock()
                self.cpu_started = self.flow.cpu_clock() if self.kind == 'cpu' else None
                row = self.flow.row(self.name, self.kind)
                if row['started'] == row['completed'] + row['failed'] + row['cancelled']:
                    row['_activeSince'] = self.started
                row['started'] += 1
                row.setdefault('firstStartMs', (self.started-self.flow.started)*1000)
                self.active = True
            _safe(start)
        return self

    def ready(self):
        # Called by the granting owner, before the waiting task resumes.
        if self.active and self.granted is None:
            self.granted = _safe(self.flow.clock)

    def __exit__(self, error_type, error, traceback):
        if self.active:
            def finish():
                ended = self.flow.clock()
                elapsed = (ended-self.started)*1000
                row = self.flow.row(self.name, self.kind)
                outcome = ('cancelled' if isinstance(error, asyncio.CancelledError)
                           else 'failed' if error_type is not None else 'completed')
                row[outcome] += 1
                row['summedWallMs'] += elapsed
                if self.cpu_started is not None:
                    row['summedCpuMs'] += (self.flow.cpu_clock()-self.cpu_started)*1000
                if self.granted is not None:
                    row['readyMarkers'] += 1
                    row['summedReadyWaitMs'] += (self.granted-self.started)*1000
                    row['summedResumeDelayMs'] += (ended-self.granted)*1000
                if elapsed >= row['maxWallMs']:
                    row.update(maxWallMs=elapsed,
                        slowestStartMs=(self.started-self.flow.started)*1000,
                        slowestEndMs=(ended-self.flow.started)*1000)
                row['lastEndMs'] = (ended-self.flow.started)*1000
            _safe(finish)
            self.active = False
        return False


def stage(name, *, kind='await'):
    return Span(current_flow(), name if name in STAGES else 'other', kind)


def link_owner(owner, relation):
    flow = current_flow()
    if flow is not None and owner is not None:
        _safe(lambda: flow.link(owner, relation))


def follow(task, relation):
    link_owner(getattr(task, 'quote_flow', None), relation)


def retain_shared_producer():
    flow = current_flow()
    if flow is not None:
        def retain():
            flow.retain_producer()
            return flow
        return _safe(retain)
    return None


def release_shared_producer(flow):
    if flow is not None:
        _safe(flow.release_producer)


def flow_entry(kind):
    def decorate(operation):
        @wraps(operation)
        async def entered(*args, **kwargs):
            with producer_flow(kind):
                return await operation(*args, **kwargs)
        return entered
    return decorate
