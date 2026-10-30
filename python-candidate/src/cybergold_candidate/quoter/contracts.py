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
    limit: int
    random_seed: int | None
    seed_done: asyncio.Event = field(default_factory=asyncio.Event)
    discovery_done: asyncio.Event = field(default_factory=asyncio.Event)
    started: set = field(default_factory=set)
    resolved: set = field(default_factory=set)
    starts: int = 0
    pruned: int = 0
    repairs: int = 0

    def claim(self):
        # Called on the owning event loop without yielding. This allowance
        # bounds optional work only; ordinary candidates use no credits.
        if self.starts >= self.limit:
            return False
        self.starts += 1
        return True


_traces = ContextVar('quoter_path_traces', default=None)
_operation = ContextVar('quoter_path_operation', default=('', 0, 0))


@contextmanager
def capture_paths():
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
