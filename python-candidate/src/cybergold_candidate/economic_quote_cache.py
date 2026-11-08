"""Operation-owned cache feeds: L1 observations, optional SQL and scope lifetime."""
import asyncio
from copy import deepcopy

from .quoter.reuse_estimate import attach_reuse_sample
from .quoter.ranking import prefer_completed
from .quoter.path_families import quote_path_family
from .quoter.provenance import merge_origins
from .quoter.reuse_routes import funded_route_identity
from .quote_flow import producer_flow, stage


class CacheFeed:
    """One operation owns its SQL feeds; completed observations enter L1 now."""
    def __init__(self, service, request):
        self.service, self.request = service, request
        self.preparing = service._own(service._capture_scope(request))
        self.transferred = False
        self.completed, self.pending, self.reads = {}, {}, {}
        self.saving = None
        self.book = None
        self.closed = False

    def local_scope(self, request=None):
        with stage('cache.capture', kind='cpu'):
            try:
                return self.service.store.capture_scope(request or self.request)
            except Exception:
                return None

    def bind(self, book):
        self.book = book
        register = getattr(self.service.store, 'register_book', None)
        scope = self.local_scope()
        if register is not None and scope is not None:
            register(scope, book)
        def prepared(task):
            if not self.closed and register is not None and not task.cancelled():
                scope = task.result()
                if scope is not None:
                    register(scope, book)
        self.preparing.add_done_callback(prepared)

    def memory_lookup(self):
        with stage('cache.memory', kind='cpu'):
            read = getattr(self.service.store, 'memory_lookup', None)
            scope = self.local_scope()
            return read(self.request, scope=scope) if read is not None and scope is not None else None

    def memory_neighbors(self):
        with stage('cache.memory', kind='cpu'):
            read = getattr(self.service.store, 'memory_neighbors', None)
            scope = self.local_scope()
            return read(self.request, scope=scope) if read is not None and scope is not None else []

    def historical_observation(self, value):
        canonical = getattr(self.service.store, 'historical_observation', None)
        scope = self.local_scope()
        return canonical(scope, value) if canonical is not None and scope is not None else (value, None)

    def route_seeds(self, neighbors=None):
        with stage('cache.seeds', kind='cpu'):
            rows, seen = [], set()
            for row in self.memory_neighbors() if neighbors is None else neighbors:
                quote = row['quote']
                identity = funded_route_identity(quote)
                if identity not in seen:
                    seen.add(identity)
                    rows.append(deepcopy(quote))
            return rows

    async def scope(self):
        with stage('cache.scope', kind='await'):
            return await asyncio.shield(self.preparing)

    async def _read(self, name, missing):
        with stage('cache.read.wait', kind='await'):
            if name not in self.reads:
                async def read():
                    try:
                        scope = await self.scope()
                        operation = getattr(self.service.store, 'load_'+name, None) or getattr(self.service.store, name)
                        with stage('cache.sql.lookup' if name == 'lookup' else 'cache.sql.neighbors', kind='await'):
                            return await operation(self.request, scope=scope) if scope is not None else missing
                    except Exception:
                        return missing
                self.reads[name] = self.service._own(read())
                track = getattr(self.service.store, 'track_io', None)
                if track is not None:
                    track(self.reads[name])
            try:
                return deepcopy(await asyncio.shield(self.reads[name]))
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
                return deepcopy(missing)

    async def sql_lookup(self):
        return await self._read('lookup', None)

    async def sql_neighbors(self):
        return await self._read('neighbors', [])

    async def lookup(self):
        memory = self.memory_lookup()
        return memory if memory is not None else await self.sql_lookup()

    async def neighbors(self):
        return self.memory_neighbors() or await self.sql_neighbors()

    def forget(self, identity):
        scope = self.local_scope()
        forget = getattr(self.service.store, 'forget', None)
        if forget is not None and scope is not None:
            forget(identity, scope=scope)
        self.forget_pending(identity)

    def forget_pending(self, identity):
        for family, value in list(self.completed.items()):
            if funded_route_identity(value) == identity:
                self.completed.pop(family, None)
                self.pending.pop(family, None)

    def announce(self, frame):
        scope = self.local_scope()
        announce = getattr(self.service.store, 'announce', None)
        if announce is not None and scope is not None:
            announce(self.request, frame, self.book, scope=scope)
        else:
            version = max(self.book.versions.values(), default=0) + 1
            self.book.on_observation(frame, version)

    def remember(self, value, *, version=None):
        family, identity = quote_path_family(value), funded_route_identity(value)
        previous = self.completed.get(family)
        if previous == value:
            return
        request = value.get('request', self.request)
        scope = self.local_scope(request)
        remember = getattr(self.service.store, 'remember', None)
        if remember is not None and scope is not None:
            if version is not None:
                if version < self.service.store.latest_version(scope, identity):
                    return
                remember(request, value, scope=scope, version=version)
            else:
                remember(request, value, scope=scope)
        same = previous is not None and funded_route_identity(previous) == identity
        if same or prefer_completed(value, previous, scalar=self.request['intent'] in (0, 1),
                                     basket=self.request['intent'] >= 2):
            self.completed[family] = deepcopy(value)
            self.pending[family] = (deepcopy(value), version)
            self.flush()
        else:
            merge_origins(previous, value)

    async def observe_family(self, value):
        self.remember(value)

    def save(self, value):
        self.remember(value)

    def flush(self):
        if self.pending and (self.saving is None or self.saving.done()):
            self.transferred = True
            self.saving = self.service._own(self._save())
            track = getattr(self.service.store, 'track_io', None)
            if track is not None:
                track(self.saving)

    async def _save(self):
        with producer_flow('cache-write'):
            try:
                scope = await self.scope()
                if scope is not None:
                    while self.pending:
                        values, self.pending = list(self.pending.values()), {}
                        for value, version in values:
                            try:
                                request = value.get('request', self.request)
                                selected = (self.service.store.point_scope(scope, request)
                                            if hasattr(self.service.store, 'point_scope') else scope)
                                write = getattr(self.service.store, 'persist', None)
                                with stage('cache.persist', kind='await'):
                                    if write is not None:
                                        await write(request, attach_reuse_sample(value), scope=selected, version=version)
                                    else:
                                        await self.service.store.save(request, attach_reuse_sample(value), scope=selected)
                            except Exception:
                                pass
            except Exception:
                pass
            finally:
                await self._close_scope()

    async def _close_scope(self):
        if not self.preparing.done():
            self.preparing.cancel()
        await asyncio.gather(self.preparing, return_exceptions=True)

    async def close(self):
        with stage('cache.close', kind='await'):
            self.closed = True
            unregister = getattr(self.service.store, 'unregister_book', None)
            if unregister is not None and self.book is not None:
                unregister(self.book)
            reads = tuple(self.reads.values())
            for task in reads:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*reads, return_exceptions=True)
            if not self.transferred:
                await self._close_scope()
