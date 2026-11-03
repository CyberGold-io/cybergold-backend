"""Internal, request-local search and replay data; never public quote fields."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field


@dataclass
class HopTrace:
    hop: dict
    funded: int
    consumed: int
    output: int
    pre_state: dict | None


@dataclass
class PathTrace:
    route: list
    funded: int
    operation: str
    branch: int
    stage: int
    hops: list[HopTrace] = field(default_factory=list)
    consumed: int = 0
    output: int = 0


@dataclass
class SearchSession:
    random_seed: int | None
    seed_done: asyncio.Event = field(default_factory=asyncio.Event)
    discovery_done: asyncio.Event = field(default_factory=asyncio.Event)
    started: set = field(default_factory=set)
    resolved: set = field(default_factory=set)
    pending: set = field(default_factory=set)
    starts: int = 0
    pruned: int = 0
    repairs: int = 0

    def claim(self):
        # Passive work count. Pricing slots bound concurrency; failed
        # attempts do not exclude later useful proposals from this search.
        self.starts += 1
        return True


_traces = ContextVar('quoter_path_traces', default=None)
_operation = ContextVar('quoter_path_operation', default=('', 0, 0))
_nomination = ContextVar('quoter_path_nomination', default=(None, ()))


@contextmanager
def path_nomination(source, origins=()):
    """Carry optional topology origins and original funding through replay."""
    token = _nomination.set((source, origins))
    try:
        yield
    finally:
        _nomination.reset(token)


def current_nomination():
    return _nomination.get()


@contextmanager
def capture_paths(*, reuse=False):
    existing = _traces.get()
    if reuse and existing is not None:
        yield existing
        return
    rows = []
    token = _traces.set(rows)
    try:
        yield rows
    finally:
        _traces.reset(token)


@contextmanager
def path_operation(operation, branch, stage):
    token = _operation.set((operation, branch, stage))
    try:
        yield
    finally:
        _operation.reset(token)


def new_path_trace(route, amount):
    rows = _traces.get()
    if rows is None:
        return None
    operation, branch, stage = _operation.get()
    trace = PathTrace(deepcopy(route), amount, operation, branch, stage)
    rows.append(trace)
    return trace
