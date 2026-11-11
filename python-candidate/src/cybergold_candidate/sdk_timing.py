"""Bounded optional SDK round-trip evidence, never scheduling or quote authority."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from time import monotonic_ns

from .quote_flow import current_flow

_operation = ContextVar('sdk_timing_operation', default=None)


def observe(action):
    try:
        return action()
    except Exception:
        return None


class ChildClock:
    """Calibrate origins with nonnegative request/response transport brackets.

    Child and parent monotonic origins may differ. A child instant plus offset
    belongs to the parent's clock. No wall-clock/NTP assumption is involved.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.lower = self.upper = None

    def join(self, sent, received, emitted, consumed):
        lower, upper = sent-received, consumed-emitted
        if received > emitted or lower > upper:
            raise ValueError('SDK timing transport bracket is inconsistent')
        lo = max(lower, self.lower) if self.lower is not None else lower
        hi = min(upper, self.upper) if self.upper is not None else upper
        reset = lo > hi
        self.lower, self.upper = (lower, upper) if reset else (lo, hi)
        # This includes pipe transport and Python readiness, not only wakeup.
        return ((consumed-emitted-self.upper)/1e6,
                (consumed-emitted-self.lower)/1e6,
                (self.upper-self.lower)/1e6, reset)


class RoundTrips:
    def __init__(self):
        self.rows = {}

    def row(self, operation, mode, phase):
        key = operation, mode, phase
        if key not in self.rows:
            self.rows[key] = dict(operation=operation, mode=mode, phase=phase,
                started=0, completed=0, failed=0, cancelled=0, childFrames=0,
                resultFrames=0, stateRequestFrames=0, errorFrames=0, otherFrames=0,
                legacyOrMissingFrames=0, invalidChildFrames=0, calibrationResets=0,
                childOperationWallMs=0.0, childProcessCpuMs=0.0, childEncodeWallMs=0.0,
                childQueueAndDecodeWallMs=0.0, requestToChildLowerMs=0.0, requestToChildUpperMs=0.0,
                responseToReadLowerMs=0.0, responseToReadUpperMs=0.0,
                maxRoundTripMs=0.0, maxClockUncertaintyMs=0.0)
        return self.rows[key]

    def snapshot(self):
        return {'clock': 'monotonic-transport-brackets; origins need not match',
                'cpuScope': 'child-process CPU during segment; includes background threads, not exclusive arithmetic',
                'completionScope': 'exchange read returned; result, state request, error or EOF, not quote success',
                'responseDelayScope': 'child pre-write to parent line consumption; pipe and Python readiness',
                'rows': [deepcopy(self.rows[key]) for key in sorted(self.rows)]}


@contextmanager
def operation_timing(clock, operation, mode):
    owner = (clock, operation, mode, asyncio.current_task()) if current_flow() is not None else None
    token = _operation.set(owner)
    try:
        yield
    finally:
        _operation.reset(token)


class ExchangeTiming:
    def __init__(self, flow, clock, operation, mode, phase):
        self.flow, self.clock = flow, clock
        self.sent = monotonic_ns()
        self.sent_ms = (flow.clock()-flow.started)*1000
        self.consumed = self.consumed_ms = None
        if flow.sdk_roundtrips is None:
            flow.sdk_roundtrips = RoundTrips()
        operation = operation if operation in ('quote', 'simulateRoute') else 'other'
        mode = mode if mode in ('exactIn', 'exactOut') else 'other'
        self.row = flow.sdk_roundtrips.row(operation, mode, phase)
        self.row['started'] += 1

    def consumed_line(self):
        self.consumed = monotonic_ns()
        self.consumed_ms = (self.flow.clock()-self.flow.started)*1000

    def finish(self, response=None, error=None):
        self.row['cancelled' if isinstance(error, asyncio.CancelledError) else
                 'failed' if error is not None else 'completed'] += 1
        if error is not None:
            return
        kind = ('stateRequestFrames' if isinstance(response, dict) and response.get('stateRequest') else
                'errorFrames' if isinstance(response, dict) and (response.get('error') or response.get('missingState')) else
                'resultFrames' if isinstance(response, dict) and 'result' in response else 'otherFrames')
        self.row[kind] += 1
        child = response.get('_sdkTiming') if isinstance(response, dict) else None
        if not isinstance(child, dict):
            self.row['legacyOrMissingFrames'] += 1
            return
        def join():
            received, started, computed, emitted = (int(child[key]) for key in
                ('receivedNs', 'startedNs', 'computedNs', 'writeStartedNs'))
            if not received <= started <= computed <= emitted or self.consumed is None:
                raise ValueError('SDK timing segment is inconsistent')
            cpu = (int(child['processCpuUserUs'])+int(child['processCpuSystemUs']))/1000
            if cpu < 0:
                raise ValueError('SDK process CPU delta is negative')
            lo, hi, uncertainty, reset = self.clock.join(self.sent, received, emitted, self.consumed)
            wall = (computed-started)/1e6
            self.row['childFrames'] += 1
            self.row['calibrationResets'] += int(reset)
            self.row['childOperationWallMs'] += wall
            self.row['childProcessCpuMs'] += cpu
            self.row['childEncodeWallMs'] += (emitted-computed)/1e6
            self.row['childQueueAndDecodeWallMs'] += (started-received)/1e6
            self.row['requestToChildLowerMs'] += (received+self.clock.lower-self.sent)/1e6
            self.row['requestToChildUpperMs'] += (received+self.clock.upper-self.sent)/1e6
            self.row['responseToReadLowerMs'] += lo
            self.row['responseToReadUpperMs'] += hi
            self.row['maxClockUncertaintyMs'] = max(self.row['maxClockUncertaintyMs'], uncertainty)
            duration = (self.consumed-self.sent)/1e6
            if duration >= self.row['maxRoundTripMs']:
                self.row['maxRoundTripMs'] = duration
                self.row['slowest'] = dict(parentSentMs=self.sent_ms,
                    parentReadConsumedMs=self.consumed_ms, childOperationWallMs=wall,
                    childResponseWriteMsLower=self.consumed_ms-hi,
                    childResponseWriteMsUpper=self.consumed_ms-lo,
                    responseToReadLowerMs=lo, responseToReadUpperMs=hi,
                    clockUncertaintyMs=uncertainty)
        try:
            join()
        except Exception:
            self.row['invalidChildFrames'] += 1


def begin_exchange(payload):
    context, flow = _operation.get(), current_flow()
    if context is None or flow is None or context[3] is not asyncio.current_task():
        return None
    clock, operation, mode, _owner = context
    return ExchangeTiming(flow, clock, operation, mode,
                          'resume' if payload.get('operation') == 'resume' else 'start')
