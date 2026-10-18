"""Process-local quote sharing, immutable Mainnet math and solver observations.

Sandbox shares only overlapping exact work. Historical observations are hints;
caller deadlines and existing Token/chain validation remain independent.
"""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from fractions import Fraction
import uuid
import json
import time

from .route_search import RouteSearchRpc
from .shared_reads import SharedReads
from .quote_errors import RpcTimeout
from .rpc_diagnostics import bind_quote_error, quote_failure_context, quote_candidate_scope
from .quote_budget import budget_entry, current_budget


class BasketMath:
    """N8: bounded ten-second decoded-success cache of deadline-free Basket math.

    Age starts at original completion and never extends on reuse. Token Helpers
    are intentionally excluded: their calldata contains the execution deadline.
    """
    def __init__(self, limit=512, now=time.monotonic):
        self.limit, self.now = limit, now
        self.completed = OrderedDict()
        self.pending = SharedReads()
        self.hits = 0

    async def read(self, chain, block, address, data, produce):
        key = (chain, block['hash'].lower(), address.lower(), data.lower())
        row = self.completed.get(key) if chain == 1 else None
        if row and self.now() - row[0] < 10:
            self.hits += 1
            self.completed.move_to_end(key)
            return deepcopy(row[1])
        self.completed.pop(key, None)
        async def fetch():
            result = await produce()  # Decoding/contract errors raise normally.
            if chain == 1:
                self.completed[key] = (self.now(), deepcopy(result))
                self.completed.move_to_end(key)
                while len(self.completed) > self.limit:
                    self.completed.popitem(last=False)
            return result
        return deepcopy(await self.pending.one(key, fetch))

    async def close(self):
        await self.pending.close()
        self.completed.clear()


class GrossSeeds:
    """N7/H1: organic, canonical completed observations, used only for inversion.

    Target allocation rounded to ppm is a hint identity, not an execution bound.
    Every proposed amount still runs the full route search and Token Helpers.
    """
    def __init__(self, interpolate=False, exact=False, limit=256):
        self.interpolate, self.exact, self.limit = interpolate, exact, limit
        self.rows = OrderedDict()

    def key(self, request, context):
        total = sum(int(t['amount']) for t in request['targets'])
        allocations = [(t['inputAsset'].lower(), t['outputAsset'].lower(),
                        int(t['amount']) * 1_000_000 // max(1, total)) for t in request['targets']]
        return (context['chainId'], context['blockHash'].lower(), request['token'].lower(),
                request['quoteToken'].lower(), request['native'], request['adapter'].lower(),
                tuple(a.lower() for a in request['orderedAssets']), tuple(allocations))

    def suggest(self, request, context):
        points = self.rows.get(self.key(request, context), [])
        if not points:
            return None
        target = int(request['amount'])
        if self.exact:
            # An ordinary exact-amount lookup miss follows the unchanged seed.
            return next((gross for amount, gross in points if amount == target), None)
        below = max((p for p in points if p[0] <= target), default=None)
        above = min((p for p in points if p[0] >= target), default=None)
        if self.interpolate and below and above and below[0] != above[0]:
            value = below[1] + Fraction((target-below[0])*(above[1]-below[1]), above[0]-below[0])
            return max(1, (value.numerator + value.denominator-1)//value.denominator)
        amount, gross = min(points, key=lambda p: abs(p[0]-target))
        return max(1, (gross*target + amount-1)//amount)

    def observe(self, request, result):
        if request['mode'] != 'redeem-exact-out':
            return
        key = self.key(request, result['context'])
        points = self.rows.setdefault(key, [])
        point = (int(request['amount']), int(result['executionAmount']))
        points[:] = sorted({*points, point})[-16:]
        self.rows.move_to_end(key)
        while len(self.rows) > self.limit:
            self.rows.popitem(last=False)


class VerifiedGrossSeed:
    """Reuse an accepted gross for the identical Mainnet amount/state/intent.

    This is immutable mathematical reuse, not a neighboring-amount guess. Only
    the deadline is excluded. Every caller still runs full redemption and final
    validation; Sandbox and unseen inputs follow the original eleven passes.
    """
    fallback = False

    def __init__(self, limit=256, now=time.monotonic):
        self.rows, self.limit, self.now = OrderedDict(), limit, now

    def key(self, request, context):
        return (context['chainId'], context['blockHash'].lower(), json.dumps(
            {k: v for k, v in request.items() if k not in ('deadline', 'retainedPlan')}, sort_keys=True, separators=(',', ':')))

    def suggest(self, request, context):
        if context['chainId'] != 1:
            return None
        key = self.key(request, context)
        row = self.rows.get(key)
        if row and self.now()-row[0] < 10:
            self.rows.move_to_end(key)
            return row[1]
        self.rows.pop(key, None)
        return None

    def observe(self, request, result):
        if request['mode'] != 'redeem-exact-out' or result['context']['chainId'] != 1:
            return
        key = self.key(request, result['context'])
        # A repeated success does not extend the original acquisition lifetime.
        self.rows.setdefault(key, (self.now(), int(result['executionAmount'])))
        self.rows.move_to_end(key)
        while len(self.rows) > self.limit:
            self.rows.popitem(last=False)


@dataclass(eq=False)
class Subscriber:
    pending: dict = field(default_factory=dict)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    terminal: tuple | None = None

    def update(self, frame):
        self.pending[(frame['type'], frame.get('stage'), frame.get('strategy'))] = frame
        self.wake.set()


class IntentSharing:
    """N6b: one producer for a full request+hash, latest-frame replay per client.

    Slow clients cannot block the producer; a last disconnect cancels it.
    Results are removed at completion, including on Mainnet (no result TTL).
    """
    def __init__(self, service, rpc_factory=RouteSearchRpc, *, head=None, request_resolver=None):
        self.service, self.pending = service, {}
        self.history = getattr(service, 'history', None)
        self.rpc_factory = rpc_factory
        self.head = head
        self.request_resolver = request_resolver
        self.started, self.joined = 0, 0

    @budget_entry
    async def get(self, request, on_update):
        budget = current_budget()
        if self.request_resolver:
            request = await budget.prepare(self.request_resolver(request))
        history = self.history
        epoch = history.epoch if history else None
        last_model = None
        async def emit(frame, model_epoch):
            nonlocal last_model
            if frame['type'] == 'model':
                if history and model_epoch != history.epoch:
                    return
                if frame['value'] == last_model:
                    return
                last_model = deepcopy(frame['value'])
            await on_update(frame)
        if history:
            # Historical display data does not depend on acquiring a new head.
            # Final validation still follows the ordinary producer below.
            await budget.prepare(emit({'type': 'model', 'value': history.packet(request)}, epoch))
        if self.service.routes.rpc is None:
            self.service.routes.rpc = self.rpc_factory(self.service.settings)
        rpc = self.service.routes.rpc
        try:
            async with asyncio.timeout_at(budget.deadline):
                block = await self.head() if self.head else await rpc.block(None)
        except RpcTimeout:
            raise
        except TimeoutError:
            # This deadline encloses only chain/head RPC reads. Preserve their
            # cause when the outer timer wins the provider's equal deadline.
            raise RpcTimeout('RPC context acquisition timed out') from None
        key = (block['hash'].lower(), json.dumps(request, sort_keys=True, separators=(',', ':')))
        entry = self.pending.get(key)
        subscriber = Subscriber()
        if entry is None:
            entry = {'clients': {subscriber}, 'latest': {}, 'task': None, 'modelEpoch': epoch,
                     'workId': str(uuid.uuid4()), 'budget': budget}
            self.pending[key] = entry
            self.started += 1
            async def update(frame):
                frame = {**frame, 'workId': entry['workId']}
                entry['latest'][(frame['type'], frame.get('stage'), frame.get('strategy'))] = frame
                for client in entry['clients']:
                    client.update(frame)
            async def produce():
                try:
                    options = {'model_epoch': entry['modelEpoch']} if history else {}
                    with quote_candidate_scope(entry['workId']):
                        value = await budget.produce(self.service.get(request, update, block=block, **options))
                    if isinstance(value, dict) and isinstance(value.get('metrics'), dict):
                        value['metrics']['totalMs'] = round(budget.elapsed(), 3)
                        value['metrics'].update(budget.metrics())
                    terminal = ('result', value)
                except BaseException as error:
                    entry['errorQuoteDiagnostics'] = quote_failure_context(error)
                    terminal = ('error', error)
                finally:
                    if self.pending.get(key) is entry:
                        del self.pending[key]
                for client in entry['clients']:
                    client.terminal = terminal
                    client.wake.set()
            entry['task'] = asyncio.create_task(produce())
        else:
            self.joined += 1
            entry['clients'].add(subscriber)
            for frame in entry['latest'].values():
                subscriber.update(frame)
        try:
            while True:
                await subscriber.wake.wait()
                subscriber.wake.clear()
                frames, subscriber.pending = subscriber.pending, {}
                for frame in frames.values():
                    await emit(deepcopy(frame), entry['modelEpoch'])
                if subscriber.terminal:
                    kind, value = subscriber.terminal
                    if kind == 'error':
                        bind_quote_error(value, entry.get('errorQuoteDiagnostics'))
                        raise value
                    return deepcopy(value)
        finally:
            entry['clients'].discard(subscriber)
            if not entry['clients'] and not entry['task'].done():
                if self.pending.get(key) is entry:
                    del self.pending[key]
                entry['task'].cancel()
                await asyncio.gather(entry['task'], return_exceptions=True)

    async def close(self):
        tasks = [entry['task'] for entry in self.pending.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if hasattr(self.service, 'close'):
            await self.service.close()
